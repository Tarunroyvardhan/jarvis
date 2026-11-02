# Jarvis

A personal AI assistant for your Windows laptop, powered by Claude. It
researches the web, drives a real browser, runs commands on your machine
(with your approval), manages files, notes, tasks, reminders, calendar and
email, can see your screen, and can carry out scheduled automations. You
can type to it or talk to it ("Hey Jarvis").

## Quickstart

```powershell
copy .env.example .env      # then set ANTHROPIC_API_KEY (and ALLOWED_DIRECTORIES)
python -m venv venv
venv\Scripts\activate
pip install -e ".[dev,system,browser,files]"
python -m jarvis
```

Optional extras: `voice` (speech in/out + wake word), `google` (Calendar +
Gmail), or `all` for everything.

Inside the chat: `/help`, `/tools`, `/reset`, `/voice`, `/wake`, `/speak`,
`/exit`. **Ctrl+C** interrupts the current reply, declines a pending
confirmation, or leaves wake-word mode; at an empty prompt it exits.

## What it can do

| Area | Tools |
|---|---|
| Web research | `web_search`, `web_fetch` (run server-side by Anthropic) |
| Browser automation | `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_press_key`, `browser_scroll`, `browser_back`, `browser_screenshot`, `browser_close` |
| System access | `run_shell_command` (PowerShell, always confirmed), `get_system_info`, `list_processes`, `kill_process` (confirmed), `take_screenshot`, `get_clipboard`, `set_clipboard`, `media_control`, `lock_screen`, `send_notification` |
| Apps & windows | `open_application`, `open_website`, `open_folder`, `launch_terminal` |
| Files (allowed dirs) | `find_files`, `list_directory`, `list_recent_files`, `read_file` (text/PDF/DOCX), `search_file_contents`, `write_file`, `create_folder`, `copy_file`, `move_file` (confirmed), `delete_file` (confirmed) |
| Personal data | notes, tasks, long-term memory (`remember`/`recall`/`forget`), reminders, weather + forecast, news |
| Automation | `create_reminder` with a `task_prompt` runs that instruction when it fires (once, daily, weekly) |
| Google (optional) | `get_calendar_events` (with date ranges), `create_calendar_event`, `delete_calendar_event`, `search_email`, `read_email`, `draft_email`, `send_email` |
| Dev | `git_status`, `git_diff`, `run_tests` |

Things to try:

- "What's the latest on the Artemis program? Give me sources."
- "Go to github.com/trending and tell me the top three Python repos."
- "How much disk space do I have left, and what's eating my RAM?"
- "What's on my screen right now?"
- "Install 7-Zip." (you'll be shown the `winget` command to approve)
- "Every weekday at 8:30am, brief me on the weather in Toronto, my calendar and top tech news."
- "Find the PDF invoices in my Downloads and summarise the totals into invoices.md."
- "Turn the volume down a bit and pause the music."

## Safety model

Claude decides what to do; trusted code decides whether it may happen.
Every tool call goes through `ToolRegistry.execute()`, which applies the
permission level for **that specific call**:

| Level | Behaviour | Examples |
|---|---|---|
| 0 read-only | runs immediately | read files, system info, search |
| 1 low risk | runs immediately | open an allowlisted app, create a new file, browser clicks |
| 2 confirm | shows you exactly what will happen, waits for "yes" | overwrite a file, move a file, open an app that isn't allowlisted, kill a process, calendar changes |
| 3 always confirm | same, never relaxed | **every shell command**, send email, delete file |

- Confirmation is always typed, even in voice mode, so a misheard "yes"
  can't approve anything.
- No confirmation handler means denied, never "run anyway". Scheduled
  automations run unattended, so anything needing approval is refused there.
- File tools are confined to `ALLOWED_DIRECTORIES` by `PathGuard`, which
  resolves symlinks and `..` before checking. The shell is the deliberate,
  always-confirmed escape hatch for anything outside them.
- Content from web pages, emails and files is treated as data, not
  instructions.
- In the browser, Jarvis is told to stop and ask before the final click that
  buys, posts, sends or submits something. Clicks themselves are Level 1 so
  browsing stays usable, so keep an eye on the (visible) browser window.

Set `SHELL_ENABLED=false` to remove shell access entirely.

## How the brain works

`app/core/assistant.py` runs an agentic loop per request: call Claude, run
any requested tools, feed results back, repeat until there's an answer (up
to `MAX_TOOL_ITERATIONS`, default 25). `app/llm/claude.py` talks to the API:

- **Model**: `claude-opus-5-5` by default with adaptive thinking.
  `CLAUDE_EFFORT` (`low`…`max`, default `medium`) trades speed/cost for
  depth; use `high` if you mostly give it complex multi-step jobs.
