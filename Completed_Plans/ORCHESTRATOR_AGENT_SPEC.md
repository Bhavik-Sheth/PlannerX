# ORCHESTRATOR AGENT — Master Agent Spec
> Drop this file into your AI IDE as the implementation brief for the Orchestrator agent.
> This agent is the only agent the user directly talks to. It handles both planning modes and routes all work to specialist agents.

---

## Role

The Orchestrator is the single entry point for all user interaction. It:
- Greets the user and determines planning mode at startup
- Manages the full file-writing sequence by delegating to specialist agents
- Calls Griller when info is missing, TechStackExpert when decisions are needed
- Updates Tracker.md after every agent action
- Handles all slash commands typed in the chat input
- Never writes planning files itself — it only routes, coordinates, and tracks

---

## Startup Flow (Mode Selection)

On every cold start (no existing PLANNER/ folder) or on `/init`, the Orchestrator must display:

```
Welcome to PlannerX.

How would you like to start?

  [1] From scratch — I have a raw idea, help me plan it fully
  [2] PS + Idea — I have a problem statement and a proposed solution

Type 1 or 2 to begin.
```

User types `1` → enter **Mode A: From Scratch**
User types `2` → enter **Mode B: PS + Idea (Hybrid)**

If PLANNER/ already exists (resume session): skip mode selection, read Tracker.md, resume from last incomplete file. Greet with:
```
Resuming session. Last status:
[print Tracker.md status table]

Continue from where we left off? [yes / no]
```

---

## Mode A: From Scratch

### Input collection
Ask user to describe their idea in plain text. Accept multi-paragraph input. When done, user types `/done` or sends a blank line after a pause.

Write input verbatim → `RawIdea.md` (append-only, never modified by agents).

### StructuredIdea.md generation
Call the **Structuring sub-routine** (internal LLM call, not a separate agent node):
- Read RawIdea.md
- Produce a clean, detailed problem statement:
  - What problem exists
  - Who has it
  - Why current solutions fail
  - What the proposed solution does at a high level
  - Key goals and non-goals
- Write result → `StructuredIdea.md`

Then hand off to the **Main Sequence** (see below).

---

## Mode B: PS + Idea (Hybrid)

### Input collection — two-step

**Step 1 — Problem Statement:**
```
Paste or describe the Problem Statement (PS).
This is the problem you are solving — not your solution.
Type /done when finished.
```
Write input → `RawIdea.md` under heading `## Problem Statement`

**Step 2 — Your Proposed Solution:**
```
Now describe your proposed solution to this PS.
What will you build? How does it address the problem?
Type /done when finished.
```
Append input → `RawIdea.md` under heading `## Proposed Solution`

### StructuredIdea.md generation (Hybrid mode)
Call the **Hybrid Structuring sub-routine** (internal LLM call):

Read both sections of RawIdea.md. Produce `StructuredIdea.md` structured as follows:

```md
## Problem Statement (Structured)
[Cleaned, specific version of the PS. Who is affected, what is the pain, why it matters, scope of the problem.]

## Solution Overview
[Cleaned, specific version of the proposed solution. What it builds, how it solves the PS, what it explicitly does not do.]

## Fit Analysis
[Does the proposed solution actually solve the stated PS? Identify:
- Gaps: aspects of the PS the solution doesn't address
- Assumptions: things the solution assumes that the PS doesn't guarantee
- Risks: where the solution may fail to solve the problem in edge cases]

## Validated Scope
[Synthesized final scope: the intersection of what the PS requires and what the solution proposes. This is what the PRD agent will build against.]
```

> The Fit Analysis section is the key differentiator of hybrid mode. It must be honest — if the proposed solution doesn't fully address the PS, say so explicitly before proceeding. Surface gaps now, not during implementation.

After writing StructuredIdea.md, show the Fit Analysis to the user and ask:
```
Here is the fit analysis between your PS and proposed solution.
[display Fit Analysis section]

Gaps or risks identified above may affect planning. 
Proceed with current scope? Or would you like to revise your solution first? [proceed / revise]
```
If `revise` → user updates their solution description, re-run Hybrid Structuring sub-routine, show new Fit Analysis. Loop until user types `proceed`.

Then hand off to the **Main Sequence**.

---

## Main Sequence (Both Modes)

After StructuredIdea.md is approved, run all specialist agents in this exact order:

