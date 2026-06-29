# Agent Specialist Knowledge Base
> Reference for each specialist agent. Gives high-quality output even from small LLMs.
> Each section = one agent's full domain knowledge: what to write, how deep, dos, don'ts, anti-patterns.

---

## PRD Agent — `PRD.md`

### What it is
Translates the structured idea into a decision-grade product spec. Not a vision doc. Not a ticket. The layer between "why we're building this" and "what engineering will build."

### Required sections + depth

| Section | Depth required |
|---|---|
| Problem statement | Specific pain, not abstract. Who hurts, how, why current solutions fail. |
| Target users / personas | Named, role-specific (e.g. "Raj, 2nd-year CS student, no AWS budget") — not "developers" |
| Core features | MoSCoW-split: Must / Should / Could / Won't. One sentence per feature max. |
| Out of scope | Explicit list. What this version will NOT do. Prevents scope creep. |
| User stories | Format: `As a [user], I want [action] so that [outcome]`. 3–8 stories. |
| Acceptance criteria | Per story: measurable, testable. "System responds in < 2s" not "fast response." |
| Success metrics | Quantified: completion rate, error rate, latency targets. No vanity metrics. |
| Edge cases | Offline behavior, empty states, invalid input, concurrent actions, auth failure. |

### Dos
- Keep it decision-focused — alignment tool, not an encyclopedia
- Show > tell: prefer examples, mockup descriptions, user stories over abstract prose
- Start with the problem, not the solution
- Match depth to project scope — small project = 1–2 pages; enterprise = 5+
- Link every feature back to a user story
- Use MoSCoW explicitly — forces prioritization

### Don'ts
- Don't include all user stories for every corner case — PRD is not a ticket board
- Don't use vague language: "user-friendly," "scalable," "modern" — unverifiable
- Don't specify implementation details — that's TRD's job
- Don't skip out-of-scope — its absence causes scope creep every time
- Don't use LLM padding: no filler intros, no "this document outlines..." boilerplate
- Don't make success metrics qualitative

### Anti-patterns to avoid
- Generic persona: "users who want to be productive" → useless
- Missing acceptance criteria → 68% of engineering re-requests trace back to this
- PRD that reads like a vision deck (too high) or a JIRA ticket (too granular)
- Trying to address all user needs simultaneously — start lean, one problem first

---

## TRD Agent — `TRD.md`

### What it is
Translates PRD into engineering language. Describes the **how**, not the **what**. Audience = engineers and QA, not PMs or stakeholders.

### Required sections + depth

| Section | Depth required |
|---|---|
| Tech stack | Every layer: frontend, backend, DB, infra, messaging, auth. Justified, not just listed. |
| System architecture overview | How components connect. High-level data flow. Use text diagram or mermaid. |
| Functional requirements | PRD features → technical behavior. Specific API contracts, data validations, logic. |
| Non-functional requirements (NFRs) | Latency (e.g. "p95 < 200ms"), uptime (e.g. "99.9%"), concurrency, storage limits. |
| API design | Endpoints: method, path, request shape, response shape, error codes. |
| Data storage + retrieval | Which DB, why, query patterns, caching strategy. |
| Security | Auth mechanism, data encryption, input validation, rate limiting. |
| Third-party integrations | Each service: purpose, API used, fallback if it fails. |
| Testing strategy | Unit/integration/e2e split. What tools. What must be tested before ship. |
| Deployment / infra | Where it runs, how it's deployed, environment vars, rollback plan. |
| Technical constraints from PRD | Hard limits inherited (budget, platform, language choices). |

### Dos
- NFRs drive architecture — state them first, then justify stack choices against them
- Use SMART requirements: Specific, Measurable, Achievable, Relevant, Time-bound
- "The API must respond in < 200ms at p95 under 1000 concurrent users" not "fast API"
- Justify tradeoffs explicitly: "PostgreSQL over MongoDB because schema is fixed and joins are required"
- Every requirement must be testable — if QA can't verify it, rewrite it
- Non-goals section: explicitly list what this TRD does NOT cover

### Don'ts
- Don't use vague NFRs: "high performance," "secure," "scalable" = untestable
- Don't skip the non-goals section — mirrors PRD's out-of-scope
- Don't over-specify implementation to the point it prevents engineering judgment
- Don't write TRD before PRD is stable — it'll change
- Don't omit error handling / failure modes — common omission that causes prod incidents
- Don't conflate TRD with API docs — TRD defines requirements, not usage instructions

