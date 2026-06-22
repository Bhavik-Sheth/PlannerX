"""
planner/main.py — Typer CLI entrypoint.

Commands:
  planner init              → scaffold PLANNER/
  planner describe <text>   → append to RawIdea.md + structure into StructuredIdea.md
  planner run               → invoke the full LangGraph orchestration pipeline
  planner status            → pretty-print Tracker.md
  planner approve <file>    → mark file approved in Tracker.md
  planner reset <file>      → clear + re-run one file's agent
  planner module add <name> → plan a new module
  planner module list       → list modules
  planner consistency       → cross-file consistency check
  planner finalize          → compile CLAUDE.md (planning done)
"""
import sys
from pathlib import Path
# pyrefly: ignore [missing-import]
import typer
from typing import Optional

app = typer.Typer(
    help="PlannerX — AI-driven project planner CLI.",
    no_args_is_help=False,
)

# Default PLANNER/ directory relative to cwd
def _planner_dir() -> Path:
    return Path.cwd() / "PLANNER"


# ─────────────────────────────────────────────
# Default command: launch TUI (future phases)
# ─────────────────────────────────────────────

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """
    Launch the TUI when no subcommand is specified.
    """
    if ctx.invoked_subcommand is None:
        from planner.tui.app import PlannerApp
        planner_dir = _planner_dir()
        tui_app = PlannerApp(planner_path=planner_dir)
        tui_app.run()



# ─────────────────────────────────────────────
# init
# ─────────────────────────────────────────────

@app.command(name="init")
def init_cmd() -> None:
    """Scaffold PLANNER/ directory and create all empty planning files."""
    try:
        from planner.files.scaffold import scaffold_project
        scaffold_project()
        typer.echo("✅  PLANNER/ initialized successfully.")
    except Exception as e:
        typer.echo(f"[ERROR] {e}", err=True)
        raise typer.Exit(1)


# ─────────────────────────────────────────────
# describe
# ─────────────────────────────────────────────

@app.command(name="describe")
def describe_cmd(text: str = typer.Argument(..., help="Your project idea text.")) -> None:
    """Append text to RawIdea.md and immediately structure it into StructuredIdea.md via LLM."""
    planner_dir = _planner_dir()
    if not planner_dir.exists():
        typer.echo("[ERROR] PLANNER/ not found. Run `planner init` first.", err=True)
        raise typer.Exit(1)

    # 1. Append to RawIdea.md
    from planner.files.writer import write_planner_file
    write_planner_file(planner_dir / "RawIdea.md", text)
    typer.echo(f"✅  Appended to RawIdea.md ({len(text)} chars).")

    # 2. Run the structuring agent
    typer.echo("⏳  Structuring idea via LLM...")
    try:
        from planner.state import PlannerState
        from planner.agents.structuring_agent import structuring_agent
        state = PlannerState(project_path=str(planner_dir))
        result = structuring_agent(state)
        if result.status == "needs_input":
            typer.echo(f"[INFO] {result.pending_questions[0]}")
        else:
            typer.echo("✅  StructuredIdea.md updated.")
    except Exception as e:
        typer.echo(f"[ERROR] Structuring failed: {e}", err=True)
        raise typer.Exit(1)


# ─────────────────────────────────────────────
# run
# ─────────────────────────────────────────────

@app.command(name="run")
def run_cmd() -> None:
    """Run the full LangGraph orchestration pipeline (fills all planning docs)."""
    planner_dir = _planner_dir()
    if not planner_dir.exists():
        typer.echo("[ERROR] PLANNER/ not found. Run `planner init` first.", err=True)
        raise typer.Exit(1)

    typer.echo("🚀  Starting planner run...\n")
    try:
        from planner.graph import run_graph
        final_state = run_graph(str(planner_dir))
        if final_state.status == "done":
            typer.echo("\n✅  Planning run complete. Run `planner status` to review.")
        elif final_state.status == "error":
            typer.echo(f"\n[ERROR] Run stopped: {final_state.error_message}", err=True)
            raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo("\n[INTERRUPTED] Run aborted by user.")
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"\n[ERROR] {e}", err=True)
        raise typer.Exit(1)


