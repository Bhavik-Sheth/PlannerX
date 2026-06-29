# Fixes — Problems 4, 5, 6
> Solutions for the three remaining major architectural issues from the critical evaluation.

---

---
# Problem 4 — TechStackExpert: Shared Writer on DesignDecisions.md

## The Problem

TechStackExpert was writing ADR entries directly to `DesignDecisions.md` on suggestion acceptance. The DesignDecisions Agent also writes to `DesignDecisions.md`. Two agents, one file, no coordination — guaranteed format corruption and duplicate ADR numbers over time.

The append-only rule was defined but there was no ownership rule. Two writers with no locking is not "append-only safety" — it's a race condition waiting to happen.

---

## Fix — TechStackExpert becomes suggestion-only

**TechStackExpert never writes to any file.** It returns a structured suggestion object. The suggestion flows through state back to whichever specialist called for it. The specialist embeds the accepted suggestion into its own file's content. DesignDecisions Agent picks it up from context when it runs in the main sequence.

One file, one writer. Always.

---

## New Data Flow

```
Before (broken):
Specialist → pending_questions → Griller → TechStackExpert → writes DesignDecisions.md
                                                           → returns answer to Specialist

After (fixed):
Specialist → pending_questions → Griller → TechStackExpert → returns Suggestion object
                                        ← Suggestion shown to user via ExecutiveAgent
                              ← answer filled into state.grill_answers
Specialist (phase=write) reads answer from state → embeds in its own file
DesignDecisions Agent runs later → reads context_files (which includes the specialist's
  output mentioning the decision) → writes proper ADR entry
```

---

## TechStackExpert — Updated Spec

### Role (updated)
Returns a structured `Suggestion` object to the Orchestrator. Reads `Constraints.md` and project context. Never writes to any file. Never routes to any agent.

### Inputs
```python
{
  "question": str,              # the specific decision needed
  "constraints": str,           # full Constraints.md content
  "structured_idea": str,       # project context
  "calling_agent": str          # which specialist triggered this
}
```

### Output — Suggestion object
```python
class Suggestion(TypedDict):
    question: str               # original question being answered
    recommendation: str         # what to use
    why: str                    # one sentence tied to a specific NFR or constraint
    tradeoff: str               # what is given up
    alternative: str            # next best option if rejected
    calling_agent: str          # passed through for Orchestrator routing
```

### Returns to Orchestrator
Orchestrator receives the Suggestion object → sends to ExecutiveAgent as `{"type": "suggestion", ...}` → user approves or rejects.

On **approval**: Orchestrator stores in `state.grill_answers[question] = recommendation` and logs:
```python
state.accepted_suggestions.append({
    "question": question,
    "answer": recommendation,
    "why": why,
    "alternative_rejected": alternative
})
```

On **rejection**: Orchestrator stores `state.grill_answers[question] = alternative` and logs the rejection similarly.

The `accepted_suggestions` list in state is passed to the **DesignDecisions Agent** as part of its `context_files` when it runs. The DesignDecisions Agent reads this list and writes one ADR entry per accepted suggestion — correctly formatted, no duplicates, no race conditions.

### Rules (updated)
1. Never write to any file — return only
2. Never call another agent — return only
3. If `Constraints.md` says "free tier only" → never suggest a paid service regardless of how good it is
4. If two options are equally valid given constraints → present both as recommendation + alternative and state the tie explicitly

---

## DesignDecisions Agent — Updated Context Input

Add `accepted_suggestions` to the context it receives from the Orchestrator:

```python
{
  "target_file": "DesignDecisions.md",
  "structured_idea": str,
  "context_files": {
      "TRD.md": str,
      "Constraints.md": str
  },
  "accepted_suggestions": [          # NEW — from state, populated by TechStackExpert flow
      {
          "question": "Which database?",
          "answer": "PostgreSQL",
          "why": "Schema is fixed, joins required per TRD data model",
          "alternative_rejected": "SQLite"
      },
      ...
  ]
}
```

The DesignDecisions Agent writes each entry in `accepted_suggestions` as a properly formatted ADR, then adds any additional architectural choices it infers from TRD/context. It is now the **sole writer** of `DesignDecisions.md`, always.

---

## State Changes

Add to `OrchestratorState`:
```python
accepted_suggestions: list[dict]    # TechStackExpert outputs, accumulated across session
                                    # cleared only on /reset DesignDecisions.md
```

Remove from `OrchestratorState`:
```python
tech_suggestions: dict              # old field — replaced by accepted_suggestions list
```

---