### Anti-patterns
- Stack choice without rationale ("we'll use React" with no NFR justification)
- Missing fallback behavior for third-party integrations
- NFRs stated as "as fast as possible" or "no downtime" — pick real numbers

---

## Design Decisions Agent — `DesignDecisions.md`

### What it is
An Architecture Decision Record (ADR) log. Append-only. Each entry captures one significant choice, its context, alternatives rejected, and consequences. Not a planning doc — a history doc.

### Required structure per entry
```
## ADR-NNN: [Short title]
**Status:** Proposed | Accepted | Superseded | Deprecated
**Date:** YYYY-MM-DD
**Context:** Why this decision was needed. What problem, what constraints.
**Decision:** What was chosen and the core reasoning.
**Alternatives considered:**
  - Option A: [why rejected]
  - Option B: [why rejected]
**Consequences:** Trade-offs accepted. What gets harder, what gets easier. Technical debt incurred.
**Supersedes / Superseded by:** [link if applicable]
```

### What qualifies as an ADR entry
Only decisions that are:
- Architecturally significant (affect structure, key quality attributes)
- Difficult or costly to reverse
- Not obvious — if everyone agrees immediately, it may not need an ADR

Examples: DB choice, auth strategy, sync vs async comms, monolith vs microservice, ORM vs raw SQL, which LLM provider, state management approach.

### Dos
- Start ADR log at project start — retroactive ADRs lose value
- Always include context and rationale — a decision without justification becomes meaningless when circumstances change
- Record confidence level if low — "chose X with low confidence; revisit after Phase 3"
- Link ADRs to relevant PRs or commits when possible
- When decision changes: write a new ADR that supersedes the old one — never edit accepted records
- Short is fine — 5 sentences per section is enough if the decision is clear

### Don'ts
- Don't go back and edit accepted records — append new superseding entries only
- Don't document obvious decisions (tabs vs spaces, variable naming)
- Don't hide consequences — all trade-offs must be explicit
- Don't record a decision without alternatives considered — forces the writer to think
- Don't let the log become stale — an unmaintained ADR log is worse than none

### Anti-patterns
- Single entry covering multiple decisions — one ADR per decision
- "We chose X because it's better" — better at what? State the NFR or constraint it satisfies
- Decisions made but not recorded → "decision amnesia" → repeated debates

---

## AppFlow Agent — `AppFlow.md`

### What it is
Maps the paths users take through the app to complete goals. Screen-to-screen navigation, state transitions, decision points. **Only populated if project has a frontend.** Backend-only → leave empty.

### Required sections + depth

| Section | Depth required |
|---|---|
| Entry points | Every way a user can arrive (direct URL, onboarding, notification, deep link, OAuth callback) |
| Primary flows | One diagram per main user goal (signup, core feature use, settings, error recovery) |
| Decision points | Explicit branches: logged in vs guest, success vs error, role A vs role B |
| State transitions | How UI state changes per action. E.g. "empty → loading → populated → error" |
| Exit points | Where flows end — success state, timeout, logout, abandonment |
| Edge/error states | What user sees on: empty data, network error, permission denied, session expiry |

### Flow diagram format (text-based, mermaid-compatible)
```
flowchart TD
  A([Entry: Landing page]) --> B{Logged in?}
  B -- Yes --> C[Dashboard]
  B -- No --> D[Login screen]
  D -- Success --> C
  D -- Forgot password --> E[Reset flow]
```

### Dos
- One flow per user goal — don't combine checkout and onboarding in one diagram
- Single entry point per flow — if multiple entries exist, split into separate flows
- Map ALL decision points as diamonds — binary branches make ambiguity visible
- Always show error/failure paths — not just happy path
- Use clear, succinct labels: "Login Choice" not "the screen where users decide whether to log in or not"
- Always include a defined end state — flows without exit points are incomplete

### Don'ts
- Don't describe emotional/motivational journey — that's a user journey map, not an app flow
- Don't create one mega-diagram covering the whole app — break by feature/goal
- Don't skip empty states and loading states — common design gaps that cause dev confusion
- Don't assume users arrive from one place — document all realistic entry points
- Don't leave decision branches without labels

### Anti-patterns
- Happy-path-only flow → engineer builds happy path, ignores error handling
- Flow with 10+ steps and no decision points → not a real flow, just a list
- Undocumented role-based branching → causes subtle auth bugs

---

## Schema Agent — `Schema.md`

