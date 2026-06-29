# UPDATES AGENT — Fixed Spec
> Replaces `UPDATES_AGENT_SPEC.md` entirely.
> Fixes issue: Updates Agent was calling specialist agents directly, bypassing the Orchestrator.
> Fixes issue: StructuredIdea.md was mutated before blast radius was complete (partial update risk).

---

## What Changed and Why

### Problem 1 — Two call paths to specialists

**Before (broken):**
```
ExecutiveAgent → Orchestrator → UpdatesAgent → SpecialistAgent
                                             → SpecialistAgent
                                             → SpecialistAgent
```
The Updates Agent was routing to specialists directly. Any logic the Orchestrator applies when calling specialists (validation, approval gating, Tracker updates, context loading) had to be duplicated inside the Updates Agent. They would inevitably drift.

**After (fixed):**
```
ExecutiveAgent → Orchestrator → UpdatesAgent   (analysis only — returns UpdatePlan)
                Orchestrator  ← UpdatesAgent
                Orchestrator  → SpecialistAgent  (via its existing call path)
                Orchestrator  → SpecialistAgent
                Orchestrator  → SpecialistAgent
```
The Updates Agent is now a **pure analysis agent**. It produces an `UpdatePlan` and returns it. The Orchestrator executes the plan using the exact same specialist-calling logic it uses for `/run`. One call path to specialists, always.

### Problem 2 — Partial update risk (StructuredIdea.md mutated too early)

**Before (broken):** StructuredIdea.md was updated in Step 2, before any specialist ran. If a specialist failed mid-blast-radius, StructuredIdea.md reflected the new state but downstream files reflected the old state. No recovery path.

**After (fixed):** StructuredIdea.md is updated **last** — only after all blast-radius files are approved. During the update run, specialists receive the change via `change_context` (the delta), not from a prematurely mutated source file. StructuredIdea.md is the committed state; it only advances when the full update succeeds.

---

## Updated Communication Flow

```
1. User types /update <description>
2. ExecutiveAgent → Orchestrator: {"command": "update", "text": "<description>"}
3. Orchestrator → UpdatesAgent: {change_description, structured_idea, all_file_contents}
4. UpdatesAgent:
     a. Produces Change Summary
     b. If confidence low → requests Griller clarification via Orchestrator
     c. Determines blast radius
     d. Generates per-file change_context
     e. Returns UpdatePlan to Orchestrator
5. Orchestrator → ExecutiveAgent: {"type": "blast_radius_report", ...}
6. User approves → ExecutiveAgent → Orchestrator: {"command": "update_confirmed"}
7. Orchestrator iterates blast_radius in order:
     → calls each SpecialistAgent via its existing /run call path
     → passes change_context alongside normal context_files
     → applies normal approval gate per file
8. After ALL files approved:
     Orchestrator writes updated StructuredIdea.md
     Orchestrator appends change log to StructuredIdea.md
     Orchestrator updates Tracker.md change log
     Orchestrator checks for CLAUDE.md staleness
```

---

## UPDATES AGENT SPEC
> File: `planner/agents/updates_agent.py`
> Role: Analysis only. No specialist calls. No file writes. Returns UpdatePlan.

---

## Role

The UpdatesAgent is a **change analyst**. Given a change description and current project state, it:
1. Understands what specifically changed
2. Clarifies ambiguity via Griller (routed through Orchestrator) if needed
3. Determines which files are affected (blast radius)
4. Generates per-file impact summaries (change_context)
5. Returns a structured `UpdatePlan` to the Orchestrator

It never calls specialist agents. It never writes files. It never talks to the user. It returns a plan and stops.

---

## Inputs (from Orchestrator)

```python
{
  "change_description": str,           # raw /update text from user
  "structured_idea": str,              # current StructuredIdea.md content (unmodified)
  "all_files": dict[str, str],         # all non-empty PLANNER/ files: {filename: content}
  "tracker_state": dict,               # current file statuses from Tracker.md
}
```

---

## Step 1 — Produce Change Summary

LLM call. Read `structured_idea` + `change_description`. Output:

```python
{
  "change_type": str,        # "scope" | "stack" | "schema" | "constraint" | "role" | "feature" | "other"
  "what_changed": str,       # one sentence: what is different now
  "what_was_before": str,    # one sentence: inferred from StructuredIdea.md
  "what_replaces_it": str,   # one sentence: from change_description
  "confidence": str,         # "high" | "medium" | "low"
  "ambiguous_parts": list[str]  # questions to clarify if confidence != "high"
}
```

If `confidence = low`: return to Orchestrator with `needs_clarification: True` and `ambiguous_parts`. Orchestrator routes these as `pending_questions` to GrillerAgent via its standard missing-info flow. Orchestrator calls UpdatesAgent again once answers are filled in state.

---

## Step 2 — Blast Radius Analysis