- **Append-only history**: every content block Claude returns (thinking,
  tool calls, search results) is replayed verbatim. The current time and
  relevant memories ride inside each user message instead of the system
  prompt, so the prompt prefix stays identical and is served from cache.
- **Long conversations** are compacted server-side instead of trimmed
  locally. (Trimming used to split tool calls from their results and break
  requests.)
- **Refusal fallback**: on supported models, a safety-classifier decline is
  retried server-side on a fallback model in the same call.
- Tool output is capped at 40k characters so one huge file can't flood the
  context; screenshots go to Claude as images.

## Browser automation

```powershell
pip install -e ".[browser]"
```

Jarvis drives **Microsoft Edge** (already on Windows, so there's no
browser download) in a separate profile stored in `data/browser_profile`.
Log in to a site once in that window and it stays logged in. If Edge isn't
available it falls back to Playwright's Chromium (`python -m playwright
install chromium`). Set `BROWSER_HEADLESS=true` to hide the window.

## Reminders and automations

Reminders fire while Jarvis is running: they print, show a Windows toast,
and are caught up on the next launch if Jarvis was closed ("While you were
away..."). A reminder with a `task_prompt` is an **automation**. When it
fires, Jarvis carries out the instruction itself and posts the result to
the terminal and as a toast. Recurring reminders roll forward to the next
future occurrence rather than firing a backlog.

Times with a UTC offset are normalised to local time on save. (Mixing them
used to misorder reminders.)

## Voice

```powershell
pip install -e ".[voice]"
```

- `/voice`: one push-to-talk turn (Enter to stop recording).
- `/wake`: hands-free. Say "Hey Jarvis" **once**; Jarvis then stays awake
  and answers any sentence that mentions "Jarvis" anywhere ("Jarvis, what's
  the time?" / "What's the weather, Jarvis?"), ignoring everything else. The
  first sentence after waking needs no name, and saying just "Jarvis" makes
  it reply "Yes?" and take your next sentence. "Jarvis, stop listening" puts
  it back to waiting for "Hey Jarvis"; Ctrl+C returns to typing.
- `/speak`: read typed replies aloud too.
- `/wakecheck`: say "Hey Jarvis" a few times; Jarvis measures how strongly
  it hears you and suggests `WAKE_WORD_THRESHOLD` / `WAKE_WORD_GAIN` values
  for your microphone and room. A short beep confirms each wake-up.

The Whisper model loads once per session. Replies are cleaned of markdown
and URLs before being spoken.

**Voice engine.** By default Jarvis speaks with Microsoft's natural British
"Ryan" voice (`TTS_ENGINE=edge`). It speaks sentence by sentence, so it
starts about 0.5–1 s after the reply appears. `TTS_ENGINE=piper` uses an
offline voice that starts instantly but sounds more synthetic. Samples of
each option are in `data/voice_samples`. A subtle "film AI" treatment
(clarity boost plus faint room reflections) is applied by default; set
`TTS_CINEMATIC_EFFECT=false` for the plain voice. Tune `TTS_*` and
`WAKE_WORD_THRESHOLD` in `.env`.
The first `/wake` downloads the openWakeWord model files (~50–100 MB).

## Calendar & Email (Google)

1. Create a Google Cloud project, enable the **Gmail API** and **Google Calendar API**.
2. Configure the OAuth consent screen (External; add yourself as a test user).
3. Create OAuth credentials (Desktop app), download as `credentials.json` into the project root.
4. `pip install -e ".[google]"`

Type `/google` inside Jarvis to sign in; the token is cached in
`data/google_token.json` and refreshed automatically at startup. Startup
never opens a browser itself: if the token is missing or expired, Jarvis
starts without Calendar/Email and tells you to run `/google`.

**"Access blocked: jarvis has not completed the Google verification
process" (Error 403: access_denied)** means the Google account you signed
in with isn't on the app's test-user list. In Google Cloud Console, open
*Google Auth Platform → Audience* (older UI: *OAuth consent screen*), add
that address under **Test users**, then run `/google` again and pick that
account. Apps in "Testing" mode also get tokens that expire after 7 days.
If you're asked to sign in weekly, click **Publish app** on the same page
(Google will warn that it's unverified; that's fine for personal use).

## Configuration

Everything lives in `.env`; see `.env.example` for every option with
comments. `.env` and `data/` are git-ignored.

## Tests

```powershell
python -m pytest -q
```

The suite runs offline and ignores your real `.env`.

## Known limitations

- Reminders and automations only run while `python -m jarvis` is open.
  Running it at logon (Task Scheduler) is the simple fix; a true background
  service isn't built yet.
- Clipboard, media keys, lock screen and toasts are Windows-only.
- Memory search is keyword-based (no embeddings). Fine at personal scale.
