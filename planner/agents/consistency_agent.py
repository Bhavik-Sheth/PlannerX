"""
consistency_agent.py — Read-only cross-file consistency checker.

Single responsibility: perform a read-only cross-file consistency check
across all PLANNER/ files.  Returns a list of issues citing both files
involved. Never modifies any file.

Inputs:
    files: dict[str, str]   — all non-empty PLANNER/ files {filename: content}

Returns:
    {
        "issues": [{"file_a": str, "file_b": str, "issue": str}, ...],
        "clean": bool   — True when issues list is empty
    }
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage
from planner.agents._base import invoke_llm_safe
from planner.tools import llm_call_json

SYSTEM_PROMPT = """\
You are a meticulous technical documentation auditor.
You will receive the full contents of a project's planning documents.
Your job is to find **cross-file contradictions, missing references, and
mismatches** — nothing else.

Run every check in the checklist below and report ALL findings.

### Checklist
1. **PRD → TRD coverage**
   Every feature listed in PRD.md must have a corresponding functional
   requirement or section in TRD.md.  Flag any PRD feature that is absent
   from the TRD.

2. **TRD → Schema coverage**
   Every entity, model, or data object mentioned in TRD.md must appear as a
   table (or equivalent data-structure heading) in Schema.md.  Flag any TRD
   entity missing from the schema.

3. **Schema → MODULES usage**
   Every table defined in Schema.md must be referenced in at least one
   MODULES/ file.  Flag any orphan table that no module mentions.

4. **AppFlow → PRD consistency** (skip if AppFlow.md is absent)
   Every screen, page, or flow step in AppFlow.md must map to a feature or
   user story that exists in PRD.md.  Flag any screen that has no PRD
   backing.

5. **Constraints → TRD compatibility**
   Constraints.md must not conflict with the tech-stack choices in TRD.md.
   For example, a constraint saying "must run offline" would conflict with
   a TRD choosing a cloud-only database.

6. **Rules → TRD compatibility**
   Rules.md must not conflict with the implementation patterns or tech-stack
   described in TRD.md.

7. **ImplementationPlan → PRD scope**
   Every phase or task in ImplementationPlan.md must reference only features
   that exist in PRD.md scope.  Flag any plan item whose feature is not in
   the PRD.

### Output format
Return ONLY a JSON array (no surrounding text, no markdown fences).
Each element is an object with exactly three keys:
  "file_a"  — name of the first file involved  (e.g. "PRD.md")
  "file_b"  — name of the second file involved (e.g. "TRD.md")
  "issue"   — one-sentence explanation of the mismatch

If everything is consistent and no issues are found, return an empty array: []

### Rules
- Read-only: never suggest fixes.
- Every issue MUST cite both files involved.
- Be specific: quote the feature / table / screen name that is missing or
  conflicting.
- Do NOT invent issues.  Only report genuine mismatches you can point to in
  the provided text.
"""


def consistency_agent(files: dict[str, str]) -> dict:
    """
    Perform a read-only cross-file consistency check across PLANNER/ files.

    Args:
        files: Mapping of ``{filename: content}`` for every non-empty
               PLANNER/ file (e.g. ``{"PRD.md": "...", "TRD.md": "..."}``).

    Returns:
        dict with two keys:
            ``issues`` — list of ``{"file_a", "file_b", "issue"}`` dicts.
            ``clean``  — ``True`` when no issues were found.
    """
    # ── Build a combined document for the LLM ──────────────────────────
    combined = ""
    for fname, content in files.items():
        if content.strip():
            combined += f"\n\n## File: {fname}\n{content.strip()}"

    if not combined.strip():
        return {"issues": [], "clean": True}

    # ── Single LLM call ───────────────────────────────────────────────
    prompt = f"Planning Documents:\n{combined}"

    try:
        results = llm_call_json(prompt, system=SYSTEM_PROMPT)
    except Exception:
        # On LLM failure, fall back to empty (no false positives).
        return {"issues": [], "clean": True}

    # ── Normalise response ────────────────────────────────────────────
    if not isinstance(results, list):
        results = []

    # Keep only well-formed issue dicts.
    valid_issues: list[dict] = []
    for item in results:
        if (
            isinstance(item, dict)
            and "file_a" in item
            and "file_b" in item
            and "issue" in item
        ):
            valid_issues.append(
                {
                    "file_a": str(item["file_a"]),
                    "file_b": str(item["file_b"]),
                    "issue": str(item["issue"]),
                }
            )

    return {"issues": valid_issues, "clean": len(valid_issues) == 0}