### What it is
Defines the data model: tables/entities, columns, types, constraints, relationships, indexes. Source of truth for all data decisions. Engineers build against this.

### Required sections + depth

| Section | Depth required |
|---|---|
| Entity overview | Brief description of each table: purpose, who creates it, who reads it |
| Table definitions | For each table: column name, type, constraints (PK/FK/UNIQUE/NOT NULL/CHECK), business meaning |
| Relationships | Each FK stated explicitly with cardinality: one-to-many, many-to-many (via join table) |
| ER diagram | Mermaid erDiagram or ASCII — all tables, all FK relationships, cardinality |
| Indexing strategy | Which columns indexed, why (query pattern), composite vs single |
| Naming conventions | snake_case columns, singular table names, consistent ID naming |

### Table definition format
```
### users
| Column | Type | Constraints | Meaning |
|---|---|---|---|
| id | UUID | PK, NOT NULL | Surrogate key |
| email | VARCHAR(255) | UNIQUE, NOT NULL | Login identifier |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Audit trail |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Audit trail |
```

### Dos
- Always include `created_at` and `updated_at` on every table — non-negotiable for debugging and audits
- Use surrogate keys (UUID or auto-increment int) over natural keys — natural keys change
- Enforce FK constraints at DB level — application-layer validation alone is not enough
- Use most specific type: DATE not TIMESTAMP for birthdates, BOOLEAN not INT for flags
- Document the business meaning of each column — schema without meaning is just data types
- Document indexing rationale: "indexed on user_id + created_at for timeline queries"
- Use CHECK constraints for business rules (e.g. `CHECK (status IN ('active', 'inactive'))`)

### Don'ts
- Don't store multiple values in one column (comma-separated IDs, JSON arrays for relational data)
- Don't use VARCHAR for everything — right type matters for performance and validation
- Don't omit nullable vs NOT NULL — it's a business rule, not a DB detail
- Don't skip the ER diagram — it reveals relationship errors text can't
- Don't name columns ambiguously: `data`, `info`, `value`, `flag` — always name by meaning
- Don't denormalize prematurely — normalize first, denormalize only when query performance requires it

### Anti-patterns
- Missing FK constraints → orphan records guaranteed over time
- Everything as TEXT/VARCHAR → loses type safety, DB-level validation, storage efficiency
- No indexes → schema looks fine, queries are unusable at scale
- Missing `updated_at` → impossible to detect stale data, breaks cache invalidation

---

## Implementation Planner Agent — `ImplementationPlan.md`

### What it is
Phased build roadmap. Breaks the full project into ordered, vertically-sliced phases, each ending in a working deliverable. Not a Gantt chart. Not a ticket list.

### Required sections + depth

| Section | Depth required |
|---|---|
| Phase overview table | Phase number, goal, deliverable, est. duration |
| Per-phase detail | Tasks, dependencies, what must be true to start, what must be true to exit |
| MVP cut-line | Explicit marker: "everything above this line = MVP" |
| Dependency graph | Which phases block which (e.g. "Phase 3 requires Phase 2's DB schema to be finalized") |
| Build order principle | Why phases are ordered this way (e.g. "DB before API, API before UI") |

### Phase format
```
### Phase N — [Name]
**Goal:** One sentence. What this phase proves or ships.
**Scope:** Bullet list of what's included.
**Dependencies:** What must exist before this starts.
**Exit criteria:** Specific, verifiable. "X works against Y input" not "phase is done."
**Estimated time:** Rough range (1 day / 1 week / 2 weeks)
```

### Dos
- Vertical slices per phase: DB layer → logic → API → UI, not "all DB first, then all UI"
- Each phase must end in something runnable/demonstrable — not just "files created"
- State dependencies explicitly — phases that can be parallelized should say so
- Mark the MVP cut-line clearly — what ships first vs what comes later
- Exit criteria must be verifiable: "headless run produces correct output file" not "agent is implemented"
- Estimate time in ranges, not exact days

### Don'ts
- Don't group by type (e.g. "Phase 1: all models; Phase 2: all views") — hard to demo, masks integration risk
- Don't skip exit criteria — a phase without a clear done-condition never ends
- Don't plan beyond 4–6 phases without acknowledging unknowns
- Don't treat "write code" as a phase deliverable — the deliverable is the behavior, not the files

### Anti-patterns
- Phase that ends in "implementation complete" with no testable behavior
- All infrastructure in Phase 1 → delay before any visible progress
- No MVP cut-line → everything is equally important → nothing ships

