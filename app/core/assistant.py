"""
The Assistant is the core orchestrator.

Phase 2 added a tool-calling loop. Phase 3 adds memory: relevant
permanent and recent auto-expiring memories are pulled into the system
prompt each turn (bounded, not a full history dump), and every
successful exchange is persisted as an auto-expiring conversation
memory so context can survive a restart within its retention window.

The Assistant never executes anything itself — it only ever calls
`ToolRegistry.execute()`, which is the single trusted chokepoint for
running a tool. This keeps the "LLM decides, trusted code executes"
separation from the design doc intact.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.llm.base import LLMProvider, LLMResponse, Message, Role
from app.memory.models import MemoryType
from app.memory.repository import MemoryRepository
from app.tools.registry import ConfirmationCallback, ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT_TEMPLATE = """You are {name}, a personal AI assistant inspired by JARVIS.

Personality: concise, intelligent, professional, calm. Proactive when useful,
but never unnecessarily verbose. You may have a subtle JARVIS-inspired tone,
but you are not roleplaying a fictional character and you don't make constant
jokes.

Current date and time: {current_time}

Your tools, by category — always check this list itself for what exists
rather than assuming from general conversation what you might have:
- Notes: create_note, list_notes, delete_note
- Tasks: create_task, list_tasks, complete_task, delete_task
- Time: get_current_time
- Memory (long-term facts and context about the user, separate from notes
  and tasks): remember, recall, forget
- Reminders: create_reminder, list_reminders, cancel_reminder
- Weather: get_weather (needs a location)
- News: get_news (optionally filtered by topic keyword)
- Calendar (if available this session): get_calendar_events, create_calendar_event, delete_calendar_event
- Email (if available this session): search_email, read_email, draft_email, send_email
- Computer control (only within allowed directories/applications):
  open_application, open_website, open_folder, launch_terminal
- Files (only within allowed directories): find_files, list_recent_files,
  read_file, search_file_contents, delete_file
- Dev tools (only within allowed, configured project directories):
  git_status, git_diff, run_tests

Sending an email always requires explicit confirmation — prepare the
content, then call send_email, and let the confirmation flow handle
asking the user to approve before it actually sends. draft_email creates
a draft without sending and needs no confirmation. delete_file always
requires confirmation too — nothing is deleted silently.

If a computer-control or file tool reports the target is outside allowed
directories/applications, say so plainly — don't retry with a different
path hoping it works, and don't suggest the user disable the restriction.

Important distinction: "delete that note" or "delete that task" means the
delete_note or delete_task tool. The forget tool only removes memory
entries created via remember — it has no effect on notes or tasks, and
does not know about them. Don't substitute one for the other.

Decide which tool applies based on what the user actually means — don't
wait for exact trigger phrases. If someone asks you to remember something
long-term, save it as permanent via remember; ordinary context you want to
keep for yourself should be non-permanent. For reminders, compute the
absolute trigger_at datetime yourself from the current date/time above and
the user's request (e.g. "in 20 minutes", "tomorrow at 8pm", "every Monday
at 9am").

Deleting a note or task will ask the user to explicitly confirm before it
happens — that's expected, not an error; just call the tool and let the
confirmation flow handle it.

