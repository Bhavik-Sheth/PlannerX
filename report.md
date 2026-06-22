# PlannerX Agent and Project Architecture Report

This report outlines the structural scaffolding, agent responsibilities, file ownership, and execution control flow of the PlannerX project.

---

## 1. Project Directory Scaffolding

```
PlannerX/
├── PLANNER/                       # Scaffolding directory for generated plans
│   ├── ARCHITECTURE_DIAGRAMS/     # Generated architecture diagrams (Markdown format)
│   │   ├── DataFlow.md
│   │   ├── FolderStructure.md
│   │   ├── SystemArchitecture.md  # Horizontal ASCII system architecture
│   │   └── SystemDesign.md        # Horizontal ASCII system design
│   ├── MODULES/                   # Optional spec sheets for planned modules
│   │   └── <module_name>.md
│   ├── AppFlow.md                 # User journeys and screen hierarchy
│   ├── CLAUDE.md                  # Compiled master execution context
│   ├── Constraints.md             # Project constraints (filled manually by user)
│   ├── DesignDecisions.md         # Architectural decisions and trade-offs log
│   ├── ImplementationPlan.md      # Phased execution plan
│   ├── PRD.md                     # Product Requirements Document
│   ├── RawIdea.md                 # Unstructured user ideas input
│   ├── Rules.md                   # Project coding rules and standards
│   ├── Schema.md                  # Database and data model schemas
│   ├── StructuredIdea.md          # Structured project description
│   └── Tracker.md                 # Project document status sheet
├── planner/                       # Main Python codebase
│   ├── agents/                    # LLM-powered specialist agents
│   │   ├── _base.py               # Shared utility functions and prompt wrapping
│   │   ├── appflow_agent.py
│   │   ├── architecture_diagram_agent.py
│   │   ├── chat_orchestrator.py
│   │   ├── design_agent.py
│   │   ├── griller_agent.py
│   │   ├── implementation_agent.py
│   │   ├── module_planner_agent.py
│   │   ├── orchestrator.py
│   │   ├── prd_agent.py
│   │   ├── rules_agent.py
│   │   ├── schema_agent.py
│   │   ├── structuring_agent.py
│   │   ├── tech_stack_agent.py
│   │   ├── tracker_agent.py
│   │   └── trd_agent.py
│   ├── files/                     # Filesystem read, write, and scaffold helpers
│   │   ├── reader.py
│   │   ├── scaffold.py
│   │   └── writer.py
│   ├── tui/                       # Textual terminal UI layout & styles
│   │   ├── widgets/
│   │   │   ├── architecture_panel.py
│   │   │   ├── chat_input.py
│   │   │   ├── file_tree.py
│   │   │   └── viewer_panel.py
│   │   ├── app.py
│   │   └── planner.css
│   ├── utils/                     # Mermaid diagram and utility scripts
│   │   └── mermaid_render.py
│   ├── watcher/                   # Watch files daemon to refresh diagrams
│   │   └── architecture_watcher.py
│   ├── graph.py                   # LangGraph orchestration graph builder
│   ├── llm.py                     # Provider configuration and key mapping
│   ├── main.py                    # Typer CLI entrypoint
│   └── state.py                   # Shared Pydantic LangGraph state
└── tests/                         # Unit tests
    └── test_watcher.py
```

---

## 2. Agent Roles and File Ownership

Below is a detailed breakdown of what each agent does, what files they read/write, and the constraints on file modifications.

### Orchestrator Agent (Master Agent)
The **Orchestrator Agent** acts as the master agent of the system, managing the pipeline's overall state and directly writing/managing the following core files:
- **`RawIdea.md`**: Appends the raw unstructured project ideas inputted by the user (via CLI/TUI chat interface).
- **`Constraints.md`**: Created during initialization and updated with user constraints.
- **`CLAUDE.md`**: Compiled from all approved planning files on finalization to provide the master execution context.

### Specialist Agents (Strict Single-File Ownership Constraint)
Each specialist agent runs within the LangGraph orchestrator loop and is strictly constrained to write **only its designated file**. No specialist agent writes or mutates files outside of its direct ownership boundary.

