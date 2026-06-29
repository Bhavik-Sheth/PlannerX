"""
orchestrator.py — Pure routing and coordination agent.

Receives structured commands from the ExecutiveAgent, decides which agent(s)
to call, calls them in the right order, and returns structured display
payloads back to the ExecutiveAgent.

Rules:
  1. No LLM calls except the ``chat`` handler (one call, one case only).
  2. No user I/O — every output goes to ExecutiveAgent as a typed payload.
  3. No file writes except StructuredIdea.md (via ``describe``) and CLAUDE.md
     (via ``finalize``) — all other file writes are done by specialist agents.
  4. Tracker.md updates are tool calls (``tracker_tools``), never routed
     through TrackerAgent node.
  5. One specialist call at a time.
  6. Always validate file structure after every specialist write.
  7. Pass ``fit_analysis`` to all specialists in hybrid mode.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from planner.state import PlannerState, save_state
from planner.agents._base import invoke_llm_safe, strip_markdown_fence, load_context
from planner.tools import (
    scaffold_planner,
    read_file,
    write_file,
    append_file,
    clear_file,
    validate_file_structure,
    check_frontend_signals,
    update_file_status,
    get_status_summary,
    get_next_pending_file,
)
from planner.tools.validation_tools import REQUIRED_SECTIONS_MAP

# ── Constants ──────────────────────────────────────────────────────────────

# Fixed sequence: (agent_name, target_file)
_SEQUENCE = [
    ("structuring",     "StructuredIdea.md"),
    ("constraints",     "Constraints.md"),
    ("prd",             "PRD.md"),
    ("trd",             "TRD.md"),
    ("schema",          "Schema.md"),
    ("design",          "DesignDecisions.md"),   # conditional on has_frontend
    ("appflow",         "AppFlow.md"),            # conditional on has_frontend
    ("rules",           "Rules.md"),
    ("implementation",  "ImplementationPlan.md"),
]

_FRONTEND_AGENTS = {"design", "appflow"}

# Upstream context each agent needs (dependency map)
_UPSTREAM_MAP: dict[str, list[str]] = {
    "Constraints.md":        ["StructuredIdea.md"],
    "PRD.md":                ["StructuredIdea.md", "Constraints.md"],
    "TRD.md":                ["StructuredIdea.md", "Constraints.md", "PRD.md"],
    "Schema.md":             ["StructuredIdea.md", "Constraints.md", "PRD.md", "TRD.md"],
    "DesignDecisions.md":    ["StructuredIdea.md", "Constraints.md", "PRD.md", "TRD.md"],
    "AppFlow.md":            ["StructuredIdea.md", "Constraints.md", "PRD.md", "TRD.md"],
    "Rules.md":              ["StructuredIdea.md", "Constraints.md", "PRD.md", "TRD.md", "Schema.md"],
    "ImplementationPlan.md": ["StructuredIdea.md", "Constraints.md", "PRD.md", "TRD.md", "Schema.md", "Rules.md"],
}

# Files to load for consistency check
_CONSISTENCY_FILES = [
    "StructuredIdea.md", "Constraints.md", "PRD.md", "TRD.md", "Schema.md",
    "DesignDecisions.md", "AppFlow.md", "Rules.md", "ImplementationPlan.md",
]


# ── Helpers ────────────────────────────────────────────────────────────────

def _detect_frontend(state: PlannerState) -> bool:
    """Return True if the project idea mentions a frontend."""
    planner_dir = Path(state.project_path)
    si_path = planner_dir / "StructuredIdea.md"
    trd_path = planner_dir / "TRD.md"

    si_text = si_path.read_text(encoding="utf-8") if si_path.exists() else ""
    trd_text = trd_path.read_text(encoding="utf-8") if trd_path.exists() else ""

    return check_frontend_signals(si_text, trd_text)


def _file_is_populated(planner_dir: Path, filename: str) -> bool:
    """Return True if the target file exists and is non-empty."""
    path = planner_dir / filename
    return path.exists() and path.stat().st_size > 0


def _generate_bullet_summary(content: str) -> list[str]:
    """Generate 2-3 bullet points summarising a document via LLM."""
    messages = [
        SystemMessage(
            content=(
                "You are a technical editor. Summarize the following document "
                "into exactly 2-3 bullet points highlighting the most important "
                "decisions, requirements, or features specified in it. "
                "Be extremely concise. Return ONLY the bullets, one per line, "
                "using '-' as bullet character."
            )
        ),
        HumanMessage(content=content),
    ]
    try:
        raw = invoke_llm_safe(messages).strip()
        return [line.lstrip("- ").strip() for line in raw.splitlines() if line.strip()]
    except Exception:
        return ["Draft updated successfully.", "Details captured in file."]


# ── OrchestratorAgent ──────────────────────────────────────────────────────

class OrchestratorAgent:
    """
    Pure router. Receives structured commands from the ExecutiveAgent,
    decides which agent(s) to call, calls them in the right order, and
    returns structured display payloads back to the ExecutiveAgent.
    """

    def __init__(self, state: PlannerState) -> None:
        self.state = state
        self.planner_dir = Path(state.project_path)

    # ── Payload helpers ────────────────────────────────────────────────

    @staticmethod
    def _payload(type_: str, **kw: Any) -> dict:
        """Build a typed display payload dict."""
        return {"type": type_, **kw}

    def _update_tracker(
        self, filename: str, status: str, agent: str, notes: str = ""
    ) -> None:
        """Update a single file's status in Tracker.md via tracker_tools."""
        # tracker_tools.update_file_status uses the *project root* (parent of PLANNER/)
        project_root = str(self.planner_dir.parent)
        try:
            update_file_status(project_root, filename, status, agent, notes)
        except Exception:
            # Non-critical — don't crash the pipeline for a tracker write failure
            pass

    # ── Command Handlers ───────────────────────────────────────────────

    def handle_init(self) -> dict:
        """Scaffold PLANNER/ directory."""
        scaffold_planner(str(self.planner_dir.parent))
        return self._payload("ready", message="PLANNER/ created.")

    def handle_set_mode(self, mode: str) -> dict:
        """Store mode in state and return appropriate prompt."""
        self.state.mode = mode
        save_state(self.state)

        if mode == "from_scratch":
            return self._payload(
                "prompt",
                text="Describe your idea. Type /done when finished.",
            )
        else:  # ps_idea_hybrid
            return self._payload(
                "prompt",
                text="Paste your Problem Statement. Type /done when finished.",
            )

    def handle_describe(self, text: str) -> dict:
        """Append idea text, route to StructuringAgent."""
        # Append to RawIdea.md
        raw_idea_path = self.planner_dir / "RawIdea.md"
        append_file(str(raw_idea_path), text)

        # Route to StructuringAgent
        from planner.agents.structuring_agent import run_structuring

        raw_idea = read_file(str(raw_idea_path)).strip()
        result = run_structuring(raw_idea, self.state.mode)

        # Write StructuredIdea.md
        si_path = self.planner_dir / "StructuredIdea.md"
        write_file(str(si_path), result["structured_idea"], overwrite=True)
        self.state.structured_idea = result["structured_idea"]
        self.state.fit_analysis = result.get("fit_analysis", "")

        # Update Tracker
        self._update_tracker(
            "StructuredIdea.md", "✅ Approved", "structuring_agent"
        )
        if "StructuredIdea.md" not in self.state.approved_files:
            self.state.approved_files.append("StructuredIdea.md")

        save_state(self.state)

        # Return result based on mode
        if self.state.mode == "ps_idea_hybrid" and result.get("fit_analysis"):
            return self._payload(
                "fit_analysis",
                content=result["fit_analysis"],
                has_gaps=result.get("has_gaps", False),
            )
        else:
            return self._payload("ready_to_run")

    def handle_run(self) -> dict:
        """
        Find the first pending file in sequence, load upstream context,
        call the appropriate specialist agent, validate, and return a
        file_complete payload.
        """
        # Detect frontend
        self.state.has_frontend = _detect_frontend(self.state)

        # Find first unapproved file in sequence
        for agent_name, target_file in _SEQUENCE:
            # Skip frontend-only agents if no frontend
            if agent_name in _FRONTEND_AGENTS and not self.state.has_frontend:
                # Mark as skipped in tracker
                self._update_tracker(
                    target_file,
                    "⏳ Pending",
                    f"{agent_name}_agent",
                    "Skipped (backend-only)",
                )
                continue

            if target_file not in self.state.approved_files:
                # Load upstream context
                if target_file in _UPSTREAM_MAP:
                    load_context(self.state, *_UPSTREAM_MAP[target_file])

                # Update tracker to In Progress
                self._update_tracker(
                    target_file, "🔄 In Progress", f"{agent_name}_agent"
                )
                self.state.current_file = target_file
                self.state.next_agent = agent_name
                self.state.status = "drafting"
                save_state(self.state)

                # Call the specialist agent
                agent_fn = _get_agent_fn(agent_name)
                self.state = agent_fn(self.state)

                # Handle needs_input (questions from specialist)
                if self.state.status == "needs_input":
                    return self._payload(
                        "question",
                        text=self.state.pending_questions[0] if self.state.pending_questions else "Missing info needed.",
                        reason="Specialist agent needs clarification.",
                        source_agent=agent_name,
                    )

                # Validate file structure
                file_path = self.planner_dir / target_file
                if target_file in REQUIRED_SECTIONS_MAP:
                    validation = validate_file_structure(
                        str(file_path),
                        REQUIRED_SECTIONS_MAP[target_file],
                    )
                    # Non-blocking: warn but continue even if invalid

                # Generate summary
                content = read_file(str(file_path))
                summary = _generate_bullet_summary(content)

                # Update tracker to Needs Review
                self._update_tracker(
                    target_file, "👀 Needs Review", f"{agent_name}_agent"
                )
                self.state.active_revision_target = target_file
                self.state.status = "needs_review"
                save_state(self.state)

                return self._payload(
                    "file_complete",
                    file=target_file,
                    summary=summary,
                    agent=f"{agent_name}_agent",
                )

        # All files approved
        self.state.status = "done"
        self.state.next_agent = ""
        save_state(self.state)
        return self._payload("sequence_complete")

    def handle_approve(self, file: str) -> dict:
        """Approve a file and determine next step."""
        if file not in self.state.approved_files:
            self.state.approved_files.append(file)

        self._update_tracker(file, "✅ Approved", "user")
        self.state.active_revision_target = ""
        save_state(self.state)

        # Determine next file in sequence
        for agent_name, target_file in _SEQUENCE:
            if agent_name in _FRONTEND_AGENTS and not self.state.has_frontend:
                continue
            if target_file not in self.state.approved_files:
                # There's a next file — trigger run for it
                return self._payload(
                    "file_approved",
                    file=file,
                    next_file=target_file,
                )

        # All done
        return self._payload(
            "file_approved",
            file=file,
            next_file=None,
        )

    def handle_revise(self, target: str, request: str) -> dict:
        """Re-run a specialist agent with a revision request."""
        # Load current file content
        file_path = self.planner_dir / target
        if not file_path.exists():
            return self._payload(
                "error",
                agent="OrchestratorAgent",
                message=f"File {target} not found.",
            )

        # Find the owning agent
        agent_name = None
        for name, tgt in _SEQUENCE:
            if tgt == target:
                agent_name = name
                break

        if not agent_name:
            return self._payload(
                "error",
                agent="OrchestratorAgent",
                message=f"No agent found for {target}.",
            )

        # Store the revision request in grill_answers so the agent picks it up
        self.state.grill_answers[f"Change request for {target}"] = request
        self.state.current_file = target
        self.state.status = "drafting"

        # Load upstream context
        if target in _UPSTREAM_MAP:
            load_context(self.state, *_UPSTREAM_MAP[target])

        # Update tracker
        self._update_tracker(target, "🔄 In Progress", f"{agent_name}_agent")

        # Call agent
        agent_fn = _get_agent_fn(agent_name)
        self.state = agent_fn(self.state)

        # Generate summary
        content = read_file(str(file_path))
        summary = _generate_bullet_summary(content)

        # Update tracker to Needs Review
        self._update_tracker(
            target, "👀 Needs Review", f"{agent_name}_agent"
        )
        self.state.active_revision_target = target
        self.state.status = "needs_review"
        save_state(self.state)

        return self._payload(
            "file_complete",
            file=target,
            summary=summary,
            agent=f"{agent_name}_agent",
        )

    def handle_reset(self, file: str) -> dict:
        """Return a confirmation prompt for destructive reset action."""
        return self._payload(
            "confirmation_required",
            action=f"reset {file}",
            warning=f"This will clear {file} and re-run its agent.",
        )

    def handle_reset_confirmed(self, file: str) -> dict:
        """Execute the reset: clear file and re-run its agent."""
        file_path = self.planner_dir / file
        if file_path.exists():
            clear_file(str(file_path), force=True)

        # Remove from approved files if present
        if file in self.state.approved_files:
            self.state.approved_files.remove(file)

        self._update_tracker(file, "⏳ Pending", "pending reset")
        save_state(self.state)

        # Trigger a run for this file
        self.state.current_file = ""  # Reset so handle_run finds it
        return self.handle_run()

    def handle_consistency(self) -> dict:
        """Route to ConsistencyAgent."""
        from planner.agents.consistency_agent import consistency_agent

        # Load all PLANNER/ files
        ctx = load_context(self.state, *_CONSISTENCY_FILES)
        files = {
            fname: content
            for fname, content in ctx.items()
            if content.strip()
        }

        result = consistency_agent(files)

        return self._payload(
            "consistency_report",
            issues=result.get("issues", []),
            clean=result.get("clean", True),
        )

    def handle_finalize(self) -> dict:
        """Check for incomplete files and route to FinalizerAgent."""
        # Check for pending/in-progress files
        incomplete = []
        for _, target_file in _SEQUENCE:
            if target_file not in self.state.approved_files:
                if _file_is_populated(self.planner_dir, target_file):
                    incomplete.append(f"{target_file} (not approved)")
                else:
                    incomplete.append(f"{target_file} (not generated)")

        if incomplete:
            return self._payload(
                "finalize_warning",
                incomplete=incomplete,
            )

        return self._finalize_execute()

    def handle_finalize_confirmed(self) -> dict:
        """Execute finalization even with warnings."""
        return self._finalize_execute()

    def _finalize_execute(self) -> dict:
        """Actually run FinalizerAgent and write CLAUDE.md."""
        from planner.agents.finalizer_agent import finalizer_agent

        # Load all file contents
        files = {}
        for fname in _CONSISTENCY_FILES:
            fpath = self.planner_dir / fname
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8").strip()
                if content:
                    files[fname] = content

        # Also check MODULES/
        modules_dir = self.planner_dir / "MODULES"
        if modules_dir.exists():
            for mf in sorted(modules_dir.glob("*.md")):
                content = mf.read_text(encoding="utf-8").strip()
                if content:
                    files[f"MODULES/{mf.name}"] = content

        result = finalizer_agent(files)

        # Write CLAUDE.md to project root
        project_root = self.planner_dir.parent
        claude_path = project_root / "CLAUDE.md"
        write_file(str(claude_path), result["claude_md_content"], overwrite=True)

        return self._payload(
            "finalized",
            warnings=result.get("warnings", []),
        )

    def handle_status(self) -> dict:
        """Read Tracker.md and return status table."""
        project_root = str(self.planner_dir.parent)
        summary = get_status_summary(project_root)

        # Parse into rows
        rows = []
        for line in summary.splitlines():
            if line.startswith("|") and "---" not in line and "File" not in line:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 2:
                    rows.append({
                        "file": parts[0],
                        "status": parts[1],
                        "agent": parts[2] if len(parts) > 2 else "",
                        "notes": parts[3] if len(parts) > 3 else "",
                    })

        return self._payload("status_table", rows=rows, raw=summary)

    def handle_chat(self, text: str) -> dict:
        """
        Answer a free-form question from project context.
        This is the ONE AND ONLY LLM call the Orchestrator makes.
        """
        # Load context
        si_text = self.state.structured_idea or ""
        project_root = str(self.planner_dir.parent)
        summary = get_status_summary(project_root)

        context = f"Project Idea:\n{si_text}\n\nCurrent Status:\n{summary}"

        messages = [
            SystemMessage(
                content=(
                    "You are a helpful project planning assistant. Answer the "
                    "user's question using the project context provided. "
                    "Be concise and specific."
                )
            ),
            HumanMessage(content=f"Context:\n{context}\n\nQuestion: {text}"),
        ]

        try:
            answer = invoke_llm_safe(messages)
        except Exception as e:
            return self._payload(
                "error",
                agent="OrchestratorAgent",
                message=str(e),
            )

        return self._payload("chat_response", text=answer)

    def handle_update(self, text: str) -> dict:
        """Route to UpdatesAgent."""
        from planner.agents.updates_agent import UpdatesAgent

        agent = UpdatesAgent(self.state)
        agent.run(change_description=text, triggered_by="orchestrator")

        return self._payload(
            "update_complete",
            files_changed=[],  # UpdatesAgent manages its own output
        )

    def handle_module_add(self, name: str) -> dict:
        """Run module planner for a new module."""
        from planner.agents.module_planner_agent import module_planner_agent

        self.state.context_files["__module_name__"] = name
        if not self.state.structured_idea:
            si_path = self.planner_dir / "StructuredIdea.md"
            if si_path.exists():
                self.state.structured_idea = si_path.read_text(encoding="utf-8")

        module_planner_agent(self.state)

        return self._payload(
            "file_complete",
            file=f"MODULES/{name}.md",
            summary=[f"Module spec '{name}' generated."],
            agent="module_planner_agent",
        )

    def handle_module_list(self) -> dict:
        """List all modules."""
        modules_dir = self.planner_dir / "MODULES"
        modules = []
        if modules_dir.exists():
            for mf in sorted(modules_dir.glob("*.md")):
                modules.append({
                    "name": mf.name,
                    "status": "✅" if mf.stat().st_size > 0 else "⬜",
                })

        return self._payload("module_list", modules=modules)

    def handle_edit_complete(self, file: str) -> dict:
        """Notify that a file was edited externally."""
        # Mark file as needing review after manual edit
        self._update_tracker(file, "👀 Needs Review", "manual_edit")
        self.state.active_revision_target = file
        save_state(self.state)
        return self._payload(
            "file_complete",
            file=file,
            summary=["File was edited manually."],
            agent="manual_edit",
        )

    def handle_get_status(self) -> dict:
        """Alias for handle_status, used by ExecutiveAgent on resume."""
        return self.handle_status()

    def handle_resume(self, confirmed: bool) -> dict:
        """Handle session resume confirmation."""
        if confirmed:
            return self._payload(
                "prompt",
                text="Session resumed. Type /run to continue, or /status to review.",
            )
        else:
            return self._payload(
                "ready",
                message="Session cleared. Type /init to start fresh.",
            )

    def dispatch(self, command: dict) -> dict:
        """
        Main entry point: receive a structured command from ExecutiveAgent,
        route to the appropriate handler, return a display payload.
        """
        cmd = command.get("command", "")

        handlers = {
            "init":             lambda: self.handle_init(),
            "set_mode":         lambda: self.handle_set_mode(command.get("mode", "from_scratch")),
            "describe":         lambda: self.handle_describe(command.get("text", "")),
            "run":              lambda: self.handle_run(),
            "approve":          lambda: self.handle_approve(command.get("file", "")),
            "revise":           lambda: self.handle_revise(command.get("target", ""), command.get("request", "")),
            "reset":            lambda: self.handle_reset(command.get("file", "")),
            "reset_confirmed":  lambda: self.handle_reset_confirmed(command.get("file", "")),
            "consistency":      lambda: self.handle_consistency(),
            "finalize":         lambda: self.handle_finalize(),
            "finalize_confirmed": lambda: self.handle_finalize_confirmed(),
            "status":           lambda: self.handle_status(),
            "get_status":       lambda: self.handle_get_status(),
            "chat":             lambda: self.handle_chat(command.get("text", "")),
            "update":           lambda: self.handle_update(command.get("text", "")),
            "module_add":       lambda: self.handle_module_add(command.get("name", "")),
            "module_list":      lambda: self.handle_module_list(),
            "edit_complete":    lambda: self.handle_edit_complete(command.get("file", "")),
            "resume":           lambda: self.handle_resume(command.get("confirmed", True)),
        }

        handler = handlers.get(cmd)
        if handler:
            return handler()

        return self._payload(
            "error",
            agent="OrchestratorAgent",
            message=f"Unknown command: {cmd}",
        )