---
# Problem 5 — Architecture Watcher: No Lifecycle, No Rate Limiting, No Failure Visibility

## The Problem

Three issues in one:

1. **No debounce.** A full `/run` writes ~10 files. Watcher fired 10 LLM calls in rapid succession. Only the last one mattered. First 9 were wasted API calls that burned rate limit.

2. **No lifecycle.** Nothing started the watcher, nothing stopped it, nothing detected if it crashed. If it died silently, diagrams stopped updating and no one knew.

3. **No failure visibility.** On LLM failure, the watcher either left a stale diagram silently or crashed. User had no signal that diagrams were out of date.

---

## Fix — Three independent solutions, one implementation

### Fix A — Debounce

Watcher does not trigger on every file write. It waits until no new writes have occurred for **800ms** before triggering diagram regeneration. On a full `/run` (10 files written in rapid sequence), watcher fires exactly **once** after the last file settles, not 10 times.

```python
# watcher/architecture_watcher.py

DEBOUNCE_SECONDS = 0.8
_last_write_time = 0.0
_pending_regen = False

async def on_file_changed(path: str):
    global _last_write_time, _pending_regen
    _last_write_time = time.monotonic()
    if not _pending_regen:
        _pending_regen = True
        asyncio.create_task(_debounced_regen())

async def _debounced_regen():
    global _last_write_time, _pending_regen
    while True:
        await asyncio.sleep(DEBOUNCE_SECONDS)
        if time.monotonic() - _last_write_time >= DEBOUNCE_SECONDS:
            break
    _pending_regen = False
    await regenerate_all_diagrams()
```

Result: 10 file writes → 1 diagram regeneration. Rate limit pressure reduced by ~90% during a full run.

### Fix B — Lifecycle Management

The watcher is a subprocess managed by the Orchestrator. Orchestrator starts it, monitors it, restarts it on crash, and kills it on session end.

**Watcher process contract:**
- Writes a **heartbeat file** (`PLANNER/.watcher_heartbeat`) every 5 seconds containing `{"pid": int, "last_regen": timestamp, "status": "idle"|"running"|"error"}`
- On clean exit: deletes the heartbeat file
- On crash: heartbeat file becomes stale (not updated)

**Orchestrator watcher management:**
```python
# In orchestrator.py

class WatcherManager:
    def start(self, project_path: str) -> subprocess.Popen:
        """Start watcher subprocess. Called on /init or /run."""

    def stop(self):
        """Terminate watcher subprocess. Called on quit."""

    def health_check(self) -> str:
        """
        Returns "alive" | "stale" | "dead".
        Reads heartbeat file. If last_update > 10s ago → "stale".
        If file missing → "dead".
        """

    def restart_if_dead(self, project_path: str):
        """Called by Orchestrator on every /run and /approve. Auto-restarts dead watcher."""
```

Orchestrator calls `watcher_manager.restart_if_dead()` at the start of every command handler. If watcher is dead → restart silently. If restarts fail 3 times → mark as permanently failed, notify ExecutiveAgent.

**Where to call:**
- `/init` → `watcher_manager.start()`
- `/run` → `watcher_manager.restart_if_dead()`
- Every `/approve` → `watcher_manager.restart_if_dead()`
- Application quit → `watcher_manager.stop()`

### Fix C — Failure Visibility in TUI

The TUI Architecture panel shows a **status indicator** in its header:

```
┌─ Architecture ──────────────────── ● Live ─┐
│                                            │
│  [diagram content]                         │
```

Status indicator states:

| Symbol | Label | Condition |
|---|---|---|
| `●` green | `Live` | Watcher alive, last regen < 30s ago |
| `●` yellow | `Regenerating...` | LLM call in progress |
| `●` yellow | `Stale` | Watcher alive but heartbeat > 30s ago (debounce or slow LLM) |
| `●` red | `Watcher crashed` | Heartbeat file stale or missing |
| `●` grey | `Unavailable` | 3 restart attempts failed |

On `Watcher crashed` or `Unavailable`: ExecutiveAgent shows a one-time notification in chat output:
```
⚠️  Architecture watcher stopped. Diagrams may be out of date.
    Type /diagram to manually regenerate, or restart the app to resume live updates.
```

On LLM failure during regen: watcher prepends `[STALE — regeneration failed at HH:MM]` to the existing diagram file content instead of overwriting. Architecture panel shows this header. User knows the diagram is old without losing the last valid version.

---

## Updated `architecture_watcher.py` — Full Spec

