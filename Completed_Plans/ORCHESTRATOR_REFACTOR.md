# Orchestrator Refactor + Executive Agent
> Replaces `ORCHESTRATOR_AGENT_SPEC.md` entirely.
> Drop all files in this document into your AI IDE as implementation briefs.

---

## What Changed and Why

The original Orchestrator was a god agent with 4 distinct responsibilities:
- User I/O (greetings, prompts, approval gates, command parsing)
- LLM content generation (StructuredIdea.md, Fit Analysis, CLAUDE.md, /consistency)
- Routing + sequencing
- State + Tracker management

These are now split into 5 agents with single responsibilities:

| Old (god agent) | New (split) |
|---|---|
| User I/O, command parsing, displaying output | → `ExecutiveAgent` |
| Routing, sequencing, state management | → `OrchestratorAgent` (now pure) |
| StructuredIdea.md + Fit Analysis generation | → `StructuringAgent` |
| /consistency cross-file check | → `ConsistencyAgent` |
| /finalize + CLAUDE.md compilation | → `FinalizerAgent` |

---

## Communication Architecture

```
User
 │
 ▼
ExecutiveAgent          ← sole user-facing agent. No routing decisions.
 │   ▲
 │   │  (structured commands up, display payloads down)
 ▼   │
OrchestratorAgent       ← pure router. No LLM calls. No user I/O.
 │
 ├──► StructuringAgent
 ├──► PRDAgent
 ├──► TRDAgent
 ├──► SchemaAgent
 ├──► DesignDecisionsAgent
 ├──► AppFlowAgent
 ├──► RulesAgent
 ├──► ImplementationPlannerAgent
 ├──► GrillerAgent
 ├──► TechStackExpertAgent
 ├──► ModulePlannerAgent
 ├──► ConsistencyAgent
 └──► FinalizerAgent

[Architecture Watcher runs independently as a separate process — not in the graph]
```

**Flow for every interaction:**
1. User types in chat input → `ExecutiveAgent` receives it
2. `ExecutiveAgent` parses it (slash command or plain text) → sends structured payload to `OrchestratorAgent`
3. `OrchestratorAgent` decides which agent(s) to call → calls them
4. Agent(s) complete → return result to `OrchestratorAgent`
5. `OrchestratorAgent` packages result as a display payload → sends to `ExecutiveAgent`
6. `ExecutiveAgent` renders it to the user (Viewer panel, chat output, approval prompt)

The user never talks to the Orchestrator directly. The Orchestrator never talks to the user directly.

---

---
# EXECUTIVE AGENT SPEC
> File: `planner/agents/executive_agent.py`

---

## Role

The ExecutiveAgent is the **only agent that communicates with the user**. It:
- Receives all raw user input (slash commands, plain text, approvals)
- Parses and validates input before passing it to the Orchestrator
- Renders all output from the Orchestrator to the user (Viewer panel, chat, approval gates)
- Manages the startup flow (mode selection, resume prompt)
- Never makes routing decisions
- Never calls specialist agents directly
- Never makes LLM calls of its own — it is purely an I/O bridge

Think of it as the **frontend** to the Orchestrator's backend.

---

## Startup Flow

On cold start (no PLANNER/ exists) or `/init`:

```
Welcome to PlannerX.

How would you like to start?

  [1] From scratch — I have a raw idea, help me plan it fully
  [2] PS + Idea — I have a problem statement and a proposed solution

Type 1 or 2 to begin.
```

Receive user input → validate it's `1` or `2` → send to Orchestrator as:
```python
{"command": "set_mode", "mode": "from_scratch" | "ps_idea_hybrid"}
```

On session resume (PLANNER/ exists):
- Request Tracker.md summary from Orchestrator: `{"command": "get_status"}`
- Render the returned status table in Viewer panel
- Prompt:
```
Resuming session. Last status shown above.
Continue from where we left off? [yes / no]
```
- Send response to Orchestrator: `{"command": "resume", "confirmed": True | False}`

---

## Input Parsing

All user input hits the ExecutiveAgent first. It classifies and packages it before passing to Orchestrator.

