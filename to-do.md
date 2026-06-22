# PlannerX Project To-Do and Diagnostics List

This document lists the broken parts, design gaps, and configuration issues discovered during testing and code auditing of the PlannerX project, along with tasks to resolve them.

---

## 1. Environment & Path Issues (Urgent)

### 🟢 Resolved: Broken Virtual Environment Interpreter Paths
- **Symptom**: Executing `./install.sh` or running scripts under `.venv/bin/` directly (such as `.venv/bin/pytest`) causes a `bad interpreter: No such file or directory` shell error.
- **Root Cause**: The virtual environment was initialized at `/home/bhavik/Coding/projects/PlannerX`, but the workspace is currently at `/home/bhavik/Tech/Coding/projects/PlannerX`. The shebangs in the virtual environment are hardcoded to the absolute paths of the old directory structure.
- **Immediate Workaround**: Run commands explicitly using the virtual environment python interpreter (e.g., `.venv/bin/python -m pytest`).
- **Resolution Tasks**:
  - [x] Recreate the virtual environment using `uv venv` to rebuild correct shebang paths.
  - [x] Re-run `uv sync` to update active package binds.

---

## 2. Agent Constraint Violations (Design Gap)

### 🟢 Resolved: Tech Stack Agent Modifies DesignDecisions.md Directly
- **Symptom**: The utility `tech_stack_agent` writes directly to `DesignDecisions.md` (via `_log_to_design_decisions` helper).
- **Root Cause**: This violates the strict **Specialist Agent Single-File Ownership Constraint**, which dictates that *only* `design_agent` should write to `DesignDecisions.md`.
- **Side Effect**: If a user resets or re-runs the `design` agent, it will overwrite the file and erase any stack suggestions appended by the `tech_stack` agent (since `design_agent` constructs the file from scratch, though it reads `grill_answers` state cache, direct file appends are unsafe).
- **Resolution Tasks**:
  - [x] Refactor `tech_stack_agent.py` to remove `_log_to_design_decisions`.
  - [x] Ensure all accepted tech suggestions are saved in `state.grill_answers` and that `design_agent` handles rendering them into the final `DesignDecisions.md` draft.

---

## 3. Dependency & Provider Risks

### 🟢 Resolved: Implicit LLM Package Dependencies
- **Symptom**: Swapping providers in TUI (`/config provider openai`) or CLI causes a runtime crash if the corresponding integration package (e.g., `langchain-openai`) is not installed in the virtual environment.
- **Root Cause**: The app uses dynamic imports in `llm.py` to import `langchain_openai`, `langchain_anthropic`, `langchain_groq`, and `langchain_nvidia_ai_endpoints`. If a user switches to a provider, they must have installed the library.
- **Resolution Tasks**:
  - [x] Add pre-flight dependency checks inside TUI provider configuration handlers.
  - [x] Print clear setup commands (`uv add <integration-package>`) or attempt automatic installation using a subprocess wrapper when a missing package is requested.

---

## 4. Subdirectory File Ownership and Accessibility

### 🟢 Resolved: Agents Unable to Access or Modify Files inside Subdirectories
- **Symptom**: Change requests and resets for files inside `MODULES/` (e.g. `MODULES/auth.md`) or `ARCHITECTURE_DIAGRAMS/` (e.g. `SystemArchitecture.md`) were rejected with "No agent associated with..." errors.
- **Root Cause**: The hardcoded `_AGENT_MAP` registry and agent invocation dispatcher in `main.py` and `app.py` only handled top-level planning documents.
- **Resolution Tasks**:
  - [x] Dynamically map all `MODULES/*.md` files to the `"modules"` agent, and `ARCHITECTURE_DIAGRAMS/*.md` files to the `"diagram"` agent in TUI and CLI.
  - [x] Update the run/dispatch execution blocks in `main.py` and `app.py` to extract the `__module_name__` if a module subfile is reset/updated, and invoke `module_planner_agent` or `architecture_diagram_agent` appropriately.

---

## Full Code Audit — Bugs, Errors & Broken Logic

> Discovered via systematic static analysis, import checks, and unit-level logic testing of every module.  
> **Audit Date**: 2026-06-22 | **Method**: Python `py_compile`, manual import + logic testing, source inspection.

---

### 🟢 Resolved: prd_agent.py Bypasses the invoke_llm_safe Retry Wrapper

