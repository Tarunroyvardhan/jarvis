"""
Terminal interface.

Run with:
    python -m jarvis

Type a message and press Enter. Commands: /help, /tools, /reset, /voice,
/wake, /speak, /exit. Ctrl+C interrupts whatever Jarvis is doing (a reply,
wake-word listening, a confirmation prompt); at an empty prompt it exits.

While running, a background task polls for due reminders. Plain reminders
are printed and shown as a desktop notification; reminders with a task
prompt are carried out automatically (anything that would need your
confirmation is refused during those unattended runs).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading
from collections.abc import Awaitable
from typing import TypeVar

from app.config.settings import settings
from app.core.assistant import Assistant
from app.integrations import system_control
from app.integrations.browser import BrowserSession
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
from app.tools.browser_tools import browser_tools
from app.tools.computer_tools import LaunchTerminalTool, OpenApplicationTool, OpenFolderTool, OpenWebsiteTool
from app.tools.dev_tools import GitDiffTool, GitStatusTool, RunTestsTool
from app.tools.file_tools import (
    CopyFileTool,
    CreateFolderTool,
    DeleteFileTool,
    FindFilesTool,
    ListDirectoryTool,
    ListRecentFilesTool,
    MoveFileTool,
    ReadFileTool,
    SearchFileContentsTool,
    WriteFileTool,
)
from app.tools.memory_tools import ForgetTool, RecallTool, RememberTool
from app.tools.news_tool import GetNewsTool
from app.tools.notes import CreateNoteTool, DeleteNoteTool, ListNotesTool
from app.tools.registry import ToolRegistry
from app.tools.reminder_tools import CancelReminderTool, CreateReminderTool, ListRemindersTool
from app.tools.system_tools import (
    GetClipboardTool,
    GetSystemInfoTool,
    KillProcessTool,
    ListProcessesTool,
    LockScreenTool,
    MediaControlTool,
    RunShellCommandTool,
    SendNotificationTool,
    SetClipboardTool,
    TakeScreenshotTool,
)
from app.tools.tasks import CompleteTaskTool, CreateTaskTool, DeleteTaskTool, ListTasksTool
from app.tools.time_tool import GetCurrentTimeTool
from app.tools.weather_tool import GetWeatherTool

logger = logging.getLogger(__name__)

T = TypeVar("T")

DIM = "\033[90m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"

HELP_TEXT = """Commands:
  /help    show this help
  /tools   list the tools available this session
  /reset   clear conversation context (saved memory is untouched)
  /voice   one push-to-talk turn (Enter to start, Enter to stop)
  /wake    hands-free mode: say "Hey Jarvis", then speak (Ctrl+C to stop)
  /speak   toggle reading typed replies aloud
  /google  sign in to Google for Calendar and Email
  /wakecheck  measure how well "Hey Jarvis" is detected and suggest a setting
  /exit    quit
Ctrl+C interrupts the current reply; at an empty prompt it exits."""


# --- Interrupt handling ---------------------------------------------------
#
# asyncio's default Ctrl+C handling cancels the whole program, and a
# blocking input() running in a worker thread can't be interrupted at all,
# which used to leave the process hanging on exit. Instead, Ctrl+C sets an
# event that whatever is currently running races against.


class Interrupted(Exception):
    pass


class _InterruptState:
    """Ctrl+C goes to the innermost interruptible() only, so pressing it at
    a confirmation prompt declines that action instead of also cancelling
    the reply the prompt belongs to."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stack: list[asyncio.Event] = []

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def _fire(self) -> None:
        if self.stack:
            self.stack[-1].set()

    def on_signal(self, signum, frame) -> None:  # noqa: ANN001 - signal handler signature
        if self.loop is None or self.loop.is_closed():
            raise KeyboardInterrupt
        self.loop.call_soon_threadsafe(self._fire)


_interrupts = _InterruptState()


async def interruptible(awaitable: Awaitable[T]) -> T:
    """Await `awaitable`, raising Interrupted (and cancelling it) on Ctrl+C."""
    event = asyncio.Event()
    _interrupts.stack.append(event)
    task = asyncio.ensure_future(awaitable)
    waiter = asyncio.ensure_future(event.wait())
    try:
        done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()
        _interrupts.stack.remove(event)
    if task in done:
        return task.result()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    raise Interrupted()