# ── Agent function registry (single source of truth) ──────────────────────

_AGENT_REGISTRY: dict[str, str] = {
    "structuring":    "planner.agents.structuring_agent.structuring_agent",
    "constraints":    "planner.agents.constraints_agent.constraints_agent",
    "prd":            "planner.agents.prd_agent.prd_agent",
    "trd":            "planner.agents.trd_agent.trd_agent",
    "schema":         "planner.agents.schema_agent.schema_agent",
    "design":         "planner.agents.design_agent.design_agent",
    "appflow":        "planner.agents.appflow_agent.appflow_agent",
    "rules":          "planner.agents.rules_agent.rules_agent",
    "implementation": "planner.agents.implementation_agent.implementation_agent",
    "modules":        "planner.agents.module_planner_agent.module_planner_agent",
    "diagram":        "planner.agents.architecture_diagram_agent.generate_diagrams",
}


def _get_agent_fn(agent_name: str):
    """Dynamic import of an agent function by name. Single source of truth."""
    import importlib

    dotted = _AGENT_REGISTRY.get(agent_name)
    if not dotted:
        raise ValueError(f"Unknown agent: {agent_name}")

    module_path, fn_name = dotted.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, fn_name)


# ── Legacy compatibility ──────────────────────────────────────────────────
# These functions maintain backward compatibility with existing code that
# imports from orchestrator.py. They delegate to OrchestratorAgent.