You have no other capabilities yet — no file access, no ability to
control the computer, and calendar/email only if those tools appear in
your list this session. If asked to do something outside your current
tools, say so plainly rather than pretending to do it.
{memory_context}"""

# Hard ceiling on tool round-trips per user turn, so a confused model can't
# loop forever burning tokens against something like a permission error.
MAX_TOOL_ITERATIONS = 5

# How many memories to surface in the system prompt each turn. Bounded on
# purpose — this is a hint, not a full memory dump.
MAX_CONTEXT_MEMORIES = 8


class Assistant:
    def __init__(
        self,
        llm: LLMProvider,
        tool_registry: ToolRegistry | None = None,
        memory_repository: MemoryRepository | None = None,
        confirmation_handler: ConfirmationCallback | None = None,
        name: str = "Jarvis",
        max_history_messages: int = 20,
    ) -> None:
        self._llm = llm
        self._tools = tool_registry
        self._memory = memory_repository
        self._confirm = confirmation_handler
        self.name = name
        self._max_history = max_history_messages
        self._history: list[Message] = []

    def _build_memory_context(self) -> str:
        if self._memory is None:
            return ""

        profile = self._memory.retrieve(type=MemoryType.PROFILE, limit=MAX_CONTEXT_MEMORIES // 2)
        episodic = self._memory.retrieve(type=MemoryType.EPISODIC, limit=MAX_CONTEXT_MEMORIES // 2)
        relevant = profile + episodic
        if not relevant:
            return ""

        lines = "\n".join(f"- {m.content}" for m in relevant)
        return f"\n\nThings you know about the user from earlier:\n{lines}"

    @property
    def system_prompt(self) -> str:
        return DEFAULT_SYSTEM_PROMPT_TEMPLATE.format(
            name=self.name,
            current_time=datetime.now().strftime("%A, %B %d, %Y %I:%M %p"),
            memory_context=self._build_memory_context(),
        )

    def reset(self) -> None:
        """Clear short-term conversational context (does not touch stored memory)."""
        self._history = []

    def _persist_conversation_turn(self, user_text: str, reply_text: str) -> None:
        if self._memory is None:
            return
        try:
            self._memory.remember(
                content=f"User: {user_text}\n{self.name}: {reply_text}",
                type=MemoryType.CONVERSATION,
                permanent=False,
                source="conversation_log",
            )
        except ValueError:
            # Empty content edge case — nothing worth persisting.
            pass

    async def chat(self, user_text: str) -> LLMResponse:
        """Send one user turn through the conversation and return the reply.

        If the model requests tools, this method drives the full
        request -> execute -> feed-back-result loop internally and only
        returns once a final text reply is ready (or the loop's safety
        limit is reached). The turn is only committed to history on
        overall success, so a failed call doesn't poison future context.
        """
        turn_start_index = len(self._history)
        self._history.append(Message(role=Role.USER, content=user_text))

        tool_schemas = self._tools.claude_schemas() if self._tools else None

        for _ in range(MAX_TOOL_ITERATIONS):
            trimmed = self._history[-self._max_history :]
            response = await self._llm.complete(
                trimmed, system_prompt=self.system_prompt, tools=tool_schemas
            )

            if not response.success:
                # Roll back this entire turn — nothing here should persist.
                del self._history[turn_start_index:]
                return response

            if not response.tool_calls:
                self._history.append(
                    Message(role=Role.ASSISTANT, content=response.content)
                )
                self._persist_conversation_turn(user_text, response.content)
                return response

            # Record the assistant's tool-use turn verbatim so the follow-up
            # tool_result can be linked to it on the next API call.
            self._history.append(
                Message(
                    role=Role.ASSISTANT,
                    content=response.content,
                    raw_blocks=response.raw_blocks,
                )
            )

            tool_result_blocks = []
            for call in response.tool_calls:
                if self._tools is None:
                    result_text = "No tools are available."
                    is_error = True
                else:
                    result = await self._tools.execute(call.name, self._confirm, **call.input)
                    is_error = not result.success
                    result_text = str(result.result) if result.success else (result.error or "Tool failed.")

                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": result_text,
                        "is_error": is_error,
                    }
                )

            self._history.append(
                Message(role=Role.USER, content="", raw_blocks=tool_result_blocks)
            )

        # Exceeded the iteration limit without a final text reply.
        logger.warning("Tool loop exceeded %s iterations without resolving.", MAX_TOOL_ITERATIONS)
        del self._history[turn_start_index:]
        return LLMResponse(
            success=False,
            error=(
                f"Gave up after {MAX_TOOL_ITERATIONS} tool round-trips without a final answer."
            ),
        )