### Slash commands
| Input | Parsed payload sent to Orchestrator |
|---|---|
| `/init` | `{"command": "init"}` |
| `/describe <text>` | `{"command": "describe", "text": "<text>"}` |
| `/run` | `{"command": "run"}` |
| `/approve <file>` | `{"command": "approve", "file": "<file>"}` |
| `/status` | `{"command": "status"}` |
| `/edit <file>` | `{"command": "edit", "file": "<file>"}` |
| `/reset <file>` | `{"command": "reset", "file": "<file>"}` |
| `/module add <name>` | `{"command": "module_add", "name": "<name>"}` |
| `/module list` | `{"command": "module_list"}` |
| `/update <text>` | `{"command": "update", "text": "<text>"}` |
| `/consistency` | `{"command": "consistency"}` |
| `/finalize` | `{"command": "finalize"}` |
| `/diagram` | `{"command": "diagram"}` |

### Plain text (no `/`)
- If Orchestrator state has `active_revision_target` set (a file in `👀 Needs Review`):
  → send as: `{"command": "revise", "target": "<file>", "request": "<text>"}`
- Otherwise:
  → send as: `{"command": "chat", "text": "<text>"}` (general question, Orchestrator answers from context)

### Validation rules (Executive enforces these before sending to Orchestrator)
- `/approve` without a filename → prompt: `"Which file? e.g. /approve PRD.md"`
- `/reset` without a filename → prompt: `"Which file? e.g. /reset PRD.md"`
- `/edit` without a filename → prompt: `"Which file? e.g. /edit PRD.md"`
- Unknown `/command` → prompt: `"Unknown command. Type /help for available commands."`
- Empty input → ignore silently

---

## Output Rendering

The Orchestrator returns structured display payloads to the ExecutiveAgent. The ExecutiveAgent renders them — it does not interpret them.

### Payload types and how to render each:

**`file_complete`** — specialist agent finished writing a file
```python
{"type": "file_complete", "file": "PRD.md", "summary": ["...", "..."], "agent": "prd_agent"}
```
Render in Viewer panel:
```
✅ PRD.md written by PRDAgent.

Key decisions:
  • [summary[0]]
  • [summary[1]]

Type /approve PRD.md to accept, or describe changes to revise it.
```

**`file_approved`** — user approved a file
```python
{"type": "file_approved", "file": "PRD.md", "next_file": "TRD.md"}
```
Render:
```
✅ PRD.md approved. Moving to TRD.md...
```

**`question`** — Griller asking the user something
```python
{"type": "question", "text": "Will users need authentication?", "reason": "Needed for TRD security section.", "source_agent": "trd_agent"}
```
Render in chat output:
```
❓ [TRDAgent needs info]
   Will users need authentication?
   (Reason: Needed for TRD security section.)

Type your answer, or type "I don't know" to get a suggestion.
```

**`suggestion`** — TechStackExpert recommendation
```python
{"type": "suggestion", "tool": "PostgreSQL", "why": "...", "tradeoff": "...", "alternative": "SQLite"}
```
Render:
```
💡 Suggestion: PostgreSQL
   Why: [why]
   Trade-off: [tradeoff]
   Alternative if rejected: SQLite

Accept this suggestion? [yes / no]
```

**`error`** — LLM failure in any agent
```python
{"type": "error", "agent": "SchemaAgent", "message": "Timeout after 30s"}
```
Render:
```
⚠️  Error in SchemaAgent: Timeout after 30s

Retry this agent? [yes / no]
```

**`status_table`** — Tracker.md summary
```python
{"type": "status_table", "rows": [...]}
```
Render as formatted table in Viewer panel.

**`fit_analysis`** — hybrid mode only, after StructuringAgent runs
```python
{"type": "fit_analysis", "content": "...", "has_gaps": True}
```
Render full Fit Analysis in Viewer panel, then:
```
Gaps or risks identified above may affect planning.
Proceed with current scope? Or revise your solution first? [proceed / revise]
```

**`consistency_report`** — from ConsistencyAgent
```python
{"type": "consistency_report", "issues": [...]}
```
Render each issue in Viewer panel. Add footer: `"No auto-fix applied. Use /reset <file> to re-run a specific agent."`