| Agent | Responsibility | Reads | Writes (Designated File) |
| :--- | :--- | :--- | :--- |
| **Structuring Agent**<br>`structuring_agent.py` | Structures raw user ideas from `RawIdea.md` into a formal, clear representation. | `RawIdea.md` | `StructuredIdea.md` |
| **PRD Agent**<br>`prd_agent.py` | Generates detailed Product Requirements (features, user roles, user stories). | `StructuredIdea.md` | `PRD.md` |
| **TRD Agent**<br>`trd_agent.py` | Defines technical architecture, API designs, tech stack, and infrastructure. | `StructuredIdea.md`, `PRD.md` | `TRD.md` |
| **Schema Agent**<br>`schema_agent.py` | Designs the database models, tables, indexes, and relationship structures. | `StructuredIdea.md`, `PRD.md`, `TRD.md` | `Schema.md` |
| **Design Agent**<br>`design_agent.py` | Logs key frontend/UX decisions, trade-offs, and rejected options (only run if frontend detected). | `StructuredIdea.md`, `TRD.md`, `PRD.md` | `DesignDecisions.md` |
| **AppFlow Agent**<br>`appflow_agent.py` | Drafts the step-by-step user journeys and view maps (only run if frontend detected). | `StructuredIdea.md`, `PRD.md`, `TRD.md` | `AppFlow.md` |
| **Rules Agent**<br>`rules_agent.py` | Establishes project coding rules, directory structures, styling patterns, and lint conventions. | `StructuredIdea.md`, `PRD.md`, `TRD.md`, `Schema.md` | `Rules.md` |
| **Implementation Agent**<br>`implementation_agent.py` | Defines a phased implementation checklist and development milestones. | All previous planning documents | `ImplementationPlan.md` |
| **Tracker Agent**<br>`tracker_agent.py` | Builds a status table indicating which files are drafted, approved, or pending. | `PlannerState` | `Tracker.md` |
| **Module Planner Agent**<br>`module_planner_agent.py` | Plans specific code files or logic blocks when modules are explicitly requested. | `StructuredIdea.md` | `MODULES/<name>.md` |

---

## 3. Orchestration & Control Flow Agents

These agents do not write planning documents themselves, but instead manage execution, routing, user input, and helper utilities.

### 1. LangGraph Orchestrator (`orchestrator.py`)
- **Control & Action**: Determines which specialist agent to run next based on what files exist and are populated.
- **Conditional Skip**: Evaluates project content for keywords indicating frontend presence. If no frontend is requested, it skips the `DesignDecisions.md` and `AppFlow.md` generators.

### 2. Conversational Brain (`chat_orchestrator.py`)
- **Control & Action**: Parses natural language messages from the TUI or CLI chat bar.
- **Routing**: Resolves intent into either plain chat answers or structured actions (e.g. `init`, `describe`, `run`, `status`, `approve`, `reset`, `module_add`, `module_list`).

### 3. Griller Agent (`griller_agent.py`)
- **Control & Action**: Intercepts pipeline execution when a specialist agent indicates they need clarification on requirements or stack choice (releasing a question into `pending_questions`).
- **Interaction**: Prompts the user interactively in the TUI/CLI terminal to answer.

### 4. Tech Stack Agent (`tech_stack_agent.py`)
- **Control & Action**: Invoked when the user replies to a griller question with "?" or requests recommendations.
- **Interaction**: Calls the LLM to propose tech options with trade-offs. Once accepted by the user, appends the choice to `DesignDecisions.md` and populates `grill_answers`.

### 5. Architecture Diagram Agent (`architecture_diagram_agent.py`)
- **Control & Action**: Independent generator that takes `TRD.md`, `Schema.md`, and `AppFlow.md` and writes detailed horizontal ASCII diagrams, folder listings, and data flow summaries to the `ARCHITECTURE_DIAGRAMS/` folder.

---

## 4. System Connections and Wiring

The data and control interactions between modules function as follows:

```
[User Chat Bar / TUI]
       │
       ▼ (1. Input string)
[Chat Orchestrator] ───► [Action Dispatched (e.g., /run)]
                                │
                                ▼
                       [LangGraph Engine]
                                │
    ┌───────────────────────────┴───────────────────────────┐
    ▼                                                       ▼
[State Manager (state.py)]                      [Orchestrator Node]
    │                                                       │
    │ (Shared state read/write)                             │ (Decides next agent)
    ▼                                                       ▼
[Specialist Agents (PRD, TRD, Schema...)] ◄─────────────────┘
    │
    ├─► [Writes markdown docs to PLANNER/] ◄─── [Watchfiles Listener]
    │                                                    │
    ├─► [Requests Clarification (needs_input)]           ▼ (Triggers regeneration)
    │           │                               [Architecture Diagram Agent]
    │           ▼                                        │
    │     [Griller Agent]                                ▼
    │           │                               [SystemDesign.md]
    │           ├─► [Query Stack Recommendation] ──────► [SystemArchitecture.md]
    │           │           ▲                           [FolderStructure.md]
    │           ▼           │                           [DataFlow.md]
    │     [User Prompt] ────┘
    │
    ▼
  [END] ───► [main.py finalizes] ───► [CLAUDE.md]
```
