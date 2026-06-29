# UPDATES AGENT — Spec
> Drop this file into your AI IDE as the implementation brief for the Updates Agent.
> This agent is called when plans change mid-session. It diffs the change, determines blast radius, and selectively re-runs only the affected specialist agents.

---

## Role

The Updates Agent is a **selective re-orchestrator**. It does not rewrite everything — it:
1. Reads the current `StructuredIdea.md` and the incoming change
2. Understands what specifically changed (scope, stack, schema, constraints, etc.)
3. Determines which files are affected by that change (blast radius)
4. Calls only the affected specialist agents in dependency order, passing them change context
5. Updates Tracker.md to reflect which files were re-run and why

It never writes planning files itself. It only routes and coordinates, same as the Orchestrator.

---

## Invocation

### Via slash command (user-initiated)
User types in chat input:
```
/update <description of change>
```
Example:
```
/update We are dropping the mobile app. Backend + web only now.
/update Switched from PostgreSQL to SQLite because of deployment constraints.
/update Added a new user role: admin. Admins can delete any content.
```

### Via Orchestrator (agent-initiated)
The Orchestrator calls the Updates Agent when:
- User sends a plain-text revision request that affects `StructuredIdea.md` (not just one file)
- User runs `/describe <new info>` after planning is already underway
- A Griller/TechStackExpert decision fundamentally changes a previously approved file's assumptions

When called by Orchestrator, it passes:
```python
{
  "change_description": str,       # what changed, in plain English
  "changed_file": str,             # which file triggered the call (e.g. "StructuredIdea.md")
  "current_state": OrchestratorState
}
```

---

## Agent Flow

### Step 1 — Ingest the change

Read `StructuredIdea.md` in full. Compare against the incoming `change_description`.

Produce a **Change Summary** (internal, not shown to user unless they ask):
```
Change type: [scope | stack | schema | constraint | role | feature | other]
What changed: [one sentence]
What was there before: [one sentence, inferred from StructuredIdea.md]
What replaces it: [one sentence from change_description]
Confidence: [high | medium | low — how clearly the change is specified]
```

If `confidence = low` → call **GrillerAgent** before proceeding. Pass the ambiguous parts as `pending_questions`. Do not guess and propagate a misunderstood change across all files.

### Step 2 — Update StructuredIdea.md

Before touching any specialist file:
- Rewrite the relevant section of `StructuredIdea.md` to reflect the change
- Append a change record at the bottom of the file:
```md
---
## Change Log
### [YYYY-MM-DD HH:MM] — [change_type]
**Change:** [what changed]
**Reason:** [user-stated reason, or "not stated"]
**Affects:** [list of files flagged for re-run]
```
`StructuredIdea.md` is the single source of truth. All downstream agents read from it — updating it first means specialist agents always get the correct context.

### Step 3 — Blast radius analysis

Determine which PLANNER/ files are affected using this dependency map:

```
Change type              → Files that must be re-run
─────────────────────────────────────────────────────
scope (features added/   → PRD, TRD, AppFlow (if frontend), Tracker,
removed/changed)           ImplementationPlan, MODULES/ (affected ones)

stack change             → TRD, Schema (if DB changed), DesignDecisions,
                           Rules, CLAUDE.md, MODULES/ (affected ones)

schema / data model      → Schema, TRD (data section), MODULES/ (affected ones)

constraint change        → Constraints, TRD, DesignDecisions, Rules

new/changed user role    → PRD, AppFlow (if frontend), Schema (if role stored),
                           Rules (if permissions logic)

frontend added/removed   → TRD, AppFlow, DesignDecisions, ImplementationPlan

new module               → MODULES/<name>.md (new file, not re-run of existing)
```

Output a **Blast Radius Report** — shown to user before any re-run:
```
📋 Change detected: [change summary one-liner]

Files that need updating:
  • PRD.md          — feature list affected
  • TRD.md          — stack section affected
  • Schema.md       — tables affected
  • Tracker.md      — status reset for above files

Files NOT affected (unchanged):
  • Constraints.md
  • Rules.md
  • AppFlow.md

Proceed with updates? [yes / no / show details]
```

`show details` → show full Change Summary and reasoning per file before asking again.
`no` → abort, no files modified, change_description discarded.
`yes` → proceed to Step 4.

### Step 4 — Re-run specialist agents in dependency order

Run only the affected agents, in this order (same dependency order as main sequence — never run a downstream agent before its upstream dependency is updated):

```
Constraints → PRD → TRD → Schema → DesignDecisions → AppFlow → Rules → ImplementationPlan → Tracker → MODULES/
```

Skip any file not in the blast radius. Do not re-run approved files that are unaffected.