```
1.  Constraints.md       ← ConstraintsAgent
2.  PRD.md               ← PRDAgent
3.  TRD.md               ← TRDAgent
4.  Schema.md            ← SchemaAgent
5.  DesignDecisions.md   ← DesignDecisionsAgent  [skip if backend-only]
6.  AppFlow.md           ← AppFlowAgent          [skip if backend-only]
7.  Tracker.md           ← TrackerAgent
8.  Rules.md             ← RulesAgent
9.  MODULES/             ← ModulePlannerAgent
```

Architecture Diagram Watcher runs independently in parallel — not part of this sequence.

### Frontend detection (skip logic)
After TRD.md is written, check for frontend signals:
- Read TRD.md for any mention of: UI, frontend, React, Vue, Next.js, HTML, CSS, mobile app, dashboard, screen, page, component, browser
- If none found AND StructuredIdea.md has no frontend signals → set `has_frontend = false`
- Mark DesignDecisions.md and AppFlow.md as `Skipped (backend-only)` in Tracker.md
- Do not call DesignDecisionsAgent or AppFlowAgent

### Per-agent handoff protocol
Before calling each specialist agent, Orchestrator must pass:
```python
{
  "target_file": "PRD.md",                     # which file this agent writes
  "structured_idea": <contents of StructuredIdea.md>,
  "context_files": {                            # only files this agent needs
      "Constraints.md": <contents>,
      # ...add upstream files relevant to this agent
  },
  "mode": "from_scratch" | "ps_idea_hybrid",   # so agent can adjust tone/depth
  "fit_analysis": <Fit Analysis section>,       # hybrid mode only — gives agents the gap context
}
```

### After each agent completes
1. Read the written file — confirm it is non-empty and structurally valid (has expected sections)
2. Update Tracker.md: file, status → `👀 Needs Review`, agent, timestamp
3. Show user a brief summary of what was written:
   ```
   ✅ PRD.md written.
   Key decisions: [2-3 bullet summary of what the PRD agent produced]
   Type /approve PRD.md to accept, or describe changes to revise it.
   ```
4. Wait for user to `/approve` or send a revision request before moving to next file

### Missing info handling
If any specialist agent sets `pending_questions` in state:
1. Pause the sequence immediately
2. Call **GrillerAgent**, pass: `pending_questions` + full `context_files` relevant to those questions
3. GrillerAgent asks user questions one at a time
4. If user answers "I don't know" → call **TechStackExpertAgent**, pass: question + Constraints.md + StructuredIdea.md
5. TechStackExpert returns structured suggestion → show to user for approval
6. On approval: log to DesignDecisions.md as ADR entry, fill answer back into state
7. Resume the paused specialist agent with filled answers

### LLM failure handling
If any agent's LLM call fails:
```
⚠️  Error in [AgentName]: [error message]

Retry this agent? [yes / no]
```
`yes` → retry same agent with same state, same inputs
`no` → mark file as `❌ Blocked` in Tracker.md, skip to next file, log blocker

---

## Slash Command Handling

All commands typed in chat input with `/` prefix. Plain text without `/` is treated as a revision request for the current active file or a general question to the Orchestrator.

| Command | Action |
|---|---|
| `/init` | Scaffold PLANNER/ + empty files. Trigger mode selection. |
| `/describe <text>` | Append text to RawIdea.md. Re-run structuring sub-routine. |
| `/run` | Start or resume main sequence from first incomplete file. |
| `/approve <file>` | Mark file ✅ Approved in Tracker.md. Move to next file in sequence. |
| `/status` | Print Tracker.md status table in Viewer panel. |
| `/edit <file>` | Open file in $EDITOR. On close, re-read file, update Tracker.md. |
| `/reset <file>` | Confirm with user → clear file → re-run its specialist agent. |
| `/module add <name>` | Create MODULES/<name>.md → call ModulePlannerAgent. |
| `/module list` | List all MODULES/ files + their status from Tracker.md. |
| `/consistency` | Read-only pass across all PLANNER/ files. Find contradictions. Output report to Viewer. Do not auto-fix. |
| `/finalize` | Compile CLAUDE.md from all approved PLANNER/ files. Mark planning phase complete. |
| `/diagram` | Manually trigger Architecture Diagram Watcher regeneration. |

### Plain text (no `/`) routing
- If a file is currently in `👀 Needs Review` state → treat plain text as revision request → pass to that file's specialist agent with the change request + current file content
- If no file is in review → treat as general question → answer from PLANNER/ file context, do not modify any files
- Never modify files from a plain text message unless the user explicitly says "change" / "update" / "revise"

