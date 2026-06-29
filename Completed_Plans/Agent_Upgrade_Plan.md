# Agent Upgrade Plan
> Upgrade agents one at a time using `Agent_Specialist_Knowledge.md` as the reference.
> After each agent: IDE pauses, reports what changed, asks permission to continue.

---

## How to use this plan

Work through agents in the order below. Each step has:
- **What to change** in the agent's system prompt / node code
- **How to verify** the upgrade worked before approving the next
- **Permission gate** — the exact prompt the IDE must display before moving on

Do not batch upgrades. One agent per session. Verify output quality on a real or mock input before proceeding.

---

## Upgrade Order

Ordered by dependency: each agent's output feeds the next. Fixing upstream agents first prevents garbage propagating downstream.

```
1. Griller
2. TechStackExpert
3. Orchestrator
4. PRD
5. TRD
6. Schema
7. DesignDecisions
8. AppFlow
9. Rules
10. Implementation Planner
11. Tracker
12. Module Planner
13. Architecture Diagram
```

---

## Agent 1 — Griller

**Why first:** Every other agent calls Griller when info is missing. If Griller asks bad questions, all downstream files get bad answers.

**Upgrade tasks:**
- [ ] System prompt: add explicit instruction to ask one question at a time, never batch 5+ questions in one shot
- [ ] System prompt: add rule — for each question, state *why* the answer is needed (e.g. "Need to know auth method before TRD agent can write security section")
- [ ] System prompt: add instruction to detect when user says "I don't know" → immediately route to TechStackExpert with full project context, don't re-ask
- [ ] System prompt: questions must be specific, not open-ended. Bad: "Tell me about your users." Good: "Will users be authenticated? If yes, will you use social login, email/password, or both?"
- [ ] Add a `questions_asked` counter to state — if >10 questions in one session, Griller must summarize what it has and proceed with reasonable defaults, flagging assumptions in the file

**Verify:** Run a test idea through. Griller should ask tight, justified questions. No shotgun lists. Unanswered questions → routes to TechStackExpert, not re-asks.

---

> ### 🔐 Permission Gate — Agent 1 Complete
> ```
> ✅ Griller agent upgraded.
>
> Summary of changes:
> - Now asks one question at a time with stated reason
> - Routes "I don't know" → TechStackExpert automatically
> - Caps at 10 questions, then proceeds with flagged assumptions
>
> Verified: [yes/no] [brief note on test result]
>
> Proceed to Agent 2 (TechStackExpert)? [yes / no / show test output first]
> ```

---

## Agent 2 — TechStackExpert

**Why second:** Griller calls this when user doesn't know what to pick. Output feeds into DesignDecisions.md and Constraints.md. Must produce justified, constraint-aware suggestions.

**Upgrade tasks:**
- [ ] System prompt: must read `Constraints.md` before making any suggestion — no paid APIs if budget = $0, no heavy libs if "lightweight" is a constraint
- [ ] System prompt: for every suggestion, output in this format:
  ```
  Suggestion: [tool/tech]
  Why: [one sentence tied to a specific NFR or constraint]
  Trade-off: [what you give up]
  Alternative if rejected: [next best option]
  ```
