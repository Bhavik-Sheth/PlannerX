"""
planner/agents/updates_agent.py

UpdatesAgent — A pure analysis agent that determines the impact of mid-session plan changes.
Does not write files or call specialist agents directly. Returns a structured UpdatePlan.
"""
from pathlib import Path
from datetime import datetime
from typing import Literal, Dict, Any, List, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

from planner.state import PlannerState
from planner.agents._base import invoke_llm_safe, strip_markdown_fence
from planner.tools.validation_tools import check_frontend_signals


class ChangeSummary(BaseModel):
    """Parsed summary of the requested change."""
    change_type: Literal["scope", "stack", "schema", "constraint", "role", "feature", "other"]
    what_changed: str = Field(..., description="One sentence summarizing what specifically changed.")
    what_was_before: str = Field(..., description="One sentence summarizing what was there before (inferred from StructuredIdea.md).")
    what_replaces_it: str = Field(..., description="One sentence summarizing what replaces it.")
    confidence: Literal["high", "medium", "low"] = Field(..., description="Confidence level in how clearly the change is specified.")
    ambiguous_parts: List[str] = Field(default_factory=list, description="Questions to clarify the change if confidence is medium or low.")


class BlastRadiusFile(BaseModel):
    """Details of a file affected by the change."""
    file: str = Field(..., description="Filename, e.g., 'PRD.md', 'TRD.md', or 'MODULES/my_module.md'")
    reason: str = Field(..., description="Reason why this file is affected.")
    priority: int = Field(..., description="Execution priority order within blast radius (1 = first, smaller numbers executed first)")


class BlastRadiusAnalysis(BaseModel):
    """Analysis of affected files based on the dependency map."""
    affected_files: List[BlastRadiusFile] = Field(..., description="List of affected files.")


class StructuredIdeaDraft(BaseModel):
    """Draft of StructuredIdea.md and change log entry."""
    structured_idea_draft: str = Field(..., description="The full, updated StructuredIdea.md markdown content.")
    change_log_entry: str = Field(..., description="Formatted markdown entry to append to StructuredIdea.md change log.")


