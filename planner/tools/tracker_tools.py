"""
planner/tools/tracker_tools.py — Tracker.md manipulation tools.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from planner.tools.exceptions import InvalidStatusError
from planner.tools.file_tools import read_file, write_file

TRACKED_FILES = [
    ("StructuredIdea.md",    "structuring_agent"),
    ("Constraints.md",       "constraints_agent"),
    ("PRD.md",               "prd_agent"),
    ("TRD.md",               "trd_agent"),
    ("Schema.md",            "schema_agent"),
    ("DesignDecisions.md",   "design_agent"),
    ("AppFlow.md",           "appflow_agent"),
    ("Rules.md",             "rules_agent"),
    ("ImplementationPlan.md","implementation_agent"),
    ("MODULES/",             "module_planner_agent"),
]

def read_tracker(project_path: str) -> dict:
    """
    Parses Tracker.md into a structured dict.
    If the file does not exist, returns a default initialized structure.
    """
    tracker_path = os.path.join(project_path, "PLANNER", "Tracker.md")
    content = read_file(tracker_path)
    
    # Default structure
    data = {
        "files": {
            filename: {"status": "⏳ Pending", "agent": "—", "updated": "—", "notes": "—"}
            for filename, _ in TRACKED_FILES
        },
        "modules": {},
        "blockers": [],
        "resolved_blockers": [],
        "change_log": []
    }
    
    if not content:
        return data
        
    lines = content.splitlines()
    current_section = None
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
            
        # Identify sections
        if stripped.startswith("## Planning Files") or stripped.startswith("## Status"):
            current_section = "files"
            continue
        elif stripped.startswith("## Modules"):
            current_section = "modules"
            continue
        elif stripped.startswith("## Blockers / Notes") or stripped.startswith("## Blockers"):
            current_section = "blockers"
            continue
        elif stripped.startswith("## Change Log"):
            current_section = "change_log"
            continue
        elif stripped.startswith("#"):
            current_section = None
            continue
            
        # Parse content based on current section
        if current_section == "files":
            if stripped.startswith("|") and not stripped.startswith("|---") and "File | Status" not in stripped:
                parts = [p.strip() for p in stripped.split("|")[1:-1]]
                if len(parts) >= 2:
                    filename = parts[0]
                    status = parts[1]
                    agent = parts[2] if len(parts) > 2 else ""
                    updated = parts[3] if len(parts) > 3 else ""
                    notes = parts[4] if len(parts) > 4 else ""
                    data["files"][filename] = {
                        "status": status,
                        "agent": agent,
                        "updated": updated,
                        "notes": notes
                    }
        elif current_section == "modules":
            if stripped.startswith("|") and not stripped.startswith("|---") and "Module | Status" not in stripped:
                parts = [p.strip() for p in stripped.split("|")[1:-1]]
                if len(parts) >= 2:
                    module_name = parts[0]
                    status = parts[1]
                    data["modules"][module_name] = status
        elif current_section == "blockers":
            if stripped.startswith("-") or stripped.startswith("*"):
                blocker_text = stripped.lstrip("-* ").strip()
                if "[RESOLVED]" in blocker_text or "Resolved:" in blocker_text:
                    data["resolved_blockers"].append(blocker_text)
                else:
                    data["blockers"].append(blocker_text)
        elif current_section == "change_log":
            if stripped.startswith("-") or stripped.startswith("*"):
                data["change_log"].append(stripped.lstrip("-* ").strip())
                
    return data

def _save_tracker(project_path: str, data: dict) -> bool:
    """Formats and writes the tracker dict back to Tracker.md atomically."""
    tracker_path = os.path.join(project_path, "PLANNER", "Tracker.md")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    rows = []
    rows.append("# Tracker.md")
    rows.append(f"Last updated: {now}\n")
    
    # 1. Status table
    rows.append("## Status\n")
    rows.append("| File | Status | Agent | Updated | Notes |")
    rows.append("|---|---|---|---|---|")
    
    # Maintain file ordering of TRACKED_FILES
    for filename, _ in TRACKED_FILES:
        file_info = data["files"].get(filename, {"status": "⏳ Pending", "agent": "—", "updated": "—", "notes": "—"})
        status = file_info.get("status", "⏳ Pending")
        agent = file_info.get("agent", "—")
        updated = file_info.get("updated", "—")
        notes = file_info.get("notes", "—")
        rows.append(f"| {filename} | {status} | {agent} | {updated} | {notes} |")
        
    # 2. Blockers
    rows.append("\n## Blockers\n")
    all_blockers = data.get("blockers", [])
    resolved = data.get("resolved_blockers", [])
    
    if not all_blockers and not resolved:
        rows.append("(none)\n")
    else:
        if all_blockers:
            for blocker in all_blockers:
                rows.append(f"- {blocker}")
        if resolved:
            rows.append("\n### Resolved Blockers:")
            for blocker in resolved:
                rows.append(f"- {blocker}")
                 
    # 3. Change Log
    rows.append("\n## Change Log\n")
    if data.get("change_log"):
        for entry in data["change_log"]:
            rows.append(f"- {entry}")
    else:
        rows.append("(none)")
            
    content = "\n".join(rows)
    return write_file(tracker_path, content, overwrite=True)

def initialize_tracker(project_path: str, file_sequence: list[str]) -> bool:
    """
    Writes the initial Tracker.md with all sequence files set to ⏳ Pending.
    Called once on /init. Overwrites any existing Tracker.md.
    """
    data = {
        "files": {
            filename: {"status": "⏳ Pending", "agent": "—", "updated": "—", "notes": "—"}
            for filename in file_sequence
        },
        "modules": {},
        "blockers": [],
        "resolved_blockers": [],
        "change_log": []
    }
    return _save_tracker(project_path, data)

def update_file_status(project_path: str, filename: str, status: str, agent: str, notes: str = "") -> bool:
    """
    Updates a single file's row in Tracker.md.
    Valid statuses: ⏳, 🔄, 👀, ✅, ❌ — raises InvalidStatusError for anything else.
    """
    valid_emojis = {"⏳", "🔄", "👀", "✅", "❌"}
    
    # Extract emoji symbol
    found_emoji = None
    for emoji in valid_emojis:
        if emoji in status:
            found_emoji = emoji
            break
            
    if not found_emoji:
        raise InvalidStatusError(f"Status '{status}' does not contain a valid status emoji from {valid_emojis}.")
        
    # If notes are not provided, we can auto-fill some defaults based on status
    if not notes:
        if found_emoji == "❌":
            notes = "Waiting on user input/answers to questions."
        elif found_emoji == "👀":
            notes = "Draft complete. Waiting for user approval."
        elif found_emoji == "✅":
            notes = "Approved by user."
            
    data = read_tracker(project_path)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    data["files"][filename] = {
        "status": status,
        "agent": agent,
        "updated": now_str,
        "notes": notes
    }
    
    return _save_tracker(project_path, data)

def add_blocker(project_path: str, description: str, unblocked_by: str) -> bool:
    """Appends a blocker entry to Tracker.md blockers section."""
    data = read_tracker(project_path)
    blocker_entry = f"{description} (unblocked by: {unblocked_by})"
    if blocker_entry not in data["blockers"]:
        data["blockers"].append(blocker_entry)
    return _save_tracker(project_path, data)

def resolve_blocker(project_path: str, description: str) -> bool:
    """Marks a blocker as resolved, moves to a 'Resolved' subsection."""
    data = read_tracker(project_path)
    
    # Find matching blocker
    found_idx = -1
    for idx, blocker in enumerate(data["blockers"]):
        if description.lower() in blocker.lower():
            found_idx = idx
            break
            
    if found_idx != -1:
        resolved_blocker = data["blockers"].pop(found_idx)
        # Prefix with timestamp/resolved tag
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        data["resolved_blockers"].append(f"[RESOLVED at {now_str}] {resolved_blocker}")
        return _save_tracker(project_path, data)
        
    return False

def append_change_log(project_path: str, change_type: str, description: str, affected_files: list[str]) -> bool:
    """Appends one entry to Tracker.md change log with timestamp."""
    data = read_tracker(project_path)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    affected_str = ", ".join(affected_files) if affected_files else "None"
    entry = f"**[{now_str}] [{change_type}]** {description} (Affects: {affected_str})"
    data["change_log"].append(entry)
    return _save_tracker(project_path, data)

def get_next_pending_file(project_path: str, sequence: list[str]) -> str | None:
    """
    Given the main sequence list, returns the first file that is ⏳ Pending or ❌ Blocked.
    """
    data = read_tracker(project_path)
    for filename in sequence:
        file_info = data["files"].get(filename)
        if file_info:
            status = file_info["status"]
            if "⏳" in status or "❌" in status:
                return filename
    return None

def get_status_summary(project_path: str) -> str:
    """Returns Tracker.md status table as a formatted string for display in TUI."""
    data = read_tracker(project_path)
    
    rows = []
    rows.append("| File | Status | Agent | Updated | Notes |")
    rows.append("|---|---|---|---|---|")
    
    for filename, _ in TRACKED_FILES:
        file_info = data["files"].get(filename, {"status": "⏳ Pending", "agent": "—", "updated": "—", "notes": "—"})
        rows.append(f"| {filename} | {file_info.get('status', '⏳ Pending')} | {file_info.get('agent', '—')} | {file_info.get('updated', '—')} | {file_info.get('notes', '—')} |")
        
    return "\n".join(rows)
