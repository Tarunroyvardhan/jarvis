# Jarvis

A personal AI assistant, built incrementally. Phase 1: terminal chat.
Phase 2: real tools + permissions. Phase 3: persistent memory. Phase 4:
reminders. Phase 5: push-to-talk voice. Phase 6: wake word. Level 2/3
confirmation flows. Phase 7: Weather, News, Calendar, Email. **Phase 8**
adds computer control and file intelligence.

## Status

| Capability | Status |
|---|---|
| Terminal chat with Claude | ✅ implemented |
| Tool system + permission levels 0/1 | ✅ implemented |
| Permission levels 2/3 (confirmation flows) | ✅ implemented |
| Persistent memory (remember/recall/forget) | ✅ implemented |
| Reminders (one-time, daily, weekly) | ✅ implemented |
| Voice: push-to-talk STT + TTS | ✅ implemented |
| Wake word ("Hey Jarvis") | ✅ implemented |
| Delete notes/tasks (confirmation-gated) | ✅ implemented |
| Weather (Open-Meteo, no API key) | ✅ implemented |
| News (RSS feeds, no API key) | ✅ implemented |
| Calendar (Google, OAuth setup required) | ✅ implemented |
| Email (Gmail, OAuth setup required) | ✅ implemented |
| Computer control (open app/website/folder/terminal) | ✅ implemented |
| File intelligence (find/read/search/delete, sandboxed) | ✅ implemented |
| Dev tools (git status/diff, run tests) | ✅ implemented |

## Permission levels 2/3: confirmation required

Some actions now require you to explicitly confirm before they happen —
matching the original design: Jarvis prepares the action, tells you
exactly what it's about to do, and only proceeds if you say yes.

Currently gated this way: `delete_note`, `delete_task`, `create_calendar_event`,
`delete_calendar_event` (Level 2), and `send_email`, `delete_file` (Level 3 —
always confirm, no exceptions). When Claude calls one of these, you'll see
something like:

```
⚠️  Jarvis wants to: Delete note #3: "pick up dry cleaning"
Confirm? (yes/no):
```

Nothing executes until you type `yes`. This applies even during voice
sessions (`/voice`, `/wake`) — confirmation always happens via typed
input, deliberately, so a misheard "yes" can't approve something
destructive on its own.

If a tool needs confirmation and somehow no confirmation handler is wired
up (shouldn't happen in the CLI, but matters for future non-interactive
contexts), it fails safe — denied, not silently executed.

## Voice setup (optional — separate install step)

```bash
pip install -e ".[voice]"
```

Two hands-free-adjacent options once installed:

- **`/voice`** — one push-to-talk turn: Enter to start recording, speak,
  Enter to stop.
- **`/wake`** — continuous hands-free mode. Jarvis listens for "Hey
  Jarvis," then automatically records until you stop talking (no Enter
  needed), transcribes, replies, and speaks the answer — then goes back to
  listening. Press Ctrl+C to leave wake-word mode and return to typing.

The wake word model is openWakeWord's official pretrained `hey_jarvis`
model — no training, no account, no API key.