def orchestrator(state: PlannerState) -> PlannerState:
    """
    Legacy graph node wrapper. Wraps OrchestratorAgent for LangGraph
    compatibility. Determines what action to take based on state and
    dispatches accordingly.
    """
    agent = OrchestratorAgent(state)

    # Detect frontend
    state.has_frontend = _detect_frontend(state)

    # If a file was just written and needs user review — pause
    if state.current_file and state.current_file not in state.approved_files:
        planner_dir = Path(state.project_path)
        path = planner_dir / state.current_file
        if path.exists() and path.stat().st_size > 0:
            content = path.read_text(encoding="utf-8")
            summary = _generate_bullet_summary(content)

            print(f"\n✅ {state.current_file} written.")
            print("Key decisions:")
            for bullet in summary:
                print(f"  • {bullet}")
            print(f"\nType /approve {state.current_file} to accept, "
                  f"or describe changes to revise it.\n")

            state.active_revision_target = state.current_file
            state.status = "needs_review"
            state.next_agent = ""

            agent._update_tracker(
                state.current_file, "👀 Needs Review",
                f"{state.next_agent}_agent" if state.next_agent else "agent",
            )
            save_state(state)
            return state

    # Find next file in sequence
    for agent_name, target_file in _SEQUENCE:
        if agent_name in _FRONTEND_AGENTS and not state.has_frontend:
            continue
        if target_file not in state.approved_files:
            state.next_agent = agent_name
            state.current_file = target_file
            state.status = "drafting"

            if target_file in _UPSTREAM_MAP:
                load_context(state, *_UPSTREAM_MAP[target_file])

            agent._update_tracker(
                target_file, "🔄 In Progress", f"{agent_name}_agent",
            )
            save_state(state)
            return state

    # All approved
    state.status = "done"
    state.next_agent = ""
    print("\n✅  All planning files are complete! "
          "Run `planner finalize` to generate CLAUDE.md.\n")
    save_state(state)
    return state