**`finalized`** — from FinalizerAgent
```python
{"type": "finalized", "warnings": [...]}
```
Render any incomplete-file warnings, then:
```
✅ CLAUDE.md generated at project root.
Planning phase complete. You can now begin implementation.
```

**`chat_response`** — answer to plain text question
```python
{"type": "chat_response", "text": "..."}
```
Render directly in chat output. No special formatting.

**`confirmation_required`** — destructive or irreversible action
```python
{"type": "confirmation_required", "action": "reset PRD.md", "warning": "This will clear PRD.md and re-run the PRD agent."}
```
Render:
```
⚠️  This will clear PRD.md and re-run the PRD agent.
Confirm? [yes / no]
```

---

## State (ExecutiveAgent maintains)

```python
class ExecutiveState(TypedDict):
    waiting_for: str        # what we're waiting on from the user:
                            # "mode_select" | "resume_confirm" | "approval" |
                            # "question_answer" | "suggestion_confirm" |
                            # "retry_confirm" | "reset_confirm" | "fit_analysis_confirm" | ""
    pending_command: dict   # partially built command awaiting user confirmation
    last_display: str       # last thing shown to user (for context)
```

The ExecutiveAgent holds minimal state — just enough to know what it's waiting for. All session/planning state lives in the Orchestrator.

---

## Rules

1. Never route to any agent except the Orchestrator
2. Never make LLM calls
3. Never read or write PLANNER/ files directly — request content from Orchestrator, display what it returns
4. Never make planning decisions — if ambiguous input arrives, ask the user to clarify, then pass clarified input to Orchestrator
5. Never display raw state dict fields to the user — always render via payload type handlers above
6. If `waiting_for` is set and user sends an unrelated command → prompt: `"Please respond to the current prompt first, or type /cancel to abort."`

---

## Implementation notes

- Lives in: `planner/agents/executive_agent.py`
- `tui/widgets/chat_input.py` sends raw text to ExecutiveAgent — ExecutiveAgent does all parsing, not the widget
- `tui/widgets/viewer_panel.py` and the chat output area receive rendered strings from ExecutiveAgent — they do no logic, just display
- `/edit <file>` is handled by the ExecutiveAgent calling `editor_tools.open_in_editor()` directly (this is a UI action, not a planning action) — after editor closes, it notifies Orchestrator: `{"command": "edit_complete", "file": "<file>"}`
- `/diagram` triggers the watcher process directly from ExecutiveAgent via IPC signal (the watcher is not in the graph — no need to route through Orchestrator for this)

---

---
# ORCHESTRATOR AGENT SPEC (Revised)
> File: `planner/agents/orchestrator.py`
> This is now a pure router. Zero LLM calls. Zero user I/O.

---

## Role

The OrchestratorAgent receives structured commands from the ExecutiveAgent, decides which agent(s) to call, calls them in the right order, and returns structured display payloads back to the ExecutiveAgent. That is its entire job.

It never:
- Talks to the user
- Makes LLM calls
- Writes files
- Reads files (it delegates file reads to tools and passes results as context to agents)
- Makes content decisions

---

## Command Handlers

For each command received from ExecutiveAgent:

### `init`
1. Call `scaffold_planner()` from `file_tools`
2. Return: `{"type": "ready", "message": "PLANNER/ created."}` → ExecutiveAgent shows mode selection

### `set_mode`
1. Store `mode` in state
2. If `mode = "from_scratch"`: return `{"type": "prompt", "text": "Describe your idea. Type /done when finished."}`
3. If `mode = "ps_idea_hybrid"`: return `{"type": "prompt", "text": "Paste your Problem Statement. Type /done when finished."}`

### `describe`
1. Append text to RawIdea.md via `append_file()`
2. Route to `StructuringAgent`, pass: `{raw_idea, mode}`
3. `StructuringAgent` returns: `{structured_idea, fit_analysis (hybrid only)}`
4. Write result to `StructuredIdea.md` via `write_file()`
5. Update Tracker.md: StructuredIdea.md → `✅`
6. If hybrid: return `{"type": "fit_analysis", "content": fit_analysis, "has_gaps": bool}`
7. If from_scratch: return `{"type": "ready_to_run"}`