_pending_input: asyncio.Future[str] | None = None


def ainput(prompt: str) -> asyncio.Future[str]:
    """input() on a daemon thread, so a pending prompt never blocks exit.

    If an earlier prompt was abandoned (Ctrl+C), its thread is still
    waiting on stdin; the new prompt reuses that read rather than starting
    a second reader that would race it for the next line.
    """
    global _pending_input
    if _pending_input is not None and not _pending_input.done():
        print(prompt, end="", flush=True)
        return asyncio.shield(_pending_input)

    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()
    _pending_input = future

    def _reader() -> None:
        try:
            value = input(prompt)
        except BaseException as exc:  # noqa: BLE001 - EOFError, KeyboardInterrupt, ...
            loop.call_soon_threadsafe(lambda: future.done() or future.set_exception(EOFError(str(exc))))
            return
        loop.call_soon_threadsafe(lambda: future.done() or future.set_result(value))

    threading.Thread(target=_reader, daemon=True).start()
    return asyncio.shield(future)


# --- Wiring ---------------------------------------------------------------


def build_tool_registry(
    memory: MemoryRepository, reminders: ReminderRepository, browser: BrowserSession | None
) -> tuple[ToolRegistry, bool]:
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
    _register_system_tools(registry)
    if browser is not None:
        for tool in browser_tools(browser):
            registry.register(tool)
    google_ready = register_google_tools(registry, interactive=False)
    return registry, google_ready


def _register_computer_and_file_tools(registry: ToolRegistry) -> None:
    """Computer control and file intelligence tools. File operations are
    bounded by ALLOWED_DIRECTORIES (empty by default, so an unconfigured
    Jarvis can't touch the filesystem through them until you opt in)."""
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
    registry.register(ListDirectoryTool(service=file_service))
    registry.register(ReadFileTool(service=file_service))
    registry.register(SearchFileContentsTool(service=file_service))
    registry.register(WriteFileTool(service=file_service))
    registry.register(CreateFolderTool(service=file_service))
    registry.register(CopyFileTool(service=file_service))
    registry.register(MoveFileTool(service=file_service))
    registry.register(DeleteFileTool(service=file_service))

    registry.register(GitStatusTool(service=dev_service))
    registry.register(GitDiffTool(service=dev_service))
    registry.register(
        RunTestsTool(service=dev_service, project_test_commands=settings.project_test_commands)
    )


def _register_system_tools(registry: ToolRegistry) -> None:
    if settings.shell_enabled:
        registry.register(RunShellCommandTool(default_timeout=settings.shell_timeout_seconds))
    registry.register(GetSystemInfoTool())
    registry.register(ListProcessesTool())
    registry.register(KillProcessTool())
    registry.register(TakeScreenshotTool())
    registry.register(GetClipboardTool())
    registry.register(SetClipboardTool())
    registry.register(MediaControlTool())
    registry.register(LockScreenTool())
    registry.register(SendNotificationTool())