class UpdatesAgent:
    def __init__(self, state: PlannerState):
        self.state = state
        self.planner_dir = Path(state.project_path)

    def run_analysis(
        self,
        change_description: str,
        structured_idea: str,
        all_files: dict[str, str],
        tracker_state: dict[str, Any],
        grill_answers: dict[str, str] = None,
        has_frontend: bool = True
    ) -> dict:
        """
        Analyze the change description and current project state.
        Produces and returns a structured UpdatePlan.
        """
        from planner.tools import get_llm_client
        llm = get_llm_client()

        # Step 1 — Produce Change Summary
        structured_llm = llm.with_structured_output(ChangeSummary)
        system_prompt = """You are an expert product analyst. Analyze the incoming change description and the current StructuredIdea.md.
Identify:
1. The change type: scope | stack | schema | constraint | role | feature | other
2. What specifically changed in one sentence
3. What was there before (inferred from StructuredIdea.md) in one sentence
4. What replaces it (from change_description) in one sentence
5. Your confidence level (high | medium | low) in how clearly the change is specified.
6. A list of 1 to 3 direct clarifying questions in ambiguous_parts if confidence is not 'high'."""

        grill_answers_str = ""
        if grill_answers:
            grill_answers_str = "\n".join(f"- Q: {q}\n  A: {a}" for q, a in grill_answers.items())

        user_content = f"StructuredIdea.md content:\n{structured_idea}\n\nChange description:\n{change_description}"
        if grill_answers_str:
            user_content += f"\n\nClarifying Details:\n{grill_answers_str}"

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content)
        ]

        summary: ChangeSummary = structured_llm.invoke(messages)

        # If confidence is low, return clarification request
        if summary.confidence == "low":
            # If we don't have ambiguous parts generated, create a default one
            questions = summary.ambiguous_parts
            if not questions:
                questions = ["Can you please explain the change in more detail?"]
            return {
                "change_summary": summary.model_dump(),
                "blast_radius": [],
                "change_context": {},
                "structured_idea_draft": "",
                "change_log_entry": "",
                "has_conflicts": False,
                "conflict_files": [],
                "frontend_changed": False,
                "new_frontend_value": has_frontend,
                "needs_clarification": True,
                "ambiguous_parts": questions
            }

        # Step 2 — Blast Radius Analysis
        # Get list of existing files
        existing_files = [f.name for f in self.planner_dir.glob("*.md") if f.is_file()]
        modules_dir = self.planner_dir / "MODULES"
        if modules_dir.exists():
            existing_files.extend(f"MODULES/{f.name}" for f in modules_dir.glob("*.md") if f.is_file())

        dependency_map = """
change_type: scope
  (feature added, removed, or modified)
  → Affected: PRD, TRD, AppFlow (if has_frontend), ImplementationPlan
  → Check: MODULES/ files referencing changed feature

change_type: stack
  (technology, framework, or provider changed)
  → Affected: TRD, DesignDecisions, Rules
  → Check: Schema (if DB layer changed), MODULES/ using changed tech

change_type: schema
  (data model, table, or field changed)
  → Affected: Schema, TRD (data section)
  → Check: MODULES/ that own or query affected tables

change_type: constraint
  (hard limit added, removed, or changed)
  → Affected: Constraints, TRD, DesignDecisions, Rules

change_type: role
  (user role added, changed, or removed)
  → Affected: PRD (personas), Schema (if role stored in DB), Rules (if permissions)
  → Check: AppFlow (if has_frontend — role-specific screens)

change_type: frontend_toggle
  (frontend added to or removed from a backend-only project, or vice versa)
  → Affected: TRD, DesignDecisions, AppFlow, ImplementationPlan
  → Update has_frontend flag in Orchestrator state

change_type: other
  → LLM must reason from change description which files are affected
  → Must cite reasoning per file in the output
"""

        system_blast = f"""You are a systems architect. Determine which of the planning files are affected by the proposed change.
Use the following dependency map:
{dependency_map}

Only include files that exist in the project or make sense to be re-run based on the dependency map, and present them in dependency order:
Constraints.md → PRD.md → TRD.md → Schema.md → DesignDecisions.md → AppFlow.md → Rules.md → ImplementationPlan.md

If the project has no frontend (has_frontend={has_frontend}), do NOT include frontend-only files (DesignDecisions.md, AppFlow.md).
Return a structured list of affected files with priority (1 is highest/run first) and reason."""

        messages_blast = [
            SystemMessage(content=system_blast),
            HumanMessage(content=f"Existing files: {existing_files}\n\nChange Summary:\n- Type: {summary.change_type}\n- What Changed: {summary.what_changed}")
        ]

        structured_llm_blast = llm.with_structured_output(BlastRadiusAnalysis)
        blast_analysis: BlastRadiusAnalysis = structured_llm_blast.invoke(messages_blast)

        # Filter blast radius and check conflicts
        filtered_blast_radius = []
        conflict_files = []
        has_conflicts = False

        from planner.agents.orchestrator import _SEQUENCE
        sequence_files = {entry[1] for entry in _SEQUENCE}

        for entry in blast_analysis.affected_files:
            filename = entry.file
            # Skip if not in sequence and not a module
            if filename not in sequence_files and not filename.startswith("MODULES/"):
                continue

            file_info = tracker_state.get("files", {}).get(filename, {})
            status = file_info.get("status", "")

            # Enforce skip rules
            if "⏳" in status or "Pending" in status:
                # skip
                continue
            elif "🔄" in status or "In Progress" in status:
                conflict_files.append(filename)
                has_conflicts = True

            filtered_blast_radius.append(entry.model_dump())

        # Sort blast_radius by priority
        filtered_blast_radius.sort(key=lambda x: x["priority"])

        # Step 3 — Generate Per-File Change Context
        change_contexts = {}
        for entry in filtered_blast_radius:
            filename = entry["file"]
            content_before = all_files.get(filename, "")
            impact = self._generate_impact_context(filename, summary, content_before)
            change_contexts[filename] = {
                "change_type": summary.change_type,
                "what_changed": summary.what_changed,
                "what_was_before": summary.what_was_before,
                "impact_on_this_file": impact
            }

        # Step 4 — Produce Updated StructuredIdea Draft
        system_rewrite = """You are an expert product strategist.
Produce an updated version of the StructuredIdea.md markdown content.
Also produce a Change Log entry to append. The entry must end with:
**Affects:** {affected_files_placeholder}
Do NOT replace '{affected_files_placeholder}', output it literally as '{affected_files_placeholder}'.
Do NOT wrap the markdown output in markdown code fences in the fields.
"""
        rewrite_messages = [
            SystemMessage(content=system_rewrite),
            HumanMessage(content=f"Current StructuredIdea.md:\n{structured_idea}\n\nChange Summary:\n- Type: {summary.change_type}\n- What Changed: {summary.what_changed}\n- What was before: {summary.what_was_before}\n- What replaces it: {summary.what_replaces_it}")
        ]

        structured_llm_rewrite = llm.with_structured_output(StructuredIdeaDraft)
        draft: StructuredIdeaDraft = structured_llm_rewrite.invoke(rewrite_messages)

        # Detect frontend change
        new_frontend_value = check_frontend_signals(draft.structured_idea_draft, "")
        frontend_changed = (has_frontend != new_frontend_value)

        # Make sure StructuredIdea.md is stripped of markdown fences
        clean_idea_draft = strip_markdown_fence(draft.structured_idea_draft)

        return {
            "change_summary": summary.model_dump(),
            "blast_radius": filtered_blast_radius,
            "change_context": change_contexts,
            "structured_idea_draft": clean_idea_draft,
            "change_log_entry": draft.change_log_entry,
            "has_conflicts": has_conflicts,
            "conflict_files": conflict_files,
            "frontend_changed": frontend_changed,
            "new_frontend_value": new_frontend_value,
            "needs_clarification": False,
            "ambiguous_parts": []
        }

    def _generate_impact_context(self, filename: str, summary: ChangeSummary, current_content: str) -> str:
        from planner.tools import get_llm_client
        llm = get_llm_client()
        system = f"You are a technical analyst. Given a change summary and the current content of {filename}, write a single sentence describing exactly what needs to be changed in this file. Be specific."
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=f"Change Summary:\n- Type: {summary.change_type}\n- What Changed: {summary.what_changed}\n\nCurrent content:\n{current_content}")
        ]
        return invoke_llm_safe(messages).strip()
