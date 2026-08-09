"""
Terminal chat interface.

Run with:
    python -m jarvis

Type a message and press Enter. Type /exit or /quit to leave, /reset to
clear conversation context (stored memory is untouched by /reset).

While running, a background task polls for due reminders and prints them
to the terminal. Reminders only fire while this process is running — see
README for that limitation and the startup catch-up behavior.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.config.settings import settings
from app.core.assistant import Assistant
from app.integrations.computer_controller import ComputerController
from app.integrations.dev_tools_service import DevToolsService
from app.integrations.file_intelligence import FileIntelligenceService
from app.integrations.news import NewsService
from app.integrations.weather import WeatherService
from app.llm.claude import ClaudeProvider
from app.logging_config import configure_logging
from app.memory.repository import MemoryRepository
from app.reminders.models import Reminder
from app.reminders.repository import ReminderRepository
from app.reminders.scheduler import ReminderScheduler
from app.security.path_guard import PathGuard
from app.tools.computer_tools import LaunchTerminalTool, OpenApplicationTool, OpenFolderTool, OpenWebsiteTool
from app.tools.dev_tools import GitDiffTool, GitStatusTool, RunTestsTool
from app.tools.file_tools import (
    DeleteFileTool,
    FindFilesTool,
    ListRecentFilesTool,
    ReadFileTool,
    SearchFileContentsTool,
)
from app.tools.memory_tools import ForgetTool, RecallTool, RememberTool
from app.tools.news_tool import GetNewsTool
from app.tools.notes import CreateNoteTool, DeleteNoteTool, ListNotesTool
from app.tools.registry import ToolRegistry
from app.tools.reminder_tools import CancelReminderTool, CreateReminderTool, ListRemindersTool
from app.tools.tasks import CompleteTaskTool, CreateTaskTool, DeleteTaskTool, ListTasksTool
from app.tools.time_tool import GetCurrentTimeTool
from app.tools.weather_tool import GetWeatherTool
from app.voice.microphone import MicrophoneError, record_push_to_talk, record_until_silence
from app.voice.stt import WhisperSTT
from app.voice.tts import EdgeTTSProvider
from app.voice.wake_word import WakeWordDetector, WakeWordError

logger = logging.getLogger(__name__)

EXIT_COMMANDS = {"/exit", "/quit"}
RESET_COMMANDS = {"/reset"}
VOICE_COMMANDS = {"/voice"}
WAKE_COMMANDS = {"/wake"}


def build_tool_registry(memory: MemoryRepository, reminders: ReminderRepository) -> ToolRegistry:
    db_path = settings.data_dir / "jarvis.db"
    registry = ToolRegistry()
    registry.register(GetCurrentTimeTool())
    registry.register(CreateNoteTool(db_path=db_path))
    registry.register(ListNotesTool(db_path=db_path))
    registry.register(DeleteNoteTool(db_path=db_path))
    registry.register(CreateTaskTool(db_path=db_path))
    registry.register(ListTasksTool(db_path=db_path))
    registry.register(CompleteTaskTool(db_path=db_path))
    registry.register(DeleteTaskTool(db_path=db_path))
    registry.register(RememberTool(repository=memory))
    registry.register(RecallTool(repository=memory))
    registry.register(ForgetTool(repository=memory))
    registry.register(CreateReminderTool(repository=reminders))
    registry.register(ListRemindersTool(repository=reminders))
    registry.register(CancelReminderTool(repository=reminders))
    registry.register(GetWeatherTool(weather_service=WeatherService(temperature_unit=settings.weather_temp_unit)))
    registry.register(GetNewsTool(news_service=NewsService(feed_urls=settings.news_feed_urls)))
    _register_computer_and_file_tools(registry)
    _register_google_tools(registry)
    return registry


def _register_computer_and_file_tools(registry: ToolRegistry) -> None:
    """Computer control and file intelligence tools. Registered
    unconditionally (unlike Google) since they have no external account
    dependency — but every operation is still bounded by
    ALLOWED_DIRECTORIES/ALLOWED_APPLICATIONS, which default to empty, so
    an unconfigured Jarvis simply can't touch the filesystem or launch
    anything until the user opts in via .env.
    """
    path_guard = PathGuard(allowed_roots=settings.allowed_directories)
    controller = ComputerController(
        allowed_applications=settings.allowed_applications, path_guard=path_guard
    )
    file_service = FileIntelligenceService(path_guard=path_guard)
    dev_service = DevToolsService(path_guard=path_guard)

    registry.register(OpenApplicationTool(controller=controller))
    registry.register(OpenWebsiteTool(controller=controller))
    registry.register(OpenFolderTool(controller=controller))
    registry.register(LaunchTerminalTool(controller=controller))

    registry.register(FindFilesTool(service=file_service))
    registry.register(ListRecentFilesTool(service=file_service))
    registry.register(ReadFileTool(service=file_service))
    registry.register(SearchFileContentsTool(service=file_service))
    registry.register(DeleteFileTool(service=file_service))

    registry.register(GitStatusTool(service=dev_service))
    registry.register(GitDiffTool(service=dev_service))
    registry.register(
        RunTestsTool(service=dev_service, project_test_commands=settings.project_test_commands)
    )


def _register_google_tools(registry: ToolRegistry) -> None:
    """Calendar/Email are opt-in: only registered if credentials.json is
    present and the google extra is installed. Missing either is not an
    error — it just means those tools aren't available this session,
    reported once at startup rather than crashing the whole app.
    """
    if not settings.google_credentials_path.exists():
        logger.info(
            "No credentials.json found at %s — calendar/email tools disabled.",
            settings.google_credentials_path,
        )
        return

    try:
        from app.integrations.calendar_service import CalendarService
        from app.integrations.email_service import EmailService
        from app.integrations.google_auth import (
            GoogleAuthError,
            build_calendar_resource,
            build_gmail_resource,
            get_credentials,
        )
        from app.tools.calendar_tools import (
            CreateCalendarEventTool,
            DeleteCalendarEventTool,
            GetCalendarEventsTool,
        )
        from app.tools.email_tools import DraftEmailTool, ReadEmailTool, SearchEmailTool, SendEmailTool
    except ImportError as exc:
        print(
            f"(Calendar/Email unavailable: {exc}. Install with: pip install -e \".[google]\")"
        )
        return

    try:
        # Runs the OAuth flow (opens a browser) on first use, or refreshes
        # a cached token on subsequent runs. This happens once, here, at
        # startup, before the scheduler or REPL loop are doing anything
        # else — a one-time blocking call at this specific moment is fine.
        credentials = get_credentials(settings.google_credentials_path, settings.google_token_path)
    except GoogleAuthError as exc:
        print(f"(Calendar/Email unavailable: {exc})")
        return

    calendar_service = CalendarService(build_calendar_resource(credentials))
    email_service = EmailService(build_gmail_resource(credentials))

    registry.register(GetCalendarEventsTool(calendar_service=calendar_service))
    registry.register(CreateCalendarEventTool(calendar_service=calendar_service))
    registry.register(DeleteCalendarEventTool(calendar_service=calendar_service))
    registry.register(SearchEmailTool(email_service=email_service))
    registry.register(ReadEmailTool(email_service=email_service))
    registry.register(DraftEmailTool(email_service=email_service))
    registry.register(SendEmailTool(email_service=email_service))


async def confirm_action(description: str) -> bool:
    """Real confirmation callback for the terminal: prints what Jarvis
    wants to do and blocks (in a thread executor, so it doesn't freeze
    the reminder scheduler) until the user types yes/no.

    Used even during voice sessions — a misheard "yes" approving
    something destructive is exactly the risk this system exists to
    prevent, so confirmation always goes through typed input regardless
    of how the request itself arrived.
    """
    print(f"\n⚠️  Jarvis wants to: {description}")
    loop = asyncio.get_running_loop()
    answer = (await loop.run_in_executor(None, input, "Confirm? (yes/no): ")).strip().lower()
    return answer in {"y", "yes"}


async def _print_reminder_notification(reminder: Reminder) -> None:
    print(f"\n🔔 Reminder: {reminder.message}\n")


def build_assistant() -> tuple[Assistant, ReminderScheduler]:
    if settings.llm_provider != "claude":
        raise ValueError(
            f"Unsupported LLM_PROVIDER '{settings.llm_provider}'. "
            "Only 'claude' is implemented so far."
        )

    llm = ClaudeProvider(
        api_key=settings.anthropic_api_key,
        model=settings.claude_model,
        max_tokens=settings.claude_max_tokens,
    )
    db_path = settings.data_dir / "jarvis.db"
    memory = MemoryRepository(db_path=db_path)
    reminders = ReminderRepository(db_path=db_path)

    # Auto-expiring memories older than their TTL are purged once at
    # startup rather than on a background schedule.
    purged = memory.purge_expired()
    if purged:
        logger.info("Purged %d expired memory record(s) on startup.", purged)

    assistant = Assistant(
        llm=llm,
        tool_registry=build_tool_registry(memory, reminders),
        memory_repository=memory,
        confirmation_handler=confirm_action,
        name=settings.assistant_name,
        max_history_messages=settings.max_history_messages,
    )
    scheduler = ReminderScheduler(repository=reminders, notify=_print_reminder_notification)
    return assistant, scheduler


async def _transcribe_chat_and_speak(
    assistant: Assistant, loop: asyncio.AbstractEventLoop, audio_path: str
) -> None:
    """Shared tail end of any voice exchange: transcribe -> chat -> speak.

    Used by both /voice (push-to-talk) and /wake (wake-word-triggered)
    so the two entry points can't drift into different behavior.
    """
    stt = WhisperSTT(model_size=settings.whisper_model_size)
    transcription = await loop.run_in_executor(None, stt.transcribe, audio_path)
    if not transcription.success:
        print(f"Couldn't understand that: {transcription.error}\n")
        return

    print(f"You (voice): {transcription.text}")

    response = await assistant.chat(transcription.text)
    if not response.success:
        print(f"{assistant.name}: I couldn't get a response — {response.error}\n")
        return

    print(f"{assistant.name}: {response.content}\n")

    tts = EdgeTTSProvider(
        voice=settings.tts_voice,
        rate=settings.tts_rate,
        pitch=settings.tts_pitch,
        cinematic_effect=settings.tts_cinematic_effect,
        effect_boost_hz=settings.tts_effect_boost_hz,
        effect_boost_db=settings.tts_effect_boost_db,
        effect_mod_hz=settings.tts_effect_mod_hz,
        effect_mod_depth=settings.tts_effect_mod_depth,
    )
    speech_result = await tts.speak(response.content)
    if not speech_result.success:
        print(f"(couldn't speak the reply aloud: {speech_result.error})\n")


async def handle_voice_turn(assistant: Assistant, loop: asyncio.AbstractEventLoop) -> None:
    """One push-to-talk exchange: record -> transcribe -> chat -> speak."""
    try:
        audio_path = await loop.run_in_executor(None, record_push_to_talk)
    except MicrophoneError as exc:
        print(f"Voice input unavailable: {exc}\n")
        return

    await _transcribe_chat_and_speak(assistant, loop, audio_path)


async def handle_wake_word_mode(assistant: Assistant, loop: asyncio.AbstractEventLoop) -> None:
    """Continuous hands-free mode: listen for 'hey jarvis', then record
    until the user goes quiet, transcribe, chat, speak — repeating until
    interrupted with Ctrl+C.
    """
    detector = WakeWordDetector(threshold=settings.wake_word_threshold)
    print('Listening for "Hey Jarvis"... (Ctrl+C to stop wake-word mode)\n')

    while True:
        try:
            await loop.run_in_executor(None, detector.listen)
        except WakeWordError as exc:
            print(f"Wake word listening unavailable: {exc}\n")
            return
        except KeyboardInterrupt:
            print("\nExiting wake-word mode, back to text input.\n")
            return

        print("Wake word detected — listening...")
        try:
            audio_path = await loop.run_in_executor(None, record_until_silence)
        except MicrophoneError as exc:
            print(f"Voice input unavailable: {exc}\n")
            continue

        await _transcribe_chat_and_speak(assistant, loop, audio_path)
        print('Listening for "Hey Jarvis" again... (Ctrl+C to stop)\n')


async def run_chat_loop() -> None:
    problems = settings.validate()
    if problems:
        for p in problems:
            print(f"Configuration error: {p}", file=sys.stderr)
        sys.exit(1)

    assistant, scheduler = build_assistant()

    # Catch up on anything that was due while Jarvis wasn't running, rather
    # than silently letting it fire (and immediately reschedule, for
    # recurring ones) with no visibility.
    missed = await scheduler.check_once()
    if missed:
        print(f"While you were away, {len(missed)} reminder(s) came due:")
        for r in missed:
            print(f"  - {r.message}")
        print()

    scheduler.start()

    print(
        f"{assistant.name} is online. Type /exit to quit, /reset to clear context, "
        f"/voice for a push-to-talk turn, /wake for hands-free mode.\n"
    )

    loop = asyncio.get_running_loop()

    try:
        while True:
            try:
                # input() is a blocking call. Running it directly here would
                # block the whole asyncio event loop — including the
                # reminder scheduler's background task — until Enter is
                # pressed, so reminders would only ever seem to "fire" right
                # after you send a message instead of when they're actually
                # due. Running it in a thread executor lets the event loop
                # (and the scheduler) keep running while we wait on input.
                user_text = (await loop.run_in_executor(None, input, "You: ")).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                break

            if not user_text:
                continue
            if user_text.lower() in EXIT_COMMANDS:
                print("Goodbye.")
                break
            if user_text.lower() in RESET_COMMANDS:
                assistant.reset()
                print("(conversation context cleared)\n")
                continue
            if user_text.lower() in VOICE_COMMANDS:
                await handle_voice_turn(assistant, loop)
                continue
            if user_text.lower() in WAKE_COMMANDS:
                await handle_wake_word_mode(assistant, loop)
                continue

            response = await assistant.chat(user_text)

            if response.success:
                print(f"{assistant.name}: {response.content}\n")
            else:
                print(f"{assistant.name}: I couldn't get a response — {response.error}\n")
    finally:
        await scheduler.stop()


def main() -> None:
    configure_logging(settings.log_level)
    asyncio.run(run_chat_loop())


if __name__ == "__main__":
    main()