- **File**: `planner/agents/prd_agent.py`
- **Symptom**: If the LLM call fails (rate limit, network error, bad key), the user sees a crash with no retry prompt. All other agents use `invoke_llm_safe()` which asks the user `"Retry? [y/n]"`.
- **Root Cause**: `prd_agent` calls `get_llm()` and `llm.invoke(messages)` directly — not via the shared `invoke_llm_safe()` wrapper defined in `_base.py`.
- **Impact**: Inconsistent error handling behaviour for the most important planning document; silent failures on transient API errors.
- **Fix Plan**:
  1. **Update the import line** in `planner/agents/prd_agent.py`:
     - Remove: `from planner.llm import get_llm`
     - Add: `from planner.agents._base import invoke_llm_safe, strip_markdown_fence`
  2. **Replace the LLM call block** (currently `llm = get_llm()` → `response = llm.invoke(messages)` → `prd_content = response.content`):
     - Replace with: `prd_content = invoke_llm_safe(messages)`
  3. **Remove the now-redundant manual markdown fence stripping** block below the LLM call — since `strip_markdown_fence()` is available from `_base.py`, replace the manual `if prd_content_stripped.startswith(...)` block with a single call: `prd_content = strip_markdown_fence(prd_content)`.
  4. **Remove the unused `import os`** at the top of `prd_agent.py` (it was only there to support the old direct LLM pattern).
  5. **Verify**: Confirm `prd_agent.py` no longer imports or calls `get_llm` directly — grep for `get_llm` in that file should return zero results.
- **Checklist**:
  - [x] Remove `from planner.llm import get_llm` and `import os` from `prd_agent.py`
  - [x] Add `from planner.agents._base import invoke_llm_safe, strip_markdown_fence` to `prd_agent.py`
  - [x] Replace `get_llm()` + `llm.invoke(messages)` block with `invoke_llm_safe(messages)`
  - [x] Replace manual fence stripping block with `strip_markdown_fence(prd_content)`
  - [x] Run `python -c "from planner.agents.prd_agent import prd_agent"` to confirm clean import

---

### 🟢 Resolved: prd_agent.py Does NOT Set state.calling_agent on needs_input`

- **File**: `planner/agents/prd_agent.py`
- **Symptom**: When `prd_agent` sets `status="needs_input"` (empty `StructuredIdea.md`), it does NOT set `state.calling_agent`. After the griller collects user answers, `_route_from_griller` uses `state.next_agent or state.calling_agent` to resume — but both are empty. The griller falls back to routing to `"orchestrator"` instead of returning to `prd_agent`, causing the PRD to be silently skipped.
- **Root Cause**: All other agents (`trd_agent`, `schema_agent`, `design_agent`, `appflow_agent`, `rules_agent`, `implementation_agent`) correctly set `state.calling_agent = "<self>"` before returning. `prd_agent` does not.
- **Impact**: After answering griller questions intended for the PRD step, the pipeline re-routes to the orchestrator which detects PRD.md is still empty and re-queues `prd_agent` — causing a potentially infinite loop.
- **Fix Plan**:
  1. **Locate the `needs_input` block** in `planner/agents/prd_agent.py` (currently lines ~47–50):
     ```python
     if not structured_idea:
         state.pending_questions = ["The StructuredIdea.md file is empty..."]
         state.status = "needs_input"
         state.current_file = "PRD.md"
         return state
     ```
  2. **Add** `state.calling_agent = "prd"` directly before the `return state` line, making it consistent with all other agents:
     ```python
     if not structured_idea:
         state.pending_questions = ["The StructuredIdea.md file is empty..."]
         state.status = "needs_input"
         state.current_file = "PRD.md"
         state.calling_agent = "prd"   # ← ADD THIS
         return state
     ```
  3. **Verify**: Run the graph routing logic test — after griller collects answers for the PRD question, `_route_from_griller` should now correctly return `"prd"` instead of `"orchestrator"`.
- **Checklist**:
  - [x] Add `state.calling_agent = "prd"` to the `needs_input` early-return block in `prd_agent.py`
  - [x] Confirm by running: `python -c "from planner.state import PlannerState; from planner.graph import _route_from_griller; s = PlannerState(project_path='/tmp', calling_agent='prd', next_agent=''); print(_route_from_griller(s))"` → should print `prd`

---

### 🟢 Resolved: scaffold.py Scaffolds CLAUDE.md Inside PLANNER/ but finalize Writes It to Project Root