**Saying just "Jarvis" instead of "Hey Jarvis":** the model was
specifically trained on the phrase "hey jarvis," and its own documentation
says plain "jarvis" alone may still work, but with a higher chance of
being missed — it's not the phrase it learned. `WAKE_WORD_THRESHOLD` in
`.env` (default `0.4`, lower than openWakeWord's own default of `0.5`) is
tuned down specifically to improve those odds, trading a bit more
false-positive risk for catching "jarvis" alone more often. If it's still
unreliable for you even at this threshold, there isn't a config fix left
to try — the real next step would be training a small custom model on
"jarvis" alone, which is a legitimate but separate mini-project (recording
or synthesizing samples, running openWakeWord's own training pipeline),
not something achievable by just tuning a number.

## Making the voice sound less robotic

edge-tts's plain defaults read noticeably flat — full speed with no
warmth. Jarvis now defaults to `en-GB-RyanNeural` at a slightly slower
rate — a calm, measured British delivery in the spirit of a JARVIS-style
assistant voice. This is a deliberately similar-in-tone choice, not an
attempt to clone Paul Bettany's actual performance or any copyrighted
character voice — that's not something built into this project.

```
TTS_VOICE=en-GB-RyanNeural
TTS_RATE=-10%
TTS_PITCH=-2Hz
```

To hear other options before committing to one, run:
```bash
edge-tts --list-voices
```
Also worth trying: `en-GB-ThomasNeural`, `en-US-AndrewNeural`,
`en-US-BrianNeural`. `TTS_RATE` accepts any relative percentage (e.g.
`-15%` for noticeably slower, `+5%` for faster); `TTS_PITCH` accepts
relative Hz (e.g. `-5Hz` for deeper). There's a real ceiling on how human
this can sound — edge-tts is a solid free option, not a studio voice actor
— so if it's still not natural enough after tuning, the next real step up
is a paid engine like ElevenLabs, which would slot in as a new
`TextToSpeech` implementation without touching anything else.

**What I could and couldn't test myself:** same caveat as Phase 5 — I have
no microphone in my build environment, so the wake-word detection logic,
the silence-based auto-stop logic, and every failure path are covered by
automated tests, but whether "Hey Jarvis" actually triggers reliably in
your room, with your mic, is something only you can verify. If it's
over- or under-triggering, the fix is usually adjusting `threshold` in
`app/voice/wake_word.py` (default 0.5 — lower catches more, but risks more
false positives) — flag it and I can help tune it based on what you're
seeing.

**First run of `/wake` downloads model files.** openWakeWord doesn't ship
every model file in the pip package — the first time you use `/wake`, it
downloads ~50-100MB of shared model files (a one-time thing, cached after
that). This now prints progress so it doesn't look frozen; if you don't
see the "Downloading wake word model files..." / "Model files ready."
messages and it's just sitting there, that's a real hang worth reporting,
not normal download time.

## "Cinematic AI" voice effect

On top of the voice/rate/pitch settings, Jarvis can apply a light audio
post-processing pass modeled on techniques audio engineers use for a
cinematic AI tone: a subtle high-frequency shelf boost around 6-8 kHz for
crispness, plus a faint ~50 Hz amplitude modulation for a barely-there
metallic texture. This is generic signal processing (a filter + a
tremolo-style modulation) applied to Jarvis's own synthesized voice — not
an attempt to clone any actor's or character's actual voice.

```
TTS_CINEMATIC_EFFECT=true
TTS_EFFECT_BOOST_HZ=7000
TTS_EFFECT_BOOST_DB=1.5
TTS_EFFECT_MOD_HZ=50
TTS_EFFECT_MOD_DEPTH=0.05
```

**This needs ffmpeg installed separately** (not pip-installable — `pydub`
uses it to decode/re-encode audio). On Windows:

```powershell
winget install ffmpeg
```
or download a build from ffmpeg.org and add its `bin` folder to your PATH.
Restart your terminal after installing so PATH changes take effect.

If ffmpeg isn't available (or processing fails for any reason), Jarvis
falls back to playing the unprocessed voice rather than losing the spoken
reply — you'll see a logged warning, but the conversation isn't
interrupted. Set `TTS_CINEMATIC_EFFECT=false` to skip this entirely.

`TTS_EFFECT_BOOST_DB` and `TTS_EFFECT_MOD_DEPTH` are the two most worth
tuning: push the boost higher (e.g. `3.0`) for more crispness, or push the
modulation depth down (e.g. `0.02`) if the metallic texture feels too
obvious rather than subtle.

## Not yet built: true push-to-talk or hold-to-talk

Global hold-a-key-to-talk needs OS-level keyboard hooks that often want
elevated permissions, especially on Windows — so this MVP uses explicit
Enter-to-start / Enter-to-stop instead. It's still fully "push to talk" in
the sense your original spec meant (as opposed to always-listening), just
without a physical key you hold down.

## Important limitation: reminders only fire while Jarvis is running

This is a terminal app, not a background service. A reminder fires by
printing to your terminal — which only works if `python -m jarvis` is
actually open at the time. If it wasn't running when a reminder came due,
Jarvis reports it as a catch-up notice ("While you were away...") the next
time you launch it, rather than silently dropping it. True background
notifications (desktop popups, etc.) need an OS-level service and aren't
built yet — that'll come later, likely alongside the dashboard.

Reminders fire in real time while you're sitting at the prompt, including
while waiting for you to type — the input prompt runs in a background
thread specifically so it doesn't block the scheduler. One small cosmetic
side effect: if a reminder fires exactly while you're mid-typed at the
`You:` prompt, the notification text may print above your unfinished input
line rather than cleanly after it. Harmless, just occasionally messy-looking.

## Try it

- "Remind me in 20 minutes to check the oven."
- "Remind me every day at 9am to check my tasks." (recurring)
- "What reminders do I have?"
- "Cancel the reminder about the oven."

Claude computes the actual trigger time from your current system clock
(injected into its context each turn) and your phrasing — there's no fixed
parser for "in 20 minutes" vs "tomorrow at 8pm"; it's the same judgment-based
tool-calling as notes, tasks, and memory.

## Weather & News

No API keys, no accounts — both use free, open services:
- **Weather**: [Open-Meteo](https://open-meteo.com/) — geocodes a place name, fetches current conditions.
- **News**: RSS feeds via `feedparser`, configurable in `.env`. Defaults to BBC World + Reuters top news; add your own comma-separated feed URLs to `NEWS_FEED_URLS`.

```
WEATHER_TEMP_UNIT=fahrenheit
NEWS_FEED_URLS=https://feeds.bbci.co.uk/news/world/rss.xml,https://www.reutersagency.com/feed/?best-topics=top-news
```

Try: "What's the weather in Toronto?", "Give me the latest news", "Any news about AI today?"

## Calendar & Email (Google)

Unlike everything else so far, this needs a one-time setup step in your
own Google account — I can't do this part for you. Full click-by-click
steps are in the project's setup history; summary:

1. Create a Google Cloud project at [console.cloud.google.com](https://console.cloud.google.com/)
2. Enable the **Gmail API** and **Google Calendar API**
3. Set up the OAuth consent screen (External, add yourself as a test user)
4. Create OAuth credentials (Desktop app type), download as `credentials.json`
5. Put `credentials.json` in the project root (`D:\jarvis\`, next to `.env`)

```bash
pip install -e ".[google]"
```

**First use of a calendar/email tool opens a real browser window** asking
you to sign in and grant Jarvis access. After that first login, a token is
cached (`data/google_token.json`, git-ignored) so you won't be prompted
every time — only when the token expires or is revoked.

If `credentials.json` isn't present, Jarvis simply runs without
calendar/email tools — no crash, just a note in the logs. Nothing else is
affected.

**What I could and couldn't test myself:** I have no browser and no
Google account in my build environment, so the actual OAuth login flow
has never been exercised by me — only you can verify that part. What I
*did* fully test: all the calendar/email logic that runs after you're
authenticated (parsing events, formatting emails, error handling,
confirmation descriptions) using fake API responses that mimic Google's
real response shape, plus the specific failure paths (missing
`credentials.json`, missing dependencies) that don't require a real
account. If the OAuth step itself misbehaves, that's the one area where
I'm working from documentation rather than firsthand verification —
flag anything unexpected there and we'll debug it together.

Try, once set up: "What's on my calendar today?", "Do I have anything
tomorrow at 2pm?", "Search my email for invoices", "Draft an email to
[address] about [topic]", "Send that email" (will ask you to confirm,
showing the actual recipient/subject/body preview first).

## Computer control & file intelligence

Nothing here works until you configure at least one allowed directory —
by default, `ALLOWED_DIRECTORIES` is empty and every file/folder tool
simply has nothing it's allowed to touch. This is intentional: opt-in,
not opt-out.

```
ALLOWED_DIRECTORIES=D:\jarvis,D:\Users\tarun\Documents
ALLOWED_APPLICATIONS=notepad=notepad.exe,calculator=calc.exe,explorer=explorer.exe,vscode=code
PROJECT_TEST_COMMANDS=D:\jarvis=python -m pytest -q
```

- **Computer control**: `open_application` (only names in `ALLOWED_APPLICATIONS`
  — never an arbitrary path), `open_website`, `open_folder`, `launch_terminal`.
  All Level 1 (low-risk).
- **File intelligence**: `find_files`, `list_recent_files`, `read_file`
  (text, PDF, DOCX), `search_file_contents` — all Level 0, all restricted
  to `ALLOWED_DIRECTORIES`. `delete_file` is Level 3 — always confirms,
  shows you the exact path before doing anything.
- **Dev tools**: `git_status`, `git_diff` (read-only, Level 0), `run_tests`
  (Level 1 — runs only the exact command configured per project in
  `PROJECT_TEST_COMMANDS`, never an arbitrary command from the model).
  There is deliberately no push, pull, merge, or branch-delete capability
  anywhere in this codebase — not gated behind confirmation, just not
  built, per the original design's explicit prohibition.

Every file/folder operation is enforced by `PathGuard`
(`app/security/path_guard.py`): it resolves the real path (symlinks
followed, `..` collapsed) and verifies it lands inside a configured
allowed root before anything touches disk. A path outside those roots is
rejected the same way regardless of how it's phrased — there's no way to
trick it via `../../` traversal.

**Optional PDF/DOCX support:**
```bash
pip install -e ".[files]"
```
Without this, `read_file` still works for plain text files; PDF/DOCX
reads fail with a clear "not installed" message rather than crashing.

**A bug this feature caught before you ever saw it:** while smoke-testing
this phase, `open_application` crashed immediately — its own parameter is
named `name`, which collided with an internal parameter also called
`name` on the tool registry itself, a name collision that would have
broken on the very first real use. Fixed by making the registry's
internal arguments positional-only, which makes this entire category of
bug structurally impossible for any future tool, not just this one. Full
test suite (248 tests) re-verified clean afterward.

Try: "Open notepad", "What files changed in D:\jarvis?" (`git_status`),
"Find files with 'report' in the name", "Read the contents of
[path]", "Delete [path]" (will ask you to confirm the exact path first).

## Quickstart

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY

pip install -e ".[dev]"
python -m jarvis
```

Commands inside the chat loop:
- `/reset` — clear conversation context
- `/exit` or `/quit` — leave

## Running tests

```bash
python -m pytest -q
```

## Architecture (Phase 6)

```
Terminal (jarvis/__main__.py)
        │
        ├── Assistant  (text or transcribed-voice input, identical pipeline either way)
        │
        ├── ReminderScheduler  (background polling, unchanged from Phase 4)
        │
        ├── /voice — one push-to-talk turn:
        │       microphone.record_push_to_talk()  (Enter/Enter)
        │               → stt.WhisperSTT.transcribe()
        │               → Assistant.chat()
        │               → tts.EdgeTTSProvider.speak()
        │
        └── /wake — continuous hands-free loop:
                wake_word.WakeWordDetector.listen()  (blocks until "hey jarvis")
                        → microphone.record_until_silence()  (auto-stop on silence)
                        → stt.WhisperSTT.transcribe()
                        → Assistant.chat()
                        → tts.EdgeTTSProvider.speak()
                        → back to listening
```

`/voice` and `/wake` share the same transcribe → chat → speak tail
(`_transcribe_chat_and_speak` in `jarvis/__main__.py`) so the two entry
points can't silently drift into different behavior — the only thing that
differs between them is how the recording gets triggered and when it
stops.

`WakeWordDetector.listen()` and `microphone.record_until_silence()` are
each blocking calls run in a thread executor, same pattern as regular text
input — so the reminder scheduler keeps working even while Jarvis is
sitting in a continuous listening loop.

`ReminderRepository` owns the recurrence math: firing a daily/weekly
reminder rolls `trigger_at` forward to the next *future* occurrence (not
just +1 interval), so a long period offline doesn't cause a burst of stale
catch-up fires — see `test_mark_fired_recurring_skips_multiple_missed_occurrences`.

`MemoryRepository` is intentionally simple: keyword LIKE search plus
importance/recency ordering, no embeddings, no vector DB. That's a real
engineering decision, not a placeholder for one — at this data volume it's
sufficient, and the interface is shaped so vector search could slot in
behind `retrieve()` later without touching callers. `purge_expired()` still
runs once at startup, deleting anything with a passed `expires_at`.
Permanent memories (`expires_at IS NULL`) are never touched by purge; only
`forget()` removes them.

## Configuration

All configuration lives in environment variables — see `.env.example` for
the full list. Nothing is ever hard-coded, and `.env` is git-ignored.