```
planner/watcher/
├── __init__.py
├── architecture_watcher.py    # main watchfiles loop + debounce
├── watcher_manager.py         # subprocess lifecycle: start/stop/health_check/restart
└── heartbeat.py               # heartbeat file read/write helpers
```

### `architecture_watcher.py` responsibilities
1. Watch `PLANNER/` for `.md` file changes using `watchfiles`
2. Debounce: 800ms after last change before triggering
3. On trigger: call `ascii_tools.generate_diagram_from_files()` for each diagram type
4. Write results to `ARCHITECTURE_DIAGRAMS/`
5. Update heartbeat file every 5s during idle, after every regen
6. On LLM failure: write STALE header to existing diagram, update heartbeat with `status: "error"`

### `watcher_manager.py` responsibilities
1. `start()` — spawn `architecture_watcher.py` as subprocess
2. `stop()` — terminate subprocess cleanly
3. `health_check()` — read heartbeat file, classify as `alive/stale/dead`
4. `restart_if_dead()` — check health, restart if not alive, increment restart counter
5. `get_status_for_tui()` → returns `{"symbol": "●", "color": "green", "label": "Live"}` for TUI panel header

### LLM rate limit coordination
Watcher uses the same `llm_tools.llm_call()` as the main graph. Since LangGraph graph execution and the watcher are separate processes, rate limiting is handled at the provider level (Groq/NIM/etc). To avoid watcher LLM calls colliding with main graph calls during a `/run`:

- Watcher reads `PLANNER/.graph_running` lock file (written by Orchestrator at start of `/run`, deleted on completion)
- If lock file exists: watcher skips the triggered regen and schedules a regen for 2s after lock file disappears
- This ensures watcher LLM calls never fire simultaneously with main graph LLM calls

```python
# In _debounced_regen():
if Path(project_path / ".graph_running").exists():
    # Graph is running — defer regen until lock clears
    await wait_for_lock_clear(project_path)
await regenerate_all_diagrams()
```

Orchestrator writes `.graph_running` at the start of `run` command handler and deletes it in a `finally` block — guaranteed deletion even on exception.

---

---
# Problem 6 — Griller: 4-Hop Routing in LangGraph

## The Problem

When a specialist needed missing info, the routing was:

```
Specialist sets pending_questions → returns
→ Orchestrator detects flag → routes to Griller
→ Griller asks user, fills answers → returns
→ Orchestrator routes back to Specialist
→ Specialist runs again from the start
```

Four hops. But worse: the specialist re-ran **from the start** on the return trip, re-reading all context files and regenerating content it had already reasoned about. For a large file like TRD.md, this is a full LLM context reload. On a small model, it produces different (sometimes worse) output on the re-run.

LangGraph also had no clean way to implement this without either blocking on `input()` (freezing the TUI) or using `interrupt_before` with a checkpointer (not specified, easy to get wrong).

---

## Fix — Two-Phase Specialist Nodes

Every specialist agent is redesigned as a **two-phase node**:

- **`phase="gather"`** — check if all required info is available in context. If yes, proceed to write. If no, return `pending_questions` immediately without any LLM content generation.
- **`phase="write"`** — all required info is confirmed present in state. Generate file content. No questions, no checks.

The Orchestrator always calls specialists in `phase="gather"` first. Only if `pending_questions` is empty does it call again in `phase="write"`. The specialist never re-runs content generation from scratch after a Griller round-trip.

---

## New Routing: 2 Specialist Invocations, No Multi-Hop

```
Before (4 hops, specialist re-runs fully):
Specialist(start) → [detects missing info] → Orchestrator → Griller → Orchestrator → Specialist(re-run from start)

After (2 specialist invocations, gather then write):
Specialist(phase=gather) → [returns pending_questions, no content generated]
Orchestrator → Griller → [answers filled in state]
Orchestrator → Specialist(phase=write) → [generates content with complete info]
```

Griller is still involved but the routing is: Orchestrator → Griller (single hop, not two), then Orchestrator → Specialist(write) (single hop, not two). No specialist re-runs content generation.

---

## Specialist Agent — Two-Phase Interface

Every specialist agent (`prd_agent.py`, `trd_agent.py`, etc.) implements this interface:

```python
def run(state: PlannerState) -> PlannerState:
    if state.phase == "gather":
        return _gather(state)
    elif state.phase == "write":
        return _write(state)

def _gather(state: PlannerState) -> PlannerState:
    """
    Check if all required info for this file is present in state.
    NO LLM calls. Deterministic logic only.
    Returns state with pending_questions populated if anything is missing.
    Returns state with pending_questions=[] if all info is present.
    """
    questions = []

    # Each specialist defines its own required-info checklist
    # Example for TRD agent:
    if not state.context_files.get("PRD.md"):
        questions.append("PRD.md is missing — cannot write TRD without it")
    if "auth" not in state.structured_idea.lower() and not state.grill_answers.get("auth_method"):
        questions.append("What authentication method will the app use?")
    if not state.context_files.get("Constraints.md"):
        questions.append("Constraints.md is missing — needed for NFR and stack decisions")

    state.pending_questions = questions
    state.phase = "gather"    # stays gather if questions exist
    return state

def _write(state: PlannerState) -> PlannerState:
    """
    All info confirmed present. Generate file content via LLM.
    No info-checking. No conditional questions. Write and return.
    """
    content = llm_call(
        prompt=_build_prompt(state),
        system=_specialist_system_prompt()
    )
    write_file(state.project_path / "PLANNER" / TARGET_FILE, content, overwrite=True)
    state.output_summary = _summarize(content)   # 2-3 bullets for ExecutiveAgent display
    state.phase = "done"
    return state
```

**Key constraint:** `_gather()` makes **zero LLM calls**. It is pure logic — checking presence of keys in `state.context_files` and `state.grill_answers`. Fast, deterministic, never burns tokens. If it called an LLM to "figure out what's missing," it would defeat the purpose.

---

## Orchestrator — Updated Specialist Call Logic

Replace the current single `call_specialist()` with the two-phase pattern:

```python
def _call_specialist(self, agent_fn, state: PlannerState) -> PlannerState:
    """
    Calls a specialist agent in two phases.
    Handles the Griller loop between phases transparently.
    Returns final state after phase=write completes.
    """
    # Phase 1: gather
    state.phase = "gather"
    state = agent_fn(state)

    # Griller loop — runs only if gather found missing info
    while state.pending_questions:
        state = self._run_griller_loop(state)
        # After griller fills answers, re-run gather to check if all info now present
        # (Griller may have answered some questions but not all)
        state.phase = "gather"
        state = agent_fn(state)

    # Phase 2: write — all info confirmed present
    state.phase = "write"
    state = agent_fn(state)

    return state

def _run_griller_loop(self, state: PlannerState) -> PlannerState:
    """
    Runs Griller for one question at a time.
    If user says 'I don't know' → routes to TechStackExpert.
    Fills grill_answers in state. Returns updated state.
    """
    question = state.pending_questions[0]   # one at a time

    # Route to GrillerAgent — single hop
    griller_result = griller_agent.run({
        "question": question,
        "context": state.structured_idea,
        "calling_agent": state.current_file
    })

    if griller_result.get("needs_expert"):
        # Route to TechStackExpert — single hop
        suggestion = tech_stack_agent.run({
            "question": question,
            "constraints": state.context_files.get("Constraints.md", ""),
            "structured_idea": state.structured_idea,
            "calling_agent": state.current_file
        })
        # Send suggestion to ExecutiveAgent for user approval
        # ... (approval flow, fills answer)
        state.grill_answers[question] = approved_answer
        state.accepted_suggestions.append(suggestion_record)
    else:
        state.grill_answers[question] = griller_result["answer"]

    state.pending_questions.pop(0)
    return state
```

---

## Griller Agent — Updated Role

Griller no longer routes to TechStackExpert itself. It returns `needs_expert: True` and the Orchestrator makes that routing decision. Griller's job is strictly: ask user one question, collect answer, return.

```python
# griller_agent.py

def run(inputs: dict) -> dict:
    """
    Asks the user one question via ExecutiveAgent.
    Returns the answer, or needs_expert=True if user says "I don't know".
    """
    # ExecutiveAgent displays the question, waits for user response
    # (ExecutiveAgent handles the I/O; Griller just formats the question)
    answer = ask_user(inputs["question"], inputs["context"])

    if answer.lower().strip() in ("i don't know", "idk", "not sure", "?", ""):
        return {"needs_expert": True, "question": inputs["question"]}

    return {"needs_expert": False, "answer": answer}
```

Simple. No routing. No LangGraph edges to TechStackExpert from Griller. Orchestrator owns all routing.

---

## LangGraph Implementation — Checkpointing (Required)

The two-phase pattern requires the graph to **pause between phase=gather and phase=write** when the Griller loop runs. This is human-in-the-loop — user input is required mid-execution.

LangGraph handles this via `interrupt_before`:

```python
# graph.py

from langgraph.checkpoint.sqlite import SqliteSaver

# Use SQLite checkpointer (survives process restart, unlike MemorySaver)
checkpointer = SqliteSaver.from_conn_string("planner/.checkpoints.db")

graph = graph_builder.compile(
    checkpointer=checkpointer,
    interrupt_before=["griller_node"]   # pause before Griller runs, await user input
)
```

**On Griller pause:**
1. Graph checkpoints current state to SQLite
2. ExecutiveAgent displays the question
3. User types answer in chat input → ExecutiveAgent sends to Orchestrator
4. Orchestrator calls `graph.update_state(thread_id, {"grill_answers": {...}})` to inject the answer
5. Orchestrator calls `graph.invoke(None, thread_config)` to resume from checkpoint
6. Graph continues from the checkpointed state — no re-run of prior nodes

This means:
- TUI never freezes (question displayed, execution paused cleanly at checkpoint)
- Answer injected into graph state, not passed as a new invocation
- Prior work (gather phase) is not repeated
- Works across app restarts (SQLite checkpointer persists)

```python
# In orchestrator.py — how /approve also uses the same checkpointing
def handle_approve(self, file: str, thread_id: str):
    update_file_status(self.project_path, file, "✅", "user")
    # Resume graph from checkpoint — continues to next file in sequence
    self.graph.invoke(None, {"configurable": {"thread_id": thread_id}})
```

The same checkpoint + resume pattern handles both the Griller pause and the per-file approval gate. One mechanism, two use cases.

---

## State Changes — `PlannerState`

Add:
```python
phase: str                  # "gather" | "write" | "done" — current specialist phase
```

Modify:
```python
pending_questions: list[str]   # was set by specialist, now set only in phase=gather
                               # cleared by Orchestrator after Griller fills each answer
```

The `phase` field replaces the old `status = "needs_input"` flag. Cleaner — the phase directly tells the Orchestrator what the specialist needs next, rather than requiring the Orchestrator to interpret a generic status string.

---

## Updated graph.py Node Table

| Node | Phase-aware? | LLM calls in gather? | Notes |
|---|---|---|---|
| `structuring_agent` | No — single phase (always writes) | N/A | No missing-info risk; raw idea is always present |
| `prd_agent` | Yes | No | Requires: StructuredIdea.md, Constraints.md |
| `trd_agent` | Yes | No | Requires: PRD.md, Constraints.md, auth decision |
| `schema_agent` | Yes | No | Requires: TRD.md (data section) |
| `design_agent` | Yes | No | Requires: TRD.md, accepted_suggestions |
| `appflow_agent` | Yes | No | Requires: PRD.md, has_frontend=True |
| `rules_agent` | Yes | No | Requires: TRD.md, Constraints.md |
| `implementation_agent` | Yes | No | Requires: PRD.md, TRD.md, Schema.md |
| `module_planner_agent` | Yes | No | Requires: all PLANNER/ files + module name |
| `griller_node` | No | No | Interrupt point — awaits user input |
| `tech_stack_agent` | No | Yes | Single-shot: question in → suggestion out |
| `consistency_agent` | No | Yes | Read-only pass |
| `finalizer_agent` | No | Yes | Compilation |

---

## Summary of Changes Per File

| File | Change |
|---|---|
| `planner/agents/tech_stack_agent.py` | Remove all file-write logic. Return `Suggestion` object only. |
| `planner/agents/griller_agent.py` | Remove TechStackExpert routing. Return `needs_expert: True` and let Orchestrator route. |
| Every specialist agent | Add `_gather()` and `_write()` methods. `run()` dispatches on `state.phase`. |
| `planner/agents/orchestrator.py` | Replace single `call_specialist()` with two-phase `_call_specialist()`. Add `_run_griller_loop()`. Add `accepted_suggestions` accumulation. Remove `tech_suggestions` field. |
| `planner/graph.py` | Add `interrupt_before=["griller_node"]`. Add SQLite checkpointer. Remove `tech_suggestions` from initial state. Add `accepted_suggestions: []`. Add `phase: "gather"`. |
| `planner/state.py` | Add `phase: str`. Add `accepted_suggestions: list[dict]`. Remove `tech_suggestions: dict`. |
| `planner/watcher/architecture_watcher.py` | Add 800ms debounce. Add heartbeat writes. Add `.graph_running` lock check. Add STALE header on failure. |
| `planner/watcher/watcher_manager.py` | New file. Subprocess lifecycle: start/stop/health_check/restart. |
| `planner/watcher/heartbeat.py` | New file. Read/write heartbeat file. |
| `planner/tui/widgets/architecture_panel.py` | Add status indicator in panel header. Poll `watcher_manager.get_status_for_tui()` every 5s. |