### `run`
1. Read Tracker.md → find first `⏳ Pending` file in sequence
2. Load `structured_idea` and required `context_files` from disk
3. Call the correct specialist agent for that file
4. On return: validate output via `validate_file_structure()`
5. Update Tracker.md: file → `👀 Needs Review`
6. Return `{"type": "file_complete", "file": "...", "summary": [...], "agent": "..."}`
7. Wait (checkpoint) for `/approve` or revision

### `approve`
1. Update Tracker.md: file → `✅ Approved`
2. Determine next file in sequence
3. If next file exists: trigger `run` for next file
4. If sequence complete: return `{"type": "sequence_complete"}`

### `revise`
1. Load current file content
2. Call file's owning specialist agent, pass: `{current_content, change_request, context_files}`
3. On return: validate, update Tracker.md → `👀 Needs Review`
4. Return `{"type": "file_complete", ...}` (same as after run)

### `reset`
1. Return `{"type": "confirmation_required", "action": "reset <file>", "warning": "..."}`
2. On confirm: call `clear_file()`, then trigger `run` for that file

### `consistency`
1. Load all non-empty PLANNER/ files
2. Route to `ConsistencyAgent`
3. Return `{"type": "consistency_report", "issues": [...]}`

### `finalize`
1. Check Tracker.md for any `⏳ Pending` or `🔄 In Progress` files
2. If any: return `{"type": "finalize_warning", "incomplete": [...]}` — wait for confirm
3. Route to `FinalizerAgent`, pass: all PLANNER/ file contents
4. Write CLAUDE.md to project root
5. Return `{"type": "finalized", "warnings": [...]}`

### `status`
1. Read Tracker.md via `get_status_summary()`
2. Return `{"type": "status_table", "rows": [...]}`

### `chat`
1. Load `structured_idea` + current Tracker.md summary as context
2. Make one LLM call: answer the question from project context — **this is the one and only LLM call the Orchestrator makes**, and only for free-form chat questions
3. Return `{"type": "chat_response", "text": "..."}`

### `update`
1. Route to `UpdatesAgent`, pass: `{change_description, current_state}`
2. `UpdatesAgent` returns blast radius + handles re-runs
3. Orchestrator returns `{"type": "update_complete", "files_changed": [...]}`

### Missing info (mid-sequence)
When a specialist sets `pending_questions`:
1. Route to `GrillerAgent`, pass: `{pending_questions, context_files, calling_agent}`
2. GrillerAgent returns either: `{answers}` or `{needs_expert: True, question}`
3. If `needs_expert`: route to `TechStackExpertAgent`, return suggestion payload to ExecutiveAgent
4. On user approval of suggestion: fill answer into state, resume specialist with `phase="write"`
5. On user providing own answer: fill into state, resume specialist with `phase="write"`

### Frontend detection
After TRD.md is written (during `run` for TRD):
1. Call `check_frontend_signals(structured_idea, trd_content)` from `validation_tools`
2. Store `has_frontend` in state
3. If `False`: mark DesignDecisions.md + AppFlow.md as `Skipped (backend-only)` in Tracker.md
4. Skip those nodes when routing the sequence

---

## State (OrchestratorAgent maintains)

```python
class OrchestratorState(TypedDict):
    mode: str                        # "from_scratch" | "ps_idea_hybrid"
    has_frontend: bool
    sequence_index: int              # current position in main sequence
    structured_idea: str             # cached StructuredIdea.md
    fit_analysis: str                # hybrid mode only, "" otherwise
    context_files: dict[str, str]    # filename → content cache
    pending_questions: list[str]     # set by specialist, cleared by Griller
    grill_answers: dict[str, str]
    active_revision_target: str      # file currently in 👀 Needs Review
    last_error: str
    pending_updates: list[str]       # queued /update calls
```

---

## Rules

1. No LLM calls except the `chat` command handler — one call, one case only
2. No user I/O — every output goes to ExecutiveAgent as a typed payload
3. No file writes except StructuredIdea.md (via `describe` handler) and CLAUDE.md (via `finalize`) — all other file writes are done by specialist agents
4. Tracker.md updates are tool calls (`tracker_tools`), never routed through TrackerAgent node
5. One specialist call at a time — never call two agents concurrently
6. Always validate file structure after every specialist write before returning `file_complete`
7. Pass `fit_analysis` to all specialists in hybrid mode; pass `""` in from-scratch mode — no `mode` flag