- [ ] System prompt: if two equally valid options exist, present both with trade-offs — do not pick one arbitrarily
- [ ] System prompt: never suggest something the user would need to pay for unless Constraints.md explicitly allows paid services
- [ ] After suggestion accepted: write result as ADR entry in DesignDecisions.md immediately (don't wait for DesignDecisions agent to run later)

**Verify:** Give it a project with `Constraints.md` saying "free tier only, Python preferred." Suggestions must be free + Python-compatible. Each comes with trade-off. Accepted pick auto-logs to DesignDecisions.

---

> ### 🔐 Permission Gate — Agent 2 Complete
> ```
> ✅ TechStackExpert agent upgraded.
>
> Summary of changes:
> - Reads Constraints.md before any suggestion
> - Structured output: suggestion / why / trade-off / alternative
> - Auto-writes ADR to DesignDecisions.md on acceptance
>
> Verified: [yes/no] [brief note]
>
> Proceed to Agent 3 (Orchestrator)? [yes / no / show test output first]
> ```

---

## Agent 3 — Orchestrator

**Why third:** Controls routing for all other agents. Must be upgraded before specialist agents so it can correctly hand off context to upgraded downstream nodes.

**Upgrade tasks:**
- [ ] System prompt: enforce the fixed execution sequence from Plan Board:
  ```
  RawIdea → StructuredIdea → Constraints → PRD → TRD → Schema →
  DesignDecisions → AppFlow → Tracker → Rules → MODULES/
  ```
- [ ] System prompt: add frontend-detection logic — check StructuredIdea.md for frontend signals. If none: skip DesignDecisions + AppFlow entirely, mark as "skipped (backend-only)" in Tracker.md
- [ ] System prompt: after each agent completes a file, must update Tracker.md with: file name, status, timestamp, agent that wrote it
- [ ] System prompt: if any agent sets `status = "needs_input"` → route to Griller immediately, pass full `pending_questions` list + relevant file context
- [ ] System prompt: on LLM failure in any node → halt, output error details, ask user: `Retry? [y/n]` before attempting again
- [ ] System prompt: on `/consistency` command → read-only pass across all PLANNER/ files, output list of contradictions to Viewer panel, do not auto-fix

**Verify:** Full run on sample idea. Confirm: sequence is correct, Tracker.md updates after each file, AppFlow skipped for backend-only idea, failure in one node halts + asks retry.

---

> ### 🔐 Permission Gate — Agent 3 Complete
> ```
> ✅ Orchestrator agent upgraded.
>
> Summary of changes:
> - Enforces fixed file sequence
> - Frontend-detection skip logic for DesignDecisions + AppFlow
> - Tracker.md updated after every node
> - Failure → halt + retry prompt
> - /consistency pass implemented
>
> Verified: [yes/no] [brief note]
>
> Proceed to Agent 4 (PRD)? [yes / no / show test output first]
> ```

---

## Agent 4 — PRD Agent

**Upgrade tasks:**
- [ ] System prompt: inject the full PRD specialist knowledge section from `Agent_Specialist_Knowledge.md` verbatim (Required sections table, dos, don'ts, anti-patterns)
- [ ] System prompt: enforce MoSCoW split — output must have Must/Should/Could/Won't labels on every feature
- [ ] System prompt: every feature must link to at least one user story
- [ ] System prompt: every user story must have acceptance criteria in measurable format ("< 2s response" not "fast response")
- [ ] System prompt: explicit out-of-scope section required — cannot be empty
- [ ] System prompt: no filler openers, no "This PRD outlines..." — start directly with Problem Statement
- [ ] System prompt: on iteration (user requests change) — modify in-place, do not regenerate from scratch; preserve unchanged sections

**Verify:** Feed it a one-paragraph idea. PRD must have: specific persona, MoSCoW features, user stories with acceptance criteria, measurable success metrics, explicit out-of-scope. No vague adjectives.

---

> ### 🔐 Permission Gate — Agent 4 Complete
> ```
> ✅ PRD agent upgraded.
>
> Summary of changes:
> - MoSCoW feature split enforced
> - Every feature linked to user story
> - Measurable acceptance criteria required
> - Out-of-scope section mandatory
> - No filler language
> - In-place edit on iteration (no full regen)
>
> Verified: [yes/no] [brief note]
>
> Proceed to Agent 5 (TRD)? [yes / no / show test output first]
> ```

---

## Agent 5 — TRD Agent

**Upgrade tasks:**
- [ ] System prompt: inject TRD specialist knowledge from `Agent_Specialist_Knowledge.md`
- [ ] System prompt: must read PRD.md first — every functional requirement must trace back to a PRD feature
- [ ] System prompt: all NFRs must be quantified (latency in ms, uptime as %, concurrency as number) — reject vague NFRs in its own output
- [ ] System prompt: stack choice must include one-sentence justification tied to a specific NFR or constraint
- [ ] System prompt: non-goals section required — mirrors PRD's out-of-scope in technical terms
- [ ] System prompt: every requirement must pass testability check — if it can't be measured, rewrite it

**Verify:** TRD should reference PRD features by name. NFRs are all numbers. Stack choices each have a "because of NFR X" clause.

---

> ### 🔐 Permission Gate — Agent 5 Complete
> ```
> ✅ TRD agent upgraded.
>
> Summary of changes:
> - Reads PRD first, traces all features
> - Quantified NFRs enforced
> - Stack choices require NFR justification
> - Non-goals section required
> - Testability check on every requirement
>
> Verified: [yes/no] [brief note]
>
> Proceed to Agent 6 (Schema)? [yes / no / show test output first]
> ```

---

## Agent 6 — Schema Agent

**Upgrade tasks:**
- [ ] System prompt: inject Schema specialist knowledge from `Agent_Specialist_Knowledge.md`
- [ ] System prompt: must read TRD.md for data storage decisions before writing any table
- [ ] System prompt: every table must have `created_at` + `updated_at` columns — non-negotiable, no exceptions
- [ ] System prompt: every column must have: name, type, constraints (NOT NULL / UNIQUE / FK / CHECK), business meaning — missing any field = incomplete
- [ ] System prompt: FK constraints must be stated explicitly, not implied
- [ ] System prompt: ER diagram required (mermaid `erDiagram` format) — must include all tables and FK relationships
- [ ] System prompt: indexing section required — state which columns indexed and why (query pattern)
- [ ] System prompt: surrogare keys over natural keys by default — flag if deviating

**Verify:** Schema.md must have: all TRD-referenced entities, no table without timestamps, full column definitions, ER diagram that matches table definitions, index rationale.

---

> ### 🔐 Permission Gate — Agent 6 Complete
> ```
> ✅ Schema agent upgraded.
>
> Summary of changes:
> - Reads TRD before writing
> - created_at/updated_at on every table, enforced
> - Full column definition: name/type/constraints/meaning
> - ER diagram required (mermaid)
> - Indexing rationale required
>
> Verified: [yes/no] [brief note]
>
> Proceed to Agent 7 (DesignDecisions)? [yes / no / show test output first]
> ```

---

## Agent 7 — Design Decisions Agent

**Upgrade tasks:**
- [ ] System prompt: inject ADR specialist knowledge from `Agent_Specialist_Knowledge.md`
- [ ] System prompt: enforce ADR format per entry: Status / Date / Context / Decision / Alternatives Considered / Consequences / Supersedes
- [ ] System prompt: must import all decisions TechStackExpert already logged — don't re-create them, only append new ones
- [ ] System prompt: `Alternatives Considered` section is mandatory per entry — single-option entries rejected
- [ ] System prompt: entries are append-only — never edit accepted entries; write new superseding entry if decision changes
- [ ] System prompt: only significant decisions get ADR entries — filter out obvious or low-impact choices

**Verify:** File has correct ADR format per entry. TechStackExpert decisions already appear. No entry missing alternatives. Append-only behavior confirmed by running agent twice on same file.

---

> ### 🔐 Permission Gate — Agent 7 Complete
> ```
> ✅ DesignDecisions agent upgraded.
>
> Summary of changes:
> - ADR format enforced per entry
> - Imports existing TechStackExpert decisions
> - Alternatives Considered mandatory
> - Append-only enforced
>
> Verified: [yes/no] [brief note]
>
> Proceed to Agent 8 (AppFlow)? [yes / no / show test output first]
> ```

---

## Agent 8 — AppFlow Agent

**Upgrade tasks:**
- [ ] System prompt: inject AppFlow specialist knowledge from `Agent_Specialist_Knowledge.md`
- [ ] System prompt: first action — check if project has frontend (read StructuredIdea.md + TRD.md). If backend-only: write single line "N/A — backend-only project" and exit. Do not generate empty sections.
- [ ] System prompt: one flow diagram per user goal — no mega-diagram
- [ ] System prompt: every flow must have: entry point(s), decision points (diamonds), happy path, error/failure path, exit state
- [ ] System prompt: mermaid `flowchart TD` format required for each flow
- [ ] System prompt: empty states, loading states, error states must be explicit nodes — not left implicit

**Verify:** AppFlow.md has one diagram per core user story. Each diagram has explicit error path. No happy-path-only flows. Backend-only project → correct N/A output.

---

> ### 🔐 Permission Gate — Agent 8 Complete
> ```
> ✅ AppFlow agent upgraded.
>
> Summary of changes:
> - Backend-only detection → N/A output
> - One diagram per user goal enforced
> - Error paths required in every flow
> - Mermaid flowchart format enforced
> - Empty/loading/error states as explicit nodes
>
> Verified: [yes/no] [brief note]
>
> Proceed to Agent 9 (Rules)? [yes / no / show test output first]
> ```

---

## Agent 9 — Rules Agent

**Upgrade tasks:**
- [ ] System prompt: inject Rules specialist knowledge from `Agent_Specialist_Knowledge.md`
- [ ] System prompt: rules must be specific and enforceable — run each rule through the test "can a linter or code reviewer check this?" If no → rewrite
- [ ] System prompt: must include an explicit "AI agent behavior" section: what agent can do without asking, what requires user permission
- [ ] System prompt: layering rules required — "no DB calls in route handlers" type rules, specific to the project's stack from TRD
- [ ] System prompt: rules must reference actual project stack (from TRD) — no generic language-agnostic rules that apply to any project

**Verify:** Rules.md has: specific naming conventions, layering rules, error handling pattern, AI behavior section. No rule is a generic platitude.

---

> ### 🔐 Permission Gate — Agent 9 Complete
> ```
> ✅ Rules agent upgraded.
>
> Summary of changes:
> - Enforceability test on every rule
> - AI behavior section mandatory
> - Layering rules tied to project stack
> - No generic platitudes
>
> Verified: [yes/no] [brief note]
>
> Proceed to Agent 10 (Implementation Planner)? [yes / no / show test output first]
> ```

---

## Agent 10 — Implementation Planner Agent

**Upgrade tasks:**
- [ ] System prompt: inject Implementation Planner specialist knowledge from `Agent_Specialist_Knowledge.md`
- [ ] System prompt: must read PRD.md + TRD.md + Schema.md before generating phases — phases must reflect actual project scope, not generic phases
- [ ] System prompt: each phase must use vertical-slice structure (DB layer → logic → API → UI per feature), not horizontal grouping (all DB first, then all API)
- [ ] System prompt: every phase requires explicit exit criteria — verifiable behavior, not "code written"
- [ ] System prompt: MVP cut-line must be marked explicitly between phases
- [ ] System prompt: dependency between phases must be stated — "Phase 4 requires Phase 3's Schema to be finalized"

**Verify:** Plan has vertical slices, explicit exit criteria, MVP marker, phase dependencies. No phase ends in "implementation complete."

---

> ### 🔐 Permission Gate — Agent 10 Complete
> ```
> ✅ Implementation Planner agent upgraded.
>
> Summary of changes:
> - Reads PRD + TRD + Schema before planning
> - Vertical slice phases enforced
> - Exit criteria verifiable, not vague
> - MVP cut-line required
> - Phase dependencies explicit
>
> Verified: [yes/no] [brief note]
>
> Proceed to Agent 11 (Tracker)? [yes / no / show test output first]
> ```

---

## Agent 11 — Tracker Agent

**Upgrade tasks:**
- [ ] System prompt: inject Tracker specialist knowledge from `Agent_Specialist_Knowledge.md`
- [ ] System prompt: after every other agent's file write, Orchestrator calls Tracker agent to update — Tracker must not batch-update; one update per file written
- [ ] System prompt: enforce status symbols: ⏳ / 🔄 / 👀 / ✅ / ❌ — no free-form status strings
- [ ] System prompt: every ❌ blocker must name: what is blocked, what unblocks it, which agent/user action is needed
- [ ] System prompt: change log entry required for every user-driven modification (not agent-driven writes — only user-requested changes)
- [ ] System prompt: Tracker.md must be self-sufficient as a resume context — if Orchestrator reads only Tracker.md, it must be able to determine exactly where to continue

**Verify:** After a full run, Tracker.md has every file with correct status, all blockers explained, change log for any user-requested changes. Reading Tracker.md alone tells you what's done and what's next.

---

> ### 🔐 Permission Gate — Agent 11 Complete
> ```
> ✅ Tracker agent upgraded.
>
> Summary of changes:
> - Per-file update, no batching
> - Status symbol set enforced
> - Blockers include unblocking action
> - Change log for user-driven modifications only
> - Self-sufficient as resume context
>
> Verified: [yes/no] [brief note]
>
> Proceed to Agent 12 (Module Planner)? [yes / no / show test output first]
> ```

---

## Agent 12 — Module Planner Agent

**Upgrade tasks:**
- [ ] System prompt: inject Module Planner specialist knowledge from `Agent_Specialist_Knowledge.md`
- [ ] System prompt: must read all PLANNER/ files before writing any module file — module constraints must be subset of project-level Constraints.md, not new rules
- [ ] System prompt: module file must stay under one screen (~50 lines) — if longer, flag that module is too large and suggest splitting
- [ ] System prompt: Interface section required on every module file: inputs, outputs, error behavior
- [ ] System prompt: tech stack section must list only what this module directly uses — no speculative imports

**Verify:** Module file is short, has Interface section, constraints are inherited not invented, no over-specification.

---

> ### 🔐 Permission Gate — Agent 12 Complete
> ```
> ✅ Module Planner agent upgraded.
>
> Summary of changes:
> - Reads all PLANNER/ before writing
> - 50-line cap enforced, split suggestion if exceeded
> - Interface section required
> - Constraints inherited, not invented
>
> Verified: [yes/no] [brief note]
>
> Proceed to Agent 13 (Architecture Diagram)? [yes / no / show test output first]
> ```

---

## Agent 13 — Architecture Diagram Agent (Watcher)

**Note:** This agent is not a LangGraph node — it's a standalone file watcher. Upgrade is to its generation logic and trigger behavior, not its system prompt.

**Upgrade tasks:**
- [ ] Update `watcher/architecture_watcher.py`: on any PLANNER/*.md change, re-read TRD.md + Schema.md + AppFlow.md (if exists) and regenerate all three diagram types:
  - `SystemArchitecture.mmd` — component + infra view from TRD
  - `DataFlow.md` — how data moves between modules (text-based, from Schema + TRD)
  - `FolderStructure.md` — canonical folder layout from ImplementationPlan + TRD
- [ ] Diagram generation prompt: each diagram must reflect actual file content — no hallucinated components
- [ ] On backend-only project: skip AppFlow-derived diagrams
- [ ] On error (LLM call fails): write last-known-good diagram + append `[STALE — regeneration failed at HH:MM]` header instead of silently leaving old diagram
- [ ] Verify diagrams update in Architecture panel of TUI within one file-save cycle

**Verify:** Edit Schema.md manually. Within one save cycle, SystemArchitecture.mmd updates. STALE header appears on LLM failure.

---

> ### 🔐 Permission Gate — Agent 13 Complete
> ```
> ✅ Architecture Diagram watcher upgraded.
>
> Summary of changes:
> - Generates all 3 diagram types on any PLANNER/ change
> - Reflects actual file content only
> - STALE header on failure instead of silent old diagram
> - Backend-only skip logic
>
> Verified: [yes/no] [brief note]
>
> 🎉 All 13 agents upgraded. Full end-to-end verification recommended before marking upgrade complete.
> Run a fresh project idea through the full /run flow. Confirm Tracker.md, all docs, and diagrams populate correctly.
> ```

---

## Final verification checklist

- [ ] Full `/run` on a new project idea with no prior state
- [ ] Griller asks tight questions, routes unknowns to TechStackExpert
- [ ] TechStackExpert suggestions respect Constraints.md
- [ ] Each PLANNER/ file matches its specialist knowledge spec
- [ ] Tracker.md is accurate after full run
- [ ] `/consistency` finds any intentionally planted contradiction
- [ ] `/finalize` generates correct CLAUDE.md
- [ ] Architecture diagrams update on manual file edit
- [ ] Backend-only idea: DesignDecisions + AppFlow skipped cleanly