def register_google_tools(registry: ToolRegistry, interactive: bool) -> bool:
    """Calendar/Email are opt-in: only registered if credentials.json is
    present and the google extra is installed. Missing either is not an
    error — it just means those tools aren't available this session.

    At startup this runs non-interactively (cached/refreshed token only);
    signing in through the browser happens only when the user runs /google.
    Returns True if the tools are registered.
    """
    if registry.get("get_calendar_events") is not None:
        return True
    if not settings.google_credentials_path.exists():
        logger.info(
            "No credentials.json found at %s — calendar/email tools disabled.",
            settings.google_credentials_path,
        )
        if interactive:
            print(f"(No credentials.json at {settings.google_credentials_path} — see README for Google setup.)")
        return False

    try:
        from app.integrations.calendar_service import CalendarService
        from app.integrations.email_service import EmailService
        from app.integrations.google_auth import (
            GoogleAuthError,
            GoogleLoginRequired,
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
        print(f"(Calendar/Email unavailable: {exc}. Install with: pip install -e \".[google]\")")
        return False

    try:
        credentials = get_credentials(
            settings.google_credentials_path, settings.google_token_path, interactive=interactive
        )
        calendar_service = CalendarService(build_calendar_resource(credentials))
        email_service = EmailService(build_gmail_resource(credentials))
    except GoogleLoginRequired:
        print(f"{DIM}Note: Calendar/Email need you to sign in to Google — type /google when ready.{RESET}")
        return False
    except GoogleAuthError as exc:
        print(f"(Calendar/Email unavailable: {exc})")
        return False
    except Exception as exc:  # noqa: BLE001 - offline at startup, revoked token, etc.
        logger.exception("Google setup failed")
        print(f"(Calendar/Email unavailable: {exc})")
        return False

    registry.register(GetCalendarEventsTool(calendar_service=calendar_service))
    registry.register(CreateCalendarEventTool(calendar_service=calendar_service))
    registry.register(DeleteCalendarEventTool(calendar_service=calendar_service))
    registry.register(SearchEmailTool(email_service=email_service))
    registry.register(ReadEmailTool(email_service=email_service))
    registry.register(DraftEmailTool(email_service=email_service))
    registry.register(SendEmailTool(email_service=email_service))
    return True


async def confirm_action(description: str) -> bool:
    """Terminal confirmation callback: shows exactly what Jarvis wants to do
    and waits for a typed yes/no.

    Used even during voice sessions — a misheard "yes" approving something
    destructive is exactly the risk this exists to prevent, so confirmation
    always goes through typed input. Ctrl+C counts as "no".
    """
    print(f"\n{YELLOW}⚠️  {settings.assistant_name} wants to:{RESET}\n{description}")
    try:
        answer = (await interruptible(ainput("Confirm? (yes/no): "))).strip().lower()
    except (Interrupted, EOFError):
        print("(declined)")
        return False
    return answer in {"y", "yes"}


class VoiceIO:
    """Lazily-built, reused speech components. Loading the Whisper model
    takes seconds, so it must happen once per session, not once per turn."""

    def __init__(self) -> None:
        self._stt = None
        self._tts = None
        self._detector = None
        self._tts_lock = threading.Lock()  # preload thread vs. first reply

    @property
    def stt(self):
        if self._stt is None:
            from app.voice.stt import WhisperSTT

            language = None if settings.whisper_language.lower() == "auto" else settings.whisper_language
            self._stt = WhisperSTT(
                model_size=settings.whisper_model_size,
                language=language,
                initial_prompt=settings.assistant_name,
            )
        return self._stt

    @property
    def tts(self):
        with self._tts_lock:
            if self._tts is None:
                self._tts = self._build_tts()
        return self._tts

    def _build_tts(self):
        """The voice engine chosen by TTS_ENGINE, falling back to Edge."""
        effect = dict(
            cinematic_effect=settings.tts_cinematic_effect,
            effect_boost_hz=settings.tts_effect_boost_hz,
            effect_boost_db=settings.tts_effect_boost_db,
            effect_mod_hz=settings.tts_effect_mod_hz,
            effect_mod_depth=settings.tts_effect_mod_depth,
            effect_room=settings.tts_effect_room,
        )
        if settings.tts_engine == "piper":
            from app.voice.piper_tts import PiperTTSProvider

            model = settings.piper_voice_dir / f"{settings.piper_voice}.onnx"
            if PiperTTSProvider.available(model):
                return PiperTTSProvider(model_path=model, rate=settings.tts_rate, **effect)
            print(
                f"{DIM}(Offline voice unavailable: install with pip install piper-tts and download it with "
                f"python -m piper.download_voices --download-dir {settings.piper_voice_dir} "
                f"{settings.piper_voice}; using the online voice instead){RESET}"
            )
        from app.voice.tts import EdgeTTSProvider

        return EdgeTTSProvider(
            voice=settings.tts_voice, rate=settings.tts_rate, pitch=settings.tts_pitch, **effect
        )

    def preload_tts(self) -> None:
        """Get the voice ready ahead of time (call from a worker thread):
        warms up the offline voice, or imports the online voice's
        libraries, so the first reply isn't delayed by ~2-3 seconds."""
        try:
            tts = self.tts
            if hasattr(tts, "warm_up"):
                tts.warm_up()
            else:
                import av  # noqa: F401
                import edge_tts  # noqa: F401
                import scipy.signal  # noqa: F401
        except Exception:  # noqa: BLE001 - speak() will report problems properly later
            logger.debug("Voice preload failed", exc_info=True)

    @property
    def detector(self):
        # One detector per session: loading the wake-word model is slow.
        if self._detector is None:
            from app.voice.wake_word import WakeWordDetector

            self._detector = WakeWordDetector(
                threshold=settings.wake_word_threshold, gain=settings.wake_word_gain
            )
        return self._detector

    def preload_stt(self) -> None:
        """Load Whisper ahead of time (call from a worker thread) so the
        first sentence after waking isn't delayed by model loading."""
        try:
            self.stt._get_model()
        except Exception:  # noqa: BLE001 - transcribe() will report it properly later
            logger.debug("Whisper preload failed", exc_info=True)

    @staticmethod
    def chime() -> None:
        """Short beep confirming the wake word was heard (non-blocking)."""
        if sys.platform != "win32":
            return

        def _beep() -> None:
            try:
                import winsound

                winsound.Beep(1046, 90)
                winsound.Beep(1568, 110)
            except Exception:  # noqa: BLE001 - no sound device; the printed message is enough
                pass

        threading.Thread(target=_beep, daemon=True).start()

    async def speak(self, text: str) -> None:
        result = await self.tts.speak(text)
        if not result.success:
            print(f"{DIM}(couldn't speak the reply aloud: {result.error}){RESET}\n")


class App:
    def __init__(self) -> None:
        if settings.llm_provider != "claude":
            raise ValueError(
                f"Unsupported LLM_PROVIDER '{settings.llm_provider}'. Only 'claude' is implemented."
            )
        llm = ClaudeProvider(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            effort=settings.claude_effort,
            web_search=settings.web_search_enabled,
        )
        db_path = settings.data_dir / "jarvis.db"
        self.memory = MemoryRepository(db_path=db_path)
        self.reminders = ReminderRepository(db_path=db_path)

        purged = self.memory.purge_expired()
        if purged:
            logger.info("Purged %d expired memory record(s) on startup.", purged)

        self.browser = (
            BrowserSession(profile_dir=settings.data_dir / "browser_profile", headless=settings.browser_headless)
            if BrowserSession.available()
            else None
        )
        self.registry, self.google_ready = build_tool_registry(self.memory, self.reminders, self.browser)
        self.assistant = Assistant(
            llm=llm,
            tool_registry=self.registry,
            memory_repository=self.memory,
            confirmation_handler=confirm_action,
            name=settings.assistant_name,
            user_name=settings.user_name,
            max_tool_iterations=settings.max_tool_iterations,
            progress_callback=self._show_progress,
        )
        self.scheduler = ReminderScheduler(repository=self.reminders, notify=self._on_reminder)
        self.voice = VoiceIO()
        self.speak_replies = False
        self._background: set[asyncio.Task] = set()
        # During the startup catch-up, plain reminders are listed once in
        # the "while you were away" summary instead of also printing here.
        self._catching_up = False

    @staticmethod
    def _show_progress(note: str) -> None:
        print(f"{DIM}  › {note}{RESET}")

    # --- reminders / automations ---

    async def _on_reminder(self, reminder: Reminder) -> None:
        if reminder.task_prompt:
            # Run the automation in the background so a long task doesn't
            # stall the scheduler's polling.
            task = asyncio.create_task(self._run_automation(reminder))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
            return
        if self._catching_up:
            return
        print(f"\n🔔 Reminder: {reminder.message}\n")
        if settings.desktop_notifications:
            system_control.show_desktop_notification(f"{settings.assistant_name} reminder", reminder.message)

    async def _run_automation(self, reminder: Reminder) -> None:
        print(f"\n{CYAN}⚙️  Running scheduled task: {reminder.message}{RESET}")
        prompt = (
            f"[Scheduled automation '{reminder.message}' has fired. Nobody is watching right now, "
            f"so anything that needs confirmation will be refused.]\n{reminder.task_prompt}"
        )
        response = await self.assistant.chat(prompt, confirmation_handler=None)
        if response.success:
            print(f"{settings.assistant_name} (scheduled): {response.content}\n")
            summary = response.content
        else:
            print(f"{settings.assistant_name} (scheduled): the task failed — {response.error}\n")
            summary = f"Scheduled task failed: {response.error}"
        if settings.desktop_notifications:
            system_control.show_desktop_notification(reminder.message, summary[:300])

    # --- voice ---

    async def _transcribe_chat_and_speak(self, audio_path: str) -> None:
        """Shared tail of any voice exchange: transcribe -> chat -> speak."""
        loop = asyncio.get_running_loop()
        transcription = await loop.run_in_executor(None, self.voice.stt.transcribe, audio_path)
        if not transcription.success:
            print(f"Couldn't understand that: {transcription.error}\n")
            return

        print(f"You (voice): {transcription.text}")
        await self._chat_and_reply(transcription.text, speak=True)

    async def handle_voice_turn(self) -> None:
        """One push-to-talk exchange: record -> transcribe -> chat -> speak."""
        from app.voice.microphone import MicrophoneError, record_push_to_talk

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, self.voice.preload_tts)  # ready by the time you finish talking
        try:
            audio_path = await loop.run_in_executor(None, record_push_to_talk)
        except MicrophoneError as exc:
            print(f"Voice input unavailable: {exc}\n")
            return
        await self._transcribe_chat_and_speak(audio_path)

    async def handle_wake_word_mode(self) -> None:
        """Hands-free mode.

        Say "Hey Jarvis" once to wake it. From then on Jarvis keeps
        listening: every sentence is transcribed, and any sentence that
        mentions "Jarvis" (anywhere in it) is answered aloud; everything
        else is ignored. The sentence right after waking, or right after
        saying just "Jarvis", is answered without needing the name.

        "Jarvis, stop listening" (or "go to sleep") puts it back to waiting
        for "Hey Jarvis"; Ctrl+C leaves voice mode entirely.
        """
        from app.voice.wake_word import WakeWordError, WakeWordStopped

        detector = self.voice.detector
        loop = asyncio.get_running_loop()
        # Load Whisper and the voice while waiting for the wake word, not after it.
        loop.run_in_executor(None, self.voice.preload_stt)
        loop.run_in_executor(None, self.voice.preload_tts)

        while True:
            print(f"{DIM}(Ctrl+C to go back to typing){RESET}")
            stop = threading.Event()
            try:
                await interruptible(loop.run_in_executor(None, detector.listen, stop))
            except Interrupted:
                stop.set()
                print("\nExiting voice mode, back to text input.\n")
                return
            except WakeWordStopped:
                return
            except WakeWordError as exc:
                print(f"Wake word listening unavailable: {exc}\n")
                return

            self.voice.chime()
            if not await self._always_listening_session():
                return  # Ctrl+C or a microphone failure: leave voice mode

    async def handle_wake_check(self) -> None:
        """Measure wake-word scores for this mic/room and suggest settings."""
        from app.voice.wake_word import WakeWordError, WakeWordStopped

        loop = asyncio.get_running_loop()
        seconds = 12
        current = settings.wake_word_threshold
        print(
            f'For the next {seconds} seconds, say "Hey Jarvis" 3 or 4 times, '
            "pausing a couple of seconds between each, the way you normally would.\n"
            "Starting in a moment..."
        )
        stop = threading.Event()
        try:
            await interruptible(loop.run_in_executor(None, self.voice.detector._get_model))
            print("Go!")
            peaks, loudness = await interruptible(
                loop.run_in_executor(None, self.voice.detector.measure, seconds, stop)
            )
        except Interrupted:
            stop.set()
            print("(cancelled)\n")
            return
        except (WakeWordError, WakeWordStopped) as exc:
            print(f"Couldn't measure: {exc}\n")
            return

        hits = sorted((p for p in peaks if p >= 0.05), reverse=True)
        print("\nWake-word score per second: " + " ".join(f"{p:.2f}" for p in peaks))
        print(f"Loudest sound heard: {loudness:.0f} (clear speech near the laptop is usually 1000+)")
        if loudness < 600:
            print("Your voice is reaching the microphone quietly — try WAKE_WORD_GAIN=2.0 in .env, "
                  "or raise the input volume in Windows (Settings > System > Sound > Input).")
        if not hits:
            print(
                'I barely heard "Hey Jarvis" at all. Check that the right microphone is the '
                "Windows default (Settings > System > Sound > Input), speak a bit louder, "
                "or boost it with WAKE_WORD_GAIN=2.0 in .env.\n"
            )
            return
        # Your detections are roughly the top few peaks; aim the threshold
        # at about 70% of your weaker attempts so each one would trigger.
        attempts = hits[:4]
        suggested = round(max(0.1, min(0.6, min(attempts) * 0.7)), 2)
        print(f"Your strongest attempts scored: {', '.join(f'{p:.2f}' for p in attempts)}")
        print(f"Current WAKE_WORD_THRESHOLD: {current}")
        if suggested < current:
            print(f"Suggestion: set WAKE_WORD_THRESHOLD={suggested} in .env (lower = more sensitive).")
        else:
            print("Your current threshold should already catch these. If it still feels slow, try lowering it by 0.05.")
        if max(attempts) < 0.3 and settings.wake_word_gain <= 1.0:
            print("Scores are low overall; WAKE_WORD_GAIN=2.0 in .env may help a quiet microphone.")
        print("Restart Jarvis after changing .env.\n")

    async def _always_listening_session(self) -> bool:
        """Listen continuously, answering sentences addressed to Jarvis.
        Returns True to go back to waiting for the wake word ("stop
        listening"), False to leave voice mode (Ctrl+C / mic failure)."""
        from app.voice.conversation import extract_command, is_stop_phrase
        from app.voice.microphone import MicrophoneError, RecordingStopped, record_utterance

        loop = asyncio.get_running_loop()
        name = settings.assistant_name
        print(
            f"{CYAN}I'm listening. Include \"{name}\" in anything you want me to answer.{RESET}\n"
            f'{DIM}("{name}, stop listening" to pause; Ctrl+C to go back to typing){RESET}\n'
        )
        # The first sentence after waking (or after a bare "Jarvis") is
        # answered even without the name: you just called it.
        expecting_follow_up = True

        while True:
            stop = threading.Event()
            try:
                audio_path = await interruptible(
                    loop.run_in_executor(
                        None,
                        lambda: record_utterance(stop, silence_seconds=settings.voice_silence_seconds),
                    )
                )
            except Interrupted:
                stop.set()
                print("\nExiting voice mode, back to text input.\n")
                return False
            except RecordingStopped:
                return False
            except MicrophoneError as exc:
                print(f"Voice input unavailable: {exc}\n")
                return False

            transcription = await loop.run_in_executor(None, self.voice.stt.transcribe, audio_path)
            if not transcription.success:
                continue  # silence or noise: keep listening
            heard = transcription.text.strip()

            addressed, command = extract_command(heard, name)
            if not addressed and not expecting_follow_up:
                print(f"{DIM}  (heard: {heard}){RESET}")
                continue

            print(f"You (voice): {heard}")
            if not command:
                # Just "Jarvis" on its own: acknowledge and take the next
                # sentence without needing the name again.
                expecting_follow_up = True
                await self.voice.speak("Yes?")
                continue
            expecting_follow_up = False

            if is_stop_phrase(command):
                await self.voice.speak("Going quiet. Say hey Jarvis when you need me.")
                print(f"{DIM}(stopped listening){RESET}\n")
                return True

            try:
                await interruptible(self._chat_and_reply(command, speak=True))
            except Interrupted:
                print("\nExiting voice mode, back to text input.\n")
                return False

    # --- chat ---

    async def _chat_and_reply(self, text: str, speak: bool = False) -> None:
        # Spoken replies take real time to listen to; keep them short.
        note = (
            "This is a voice conversation: reply in one to three short spoken sentences "
            "unless the user asks for detail."
            if speak
            else None
        )
        response = await self.assistant.chat(text, turn_note=note)
        if not response.success:
            print(f"{settings.assistant_name}: I couldn't complete that — {response.error}\n")
            return
        print(f"{settings.assistant_name}: {response.content}\n")
        if (speak or self.speak_replies) and response.content:
            await self.voice.speak(response.content)

    async def handle_google_login(self) -> None:
        if self.google_ready:
            print("(Calendar and Email are already connected.)\n")
            return
        loop = asyncio.get_running_loop()
        print("Opening Google sign-in in your browser (you have 5 minutes)...")
        ok = await loop.run_in_executor(None, register_google_tools, self.registry, True)
        if ok:
            self.google_ready = True
            # The tool list is part of the conversation prefix; start fresh
            # so the new tools are visible from the first message.
            self.assistant.reset()
            print("Calendar and Email connected (conversation context was reset).\n")

    def _print_tools(self) -> None:
        names = sorted(tool.name for tool in self.registry.all_tools())
        extra = " + web_search, web_fetch (server-side)" if settings.web_search_enabled else ""
        print(f"{len(names)} tools{extra}:\n  " + ", ".join(names) + "\n")

    async def run(self) -> None:
        self._catching_up = True
        try:
            missed = await self.scheduler.check_once()
        finally:
            self._catching_up = False
        if missed:
            print(f"While you were away, {len(missed)} reminder(s) came due:")
            for r in missed:
                print(f"  - {r.message}")
            print()

        self.scheduler.start()
        for note in settings.warnings():
            print(f"{DIM}Note: {note}{RESET}")
        if self.browser is None:
            print(f'{DIM}Note: browser automation is off (install with: pip install -e ".[browser]").{RESET}')
        print(f"{settings.assistant_name} is online ({settings.claude_model}). Type /help for commands.\n")

        try:
            while True:
                try:
                    user_text = (await interruptible(ainput("You: "))).strip()
                except (Interrupted, EOFError):
                    print("\nGoodbye.")
                    break

                if not user_text:
                    continue
                command = user_text.lower()
                if command in {"/exit", "/quit"}:
                    print("Goodbye.")
                    break
                if command == "/help":
                    print(HELP_TEXT + "\n")
                    continue
                if command == "/tools":
                    self._print_tools()
                    continue
                if command == "/reset":
                    self.assistant.reset()
                    print("(conversation context cleared)\n")
                    continue
                if command == "/speak":
                    self.speak_replies = not self.speak_replies
                    print(f"(spoken replies {'on' if self.speak_replies else 'off'})\n")
                    if self.speak_replies:
                        asyncio.get_running_loop().run_in_executor(None, self.voice.preload_tts)
                    continue
                if command == "/google":
                    await self.handle_google_login()
                    continue
                if command == "/voice":
                    await self.handle_voice_turn()
                    continue
                if command == "/wake":
                    await self.handle_wake_word_mode()
                    continue
                if command == "/wakecheck":
                    await self.handle_wake_check()
                    continue

                try:
                    await interruptible(self._chat_and_reply(user_text))
                except Interrupted:
                    print(f"\n{DIM}(interrupted){RESET}\n")
        finally:
            await self.scheduler.stop()
            for task in list(self._background):
                task.cancel()
            if self.browser is not None:
                await self.browser.close()


async def run_app() -> None:
    _interrupts.attach(asyncio.get_running_loop())
    await App().run()


def main() -> None:
    configure_logging(settings.log_level)
    if sys.platform == "win32":
        os.system("")  # enables ANSI colour codes in the classic Windows console
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # emoji/non-ASCII replies
        except (AttributeError, ValueError):
            pass

    problems = settings.validate()
    if problems:
        for p in problems:
            print(f"Configuration error: {p}", file=sys.stderr)
        sys.exit(1)

    signal.signal(signal.SIGINT, _interrupts.on_signal)
    try:
        asyncio.run(run_app())
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