---

## Tracker Agent — `Tracker.md`

### What it is
Live status of every file, task, and known blocker. The Orchestrator updates this after every agent run. Single source of truth for progress. Also serves as the resume context — agent can read this to know where to pick up.

### Required structure

```
## Status Overview
Last updated: YYYY-MM-DD HH:MM

| File | Status | Agent | Notes |
|---|---|---|---|
| PRD.md | ✅ Approved | prd_agent | v2, user requested scope change |
| TRD.md | 🔄 In Progress | trd_agent | Waiting for DB decision |
| Schema.md | ⏳ Pending | schema_agent | Blocked: TRD not finalized |

## Blockers
- [ ] TRD: user hasn't decided between PostgreSQL and SQLite → Griller queued

## Completed
- [x] RawIdea.md — written by user
- [x] StructuredIdea.md — structured by orchestrator
- [x] Constraints.md — filled by griller

## Change Log
- 2026-06-23: PRD revised — user removed "admin dashboard" from scope
- 2026-06-22: TechStackExpert suggested PostgreSQL over SQLite (see DesignDecisions ADR-002)
```

### Status symbols
| Symbol | Meaning |
|---|---|
| ⏳ Pending | Not started yet |
| 🔄 In Progress | Agent currently working |
| 👀 Needs Review | Draft done, user hasn't approved |
| ✅ Approved | User approved |
| ❌ Blocked | Can't proceed, reason documented |

### Dos
- Update after every single agent action — not in batches
- Always record why something is blocked, not just that it is
- Include a change log for every user-driven modification
- Keep notes column short — one-liners, not paragraphs
- Blocked items must link to which agent/action unblocks them

### Don'ts
- Don't let Tracker drift from actual file state — must reflect disk truth
- Don't use vague statuses: "WIP" or "in review" without owner
- Don't omit the change log — it's how the Orchestrator understands what changed between sessions

---

## Rules Agent — `Rules.md`

### What it is
Coding standards and AI agent behavior rules for the project. Constrains how code is written, what patterns are followed, and what the AI agent can/can't change unprompted. Not aspirational — must be specific enough to enforce.

### Required sections + depth

| Section | Depth required |
|---|---|
| Naming conventions | Variables, functions, files, DB columns — language-specific patterns |
| Code structure / folder layout | Where files go, import rules, layering (e.g. "no DB calls in routes, only in services") |
| Error handling pattern | How errors propagate, what gets logged, what gets surfaced to user |
| Validation rules | Where validation happens (DB, service, API layer), what library, pattern |
| Testing requirements | Min coverage, what must have unit tests, what uses integration tests |
| AI agent behavior rules | What agent CAN do without asking, what it MUST ask before changing |
| Code review / PR rules | If applicable: what requires review, what's auto-approvable |

### Dos
- Be specific: "use snake_case for Python variables, PascalCase for classes" not "follow language conventions"
- State the layering rule explicitly: "no direct DB queries in route handlers"
- Define the error format: "all errors return `{error: str, code: int}`, never raw exception strings"
- AI rules must be granular: "agent may add new functions freely; must ask before deleting existing ones; must ask before changing DB schema"
- Keep it short — rules that take too long to read get skipped

### Don'ts
- Don't write aspirational rules: "write clean code" → unenforceable
- Don't omit AI behavior rules — without them, agent will make well-intentioned but wrong decisions
- Don't duplicate what the linter/formatter already enforces — link to config instead
- Don't make rules that conflict with each other

### Anti-patterns
- Rules so vague they apply to any project ("write tests," "handle errors")
- No AI behavior rules → agent modifies things it shouldn't
- 30-page rules doc → nobody reads it, agent ignores it

---

## Constraints Agent — `Constraints.md`

### What it is
Hard limits that govern the entire project. Non-negotiable. Anything that MUST be true regardless of what PRD or TRD say. Primary input for TechStackExpert agent.

### Required sections + depth

| Section | Depth required |
|---|---|
| Technical constraints | Platform (OS, runtime, language version), library restrictions, no-go dependencies |
| Budget / resource constraints | Free tier only, max monthly cost, no paid APIs without approval |
| Legal / compliance | Data privacy rules, licensing restrictions, what data can't be stored |
| Performance floor | Minimum acceptable latency/throughput the system must meet |
| Things AI must never do | Destructive ops (DROP TABLE without explicit confirmation), push to prod, delete files |
| Hard assumptions | Facts assumed true that must not be violated (e.g. "users always have internet access") |