- **File**: `planner/files/scaffold.py` (line 16) and `planner/main.py` (`_compile_claude_md`)
- **Symptom**: After `planner init`, an empty `PLANNER/CLAUDE.md` file is created. After `planner finalize`, a real `CLAUDE.md` is written to the **project root** (not inside `PLANNER/`). The user ends up with two files: an empty `PLANNER/CLAUDE.md` and the real root-level `CLAUDE.md`.
- **Root Cause**: `scaffold.py` includes `"CLAUDE.md"` in `PLANNER_FILES`, but `_compile_claude_md()` calculates the write path as `planner_dir.parent / "CLAUDE.md"` (the project root).
- **Impact**: Confusing file layout, the empty `PLANNER/CLAUDE.md` may mislead the user or coding agents reading the planner directory.
- **Fix Plan**:
  1. **Edit `planner/files/scaffold.py`**: Remove `"CLAUDE.md"` from the `PLANNER_FILES` list (line 16). `CLAUDE.md` is not a planning input document — it is the final compiled output and must only live at the project root.
  2. **Add a note comment** in `scaffold.py` above `PLANNER_FILES` explaining that `CLAUDE.md` is intentionally excluded because it is written by `planner finalize` to the project root.
  3. **No changes needed** to `_compile_claude_md` in `main.py` — the write path (`planner_dir.parent / "CLAUDE.md"`) is already correct.
  4. **Cleanup for existing projects**: If users already ran `planner init` and have a stale `PLANNER/CLAUDE.md`, add a one-time cleanup step in `scaffold_project()` to detect and delete `PLANNER/CLAUDE.md` if it is empty (size == 0), since the scaffolded file was always empty.
- **Checklist**:
  - [x] Remove `"CLAUDE.md"` from `PLANNER_FILES` list in `planner/files/scaffold.py`
  - [x] Add an explanatory comment above `PLANNER_FILES` clarifying the exclusion
  - [x] Optionally: add cleanup of stale empty `PLANNER/CLAUDE.md` inside `scaffold_project()`
  - [x] Verify with: `python -c "from planner.files.scaffold import PLANNER_FILES; assert 'CLAUDE.md' not in PLANNER_FILES"`

---

### 🟢 Resolved: watchfiles Is a Runtime Dependency Declared Only in [dependency-groups].dev`

- **File**: `pyproject.toml`, `planner/tui/app.py`
- **Symptom**: `planner/tui/app.py`'s `start_watcher()` imports `watchfiles` at runtime. `watchfiles` is only declared under `[dependency-groups].dev`. A production-style install (`uv sync --no-dev`) will crash the TUI watcher at launch.
- **Root Cause**: `watchfiles` was placed in dev dependencies alongside pytest, but it is used by production TUI code.
- **Impact**: Anyone installing `plannerx` without dev dependencies (e.g., via `pip install` or `uv sync --no-dev`) will see a `ModuleNotFoundError: No module named 'watchfiles'` when the TUI starts.
- **Fix Plan**:
  1. **Edit `pyproject.toml`**: Move `"watchfiles>=1.2.0"` from `[dependency-groups].dev` into the `[project].dependencies` list.
     - Before:
       ```toml
       [dependency-groups]
       dev = [
           "pytest>=9.1.1",
           "pytest-mock>=3.15.1",
           "watchfiles>=1.2.0",
       ]
       ```
     - After:
       ```toml
       [project]
       dependencies = [
           ...
           "watchfiles>=1.2.0",   # ← moved here
       ]

       [dependency-groups]
       dev = [
           "pytest>=9.1.1",
           "pytest-mock>=3.15.1",
       ]
       ```
  2. **Run `uv sync`** after editing to regenerate the lockfile and ensure the dependency is pinned correctly.
  3. **Verify**: Confirm `watchfiles` is in the resolved dependency tree: `uv pip show watchfiles` (or check `uv.lock`).
- **Checklist**:
  - [x] Move `watchfiles>=1.2.0` to `[project].dependencies` in `pyproject.toml`
  - [x] Remove it from `[dependency-groups].dev`
  - [x] Run `uv sync` to update `uv.lock`
  - [x] Verify `watchfiles` appears in the main dependency list: `uv pip show watchfiles`

---

### 🟢 Resolved: Triple-Duplicated _AGENT_MAP in app.py (DRY Violation)