For each affected agent call, pass:
```python
{
  "target_file": "PRD.md",
  "structured_idea": <updated StructuredIdea.md>,
  "context_files": { <upstream files this agent reads> },
  "change_context": {
      "change_type": "scope",
      "what_changed": "Mobile app removed. Web only.",
      "what_was_before": "PRD included iOS + Android apps.",
      "impact_on_this_file": "Remove all mobile-specific user stories and acceptance criteria."
  }
}
```

The `change_context` field is the key addition vs a normal agent call — it tells the specialist exactly what to look for and change, rather than asking it to regenerate the whole file from scratch.

### Step 5 — Per-file approval gate

After each specialist agent rewrites its file:
1. Show user a diff summary:
```
✅ PRD.md updated.

Changes made:
  - Removed: "Mobile app" user story (US-04, US-05)
  - Removed: iOS/Android from target platforms
  - Added: "Web browser" as sole client platform

/approve PRD.md to accept, or describe further changes.
```
2. Wait for `/approve <file>` before running the next agent in the blast radius sequence
3. If user requests further changes → handle within that file's specialist agent (same revision loop as normal flow), then continue the blast radius sequence

### Step 6 — Tracker update

After all affected files are updated and approved:
- Update Tracker.md: all re-run files → `✅ Approved` (or `👀 Needs Review` if not yet approved)
- Append to Tracker.md change log: which files were re-run, what triggered it, timestamp
- If `has_frontend` status changed (frontend added or removed): update Orchestrator state flag, update Tracker.md accordingly

### Step 7 — CLAUDE.md invalidation

If CLAUDE.md exists (i.e. `/finalize` was already run):
```
⚠️  CLAUDE.md exists from a previous /finalize.
    It may now be out of date due to these changes.
    Re-run /finalize after approving all updates to regenerate it.
```
Do not auto-regenerate CLAUDE.md — user may have more changes coming. Flag it, let them decide when to re-finalize.

---

## What this agent does NOT do

- Does not rewrite every file on every change — only blast radius files
- Does not auto-approve updated files — user approves each one
- Does not modify `RawIdea.md` — that file is append-only, owned by the user
- Does not call the Architecture Diagram Watcher — the watcher fires automatically when files change on disk
- Does not make tech decisions — if the change implies a new stack decision, calls TechStackExpert via Griller flow, does not pick itself
- Does not run if no PLANNER/ files exist yet — returns error: `"No planning session found. Run /init first."`

---

## Edge cases

| Situation | Behaviour |
|---|---|
| Change affects a file that is still `⏳ Pending` (not yet written) | Skip — agent hasn't run yet, so it will naturally incorporate the change when it runs |
| Change affects a file that is `🔄 In Progress` | Halt current run, apply change to StructuredIdea.md, resume the in-progress agent with updated context |
| Change is to Constraints.md and contradicts an already-approved TRD stack choice | Flag as conflict, surface to user: `"New constraint conflicts with approved TRD decision [X]. Resolve before proceeding."` Do not silently overwrite. |
| User runs `/update` with no description | Prompt: `"What changed? Describe the update:"` — wait for input |
| Two `/update` calls in quick succession before first is approved | Queue the second, finish the first fully (all approvals), then process the second |

---

## State

```python
class UpdatesAgentState(TypedDict):
    change_description: str          # raw user input or orchestrator-passed description
    change_summary: dict             # parsed: type, what_changed, before, after, confidence
    blast_radius: list[str]          # ordered list of files to re-run
    files_updated: list[str]         # files successfully re-run so far
    files_pending: list[str]         # files in blast radius not yet re-run
    current_target: str              # file currently being re-run
    change_context: dict             # per-file impact context passed to specialists
    triggered_by: str                # "user_command" | "orchestrator"
```

---

## Implementation notes for the IDE

- Lives in: `planner/agents/updates_agent.py`
- The blast radius analysis is an LLM call, not hardcoded logic — pass the change summary + list of all current PLANNER/ files + the dependency map (above) and ask the LLM to determine which files are affected and why. The dependency map in this spec is the prompt content for that call.
- `change_context["impact_on_this_file"]` must be generated per file — one LLM call that takes the change summary + the current file content and returns a one-sentence description of what specifically needs to change in that file. This is what makes specialist agents precise on updates rather than doing full rewrites.
- Diff summary shown to user (Step 5) is generated by comparing the file content before and after the specialist agent runs — read file before calling agent, read again after, produce a semantic diff summary (not a raw git diff).
- The queuing behavior for rapid `/update` calls can be implemented as a simple list in OrchestratorState — `pending_updates: list[str]`. Orchestrator appends to it; Updates Agent processes one at a time.
- Register `/update` command in `tui/widgets/chat_input.py` → dispatch to `UpdatesAgent.run()` with the text after `/update` as `change_description`.
- If called by Orchestrator (not user slash command), `triggered_by = "orchestrator"` — in this case skip the Blast Radius Report display (Orchestrator already showed the user what's happening) and go straight to Step 4.
