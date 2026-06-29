# PlannerX — Tools Registry
> All tools used by any agent in the system live in `planner/tools/`.
> Agents import from here only — no tool logic inside agent files.

---

## Folder structure

```
planner/tools/
├── __init__.py                  # exports everything, agents import from here
│
├── file_tools.py                # read, write, append, scaffold, diff
├── llm_tools.py                 # LLM call factory, retry wrapper
├── tracker_tools.py             # read/write/update Tracker.md
├── ascii_tools.py               # ASCII diagram generation (PHART + LLM fallback)
├── mermaid_tools.py             # .mmd generation + render to text (kept for compat)
├── editor_tools.py              # open file in $EDITOR, detect close
├── diff_tools.py                # semantic before/after diff summary
├── search_tools.py              # web search (TechStackExpert)
└── validation_tools.py          # file structure checks, section presence
```

---

## `file_tools.py`

Used by: every agent.

### `read_file(path: str) -> str`
- Reads a file from `PLANNER/` (or any path) and returns its content as a string
- Returns empty string `""` if file doesn't exist — never raises on missing file
- Caches read in session memory to avoid repeated disk reads for same file in same agent run

### `write_file(path: str, content: str, overwrite: bool = False) -> bool`
- Writes content to file
- If file is non-empty and `overwrite=False` → raises `OverwriteProtectionError` — caller must confirm
- If file is `RawIdea.md` → always raises `ReadOnlyFileError`, regardless of `overwrite` flag
- Atomic write: writes to `.tmp` first, then renames — prevents partial writes corrupting files

### `append_file(path: str, content: str) -> bool`
- Appends content to end of file with a trailing newline
- Only valid operation on: `RawIdea.md`, `DesignDecisions.md` (ADR log), `Tracker.md` change log
- Other files: use `write_file` with `overwrite=True`

### `scaffold_planner(project_path: str) -> list[str]`
- Creates `PLANNER/` directory + all required empty `.md` files
- Creates `ARCHITECTURE_DIAGRAMS/` and `MODULES/` subdirectories
- Returns list of paths created
- Idempotent: if folder/file already exists, skips it without error

### `list_planner_files(project_path: str) -> dict[str, dict]`
- Returns all files in `PLANNER/` with metadata: `{path: {size, modified_at, is_empty}}`
- Used by Orchestrator to detect session state on startup

### `file_exists(path: str) -> bool`
- Simple existence check — wraps `os.path.exists`

### `clear_file(path: str) -> bool`
- Empties a file (used by `/reset` command)
- Requires `force=True` parameter — prevents accidental clears

### `read_section(path: str, heading: str) -> str`
- Reads a specific `##`/`###` section from a markdown file by heading name
- Returns empty string if heading not found
- Used by agents that need only one part of a large file (e.g. Orchestrator reading only Fit Analysis from StructuredIdea.md)

---

## `llm_tools.py`

Used by: every agent that makes an LLM call (all except file watcher).

### `get_llm_client() -> BaseChatModel`
- Reads provider config from `.env` / `providers.yaml`
- Instantiates correct LangChain chat client based on `PROVIDER` env var
- Supported out of the box: `groq`, `openai`, `anthropic`, `nvidia`, `ollama`, `together`, `mistral`
- Adding new provider: add entry to `PROVIDER_MAP` dict in this file — no other file changes needed
- Returns a `BaseChatModel` — all agents work against this interface, never against a provider-specific class

### `llm_call(prompt: str, system: str = "", max_tokens: int = 4000) -> str`
- Single LLM call, returns response text
- Wraps `get_llm_client()` internally — agents don't instantiate client themselves
- Raises `LLMCallError` on failure (timeout, API error, empty response) — caller handles retry

### `llm_call_with_retry(prompt: str, system: str = "", max_retries: int = 1) -> str`
- Wraps `llm_call` with one retry on `LLMCallError`
- On second failure: raises `LLMCallError` with full error details for Orchestrator to surface to user
- `max_retries=1` by default — never silently retries more than once