---

## /consistency Implementation

When `/consistency` is called:

1. Read all non-empty PLANNER/ files
2. Run a cross-file analysis LLM call with this prompt structure:
```
You are checking consistency across a set of project planning documents.
Find contradictions, gaps, and mismatches between files.
Check:
- Does every PRD feature appear in TRD functional requirements?
- Does every TRD entity appear in Schema.md as a table?
- Does every Schema table get referenced in at least one module?
- Does AppFlow reference only screens/features that exist in PRD?
- Do Constraints conflict with any TRD tech stack choice?
- Do Rules conflict with any implementation pattern in TRD?
List each issue as: [File A] ↔ [File B]: [description of contradiction or gap]
Do not suggest fixes. List only.
```
3. Display result in Viewer panel
4. Do not auto-fix anything — user decides which file to revise

---

## /finalize Implementation

When `/finalize` is called:

1. Check if any required file is still in ⏳ Pending or 🔄 In Progress state
   - If yes: warn user, list incomplete files, ask `Finalize anyway? [yes / no]`
2. Compile `CLAUDE.md` by reading all PLANNER/ files and extracting:
   - Project summary (3–5 sentences from StructuredIdea.md)
   - Active tech stack with exact versions (from TRD.md)
   - Key folder structure (from ImplementationPlan.md)
   - Top 5–10 coding rules (from Rules.md)
   - Hard constraints — must-never-do list (from Constraints.md)
   - Data model summary — key tables + primary columns only (from Schema.md)
   - Key API endpoints (from TRD.md)
3. Write → `CLAUDE.md` at project root (not inside PLANNER/)
4. Keep CLAUDE.md under 300 lines — summarize, do not copy-paste verbatim from source files
5. Confirm to user:
   ```
   ✅ CLAUDE.md generated at project root.
   Planning phase complete. You can now begin implementation.
   ```

---

## State the Orchestrator maintains

```python
class OrchestratorState(TypedDict):
    mode: str                        # "from_scratch" | "ps_idea_hybrid"
    has_frontend: bool               # set after TRD is written
    current_file: str                # which file is being worked on now
    sequence_index: int              # position in main sequence
    structured_idea: str             # cached StructuredIdea.md content
    fit_analysis: str                # hybrid mode only
    context_files: dict[str, str]    # filename → content cache
    pending_questions: list[str]     # from specialist agents
    grill_answers: dict[str, str]    # filled by Griller
    active_revision_target: str      # file currently in Needs Review state
    tracker_state: dict              # current Tracker.md parsed state
    last_error: str                  # last LLM failure message, for retry
```

---

## Orchestrator's own rules

1. **Never write a planning file directly.** Always delegate to the correct specialist agent.
2. **Never skip the per-agent summary + approval wait.** User must see what was written before the next file starts.
3. **Never auto-approve.** Even if output looks correct, wait for explicit `/approve`.
4. **Never hallucinate file contents.** If a file doesn't exist yet, pass empty string in context — do not invent content.
5. **Always update Tracker.md after every state change**, not in batches.
6. **In hybrid mode**, always pass `fit_analysis` to all specialist agents — it gives them the gap context that shapes how deep/defensive the planning needs to be.
7. **Maintain mode throughout session.** Once mode is set, do not re-ask. Mode is stored in state and persists across agent calls.
8. **Revision requests stay within the owning agent.** If user asks to change PRD.md, only PRDAgent handles it — Orchestrator never edits files itself even for "small" changes.

---

## Implementation notes for the IDE

- This agent lives in: `planner/agents/orchestrator.py`
- The startup mode selection and Structuring sub-routines are methods on this class, not separate agent files
- The Hybrid Structuring sub-routine is a distinct LLM call from the From Scratch one — do not share the same prompt template
- `OrchestratorState` extends `PlannerState` from `state.py` — add hybrid-specific fields, don't replace base state
- All slash command parsing happens in `tui/widgets/chat_input.py` → dispatches to Orchestrator methods; Orchestrator does not parse raw text itself
- The Fit Analysis loop (revise → re-run → show → loop) must be implemented as a while loop with a max of 5 iterations before Orchestrator forces `proceed` with a warning: `"Max revisions reached. Proceeding with current scope."`
- Tracker.md writes must be atomic — read current content, update in memory, write full file — never append raw lines, to avoid format corruption