# ─────────────────────────────────────────────
# status
# ─────────────────────────────────────────────

@app.command(name="status")
def status_cmd() -> None:
    """Show the current status from Tracker.md."""
    planner_dir = _planner_dir()
    tracker_path = planner_dir / "Tracker.md"
    if not tracker_path.exists():
        typer.echo("Tracker.md not found. Run `planner run` first.")
        return
    typer.echo(tracker_path.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────
# approve
# ─────────────────────────────────────────────

@app.command(name="approve")
def approve_cmd(file: str = typer.Argument(..., help="Filename to approve, e.g. PRD.md")) -> None:
    """Mark a planning file as approved in Tracker.md."""
    planner_dir = _planner_dir()
    target = planner_dir / file
    if not target.exists():
        typer.echo(f"[ERROR] {file} not found in PLANNER/.", err=True)
        raise typer.Exit(1)

    # Re-run tracker_agent with the file in approved_files
    from planner.state import PlannerState
    from planner.agents.tracker_agent import tracker_agent
    state = PlannerState(project_path=str(planner_dir))

    # Load existing approved_files from Tracker.md (simple keyword search)
    tracker_path = planner_dir / "Tracker.md"
    approved: list[str] = []
    if tracker_path.exists():
        for line in tracker_path.read_text(encoding="utf-8").splitlines():
            if "✅" in line and ".md" in line:
                # Extract filename from table row: | PRD.md | ... | ✅ |
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if parts and parts[-1] == "✅":
                    approved.append(parts[0])

    if file not in approved:
        approved.append(file)

    state.approved_files = approved
    tracker_agent(state)
    typer.echo(f"✅  {file} marked as approved.")


# ─────────────────────────────────────────────
# reset
# ─────────────────────────────────────────────

@app.command(name="reset")
def reset_cmd(file: str = typer.Argument(..., help="Filename to reset and re-run, e.g. PRD.md")) -> None:
    """Clear a planning file and re-run its agent (requires confirmation)."""
    planner_dir = _planner_dir()
    target = planner_dir / file

    if not target.exists():
        typer.echo(f"[ERROR] {file} not found in PLANNER/.", err=True)
        raise typer.Exit(1)

    confirmed = typer.confirm(f"Clear {file} and re-run its agent?", default=False)
    if not confirmed:
        typer.echo("Aborted.")
        return

    # Clear the file
    target.write_text("", encoding="utf-8")
    typer.echo(f"🗑  {file} cleared.")

    # Re-run the appropriate agent
    _AGENT_MAP = {
        "StructuredIdea.md":  "structuring",
        "PRD.md":             "prd",
        "TRD.md":             "trd",
        "Schema.md":          "schema",
        "DesignDecisions.md": "design",
        "AppFlow.md":         "appflow",
        "Rules.md":           "rules",
        "ImplementationPlan.md": "implementation",
        "Tracker.md":         "tracker",
    }
    agent_name = None
    if file.startswith("MODULES/"):
        agent_name = "modules"
    elif file.startswith("ARCHITECTURE_DIAGRAMS/"):
        agent_name = "diagram"
    else:
        agent_name = _AGENT_MAP.get(file)

    if not agent_name:
        typer.echo(f"[WARN] No agent known for {file}. File cleared but not re-run.")
        return

    typer.echo(f"⏳  Re-running {agent_name} agent...")
    _run_single_agent(str(planner_dir), agent_name, file)
    typer.echo(f"✅  {file} regenerated.")


def _run_single_agent(planner_path: str, agent_name: str, filename: Optional[str] = None) -> None:
    """Import and invoke a single agent by name."""
    from planner.state import PlannerState
    from planner.files.reader import read_planner_file

    if agent_name == "diagram":
        from planner.agents.architecture_diagram_agent import generate_diagrams
        generate_diagrams(planner_path)
        return

    planner_dir = Path(planner_path)
    si_path = planner_dir / "StructuredIdea.md"
    structured_idea = read_planner_file(si_path, use_cache=False).strip() if si_path.exists() else ""
    state = PlannerState(project_path=planner_path, structured_idea=structured_idea)

    if agent_name == "modules" and filename:
        module_name = filename.split("/")[-1].replace(".md", "")
        state.context_files["__module_name__"] = module_name

    agents = {
        "structuring": "planner.agents.structuring_agent.structuring_agent",
        "prd":         "planner.agents.prd_agent.prd_agent",
        "trd":         "planner.agents.trd_agent.trd_agent",
        "schema":      "planner.agents.schema_agent.schema_agent",
        "design":      "planner.agents.design_agent.design_agent",
        "appflow":     "planner.agents.appflow_agent.appflow_agent",
        "rules":       "planner.agents.rules_agent.rules_agent",
        "implementation": "planner.agents.implementation_agent.implementation_agent",
        "tracker":     "planner.agents.tracker_agent.tracker_agent",
        "modules":     "planner.agents.module_planner_agent.module_planner_agent",
    }
    import importlib
    dotted = agents[agent_name]
    module_path, fn_name = dotted.rsplit(".", 1)
    module = importlib.import_module(module_path)
    fn = getattr(module, fn_name)
    fn(state)


# ─────────────────────────────────────────────
# module subcommands
# ─────────────────────────────────────────────

module_app = typer.Typer(help="Manage planner modules.")
app.add_typer(module_app, name="module")


@module_app.command(name="add")
def module_add_cmd(name: str = typer.Argument(..., help="Module name (no spaces, no .md)")) -> None:
    """Create and generate a spec for a new module."""
    planner_dir = _planner_dir()
    if not planner_dir.exists():
        typer.echo("[ERROR] PLANNER/ not found. Run `planner init` first.", err=True)
        raise typer.Exit(1)

    from planner.state import PlannerState
    from planner.agents.module_planner_agent import module_planner_agent
    from planner.files.reader import read_planner_file

    si_path = planner_dir / "StructuredIdea.md"
    structured_idea = read_planner_file(si_path, use_cache=False).strip() if si_path.exists() else ""

    state = PlannerState(
        project_path=str(planner_dir),
        structured_idea=structured_idea,
        context_files={"__module_name__": name},
    )
    typer.echo(f"⏳  Generating spec for module '{name}'...")
    module_planner_agent(state)
    typer.echo(f"✅  MODULES/{name}.md created.")


@module_app.command(name="list")
def module_list_cmd() -> None:
    """List all modules in PLANNER/MODULES/."""
    modules_dir = _planner_dir() / "MODULES"
    if not modules_dir.exists():
        typer.echo("No MODULES/ directory found.")
        return
    files = sorted(modules_dir.glob("*.md"))
    if not files:
        typer.echo("No modules defined yet. Use `planner module add <name>`.")
        return
    for f in files:
        size = f.stat().st_size
        status = "✅" if size > 0 else "⬜"
        typer.echo(f"  {status}  {f.name}")


# ─────────────────────────────────────────────
# consistency
# ─────────────────────────────────────────────

@app.command(name="consistency")
def consistency_cmd() -> None:
    """Run a read-only cross-file consistency check and print the report."""
    planner_dir = _planner_dir()
    if not planner_dir.exists():
        typer.echo("[ERROR] PLANNER/ not found. Run `planner init` first.", err=True)
        raise typer.Exit(1)

    from planner.state import PlannerState
    from planner.agents.orchestrator import run_consistency_check

    state = PlannerState(project_path=str(planner_dir))
    typer.echo("🔍  Running consistency check...\n")
    report = run_consistency_check(state)
    typer.echo(report)



# ─────────────────────────────────────────────
# diagram
# ─────────────────────────────────────────────

@app.command(name="diagram")
def diagram_cmd() -> None:
    """Manually regenerate architecture diagrams from TRD.md, Schema.md, and AppFlow.md."""
    planner_dir = _planner_dir()
    if not planner_dir.exists():
        typer.echo("[ERROR] PLANNER/ not found. Run `planner init` first.", err=True)
        raise typer.Exit(1)

    typer.echo("⏳  Regenerating architecture diagrams...")
    try:
        from planner.agents.architecture_diagram_agent import generate_diagrams
        generate_diagrams(str(planner_dir))
        typer.echo("✅  Architecture diagrams regenerated.")
    except Exception as e:
        typer.echo(f"[ERROR] Diagram generation failed: {e}", err=True)
        raise typer.Exit(1)


# ─────────────────────────────────────────────
# finalize (compile CLAUDE.md)
# ─────────────────────────────────────────────

@app.command(name="finalize")
def finalize_cmd() -> None:
    """Compile CLAUDE.md from all approved planning docs (ends the planning phase)."""
    planner_dir = _planner_dir()
    if not planner_dir.exists():
        typer.echo("[ERROR] PLANNER/ not found. Run `planner init` first.", err=True)
        raise typer.Exit(1)

    confirmed = typer.confirm(
        "This will compile CLAUDE.md and signal that planning is complete. Continue?",
        default=False,
    )
    if not confirmed:
        typer.echo("Aborted.")
        return

    typer.echo("⏳  Compiling CLAUDE.md...")
    _compile_claude_md(str(planner_dir))
    typer.echo("✅  CLAUDE.md written to project root. Planning phase complete.")


def _compile_claude_md(planner_path: str) -> None:
    """Compile a condensed CLAUDE.md from all PLANNER docs."""
    planner_dir = Path(planner_path)
    project_root = planner_dir.parent

    sections = [
        ("PRD.md",             "Product Requirements"),
        ("TRD.md",             "Technical Stack & Architecture"),
        ("Schema.md",          "Data Schema"),
        ("Rules.md",           "Coding Rules & Conventions"),
        ("Constraints.md",     "Constraints"),
        ("ImplementationPlan.md", "Implementation Plan"),
    ]

    instructions = """
## Context Binding & Coding Instructions

This file serves as the master execution context for any coding agent (such as Claude Code or another coding AI) operating on this repository.

### Context Guidelines:
- Use **PRD.md** under `PLANNER/` for product requirements, scope, features, and success metrics.
- Use **TRD.md** under `PLANNER/` for technical stack specifications, architecture overview, and API interfaces.
- Use **Schema.md** under `PLANNER/` for database schemas, models, and relationships.
- Use **AppFlow.md** under `PLANNER/` for user journey flows, view maps, and UX state transitions.
- Use **DesignDecisions.md** under `PLANNER/` for historical architectural decisions, justifications, and trade-offs.
- Use **Rules.md** under `PLANNER/` for project-level coding rules, folder layouts, and styling conventions.
- Use **Constraints.md** under `PLANNER/` for system/environment limitations.
- Use **ImplementationPlan.md** under `PLANNER/` as the phased, checked-off implementation path.
- Check the **MODULES/** directory under `PLANNER/` for detailed modular spec sheets.
- Check the **ARCHITECTURE_DIAGRAMS/** directory under `PLANNER/` for system architecture, design, and data flow ASCII diagrams.

### Coding Agent Constraint:
The coding agent MUST strictly bind its execution and implementation choices to the detailed documents and rules located under the `PLANNER/` directory. Do not deviate from the constraints, technical architectures, schemas, or design decision records defined therein.
"""

    lines = [
        "# CLAUDE.md — Project Execution Context\n",
        "_Auto-generated by `planner finalize`. Do not edit manually._\n",
        instructions
    ]

    for fname, heading in sections:
        fpath = planner_dir / fname
        if fpath.exists() and fpath.stat().st_size > 0:
            content = fpath.read_text(encoding="utf-8").strip()
            # Truncate very long files to keep CLAUDE.md digestible
            if len(content) > 3000:
                content = content[:3000] + "\n\n... [truncated — see full file in PLANNER/]"
            lines.append(f"\n---\n## {heading}\n\n{content}\n")

    claude_path = project_root / "CLAUDE.md"
    claude_path.write_text("\n".join(lines), encoding="utf-8")


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app()