- **File**: `planner/tui/app.py`
- **Symptom**: `_AGENT_MAP` (the dict mapping filenames to agent names) is defined **3 separate times** — in `_cmd_reset`, inside the `run_reset` closure, and in `_handle_change_request`. Any new agent addition requires updating all three independently. One is already incomplete (missing `MODULES/` and `ARCHITECTURE_DIAGRAMS/` handling in the orchestrator dispatch reset block).
- **Root Cause**: No shared helper/constant was extracted; each handler copy-pasted the map.
- **Impact**: Inconsistent behaviour across reset mechanisms; maintenance burden; active bugs already present from stale copies.
- **Fix Plan**:
  1. **Extract a module-level helper function** at the top of `planner/tui/app.py` (after imports, before the class definition):
     ```python
     # Single source of truth: maps planning filenames to their owning agent name
     _FILE_AGENT_MAP = {
         "StructuredIdea.md":     "structuring",
         "PRD.md":                "prd",
         "TRD.md":                "trd",
         "Schema.md":             "schema",
         "DesignDecisions.md":    "design",
         "AppFlow.md":            "appflow",
         "Rules.md":              "rules",
         "ImplementationPlan.md": "implementation",
         "Tracker.md":            "tracker",
     }

     def _resolve_agent(filename: str) -> str | None:
         """Return the agent name for a given planning filename, including subdirectory prefixes."""
         if filename.startswith("MODULES/"):
             return "modules"
         if filename.startswith("ARCHITECTURE_DIAGRAMS/"):
             return "diagram"
         return _FILE_AGENT_MAP.get(filename)
     ```
  2. **Replace all three inline `_AGENT_MAP` definitions** in `_cmd_reset`, the `run_reset` closure, and `_handle_change_request` with calls to `_resolve_agent(filename)` / `_resolve_agent(target)`. Delete the local `_AGENT_MAP = {...}` dict in each location.
  3. **Ensure `_resolve_agent` is the canonical source** — `main.py` has its own `_run_single_agent` which also contains a copy. Either import `_resolve_agent` from `app.py` (discouraged: circular) or extract it into a shared `planner/utils/agent_utils.py` that both `main.py` and `app.py` import from.
- **Checklist**:
  - [x] Define `_FILE_AGENT_MAP` and `_resolve_agent()` at module level in `app.py` (or in a shared `planner/utils/agent_utils.py`)
  - [x] Delete the 3 local `_AGENT_MAP = {...}` dicts from `_cmd_reset`, `run_reset`, and `_handle_change_request`
  - [x] Replace each `_AGENT_MAP.get(...)` / manual prefix checks with `_resolve_agent(...)`
  - [x] Also update `main.py`'s `_run_single_agent` to use the same shared map
  - [x] Verify grep finds zero remaining `_AGENT_MAP = {` in `app.py`

---

### 🟢 Resolved: reset Action in Chat Orchestrator Dispatch Misses MODULES/ and ARCHITECTURE_DIAGRAMS/ Files

- **File**: `planner/tui/app.py` → `_handle_change_request` → `elif action == "reset"` block (lines ~757–802)
- **Symptom**: If a user types a chat message like *"reset MODULES/auth.md"* or *"reset ARCHITECTURE_DIAGRAMS/SystemArchitecture.md"*, the chat orchestrator dispatch block resolves `agent_name = _AGENT_MAP.get(target)` which returns `None` for those paths, silently printing `"No agent associated with..."` and doing nothing.
- **Root Cause**: The `_AGENT_MAP` in the reset dispatch block does not include `MODULES/` prefix or `ARCHITECTURE_DIAGRAMS/` prefix detection (unlike `_cmd_reset` and `change_request` which do check `startswith("MODULES/")`).
- **Impact**: Reset of module specs or architecture diagram files via conversational chat is broken — fails silently.
- **Fix Plan**:
  > **Note**: This fix is naturally solved as a consequence of the DRY fix above (Triple-Duplicated `_AGENT_MAP`). If `_resolve_agent()` is extracted and used in all three dispatch locations, this bug is automatically fixed. The steps below describe the standalone fix if applied independently.
  1. **Locate the `elif action == "reset"` block** inside the `run_orchestrator` function in `_handle_change_request` (approximately lines 757–802 of `app.py`).
  2. **Find the `agent_name` resolution line** — currently it is `agent_name = _AGENT_MAP.get(target)` with no prefix handling.
  3. **Replace it** with the same prefix-aware pattern used in `_cmd_reset`:
     ```python
     # Before (broken):
     agent_name = _AGENT_MAP.get(target)

     # After (fixed):
     if target.startswith("MODULES/"):
         agent_name = "modules"
     elif target.startswith("ARCHITECTURE_DIAGRAMS/"):
         agent_name = "diagram"
     else:
         agent_name = _AGENT_MAP.get(target)
     ```
  4. **Also add module name extraction** for the reset path — when agent_name is `"modules"`, extract and pass the module name into state similarly to how `change_request` does.
