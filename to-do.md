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