LLM call using the dependency map as prompt context. Determine which files need re-running based on `change_type` and `change_summary`.

**Dependency map (inject into LLM prompt verbatim):**
```
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
```

**Blast radius output (per file):**
```python
[
  {
    "file": "PRD.md",
    "reason": "Feature list changed — mobile app removed",
    "priority": 1   # execution order within blast radius (1 = first)
  },
  {
    "file": "TRD.md",
    "reason": "Stack section must drop mobile-specific dependencies",
    "priority": 2
  },
  ...
]
```

**Skip rules (enforce these, do not pass to LLM — deterministic):**
- File is `⏳ Pending` → skip (will incorporate change naturally when first written)
- File is `🔄 In Progress` → flag as `conflict: True` in UpdatePlan (Orchestrator halts current run, injects change, resumes)
- File is not in PLANNER/ sequence (e.g. RawIdea.md) → always skip

---

## Step 3 — Generate Per-File Change Context

For each file in the blast radius: one focused LLM call.

Input: `change_summary` + current content of that specific file.
Output: one-sentence `impact_on_this_file` — what the specialist agent should look for and change.

```python
{
  "PRD.md": {
    "change_type": "scope",
    "what_changed": "Mobile app removed. Web only now.",
    "what_was_before": "PRD included iOS and Android user stories.",
    "impact_on_this_file": "Remove all mobile-specific user stories (US-04, US-05) and platform references."
  },
  "TRD.md": {
    "change_type": "scope",
    "what_changed": "Mobile app removed. Web only now.",
    "what_was_before": "TRD included React Native and mobile deployment sections.",
    "impact_on_this_file": "Remove React Native from tech stack, drop mobile deployment section, update NFRs to web-only."
  }
}
```

This is the key mechanism that makes specialist agents surgical on updates. They receive explicit instruction on what to change in their specific file — not just the global change description.

---

## Step 4 — Produce Updated StructuredIdea Draft

LLM call. Produce an updated version of StructuredIdea.md reflecting the change.

**This is NOT written to disk yet.** It is returned as `structured_idea_draft` in the UpdatePlan. The Orchestrator writes it to disk only after all blast-radius files are approved.

```python
{
  "structured_idea_draft": str,   # full new StructuredIdea.md content
  "change_log_entry": str         # formatted entry to append to StructuredIdea.md change log
}
```

---

## Returns to Orchestrator — UpdatePlan

```python
class UpdatePlan(TypedDict):
    change_summary: dict             # type, what_changed, before, after
    blast_radius: list[dict]         # [{file, reason, priority}], sorted by priority
    change_context: dict[str, dict]  # per-file impact context for each blast radius file
    structured_idea_draft: str       # updated StructuredIdea.md — NOT written yet
    change_log_entry: str            # formatted entry for StructuredIdea.md change log
    has_conflicts: bool              # True if any blast radius file is 🔄 In Progress
    conflict_files: list[str]        # files that are mid-run and need special handling
    frontend_changed: bool           # True if has_frontend flag needs updating
    new_frontend_value: bool         # new value of has_frontend if it changed
    needs_clarification: bool        # True if confidence was low, Griller needed
    ambiguous_parts: list[str]       # questions for Griller (if needs_clarification)
```

---

## ORCHESTRATOR — /update Command Handler (New)

> Replaces the old Updates Agent Step 4–7 logic that was incorrectly living inside Updates Agent.
> Add this handler to `planner/agents/orchestrator.py`.

### Handler: `update`

Receives from ExecutiveAgent: `{"command": "update", "text": "<change_description>"}`