### Dos
- Written in absolute terms: "must not," "never," "always" — no "try to" or "ideally"
- Distinguish hard constraints (immovable) from soft preferences (negotiable)
- State the reason for each constraint when non-obvious
- "Must not use paid APIs" → "because project budget is $0/month"
- Update this file first when project conditions change — it propagates to all other docs

### Don'ts
- Don't list preferences here — "prefer PostgreSQL" is not a constraint
- Don't make constraints so numerous they become noise — hard limits only
- Don't leave AI behavioral constraints vague: "be careful with destructive ops" → too loose

### Anti-patterns
- Empty constraints file → TechStackExpert has no guardrails, will suggest paid services
- Constraints that contradict PRD requirements → forces impossible build
- "No constraints" → always false; every project has them

---

## CLAUDE.md

### What it is
Execution context file, not a planning doc. Generated by the Orchestrator on `/finalize`. Injected into Claude's context on every prompt during the build phase. Must be dense, correct, and short — this file is token budget.

### Required sections + depth

| Section | Depth required |
|---|---|
| Project summary | 3–5 sentences: what it is, who uses it, core purpose |
| Tech stack (active) | Exact versions, no alternatives — what's actually being built |
| Folder structure | Key directories and their purpose, one line each |
| Coding rules (critical) | The 5–10 rules from Rules.md that matter most for day-to-day coding |
| Hard constraints | The 3–5 must-never-do items from Constraints.md |
| Active module | Which module is currently being built |
| Data model (compact) | Key tables and their primary columns — not full schema, just orientation |
| API surface (compact) | Key endpoints, not full spec |

### Dos
- Optimize for token efficiency — this file is read on every prompt
- Only include what an LLM needs to write correct code for THIS project
- Use compact formats: tables, one-liners, bullet points
- Keep it updated when active module changes (`/module add` triggers update)
- Generated by Orchestrator from other PLANNER/ files — not hand-written

### Don'ts
- Don't copy-paste from PRD/TRD verbatim — synthesize into dense, actionable summary
- Don't include historical decisions — that's DesignDecisions.md
- Don't include aspirational rules — only rules that affect what code is written today
- Don't let it grow beyond ~300 lines — context bloat makes responses worse, not better

---

## Module Planner Agent — `MODULES/<name>.md`

### What it is
Minimal scoping file for one backend module. Not a planning doc, not a PRD. Working reference for the engineer/agent writing that module. Kept deliberately short.

### Required content (no more than this)

```md
# Module: <name>

## Purpose
One paragraph. What this module does, who calls it, what it owns.

## Tech stack
- Language/runtime:
- Key imports / packages:
- External APIs used:
- DB tables owned:

## Constraints
- [inherited hard limits from Constraints.md relevant to this module]
- [any module-specific limits]

## Rules
- [coding rules from Rules.md that specifically apply here]
- [any module-specific patterns]

## Interface
- Inputs: what this module receives
- Outputs: what it returns / emits
- Error behavior: how it signals failure to caller
```

### Dos
- Keep it to one screen — if it's longer, the module is probably too large
- Pull constraints and rules from project-level files — don't invent new ones here
- Interface section must match what other modules expect from this one
- Users can iterate freely on this file — it's a working document, not a locked spec

### Don'ts
- Don't include full API docs — link to TRD instead
- Don't include architectural context — that's for CLAUDE.md and TRD
- Don't make it aspirational — module files describe what to build, not what would be ideal

---

## Cross-cutting: Anti-patterns All Agents Must Avoid

- **LLM padding:** Never open with "This document outlines..." or "In order to ensure..." — start with the content
- **Vague adjectives:** fast, scalable, secure, modern, robust → always quantify or don't include
- **Hallucinated specifics:** If a fact (library version, API name, metric) isn't confirmed by StructuredIdea.md or user input, don't invent it — ask Griller instead
- **Missing negatives:** Every doc needs its "what this is NOT" section — out-of-scope, non-goals, must-not-do
- **Premature detail:** Don't write TRD-level detail in PRD, don't write module-level detail in TRD. Each doc owns its layer.
- **Inconsistency across files:** If Schema.md adds a table, check if TRD needs updating. If PRD changes scope, flag downstream files. The Orchestrator runs `/consistency` — but agents should flag obvious cross-file conflicts as `pending_questions` instead of silently proceeding.