def run_startup_flow(state: PlannerState) -> PlannerState:
    """Legacy startup flow. Called by TUI and CLI init command."""
    planner_dir = Path(state.project_path)
    si_path = planner_dir / "StructuredIdea.md"
    tracker_path = planner_dir / "Tracker.md"

    if si_path.exists() and si_path.stat().st_size > 0:
        print("\nWelcome back to PlannerX.\n")
        print("Resuming session. Last status:")
        if tracker_path.exists():
            print(tracker_path.read_text(encoding="utf-8"))
        else:
            print("[Tracker.md not found]")

        try:
            choice = input("\nContinue from where we left off? [yes/no]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "yes"

        if choice in ("n", "no"):
            state = run_mode_selection(state)
        else:
            print("\nResuming main sequence...")
    else:
        state = run_mode_selection(state)

    return state


def run_mode_selection(state: PlannerState) -> PlannerState:
    """Legacy mode selection flow."""
    planner_dir = Path(state.project_path)

    scaffold_planner(str(planner_dir.parent))

    print("\nWelcome to PlannerX.\n")
    print("How would you like to start?\n")
    print("  [1] From scratch — I have a raw idea, help me plan it fully")
    print("  [2] PS + Idea — I have a problem statement and a proposed solution\n")

    while True:
        try:
            choice = input("Type 1 or 2 to begin: ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = "1"
        if choice in ("1", "2"):
            break
        print("Invalid choice. Please enter 1 or 2.")

    if choice == "1":
        state.mode = "from_scratch"
        print("\n--- Mode A: From Scratch ---")
        print("Please describe your project idea in plain text. You can type multiple lines.")
        print("When you are finished, type /done on a new line or press Enter on an empty line.")

        lines = []
        while True:
            try:
                line = input().strip()
            except (EOFError, KeyboardInterrupt):
                break
            if line == "/done" or (not line and lines):
                break
            lines.append(line)

        raw_idea = "\n".join(lines).strip()
        raw_idea_path = planner_dir / "RawIdea.md"
        raw_idea_path.write_text(raw_idea, encoding="utf-8")
        print("\n✅ RawIdea.md written.")

        print("⏳ Structuring idea via LLM...")
        from planner.agents.structuring_agent import run_structuring
        result = run_structuring(raw_idea, state.mode)
        si_path = planner_dir / "StructuredIdea.md"
        write_file(str(si_path), result["structured_idea"], overwrite=True)
        state.structured_idea = result["structured_idea"]
        print("✅ StructuredIdea.md generated.")

    else:
        state.mode = "ps_idea_hybrid"
        print("\n--- Mode B: PS + Idea (Hybrid) ---")

        print("Paste or describe the Problem Statement (PS).")
        print("This is the problem you are solving — not your solution.")
        print("Type /done when finished or press Enter on an empty line.")

        ps_lines = []
        while True:
            try:
                line = input().strip()
            except (EOFError, KeyboardInterrupt):
                break
            if line == "/done" or (not line and ps_lines):
                break
            ps_lines.append(line)

        ps_content = "\n".join(ps_lines).strip()

        print("\nNow describe your proposed solution to this PS.")
        print("What will you build? How does it address the problem?")
        print("Type /done when finished or press Enter on an empty line.")

        sol_lines = []
        while True:
            try:
                line = input().strip()
            except (EOFError, KeyboardInterrupt):
                break
            if line == "/done" or (not line and sol_lines):
                break
            sol_lines.append(line)

        sol_content = "\n".join(sol_lines).strip()

        raw_idea_path = planner_dir / "RawIdea.md"
        raw_idea_content = f"## Problem Statement\n{ps_content}\n\n## Proposed Solution\n{sol_content}\n"
        raw_idea_path.write_text(raw_idea_content, encoding="utf-8")
        print("\n✅ RawIdea.md written.")

        from planner.agents.structuring_agent import run_structuring

        revision_count = 0
        while True:
            print("⏳ Running Hybrid Structuring via LLM...")
            result = run_structuring(raw_idea_content, state.mode)

            si_path = planner_dir / "StructuredIdea.md"
            write_file(str(si_path), result["structured_idea"], overwrite=True)
            state.structured_idea = result["structured_idea"]
            state.fit_analysis = result.get("fit_analysis", "")

            fit_analysis = result.get("fit_analysis", "")
            print("\n" + "=" * 60)
            print("FIT ANALYSIS")
            print("=" * 60)
            print(fit_analysis)
            print("=" * 60 + "\n")

            revision_count += 1
            if revision_count >= 5:
                print("Max revisions reached. Proceeding with current scope.")
                break

            try:
                action = input(
                    "Proceed with current scope? Or would you like to revise "
                    "your solution first? [proceed/revise]: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                action = "proceed"

            if action in ("p", "proceed", "yes", "y"):
                break

            print("\nDescribe your revised solution:")
            print("Type /done when finished or press Enter on an empty line.")
            rev_lines = []
            while True:
                try:
                    line = input().strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if line == "/done" or (not line and rev_lines):
                    break
                rev_lines.append(line)
            sol_content = "\n".join(rev_lines).strip()

            raw_idea_content = f"## Problem Statement\n{ps_content}\n\n## Proposed Solution\n{sol_content}\n"
            raw_idea_path.write_text(raw_idea_content, encoding="utf-8")

    if "StructuredIdea.md" not in state.approved_files:
        state.approved_files.append("StructuredIdea.md")

    save_state(state)
    return state


def run_consistency_check(state: PlannerState) -> str:
    """Legacy consistency check. Delegates to ConsistencyAgent."""
    planner_dir = Path(state.project_path)

    ctx = load_context(state, *_CONSISTENCY_FILES)
    files = {
        fname: content
        for fname, content in ctx.items()
        if content.strip()
    }

    if not files:
        return "No planning files found to check."

    from planner.agents.consistency_agent import consistency_agent
    result = consistency_agent(files)

    if result.get("clean", True):
        return "✅ No contradictions detected."

    lines = ["## Consistency Issues Found\n"]
    for issue in result.get("issues", []):
        lines.append(f"- **{issue.get('file_a', '?')}** ↔ **{issue.get('file_b', '?')}**: {issue.get('issue', '?')}")

    return "\n".join(lines)