- **Checklist**:
  - [x] Add `MODULES/` and `ARCHITECTURE_DIAGRAMS/` prefix checks to the reset dispatch in `_handle_change_request`
  - [x] Add module name extraction (`target.split("/")[-1].replace(".md", "")`) when resetting a module
  - [x] Test by sending chat: "reset MODULES/auth.md" and confirm agent is invoked
  - [x] Test: "reset ARCHITECTURE_DIAGRAMS/SystemArchitecture.md" → confirm `generate_diagrams` is called

---

### 🟢 Resolved: tracker_agent Sets next_agent="modules" Causing Spurious Graph Node Invocation

- **File**: `planner/agents/tracker_agent.py` (line 77) and `planner/graph.py`
- **Symptom**: After `tracker_agent` completes, it sets `state.next_agent = "modules"`. The orchestrator **skips** `modules` in its `_SEQUENCE` loop (via `continue`), but `"modules"` IS in `_VALID_NODES`. This means `_route_from_orchestrator` routes to the `modules` node — and `module_planner_agent` immediately returns `status="done"` with no work done (since `__module_name__` is not set). This is a wasted LangGraph invocation on every pipeline run.
- **Root Cause**: `tracker_agent` hardcodes `next_agent="modules"` as a "what should run next" signal, but modules are skipped in the orchestrator's main sequence and are only triggered by user commands.
- **Impact**: Adds one spurious node hop per pipeline run; makes `state.status="done"` originate from `module_planner_agent` instead of `orchestrator`, which could confuse any future orchestrator logic that checks `status`.
- **Fix Plan**:
  1. **Edit `planner/agents/tracker_agent.py`** line 77:
     - Change `state.next_agent = "modules"` → `state.next_agent = "orchestrator"`
     - This makes `tracker_agent` correctly hand control back to the orchestrator, which will then detect all files are populated and set `state.status = "done"` (its intended job).
  2. **Update the docstring/comment** in `tracker_agent.py` to note that it routes back to `orchestrator` to determine pipeline completion, not to `modules` directly.
  3. **No changes needed** in `graph.py` — the routing logic already handles `next_agent = "orchestrator"` correctly via `_route_from_specialist` → `"orchestrator"`.
  4. **Verify the end-to-end flow**: After the fix, a full `planner run` should terminate cleanly from `orchestrator` (all files populated → `state.status = "done"`) without an extra round-trip through `module_planner_agent`.
- **Checklist**:
  - [x] In `tracker_agent.py` line 77: change `state.next_agent = "modules"` to `state.next_agent = "orchestrator"`
  - [x] Run the graph routing test: confirm `_route_from_specialist` with `tracker_agent` output routes to `orchestrator`, not `modules`
  - [x] Optionally: add a comment explaining that `modules` is triggered explicitly by user, not from the main pipeline

---

### 🟢 Resolved: planner/watcher/architecture_watcher.py Is Orphaned Dead Code

- **File**: `planner/watcher/architecture_watcher.py`
- **Symptom**: This module defines a standalone `start_watcher()` function that watches for `.md` changes and re-runs diagram generation. However, it is **never imported or called** from any production code path. The TUI `app.py` implements its own inline watcher via an anonymous `watch_loop()` thread. There is no CLI command `planner watch`. The module can only be run as a script directly.
- **Root Cause**: The watcher module was written as a standalone utility but never integrated with the CLI or TUI.
- **Impact**: Dead code that creates confusion and increases maintenance surface unnecessarily.
- **Fix Plan** — Chosen approach: **Delete the orphaned module** (the TUI watcher covers the same functionality inline and is already working):
  1. **Delete** `planner/watcher/architecture_watcher.py`.
  2. **Delete** `planner/watcher/__init__.py`.
  3. **Delete** the now-empty `planner/watcher/` directory.
  4. **Verify** no other file imports from `planner.watcher` — run: `grep -r "from planner.watcher" .` and `grep -r "import planner.watcher" .` — both should return zero results.
  5. **Alternative** (if a standalone headless watcher is desired for CI/CD use cases): Register a `planner watch` CLI command in `main.py` that imports `start_watcher` from this module, and document it in the help text. Only choose this path if there is a concrete use case beyond the TUI.