---

## LangGraph checkpointing (required)

The Orchestrator must use a LangGraph checkpointer (minimum: `MemorySaver`; production: SQLite checkpointer). Every `file_complete` payload sent to ExecutiveAgent is a checkpoint. The `/approve` command resumes from that checkpoint. Without this, the graph cannot pause between file writes for user approval.

```python
from langgraph.checkpoint.memory import MemorySaver
checkpointer = MemorySaver()
graph = graph_builder.compile(checkpointer=checkpointer, interrupt_before=["approval_gate"])
```

---

## Implementation notes

- Lives in: `planner/agents/orchestrator.py`
- Is a class with one method per command handler (not a monolithic `run()`)
- Does not implement slash command parsing — that is ExecutiveAgent's job
- TrackerAgent node is removed from the LangGraph graph — all Tracker updates are `tracker_tools` calls inside command handlers
- Specialist two-phase invocation pattern: call with `phase="gather"`, check for `pending_questions`; if present → Griller flow; if clear → call again with `phase="write"`

---

---
# STRUCTURING AGENT SPEC
> File: `planner/agents/structuring_agent.py`
> Extracted from old Orchestrator. Handles StructuredIdea.md generation for both modes.

---

## Role

Single responsibility: take raw idea input, produce a clean structured specification in `StructuredIdea.md`. Called by the Orchestrator after user finishes describing their idea.

---

## Inputs (received from Orchestrator)

```python
{
  "raw_idea": str,       # full content of RawIdea.md
  "mode": str            # "from_scratch" | "ps_idea_hybrid"
}
```

---

## From-Scratch mode output

Produces `StructuredIdea.md` with:
```md
## Problem Statement
[Specific pain. Who has it. Why current solutions fail.]

## Proposed Solution
[What this project builds. How it addresses the problem at a high level.]

## Key Goals
[3–5 concrete goals, not vague aspirations.]

## Non-Goals
[What this project explicitly will not do.]

## Target Users
[Specific user personas. Not "developers" — name the role and context.]
```

---

## Hybrid mode output

Produces `StructuredIdea.md` with:
```md
## Problem Statement (Structured)
[Cleaned PS from user input. Specific, not a restatement.]

## Solution Overview
[Cleaned solution from user input. What it builds, how it addresses the PS.]

## Fit Analysis
[Honest assessment:
- Gaps: parts of PS the solution doesn't cover
- Assumptions: what the solution assumes the PS doesn't guarantee
- Risks: where it may fail edge cases]

## Validated Scope
[Intersection of PS requirements and solution proposal. This is what PRD builds against.]
```

---

## Returns to Orchestrator

```python
{
  "structured_idea": str,   # full StructuredIdea.md content
  "fit_analysis": str,      # Fit Analysis section only (hybrid) or "" (from_scratch)
  "has_gaps": bool          # True if Fit Analysis found any gaps (hybrid only)
}
```

Orchestrator writes the file, not this agent.

---

## Fit Analysis revision loop

The StructuringAgent does not manage the revision loop. It runs once, returns output. The Orchestrator shows the Fit Analysis to the user via ExecutiveAgent. If user says `revise`, the Orchestrator calls StructuringAgent again with updated `raw_idea`. Max 5 calls before Orchestrator forces proceed.

---

## Rules

- Never ask the user questions — if raw idea is too vague, produce the best structure possible and flag `has_gaps = True`
- Never invent details not in RawIdea.md
- Fit Analysis must be honest — no positive spin if genuine gaps exist

---

---
# CONSISTENCY AGENT SPEC
> File: `planner/agents/consistency_agent.py`
> Extracted from old Orchestrator /consistency implementation.

---

## Role

Single responsibility: perform a read-only cross-file consistency check across all PLANNER/ files. Returns a list of issues. Never modifies any file.

---

## Inputs

```python
{
  "files": dict[str, str]   # all non-empty PLANNER/ files: {filename: content}
}
```

---

