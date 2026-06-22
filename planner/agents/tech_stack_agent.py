"""
tech_stack_agent.py — Tech Stack Expert agent.
Given a question from the Griller, uses LLM + project context to suggest the best option.
Presents the suggestion to the user for approval, then fills grill_answers and routes back to Griller.

Reads: Constraints.md, StructuredIdea.md, pending question from tech_suggestions state
Writes: Updates state grill_answers with accepted recommendations.
"""
import sys
from pathlib import Path
from langchain_core.messages import SystemMessage, HumanMessage
from planner.state import PlannerState
from planner.agents._base import load_context, invoke_llm_safe, strip_markdown_fence

SYSTEM_PROMPT = """You are a world-class technology consultant who gives concise, specific, 
justified technology recommendations.

Given a question about which tool/technology/library/service to use, you will:
1. Suggest **the best 1-2 options** for this specific project context.
2. For each option explain:
   - What it is (one line).
   - Why it fits THIS project specifically.
   - Any notable trade-off or caveat.
3. Give a clear **recommendation** (one option you'd choose if it were your project).

Format: Clean Markdown, concise. No code fences around the whole response.
"""


def tech_stack_agent(state: PlannerState) -> PlannerState:
    """Generate a technology suggestion for the current pending question, present it to the user."""
    question = state.tech_suggestions.get("__current_question__", "")
    if not question:
        # No question to answer — just go back to griller
        state.next_agent = "griller"
        return state

    ctx = load_context(state, "StructuredIdea.md", "Constraints.md")
    structured_idea = ctx.get("StructuredIdea.md", "")
    constraints = ctx.get("Constraints.md", "")

    user_content = f"Question: {question}\n"
    if structured_idea:
        user_content += f"\nProject Context:\n{structured_idea}\n"
    if constraints:
        user_content += f"\nConstraints:\n{constraints}\n"

    print("\n" + "=" * 60)
    print("🤖  TECH STACK EXPERT — generating suggestion...")
    print("=" * 60)

    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_content)]
    suggestion = strip_markdown_fence(invoke_llm_safe(messages))

    print(f"\n{suggestion}\n")
    print("-" * 60)

    try:
        choice = input("Accept this suggestion? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = "n"

    if choice == "y":
        # Store the accepted suggestion as the answer
        state.grill_answers[question] = suggestion
        # Remove the current question from pending_questions
        if question in state.pending_questions:
            state.pending_questions.remove(question)
    else:
        # User rejected — let them type a custom answer
        try:
            custom = input("Enter your own answer: ").strip()
        except (EOFError, KeyboardInterrupt):
            custom = ""
        if custom:
            state.grill_answers[question] = custom
            if question in state.pending_questions:
                state.pending_questions.remove(question)

    # Clean up tech_suggestions tracker
    state.tech_suggestions.pop("__current_question__", None)

    # Route back to griller to handle any remaining questions
    state.next_agent = "griller"
    return state
