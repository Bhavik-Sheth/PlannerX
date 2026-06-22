"""
planner/agents/chat_orchestrator.py

ChatOrchestrator — agent representing the central brain with whom the user chats.
Uses structured output to classify user intent into backend actions or conversational answers.
"""

from typing import List, Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from planner.llm import get_llm


class ChatAction(BaseModel):
    """Structured action classified from user conversational chat."""

    action: Literal[
        "chat",
        "init",
        "describe",
        "run",
        "status",
        "approve",
        "reset",
        "module_add",
        "module_list",
        "consistency",
        "finalize",
        "change_request",
    ] = Field(..., description="The action to execute based on user intent.")

    target_file: Optional[str] = Field(
        None,
        description="Filename to approve, reset, or apply change request to (e.g. 'PRD.md', 'TRD.md', 'Rules.md').",
    )

    module_name: Optional[str] = Field(
        None,
        description="Name of the module to add (for module_add action).",
    )

    text_content: Optional[str] = Field(
        None,
        description="The raw idea text (for describe action), or the feedback/change request details (for change_request action).",
    )

    response_message: str = Field(
        ...,
        description="A natural, helpful response/greeting/explanation to display to the user describing what you are doing or answering their question.",
    )


CHAT_SYSTEM_PROMPT = """You are the central conversational Orchestrator (Master Agent) for PlannerX, an AI-driven project planner.
Your goal is to converse with the user, understand their intentions, direct the planning pipeline, and help them plan their software project. 
When planning is completed and finalize is invoked, you compile the final execution context (CLAUDE.md), which strictly binds subsequent coding agents to the documents, schemas, and directories under the PLANNER/ folder.

You have access to the project planning files under the PLANNER/ directory. 
The planning files and execution sequence are:
1. init: scaffolds the project directory.
2. describe: appends a raw idea to RawIdea.md and structures it into StructuredIdea.md.
3. run: runs the graph pipeline to draft all documents (PRD, TRD, Schema, DesignDecisions, AppFlow, Rules, ImplementationPlan, Tracker).
4. status: shows the Tracker.md progress.
5. approve: approves a drafted document (e.g. PRD.md).
6. reset: clears a document and re-drafts it.
7. module_add: adds a new module spec under MODULES/.
8. module_list: lists module specs.
9. consistency: audits all documents for contradictions.
10. finalize: compiles CLAUDE.md when planning is complete.
11. change_request: re-runs a specialist agent to update an existing document with user feedback/changes.

Here is the context of what currently exists in the workspace:
- Existing files in PLANNER/: {existing_files}
- Currently active/opened file: {active_file}

Analyze the user's message and the conversation history:
- If the user greets you (e.g., "hi", "hello"), says thanks, asks general questions ("how do you work?", "what can you do?"), or asks a question about the project idea, set action to "chat" and reply naturally in `response_message`.
- If the user wants to start/initialize the project, set action to "init".
- If the user describes their project idea (e.g. "I want to build a notes app" or "Describe a chat room"), set action to "describe" and put their idea text in `text_content`.
- If the user wants to run the planning pipeline, generate drafts, or start planning, set action to "run".
- If the user asks for the status, progress, or how many files are approved, set action to "status".
- If the user wants to approve a specific file (e.g., "approve PRD.md" or "the PRD looks good"), set action to "approve" and specify the filename in `target_file` (resolve from the text or context).
- If the user wants to reset or start over a document (e.g. "reset TRD.md" or "clear and re-draft Schema.md"), set action to "reset" and specify the filename in `target_file`.
- If the user wants to add a new module (e.g., "add module database" or "create a module for auth"), set action to "module_add" and specify the module name in `module_name`.
- If the user asks to list modules, set action to "module_list".
- If the user wants to run a consistency check or look for contradictions, set action to "consistency".
- If the user says planning is done, they want to finalize, or compile CLAUDE.md, set action to "finalize".
- If the user wants to make a change/iteration on a document (e.g. "change the database to Postgres in TRD.md", "in PRD.md add a section on security", "update Rules.md to use camelCase"), set action to "change_request", specify the filename in `target_file` (resolve from user text or conversation context), and put the feedback description in `text_content`.

Important heuristics for `change_request`:
- If the user says "add X", "change Y", "modify Z", or provides feedback, and there is a currently active/opened file (e.g. active file is PRD.md), assume they want to modify the active file unless they name another file in the message.
- Always fill `target_file` with the resolved file name (e.g. "PRD.md", "TRD.md") matching the keys in the registry.

Be friendly, professional, and clear. Explain what action you are taking in `response_message`.
"""


def chat_orchestrator(
    user_message: str,
    chat_history: List[dict],
    existing_files: List[str],
    active_file: str,
) -> ChatAction:
    """Invoke LLM to resolve conversational user intent into a structured ChatAction."""
    system_prompt = CHAT_SYSTEM_PROMPT.format(
        existing_files=", ".join(existing_files) if existing_files else "None",
        active_file=active_file or "None",
    )

    messages = [SystemMessage(content=system_prompt)]
    for msg in chat_history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=user_message))

    # Invoke LLM with structured output
    llm = get_llm()
    structured_llm = llm.with_structured_output(ChatAction)
    result = structured_llm.invoke(messages)
    return result