### `llm_call_json(prompt: str, system: str = "") -> dict`
- Same as `llm_call` but parses response as JSON
- Strips markdown fences (` ```json `) before parsing
- Raises `LLMParseError` if response is not valid JSON — caller handles

### `stream_llm_call(prompt: str, system: str = "") -> Generator[str, None, None]`
- Streaming version — yields text chunks as they arrive
- Used by agents that stream output into the TUI Viewer panel in real time

---

## `tracker_tools.py`

Used by: Orchestrator, Updates Agent, Tracker Agent.

### `read_tracker(project_path: str) -> dict`
- Parses `Tracker.md` into structured dict:
```python
{
  "files": {
    "PRD.md": {"status": "✅ Approved", "agent": "prd_agent", "notes": "...", "updated_at": "..."},
    ...
  },
  "blockers": [...],
  "change_log": [...]
}
```

### `update_file_status(project_path: str, filename: str, status: str, agent: str, notes: str = "") -> bool`
- Updates a single file's row in Tracker.md
- Valid statuses: `⏳`, `🔄`, `👀`, `✅`, `❌` — raises `InvalidStatusError` for anything else
- Atomic write (read full file → update in memory → write back full file)

### `add_blocker(project_path: str, description: str, unblocked_by: str) -> bool`
- Appends a blocker entry to Tracker.md blockers section

### `resolve_blocker(project_path: str, description: str) -> bool`
- Marks a blocker as resolved, moves to a "Resolved" subsection

### `append_change_log(project_path: str, change_type: str, description: str, affected_files: list[str]) -> bool`
- Appends one entry to Tracker.md change log with timestamp

### `get_next_pending_file(project_path: str, sequence: list[str]) -> str | None`
- Given the main sequence list, returns the first file that is `⏳ Pending` or `❌ Blocked`
- Used by Orchestrator to find where to resume on startup

### `get_status_summary(project_path: str) -> str`
- Returns Tracker.md status table as a formatted string for display in TUI

---

## `ascii_tools.py`

Used by: Architecture Diagram Watcher, AppFlow Agent, Schema Agent (ER diagrams).

**Primary library: [PHART](https://github.com/scottvr/phart) (`pip install phart`)**

Pure Python, published to PyPI, actively maintained (2+ years). Renders NetworkX digraphs, GraphML, and GraphViz/DOT files into 7-bit ASCII, Unicode box-drawing characters, or ANSI-colored output. This is the best fit for PlannerX because:
- Pure Python, no external binary dependencies (no Java, no Graphviz install required)
- Works in any terminal including the Textual TUI
- Takes a NetworkX graph as input — which is exactly what an LLM can generate as structured JSON → graph → ASCII

**Secondary: LLM fallback**
If the graph structure is ambiguous or too complex to represent as a clean NetworkX graph, fall back to an LLM call that generates raw ASCII art directly using box-drawing characters. This is less structured but works for any diagram type.

**Required packages:** `phart`, `networkx`

---

### `build_graph_from_description(description: dict) -> nx.DiGraph`
- Takes a structured dict describing nodes + edges (generated by LLM from file contents)
- Returns a `networkx.DiGraph` ready to pass to PHART
- Input format:
```python
{
  "nodes": ["API Gateway", "Auth Service", "DB", "Cache"],
  "edges": [
    {"from": "API Gateway", "to": "Auth Service", "label": "verify"},
    {"from": "API Gateway", "to": "DB", "label": "query"},
    {"from": "Auth Service", "to": "Cache", "label": "session"}
  ]
}
```

### `render_ascii_diagram(graph: nx.DiGraph, charset: str = "ascii") -> str`
- Wraps PHART's `ASCIIRenderer`
- `charset`: `"ascii"` (7-bit, max compatibility) | `"unicode"` (box-drawing, cleaner) | `"ansi"` (ASCII + ANSI color)
- PHART supports `--charset ascii` for pure 7-bit output ensuring maximum compatibility, `--charset unicode` (default) for cleaner Unicode box drawing characters and arrows, and `--charset ansi` for ASCII glyphs with ANSI color escapes for older terminals that support color but not Unicode line-art.
- Returns rendered diagram as a plain string — write directly to `.md` or `.mmd` file
- Example output (ascii charset):
```
[API Gateway]
    +--------+--------+
    v                 v
[Auth Service]      [DB]
    v
 [Cache]
```

### `generate_diagram_from_files(diagram_type: str, context_files: dict[str, str], charset: str = "ascii") -> str`

One-shot pipeline: reads file contents → LLM extracts graph structure as JSON → `build_graph_from_description` → `render_ascii_diagram`.

`diagram_type` options and what files they read:

| `diagram_type` | Reads | Produces |
|---|---|---|
| `"system_architecture"` | TRD.md | Component + service flow diagram |
| `"data_flow"` | TRD.md + Schema.md | How data moves between modules |
| `"er_diagram"` | Schema.md | Entities + FK relationships |
| `"app_flow"` | AppFlow.md | User flow as directed graph |
| `"module_map"` | MODULES/*.md | Module dependency/interface map |

### `render_ascii_fallback(diagram_type: str, context: str) -> str`
- LLM-only fallback when PHART rendering fails or graph structure is too complex
- Prompt instructs LLM to draw the diagram directly using ASCII box characters (`+`, `-`, `|`, `>`, `v`, `^`)
- Used when: graph has cycles PHART can't lay out cleanly, or diagram type doesn't map to a DAG (e.g. bidirectional data flows)
- Result is less structured but always produces something renderable

### `write_ascii_diagram(path: str, content: str, diagram_type: str) -> bool`
- Writes ASCII diagram string to `ARCHITECTURE_DIAGRAMS/<filename>.md`
- Prepends metadata header:
```
<!-- Generated: YYYY-MM-DD HH:MM | Type: system_architecture | Charset: ascii -->
```
- On failure: prepends `[STALE — regeneration failed at HH:MM]` to existing content, does not overwrite

### `diagram_to_rich_text(ascii_content: str) -> str`
- Wraps the ASCII diagram in Rich `Text` with monospace formatting for display in the TUI Architecture panel
- Ensures correct line-by-line rendering — no word wrap, preserves spacing

---

## `mermaid_tools.py`

Used by: AppFlow Agent (flowchart syntax still valid for `.md` embedding), legacy diagram references.

> **Note:** ASCII is now the primary diagram format via `ascii_tools.py`. `mermaid_tools.py` is kept because mermaid flowchart syntax is still human-readable in `.md` files and valid as a secondary output format. Architecture Diagram Watcher uses `ascii_tools.py` for all `.md` diagram files; mermaid is only used when a file explicitly needs an embeddable mermaid block (e.g. AppFlow.md).

### `generate_mermaid(diagram_type: str, context: dict) -> str`
- LLM call that generates a mermaid diagram string
- `diagram_type`: `"flowchart"` | `"erDiagram"` | `"sequenceDiagram"` | `"architecture"`
- `context`: relevant file contents (e.g. Schema.md for erDiagram, AppFlow.md for flowchart)
- Returns raw mermaid string (no fences)

### `render_mermaid_to_text(mmd_content: str) -> str`
- Converts `.mmd` content to syntax-highlighted Rich text for display in TUI Architecture panel
- Does not require Node.js or external renderer — uses Rich's syntax highlighting on the mermaid source
- Returns a `rich.Text` or plain string with ANSI color codes

### `write_diagram(path: str, mmd_content: str) -> bool`
- Writes `.mmd` string to a file in `ARCHITECTURE_DIAGRAMS/`
- Prepends a `[Generated: YYYY-MM-DD HH:MM]` comment header
- On failure: prepends `[STALE — regeneration failed at HH:MM]` to existing file content instead of overwriting

### `validate_mermaid(mmd_content: str) -> bool`
- Basic structural validation: checks for valid diagram type declaration, no unclosed brackets
- Not a full parser — catches obvious malformed output from LLM before writing to disk

---

## `editor_tools.py`

Used by: Orchestrator (for `/edit` command).

### `open_in_editor(path: str) -> str`
- Opens file at `path` in `$EDITOR` (falls back to `nano` if unset)
- Blocks until editor process exits
- Returns updated file content after editor closes
- Used for `/edit <file>` command flow

### `detect_editor() -> str`
- Returns the editor that will be used: reads `$EDITOR`, `$VISUAL`, falls back to `nano`
- Used to display "Opening in [editor]..." message to user before launching

---

## `diff_tools.py`

Used by: Updates Agent (for showing before/after diff per file after re-run).

### `semantic_diff(before: str, after: str) -> str`
- LLM call: given two versions of a file, returns a human-readable summary of what changed
- Not a raw git diff — returns bullet points like "Removed: mobile user stories (US-04, US-05)"
- Max 10 bullet points — summarizes, does not enumerate every line
- Used by Updates Agent to show user what each specialist agent changed

### `raw_diff(before: str, after: str) -> list[str]`
- Standard Python `difflib.unified_diff` output
- Used internally for logging, not shown to user directly

---

## `search_tools.py`

Used by: TechStackExpert Agent (optional — only if live web search is enabled).

### `web_search(query: str, max_results: int = 5) -> list[dict]`
- Web search via Tavily API (requires `TAVILY_API_KEY` in `.env`)
- Returns list of `{title, url, snippet}` dicts
- If `TAVILY_API_KEY` not set: raises `SearchUnavailableError` — TechStackExpert falls back to LLM training data only, logs that search was unavailable
- TechStackExpert calls this to get current pricing/availability info for tool suggestions (e.g. "is this still free tier?")

### `search_enabled() -> bool`
- Returns `True` if `TAVILY_API_KEY` is set — used by TechStackExpert to decide whether to call `web_search` or work from LLM knowledge only

---

## `validation_tools.py`

Used by: Orchestrator (post-agent file validation), Updates Agent (blast radius check).

### `validate_file_structure(path: str, required_sections: list[str]) -> dict`
- Checks that a written file contains all required `##` headings
- Returns `{valid: bool, missing_sections: list[str], empty_sections: list[str]}`
- Called by Orchestrator after every specialist agent run, before showing output to user

### `check_frontend_signals(structured_idea: str, trd_content: str) -> bool`
- Checks both StructuredIdea.md and TRD.md for frontend-indicating keywords
- Returns `True` if frontend detected, `False` if backend-only
- Used by Orchestrator for AppFlow/DesignDecisions skip logic

### `check_consistency(files: dict[str, str]) -> list[dict]`
- Cross-file consistency check via LLM call
- Takes `{filename: content}` dict of all PLANNER/ files
- Returns list of `{file_a, file_b, issue}` dicts
- Used by `/consistency` command

### `file_is_complete(path: str, filename: str) -> bool`
- Returns `True` if file is non-empty AND has its required sections (based on known section map per filename)
- Used by Orchestrator to determine if a file can be skipped on resume

---

## Required packages per tool file

| Tool file | Package(s) |
|---|---|
| `file_tools.py` | stdlib only (`os`, `pathlib`, `shutil`) |
| `llm_tools.py` | `langchain-core`, `langchain-groq` / `langchain-openai` / etc. per provider |
| `tracker_tools.py` | stdlib only (`re`, `datetime`) |
| `ascii_tools.py` | `phart`, `networkx` |
| `mermaid_tools.py` | `rich` (for text rendering), `langchain-core` (for diagram generation LLM call) |
| `editor_tools.py` | stdlib only (`subprocess`, `os`) |
| `diff_tools.py` | stdlib `difflib` + `langchain-core` (for semantic diff LLM call) |
| `search_tools.py` | `tavily-python` (optional — graceful fallback if absent) |
| `validation_tools.py` | `langchain-core` (for consistency LLM call), stdlib `re` |

---

## `__init__.py` — what agents import

```python
# planner/tools/__init__.py
# Agents import everything from here. Never import tool modules directly.

from .file_tools import (
    read_file, write_file, append_file,
    scaffold_planner, list_planner_files,
    file_exists, clear_file, read_section
)
from .llm_tools import (
    get_llm_client, llm_call, llm_call_with_retry,
    llm_call_json, stream_llm_call
)
from .tracker_tools import (
    read_tracker, update_file_status,
    add_blocker, resolve_blocker,
    append_change_log, get_next_pending_file,
    get_status_summary
)
from .ascii_tools import (
    build_graph_from_description, render_ascii_diagram,
    generate_diagram_from_files, render_ascii_fallback,
    write_ascii_diagram, diagram_to_rich_text
)
from .mermaid_tools import (
    generate_mermaid, render_mermaid_to_text,
    write_diagram, validate_mermaid
)
from .editor_tools import open_in_editor, detect_editor
from .diff_tools import semantic_diff, raw_diff
from .search_tools import web_search, search_enabled
from .validation_tools import (
    validate_file_structure, check_frontend_signals,
    check_consistency, file_is_complete
)
```

Agent usage:
```python
# In any agent file — single import line
from planner.tools import read_file, write_file, llm_call, update_file_status
```

---

## Error types (raise from tools, caught by agents/Orchestrator)

Defined in `planner/tools/exceptions.py`:

```python
class OverwriteProtectionError(Exception): pass   # write_file: file non-empty, overwrite=False
class ReadOnlyFileError(Exception): pass           # write_file: attempted write to RawIdea.md
class LLMCallError(Exception): pass               # llm_call: API failure, timeout, empty response
class LLMParseError(Exception): pass              # llm_call_json: response not valid JSON
class InvalidStatusError(Exception): pass         # update_file_status: bad status symbol
class SearchUnavailableError(Exception): pass     # web_search: no API key set
```

All agent nodes catch these and either handle locally or set `pending_questions` / surface error to Orchestrator for user-facing retry prompt.

---

## What is NOT a tool (and why)

| Thing | Where it lives | Why not a tool |
|---|---|---|
| Slash command parsing | `tui/widgets/chat_input.py` | UI concern, not agent concern |
| File watcher loop | `watcher/architecture_watcher.py` | Long-running process, not a callable function |
| LangGraph graph definition | `graph.py` | Routing logic, not a tool |
| PlannerState schema | `state.py` | Data model, not a tool |
| Textual widgets | `tui/widgets/` | UI layer, not agent layer |
| Provider config loading | `llm_tools.py` internally | Encapsulated inside `get_llm_client()` |