- **Checklist**:
  - [x] Confirm no production imports reference `planner.watcher` (grep check)
  - [x] Delete `planner/watcher/architecture_watcher.py`
  - [x] Delete `planner/watcher/__init__.py`
  - [x] Remove the `planner/watcher/` directory
  - [x] Run full import check: `python -c "import planner"` to confirm no broken imports remain

---

### 🟢 Resolved: ViewerPanel.output_buffer Grows Without Bound in Long Sessions

- **File**: `planner/tui/widgets/viewer_panel.py`
- **Symptom**: Every call to `write_output(text)` appends to `self.output_buffer`. This buffer is never pruned, cleared (unless explicitly via `clear_output()`), or limited. On long planning sessions with many LLM calls, the buffer grows unboundedly, consuming increasing memory.
- **Root Cause**: No max-size guard or rolling-window eviction on the buffer list.
- **Impact**: Gradual memory growth; on multi-hour sessions with verbose agents this could become noticeable.
- **Fix Plan**:
  1. **Add `from collections import deque`** import at the top of `planner/tui/widgets/viewer_panel.py`.
  2. **Change `self.output_buffer = []`** in `__init__` to `self.output_buffer = deque(maxlen=500)`. A `deque` with `maxlen` automatically evicts the oldest items when full — zero extra logic needed.
  3. **The `clear_output` method** already calls `self.output_buffer.clear()` — this works identically on `deque`, no changes needed.
  4. **The replay loop** in `write_output` iterates `for line in self.output_buffer` — also works identically on `deque`, no changes needed.
  5. **Choose a sensible `maxlen`** — 500 lines is a safe default (covers most full pipeline runs). Can be made configurable via a class constant `_MAX_BUFFER = 500` if desired.
- **Checklist**:
  - [x] Add `from collections import deque` to `viewer_panel.py`
  - [x] Change `self.output_buffer = []` → `self.output_buffer = deque(maxlen=500)` in `__init__`
  - [x] Verify `clear()` and iteration still work (they do natively on `deque`)

---

### 🟢 Resolved: waiting_for_input Boolean Is Not Thread-Safe

- **File**: `planner/tui/app.py`
- **Symptom**: `self.waiting_for_input` is read in the Textual main thread (inside `on_chat_input_command_submitted`) and written in background worker threads (inside the `worker()` closure of `run_in_background`). There is no `threading.Lock` protecting access.
- **Root Cause**: Plain bool assignment was used under the assumption that it is GIL-safe, which is mostly true, but not formally guaranteed for compound check-then-act patterns.
- **Impact**: Edge case: user submits input while a worker is simultaneously setting `waiting_for_input = False` — could cause a submitted answer to be treated as a new command instead of a griller response, or vice versa.
- **Fix Plan** — Replace the plain bool with `threading.Event`:
  1. **Add `import threading`** at the top of `planner/tui/app.py` (it may already be there via other imports — if so, skip).
  2. **In `__init__`**, change:
     - `self.waiting_for_input = False` → `self._input_event = threading.Event()`
  3. **In the `worker()` function** inside `run_in_background`:
     - `self.waiting_for_input = True` → `self._input_event.set()`
     - `self.waiting_for_input = False` → `self._input_event.clear()`
  4. **In `on_chat_input_command_submitted`**, change:
     - `if self.waiting_for_input:` → `if self._input_event.is_set():`
  5. **In the `tui_input` lambda** (patched `builtins.input` inside `worker`):
     - The flag is set before calling `self.input_queue.get()` — the `Event.set()` call ensures visibility to the main thread before any answer is consumed.
  6. **Result**: `threading.Event` uses a proper internal lock and is guaranteed safe for cross-thread signal/check patterns.
