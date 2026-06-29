# TrackerAgent — Demotion Fix
> TrackerAgent is removed as a LangGraph graph node.
> All Tracker.md operations become direct `tracker_tools` calls at the exact point in code where the state change happens.

---

## Problem

TrackerAgent was a LangGraph graph node. Its job: update Tracker.md after every other agent ran.

This caused two structural problems:

**Problem A — Graph topology explosion**
To update Tracker.md after every agent, the graph needed an edge from every node to TrackerAgent and back. That's 12+ conditional edges all funnelling into one node for a task that is a deterministic file write — no LLM, no decisions, just `update status → write file`.

```
PRDAgent ──────────────────────► TrackerAgent ──► Orchestrator
TRDAgent ──────────────────────► TrackerAgent ──► Orchestrator
SchemaAgent ───────────────────► TrackerAgent ──► Orchestrator
...12 agents total
```

Every one of those hops goes through LangGraph's full node invocation: state serialization, edge routing, checkpoint write. For a file write that takes 2ms, this overhead is pure waste.

**Problem B — Wrong abstraction**
Agent nodes are for LLM calls — they exist to generate content. Tracker updates need zero LLM involvement. Putting a deterministic file write in a graph node is the wrong abstraction. It also means the "Tracker Agent" has no prompt, no LLM client, and no reason to be an agent.

---

## Fix

**Remove TrackerAgent from the graph entirely.**

Every Tracker.md write becomes a direct call to `tracker_tools` at the exact line in code where the state change occurs. No graph hop. No node invocation. No routing.

```python
# Before (wrong) — graph hop to TrackerAgent node
state["next_agent"] = "tracker_agent"
return state

# After (correct) — inline tool call
from planner.tools import update_file_status
update_file_status(project_path, "PRD.md", "👀", "prd_agent", notes="")
# continue execution, no routing needed
```

---

## Tracker.md still exists as a file

Demoting TrackerAgent does not affect Tracker.md the file. It still exists, still tracks status, still has the same format. The only thing removed is the agent node that wrote to it. The writes now happen inline via `tracker_tools`.

---

## Call Map — Who Calls What, When

Every Tracker.md write that previously went through TrackerAgent now happens inline. Full list:

### In `orchestrator.py`

| Event | tracker_tools call |
|---|---|
| `scaffold_planner()` completes (on `/init`) | `update_file_status(path, file, "⏳", "none")` for every file in sequence |
| StructuringAgent returns StructuredIdea.md | `update_file_status(path, "StructuredIdea.md", "✅", "structuring_agent")` |
| Specialist agent writes a file | `update_file_status(path, file, "👀", agent_name)` |
| User `/approve <file>` | `update_file_status(path, file, "✅", "user")` |
| `/run` skips file (backend-only, frontend not detected) | `update_file_status(path, file, "✅", "orchestrator", notes="Skipped — backend-only")` |
| LLM failure in any agent, user chooses `no` | `update_file_status(path, file, "❌", agent_name, notes=error_message)` + `add_blocker(path, description, unblocked_by)` |
| LLM failure, user chooses retry + succeeds | `update_file_status(path, file, "👀", agent_name)` (overwrite blocked status) |
| `/reset <file>` confirmed | `update_file_status(path, file, "⏳", "user", notes="Reset by user")` |
| Sequence complete (all files approved) | `append_change_log(path, "sequence_complete", "All files written and approved", [])` |
| Frontend detection sets `has_frontend = False` | `update_file_status(path, "DesignDecisions.md", "✅", "orchestrator", notes="Skipped — backend-only")` + same for AppFlow.md |

### In `updates_agent` handler (orchestrator.py `update` command)

| Event | tracker_tools call |
|---|---|
| Blast radius file starts re-run | `update_file_status(path, file, "🔄", "updates_agent")` |
| Blast radius file written | `update_file_status(path, file, "👀", agent_name)` |
| Blast radius file approved | `update_file_status(path, file, "✅", "user")` |
| Update aborted mid-run (user said no at approval gate) | `add_blocker(path, file, "Update aborted mid-run — re-run /update to complete")` for remaining files |
| Full update complete | `append_change_log(path, "update", change_summary.what_changed, blast_radius_files)` |

### In `griller_agent.py`

| Event | tracker_tools call |
|---|---|
| Griller pauses sequence to ask questions | `update_file_status(path, current_file, "❌", "griller_agent", notes="Awaiting user input")` |
| Griller answers filled, specialist resumes | `update_file_status(path, current_file, "🔄", specialist_agent_name)` |

### In specialist agents (`prd_agent.py`, `trd_agent.py`, etc.)

Specialist agents do **not** call tracker_tools directly. They have no awareness of Tracker.md. They write their file and return. The Orchestrator makes the tracker call after receiving the result.

This preserves single responsibility: specialists only write their one file.

---

## What Happens to `tracker_agent.py`

The file stays but is gutted. It becomes a thin module with one function used only for the `/status` command display — formatting the Tracker.md dict into a human-readable string for the TUI Viewer panel. This is not a graph node; it's a helper called by the Orchestrator's `status` command handler.

```python
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
```

That's the entire file. Everything else that was in TrackerAgent moves to `tracker_tools.py` or the Orchestrator's command handlers.

---

## `tracker_tools.py` — Updates

The existing functions in `tracker_tools.py` are already sufficient. Two additions needed:

### New: `initialize_tracker(project_path: str, file_sequence: list[str]) -> bool`
Called once by Orchestrator on `/init` after `scaffold_planner()`.

```python
def initialize_tracker(project_path: str, file_sequence: list[str]) -> bool:
    """
    Writes the initial Tracker.md with all sequence files set to ⏳ Pending.
    Called once on /init. Overwrites any existing Tracker.md.
    """
```

Generates:
```md
# Tracker.md
Last updated: YYYY-MM-DD HH:MM

## Status

| File | Status | Agent | Updated | Notes |
|---|---|---|---|---|
| StructuredIdea.md | ⏳ Pending | — | — | — |
| Constraints.md | ⏳ Pending | — | — | — |
| PRD.md | ⏳ Pending | — | — | — |
| TRD.md | ⏳ Pending | — | — | — |
| Schema.md | ⏳ Pending | — | — | — |
| DesignDecisions.md | ⏳ Pending | — | — | — |
| AppFlow.md | ⏳ Pending | — | — | — |
| Rules.md | ⏳ Pending | — | — | — |
| ImplementationPlan.md | ⏳ Pending | — | — | — |
| MODULES/ | ⏳ Pending | — | — | — |

## Blockers
(none)

## Change Log
(none)
```

### Updated: `update_file_status()` — add `updated_at` auto-stamp

The existing signature:
```python
def update_file_status(project_path: str, filename: str, status: str, agent: str, notes: str = "") -> bool
```
Add automatic `updated_at` timestamp (current datetime) on every call. No caller should pass a timestamp — it's always now.

---

## `graph.py` — Changes

Remove TrackerAgent from graph entirely.

```python
# BEFORE — TrackerAgent as a node (remove this)
graph.add_node("tracker_agent", tracker_agent.run)
graph.add_edge("prd_agent", "tracker_agent")
graph.add_edge("trd_agent", "tracker_agent")
graph.add_edge("tracker_agent", "orchestrator")
# ... 12 more edges

# AFTER — no TrackerAgent node, no tracker edges
# Nothing to add. TrackerAgent is gone from the graph.
# Tracker updates happen inline via tracker_tools calls.
```

The graph becomes simpler:
```
orchestrator
├──► structuring_agent → orchestrator
├──► prd_agent → orchestrator
├──► trd_agent → orchestrator
├──► schema_agent → orchestrator
├──► design_agent → orchestrator
├──► appflow_agent → orchestrator
├──► rules_agent → orchestrator
├──► implementation_agent → orchestrator
├──► griller_agent → orchestrator
├──► tech_stack_agent → orchestrator
├──► module_planner_agent → orchestrator
├──► consistency_agent → orchestrator
└──► finalizer_agent → orchestrator
```

All edges are `agent → orchestrator`. No inter-agent edges. No TrackerAgent in the middle.

---

## Tracker.md as part of the planning sequence — change

In the original Plan Board, Tracker.md appeared in the main file sequence:
```
... → AppFlow.md → Tracker.md → Rules.md → ...
```

Tracker.md is not a planning document written by an LLM. Remove it from the main sequence. It is a live status file maintained incrementally throughout the run, not generated once at a fixed point.

**Updated sequence:**
```
StructuredIdea.md → Constraints.md → PRD.md → TRD.md → Schema.md →
DesignDecisions.md → AppFlow.md → Rules.md → ImplementationPlan.md → MODULES/
```

Tracker.md is initialised on `/init` and updated continuously. It is never in the sequence.

---

## Updated `tracker_tools.py` — Used By

Change "Used by: Orchestrator, Updates Agent, Tracker Agent" to:

**Used by:** Orchestrator (all command handlers), GrillerAgent (pause/resume status), `tracker_agent.py` format helper (`get_status_summary` only).

Specialist agents never import `tracker_tools` directly.

---

## Build Phase Impact

In `Agent_Upgrade_Plan.md`, the Tracker Agent upgrade step (Agent 11) changes:

**Before:** Upgrade the TrackerAgent node — system prompt, status symbols, change log format.

**After:** No agent to upgrade. Instead:
- [ ] Implement `initialize_tracker()` in `tracker_tools.py`
- [ ] Add `updated_at` auto-stamp to `update_file_status()`
- [ ] Audit every state-change point in `orchestrator.py` and add the correct `tracker_tools` call (use the call map above)
- [ ] Audit `griller_agent.py` — add pause/resume status calls
- [ ] Remove TrackerAgent node from `graph.py`
- [ ] Gut `tracker_agent.py` to the single `format_status_for_display()` function
- [ ] Remove Tracker.md from main file sequence in `graph.py` sequence list
- [ ] Verify: after a full `/run`, Tracker.md reflects accurate status for every file at every stage

---

## Summary

| What | Before | After |
|---|---|---|
| TrackerAgent | LangGraph node, 12+ incoming edges | Removed from graph |
| Tracker.md writes | Routed through TrackerAgent node | Inline `tracker_tools` calls at point of state change |
| `tracker_agent.py` | Full agent with run() method | Thin helper: one `format_status_for_display()` function |
| Graph edges | Each agent → TrackerAgent → Orchestrator | Each agent → Orchestrator (direct) |
| Tracker.md in sequence | Step 7 of main sequence | Removed from sequence, maintained continuously |
| LLM calls for tracking | 0 (TrackerAgent had none — it was deterministic) | 0 (same, but now explicit) |