```
1. Load all current PLANNER/ file contents + tracker_state into memory

2. Call UpdatesAgent with:
   {change_description, structured_idea, all_files, tracker_state}

3. If UpdatePlan.needs_clarification:
   a. Treat UpdatePlan.ambiguous_parts as pending_questions
   b. Route to GrillerAgent via standard missing-info flow
   c. Once answered: re-call UpdatesAgent with clarified change_description
   d. Get new UpdatePlan

4. If UpdatePlan.has_conflicts:
   a. Send to ExecutiveAgent:
      {"type": "update_conflict", "files": conflict_files,
       "message": "These files are mid-run. Halt current run and apply change? [yes / no]"}
   b. If yes: mark conflict files as ⏳ Pending in Tracker, proceed
   c. If no: abort update entirely

5. Send Blast Radius Report to ExecutiveAgent:
   {"type": "blast_radius_report",
    "change_summary": UpdatePlan.change_summary,
    "affected_files": [{file, reason} for each in blast_radius],
    "unaffected_files": [all PLANNER/ files NOT in blast_radius]}
   Wait for user confirmation.

6. On user confirms:
   If UpdatePlan.frontend_changed:
     Update has_frontend in OrchestratorState
     Update Tracker.md accordingly

7. Execute blast radius in priority order.
   For each file in UpdatePlan.blast_radius (sorted by priority):

     a. Load context_files for this specialist (upstream files only)

     b. Call specialist via EXISTING /run call path, injecting change_context:
        {
          "target_file": file,
          "structured_idea": <current StructuredIdea.md — unmodified>,
          "context_files": {...upstream files...},
          "change_context": UpdatePlan.change_context[file],
          "fit_analysis": state.fit_analysis   (hybrid mode only)
        }
        NOTE: structured_idea passed here is the CURRENT unmodified version.
        The change_context carries the delta. Specialists apply it as an edit.

     c. Validate output via validate_file_structure()

     d. Update Tracker.md: file → 👀 Needs Review

     e. Send to ExecutiveAgent:
        {"type": "file_complete", "file": file, "summary": [...], "context": "update"}
        Wait for /approve before next file in blast radius.

     f. On /approve: update Tracker.md → ✅, continue to next file

8. After ALL blast radius files approved:

     a. Write UpdatePlan.structured_idea_draft → StructuredIdea.md
        (this is the ONLY moment StructuredIdea.md is mutated)

     b. Append UpdatePlan.change_log_entry to StructuredIdea.md change log

     c. Update Tracker.md change log: which files re-run, what triggered it, timestamp

     d. If CLAUDE.md exists at project root:
        Send to ExecutiveAgent:
        {"type": "stale_warning",
         "message": "CLAUDE.md is now out of date. Re-run /finalize to regenerate."}

9. Update sequence_index if blast radius re-ran files beyond current index
```

### Two-phase commit guarantee

StructuredIdea.md is written in step 8a, after all approvals. If user aborts mid-blast-radius (says `no` at any approval gate), the abort state is:
- StructuredIdea.md = unchanged (original)
- Some blast-radius files = updated + approved
- Remaining blast-radius files = unchanged

This is a known partial-update state. Orchestrator marks remaining blast-radius files as `❌ Blocked` in Tracker.md with the note `"Update aborted mid-run — re-run /update to complete"`. User can either re-run `/update` with the same description (Orchestrator skips already-approved files in the blast radius) or manually `/reset` affected files.

---

## Edge Cases (Orchestrator owns these, not Updates Agent)

| Situation | Handler |
|---|---|
| Change affects `⏳ Pending` file | Updates Agent skips it in blast radius. Orchestrator notes it will be handled naturally when that file's specialist runs during `/run` |
| Change affects `🔄 In Progress` file | UpdatePlan.has_conflicts = True. Orchestrator halts, confirms with user, marks file ⏳ Pending, injects change_context into next run |
| New constraint contradicts approved TRD stack choice | ConsistencyAgent detects it after blast radius completes. Or: UpdatesAgent flags it as a conflict in Change Summary |
| `/update` with no description | ExecutiveAgent catches this before routing to Orchestrator: prompts user for description |
| Two `/update` calls before first is approved | Orchestrator queues second in `pending_updates: list[str]`. Processes one at a time. ExecutiveAgent shows: `"Update queued. Will run after current update is complete."` |
| Blast radius is empty (change has no effect on any file) | Orchestrator receives UpdatePlan with empty blast_radius. Sends to ExecutiveAgent: `"No files affected by this change."` Does not update StructuredIdea.md. |

---

## State (UpdatesAgent — used only during analysis call, discarded after)

```python
class UpdatesAgentState(TypedDict):
    change_description: str
    change_summary: dict
    blast_radius: list[dict]
    change_context: dict[str, dict]
    structured_idea_draft: str
    change_log_entry: str
    needs_clarification: bool
    ambiguous_parts: list[str]
    has_conflicts: bool
    conflict_files: list[str]
    frontend_changed: bool
    new_frontend_value: bool
```

This state is local to one UpdatesAgent invocation. Once UpdatePlan is returned to the Orchestrator, this state is discarded. The Orchestrator maintains the execution state of the update run in its own `OrchestratorState`.

---

## Implementation Notes

- `planner/agents/updates_agent.py` — contains only Steps 1–4 (analysis). No `run_specialist()` call anywhere in this file.
- All blast radius execution (Steps 7–9 in the Orchestrator handler above) lives in `planner/agents/orchestrator.py` under the `update` command handler.
- The specialist call in step 7b must reuse the exact same method the Orchestrator uses for `/run` — not a copy. Extract into a shared `_call_specialist(target_file, context, change_context=None)` private method on the Orchestrator class. Both `/run` and `/update` call this method. `change_context` is `None` during normal `/run`, populated during `/update`.
- `change_context` is passed through `PlannerState` as an optional field. Specialists check: `if state.change_context: apply as targeted edit; else: generate from scratch`. This is the ONLY behavioral difference between a normal run and an update run for a specialist.
- Partial-update recovery: on abort, use `tracker_tools.add_blocker()` for remaining blast-radius files with the message `"Update aborted — re-run /update '<same description>' to complete"`.