- **Checklist**:
  - [x] Add `import threading` to `app.py` if not present
  - [x] Replace `self.waiting_for_input = False` with `self._input_event = threading.Event()` in `__init__`
  - [x] Replace all `self.waiting_for_input = True` → `self._input_event.set()`
  - [x] Replace all `self.waiting_for_input = False` → `self._input_event.clear()`
  - [x] Replace `if self.waiting_for_input:` → `if self._input_event.is_set():`

---

### 🟢 Resolved: pyproject.toml Has Placeholder Description

- **File**: `pyproject.toml` (line 4)
- **Symptom**: `description = "Add your description here"` was never filled in.
- **Fix Plan**:
  1. **Edit `pyproject.toml` line 4**:
     - Change: `description = "Add your description here"`
     - To: `description = "AI-driven project planning CLI and TUI — generates PRD, TRD, Schema, and architecture docs via LangGraph agent pipelines."`
- **Checklist**:
  - [x] Update `description` field in `pyproject.toml` line 4

---

### 🟢 Resolved: ArchitecturePanel Docstring Incorrectly Describes .mmd Rendering

- **File**: `planner/tui/widgets/architecture_panel.py`
- **Symptom**: The class docstring states *"renders the active .mmd diagram using Rich's Syntax highlighter (mermaid lexer)"`. In reality, the panel reads `.md` files (`SystemArchitecture.md`, `SystemDesign.md`) and renders them with `rich.markdown.Markdown`, not Mermaid syntax highlighting.
- **Fix Plan**:
  1. **Edit the module-level docstring** at the top of `architecture_panel.py` (lines 1–8):
     - Remove: `"renders the active .mmd diagram using Rich's Syntax highlighter (mermaid lexer)"`
     - Replace with: `"Renders SystemArchitecture.md (or SystemDesign.md as fallback) from the ARCHITECTURE_DIAGRAMS/ directory using rich.markdown.Markdown. Refreshes live when diagram files change."`
  2. **Edit the `ArchitecturePanel` class docstring** (line 28):
     - Change: `"Top-right panel — renders the active Mermaid architecture diagram."`
     - To: `"Top-right panel — displays architecture documents as rendered Markdown."`
  3. **Also fix the `refresh_diagram` method docstring** which references `.mmd` and `SystemArchitecture.mmd` — update to `.md` extension.
- **Checklist**:
  - [x] Update module-level docstring in `architecture_panel.py`
  - [x] Update `ArchitecturePanel` class docstring
  - [x] Update `refresh_diagram` method docstring to reference `.md` not `.mmd`

---

### 🟢 Resolved: structuring_agent Hardcodes next_agent="prd", Bypassing Orchestrator Routing

- **File**: `planner/agents/structuring_agent.py` (line 53)
- **Symptom**: On success, `structuring_agent` explicitly sets `state.next_agent = "prd"` — meaning when `_route_from_specialist` returns `"orchestrator"`, the orchestrator receives a pre-populated `next_agent` pointing to `prd` rather than re-evaluating the sequence.
- **Root Cause**: Hardcoded routing decision in a specialist agent.
- **Impact**: Minor architectural inconsistency. If the pipeline sequence is ever reordered (e.g., inserting a new agent between `structuring` and `prd`), this hardcoded routing will silently skip the new agent.
- **Fix Plan**:
  1. **Edit `planner/agents/structuring_agent.py`** — locate the success return block (currently lines ~47–54):
     ```python
     # Current (bad):
     state.structured_idea = content
     state.current_file = "StructuredIdea.md"
     state.status = "drafting"
     state.next_agent = "prd"   # ← REMOVE THIS
     return state
     ```
     Replace with:
     ```python
     # Fixed:
     state.structured_idea = content
     state.current_file = "StructuredIdea.md"
     state.status = "drafting"
     state.next_agent = "orchestrator"   # ← hand control back to orchestrator
     return state
     ```
  2. **Verify**: After the fix, `_route_from_specialist(structuring_output)` returns `"orchestrator"`, and `orchestrator` scans its sequence — finding `StructuredIdea.md` is now populated, it advances to `prd` naturally.
  3. **Consistency check**: Confirm `state.next_agent = "orchestrator"` (or leaving it empty, which defaults to orchestrator via `_route_from_specialist`) is the pattern used by all other successful specialist agents.
- **Checklist**:
  - [x] In `structuring_agent.py` line 53: change `state.next_agent = "prd"` → `state.next_agent = "orchestrator"`
  - [x] Verify the graph routing test still correctly transitions `structuring → orchestrator → prd`