## Check list (run all, report all findings)

- Every PRD feature appears in TRD functional requirements
- Every TRD entity/model appears as a table in Schema.md
- Every Schema table is referenced in at least one MODULES/ file
- AppFlow references only screens/features that exist in PRD (if AppFlow exists)
- Constraints.md does not conflict with TRD stack choices
- Rules.md does not conflict with implementation patterns in TRD
- ImplementationPlan.md phases reference only features in PRD scope

---

## Returns

```python
{
  "issues": [
      {"file_a": "PRD.md", "file_b": "TRD.md", "issue": "Feature 'Admin Dashboard' in PRD has no corresponding TRD functional requirement"},
      ...
  ],
  "clean": bool   # True if issues is empty
}
```

---

## Rules

- Read-only — never suggest fixes, never modify files
- Every issue must cite both files involved
- If no issues found: return `clean: True`, `issues: []`

---

---
# FINALIZER AGENT SPEC
> File: `planner/agents/finalizer_agent.py`
> Extracted from old Orchestrator /finalize implementation.

---

## Role

Single responsibility: compile `CLAUDE.md` from all approved PLANNER/ files. Called once per project when user runs `/finalize`. Writes CLAUDE.md to project root.

---

## Inputs

```python
{
  "files": dict[str, str]   # all PLANNER/ file contents
}
```

---

## CLAUDE.md output structure

Keep under 300 lines. Summarize — never copy-paste full sections verbatim.

```md
# CLAUDE.md
> Auto-generated by PlannerX /finalize. Do not edit manually.
> Regenerate with /finalize after planning changes.

## Project Summary
[3–5 sentences from StructuredIdea.md]

## Tech Stack
[Exact versions from TRD.md. Table format: Layer | Technology | Version]

## Folder Structure
[Key directories from ImplementationPlan.md. One line per dir with purpose.]

## Coding Rules (Critical)
[Top 5–10 rules from Rules.md that affect day-to-day code writing. Bullets.]

## Hard Constraints
[Must-never-do list from Constraints.md. Bullets.]

## Data Model (Summary)
[Key tables + primary columns only from Schema.md. Not full schema.]

## Key API Endpoints
[Core endpoints from TRD.md. Method + path + one-line purpose only.]

## Active Module
[Currently active module name, if any. Updated on /module add.]
```

---

## Returns

```python
{
  "claude_md_content": str,      # full CLAUDE.md text to write
  "warnings": list[str]          # e.g. ["AppFlow.md was empty — skipped"]
}
```

Orchestrator writes the file. FinalizerAgent only generates content.

---

## Rules

- Under 300 lines, hard cap — if summarization isn't enough, cut API endpoints section first, then data model
- No verbatim copy-paste from source files
- Sections for missing/empty files get a one-liner: `[Not available — <file> was not generated]`

---

---
## Updated Agent List

```
planner/agents/
├── executive_agent.py        # NEW — sole user I/O agent
├── orchestrator.py           # REVISED — pure router, minimal LLM calls
├── structuring_agent.py      # NEW — extracted from old Orchestrator
├── consistency_agent.py      # NEW — extracted from old Orchestrator
├── finalizer_agent.py        # NEW — extracted from old Orchestrator
├── prd_agent.py
├── trd_agent.py
├── design_agent.py
├── schema_agent.py
├── appflow_agent.py
├── rules_agent.py
├── implementation_agent.py
├── tracker_agent.py          # DEMOTED — no longer a graph node, use tracker_tools directly
├── tech_stack_agent.py       # FIXED — no longer writes to DesignDecisions.md
├── griller_agent.py
├── module_planner_agent.py
└── updates_agent.py
```

**TrackerAgent** is removed from the LangGraph graph. All Tracker.md updates are direct `tracker_tools` calls inside the Orchestrator's command handlers. If a standalone Tracker read/format is needed (e.g. for `/status`), it's a tool call, not an agent invocation.

**TechStackExpertAgent** no longer writes to DesignDecisions.md. It returns suggestions to the Orchestrator. The Orchestrator passes them to the calling specialist agent via state. The specialist includes the accepted suggestion in its file output. DesignDecisions Agent picks it up from context when it runs.
