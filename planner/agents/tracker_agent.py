# planner/agents/tracker_agent.py
# NOTE: This is NOT a LangGraph node. Do not add to graph.py.
# Called directly by Orchestrator for /status display only.

from planner.tools import read_tracker, get_status_summary

def format_status_for_display(project_path: str) -> str:
    """
    Reads Tracker.md and returns a formatted string for the TUI Viewer panel.
    Used by Orchestrator's 'status' command handler only.
    """
    return get_status_summary(project_path)
