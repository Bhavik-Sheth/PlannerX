from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional, TypedDict


class ExecutiveState(TypedDict):
    """
    Minimal state held by the ExecutiveAgent — just enough to know
    what it's waiting for.  All session / planning state lives in
    PlannerState (owned by the Orchestrator).
    """
    waiting_for: str        # "mode_select" | "resume_confirm" | "approval" |
                            # "question_answer" | "suggestion_confirm" |
                            # "retry_confirm" | "reset_confirm" |
                            # "fit_analysis_confirm" | ""
    pending_command: dict   # partially built command awaiting user confirmation
    last_display: str       # last thing shown to user (for context)


class PlannerState(BaseModel):
    """
    Shared state passed between all LangGraph nodes.
    Every agent reads this, mutates it, and returns it.
    Files on disk are the true source of truth; this is just the runtime bus.
    """
    project_path: str = Field(
        ...,
        description="Absolute path to the PLANNER/ directory.",
    )
    current_file: str = Field(
        "",
        description="Which file is currently being written, e.g. 'PRD.md'.",
    )
    structured_idea: str = Field(
        "",
        description="Cached content of StructuredIdea.md (loaded once per run).",
    )
    context_files: Dict[str, str] = Field(
        default_factory=dict,
        description="filename -> content cache, loaded from disk on demand by agents.",
    )
    pending_questions: List[str] = Field(
        default_factory=list,
        description="Questions set by a specialist agent when it needs clarification.",
    )
    grill_answers: Dict[str, str] = Field(
        default_factory=dict,
        description="question -> answer, filled by the Griller agent after prompting user.",
    )
    tech_suggestions: Dict[str, Any] = Field(
        default_factory=dict,
        description="Suggestions from the TechStackExpert agent, keyed by question.",
    )
    status: str = Field(
        "drafting",
        description="Workflow status: 'drafting' | 'needs_input' | 'approved' | 'done' | 'error'.",
    )
    next_agent: str = Field(
        "",
        description="The next agent node the orchestrator (or griller) wants to route to.",
    )
    calling_agent: str = Field(
        "",
        description="Tracks which specialist last routed to the Griller, so Griller can route back.",
    )
    has_frontend: bool = Field(
        True,
        description="Whether the project has a frontend. False skips DesignDecisions/AppFlow agents.",
    )
    approved_files: List[str] = Field(
        default_factory=list,
        description="Filenames that have been explicitly approved by the user.",
    )
    error_message: str = Field(
        "",
        description="Last error message from a failed LLM call, for display to the user.",
    )
    mode: str = Field(
        "",
        description="Startup mode: 'from_scratch' | 'ps_idea_hybrid'.",
    )
    sequence_index: int = Field(
        0,
        description="Current index in the main sequence.",
    )
    fit_analysis: str = Field(
        "",
        description="Fit analysis between PS and proposed solution in hybrid mode.",
    )
    active_revision_target: str = Field(
        "",
        description="The file currently in 'Needs Review' status.",
    )
    tracker_state: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parsed status mapping of Tracker.md.",
    )
    last_error: str = Field(
        "",
        description="Last LLM failure message, for retry mechanism.",
    )
    pending_updates: List[str] = Field(
        default_factory=list,
        description="Queue of pending update descriptions.",
    )
    change_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Current target file's change context during updates.",
    )


def load_state(project_path: str) -> PlannerState:
    from pathlib import Path
    import json
    planner_dir = Path(project_path)
    state_file = planner_dir / ".state.json"
    
    # Try loading StructuredIdea.md
    si_path = planner_dir / "StructuredIdea.md"
    structured_idea = si_path.read_text(encoding="utf-8").strip() if si_path.exists() else ""
    
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            data["project_path"] = str(planner_dir)
            data["structured_idea"] = structured_idea
            return PlannerState(**data)
        except Exception:
            pass
            
    return PlannerState(
        project_path=str(planner_dir),
        structured_idea=structured_idea,
    )


def save_state(state: PlannerState) -> None:
    from pathlib import Path
    planner_dir = Path(state.project_path)
    if planner_dir.exists():
        state_file = planner_dir / ".state.json"
        state_file.write_text(state.model_dump_json(indent=2), encoding="utf-8")
