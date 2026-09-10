# mini-mouth — setup on a fresh Mac (≈10 minutes)

A small, fast, full-duplex voice assistant. One process owns an OpenAI **realtime**
websocket; all state lives in an **XO** event-sourced graph over loopback Redis, so a TUI,
a CLI and the driver are peers over one state.

This bundle is **standalone**: your own machine, your own OpenAI credentials, no connection
to anyone else's system.

Bundle: `mini-mouth-handoff-2026-09-10-r3.tar.gz` (file list + sha256 in `MANIFEST-r3.txt`).
Tested-on note: the source runs today on macOS 14 (Darwin 23), Apple Silicon, Python 3.12.

---

## 0. What you need

| Thing | Why | Required? |
|---|---|---|
| macOS | mic capture is `avfoundation`; the caps sensor is CoreGraphics | **yes** |
| Python ≥ 3.11 | driver + TUI | **yes** |
| `redis-server` | the XO graph substrate (loopback only) | **yes** |
| `ffmpeg` + `ffplay` | mic capture in, audio playback out | **yes** |
| `swiftc` (Xcode CLT) | builds the caps-lock sensor `src/mm-caps` | **yes** (or set `MM_CAPS=0`) |
| An OpenAI key with **realtime** access | the mouth itself | **yes** |
| `mlx-whisper` | word-level karaoke + local re-read of garbled speech | optional |
| WezTerm | inline images + pane tricks in the TUI | optional |

## 1. System deps

```bash
xcode-select --install                 # gives you swiftc (skip if already installed)
brew install redis ffmpeg python@3.12
```

## 2. Unpack

```bash
mkdir -p ~/Creations && cd ~/Creations
tar -xzf ~/Downloads/mini-mouth-handoff-2026-09-10-r3.tar.gz   # → ~/Creations/mini-mouth and ~/Creations/XO
```

**Put them at `~/Creations/mini-mouth` and `~/Creations/XO`** if you want zero edits:
`app/run.sh` hard-codes `ROOT="$HOME/Creations/mini-mouth"`, and `mm`, `live.py`, `tui.py`
and `watch.py` each *also* add `~/Creations/XO/src` to `sys.path` as a fallback. Anywhere
else works once step 3 is done — then edit `ROOT` in `app/run.sh` if you use the app.

## 3. Python environment — ONE canonical step

```bash
cd ~/Creations
python3 -m venv .venv-mm
source .venv-mm/bin/activate
pip install -e ./XO -e ./mini-mouth 'websockets==13.1' certifi
```

That editable pair is the whole install. **Verified in a clean venv:** setuptools writes a
`.pth` pointing at `mini-mouth/src`, so from **any** working directory

```bash
cd /tmp && python -c "import xo, xomouth, rt_driver, app_resolver, audio_io; print('ok')"
```

imports cleanly — no `PYTHONPATH`, no cwd rules.

**Pin `websockets==13.1`.** The driver calls `websockets.connect(..., extra_headers=...)`.
websockets ≥ 14 renamed that argument; on 17.1 the call fails with
`TypeError: BaseEventLoop.create_connection() got an unexpected keyword argument 'extra_headers'`
(measured, not guessed). Either pin 13.1 or change both `extra_headers=` call sites in
`src/rt_driver.py` to `additional_headers=`.

## 4. Credentials — your own key

**Option A (recommended, already wired in this bundle): `OPENAI_API_KEY`.**

```bash
export OPENAI_API_KEY=sk-...        # the account needs realtime access
```

`src/rt_driver.py::load_token()` in this bundle reads the environment first. No code edit is
needed — the 6-line change the previous bundle asked you to make is **applied here**. All
three branches were run in a clean venv: env key returned as-is; a valid `~/.codex/auth.json`
still accepted; neither present prints one line and exits —

```
no credentials: set OPENAI_API_KEY=sk-... (realtime access required),
or log in with the Codex CLI so /Users/you/.codex/auth.json exists
```

— no traceback.

**Option B — ChatGPT OAuth (what the author uses).** Install OpenAI's Codex CLI, log in with
your ChatGPT account; it writes `~/.codex/auth.json`, and `load_token()` takes
`tokens.access_token` (a JWT, expiry-checked) when `OPENAI_API_KEY` is unset.

**Models used** (defaults in `src/xomouth.py`, changeable at runtime with `mm spec set`):

- speech ⇄ speech: `gpt-realtime` at `wss://api.openai.com/v1/realtime?model=`
- input transcription: `gpt-4o-mini-transcribe`
- voice: `cedar`

## 5. Build the caps-lock sensor (10 seconds)

The mic is gated by Caps Lock — caps **on** = the mouth hears you, caps **off** = muted. The
gate **fails closed**: if the sensor binary is missing, *the mic is muted forever and nothing
tells you why*. This is the single most common way a fresh install looks broken.

```bash
cd ~/Creations/mini-mouth
swiftc -O -o src/mm-caps src/mm-caps.swift
./src/mm-caps          # → caps=on combined=true hid=true ts=...
```

Prefer no caps gating at all? Run with `MM_CAPS=0` and the mic stays open. (Then the only
mute is `mm`/TUI.)

`src/mm-esc` (global ESC = stop the current spoken line) ships as a prebuilt **arm64** binary.
On Intel, or if macOS refuses it, rebuild: `swiftc -O -o src/mm-esc src/mm-esc.swift`. It needs
an Accessibility grant; without one it exits 78, says so, and everything else keeps working.

## 6. First run — `MM_BARGE=0` on a fresh Mac

```bash
mkdir -p ~/.livemind/mini-mouth          # runtime dir: log, pidfile, control files
redis-server --daemonize yes --bind 127.0.0.1 --save '' --appendonly no
cd ~/Creations/mini-mouth
MM_BARGE=0 ~/Creations/.venv-mm/bin/python live.py
```

- macOS will ask for **Microphone** permission for your terminal — grant it.
- Press **Caps Lock ON** and talk. It answers by itself (server VAD).
- **Ctrl-C** ends it.

**`MM_BARGE=0` is not optional on a fresh machine.** `MM_BARGE=1` makes the driver expect an
external echo-cancelled mic helper (`pipeA`) that is **not in this bundle** (see §8); without
it the mic capture never starts and the watchdog restarts it in a loop. Set it in three
places, all explicit:

1. the command line above (`MM_BARGE=0 … python live.py`);
2. `app/run.sh` line ~23 — `export MM_BARGE="${MM_BARGE:-1}"` → change the default to `0`
   (or always launch the app with `MM_BARGE=0` in the environment);
3. `mm restart` inherits your environment, so `export MM_BARGE=0` in the shell profile you
   use for it.

Second terminal, same venv, while it runs:

```bash
cd ~/Creations/mini-mouth
./mm status            # socket · playing · mic · pids
./mm say "hello"       # speak a line verbatim
./mm text "what time is it"     # a typed turn, as if you had said it
./mm context "quiet fact the mouth absorbs and never says"
./mm log 40            # tail the driver log (~/.livemind/mini-mouth-live.log)
python3 watch.py       # watch every internal of the live graph
```

The richer terminal UI (transcript, karaoke, meters): `python3 tui.py` (needs a real TTY).

## 7. The packaged app (optional) — the two edits it needs

`app/run.sh` is the one-window launcher: redis (only if absent) → driver → ESC watcher → TUI
in the foreground, and it kills all of it on exit. `app/build.sh` wraps that into
`mini-mouth.app`. Edit at the top of `app/run.sh`:

- `ROOT="$HOME/Creations/mini-mouth"` → wherever you unpacked it;
- `PY="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"` → your venv's python
  (`~/Creations/.venv-mm/bin/python`), otherwise it falls back to `command -v python3` and
  will not see the packages you installed in §3;
- `export MM_BARGE="${MM_BARGE:-1}"` → `0` (see §6).

**Cleanup scope (changed in this bundle).** The original exit sweep killed *every* orphan
`ffplay` on the machine, including players belonging to other people's programs. Here it is
scoped to this app's own player shape (`-f s16le -ar 24000 -ch_layout mono`, ppid 1), which is
what `src/audio_io.py::player_argv()` builds. Nothing else is touched.

## 8. Barge-in (interrupting the mouth mid-sentence) — NOT included

Full-duplex barge on speakers needs an echo-cancelled mic. The driver gets that from an
external helper — a Swift `aecmic` (macOS VoiceProcessingIO) behind a Silero VAD gate, run as
`pipeA` — which lives in the author's other project and is **not in this bundle**.

- `MM_BARGE=1` → the driver expects `pipeA` at `~/Creations/LiveMind/barge/pipeA`
  (override with `MM_PIPEA=/path/to/pipeA`). Missing → capture fails to start, in a loop.
- `MM_BARGE=0` (**use this**) → `src/audio_io.py` falls back to a plain resident
  `ffmpeg -f avfoundation -i :default` capture and the driver runs **half-duplex**: mic frames
  are dropped while the mouth is playing, so it cannot hear itself. You talk between replies.

**Headphones make half-duplex feel almost as good** — no speaker leak to cancel.

## 9. Everyday commands

| Want | Command |
|---|---|
| is it up? | `./mm status` |
| speak a line | `./mm say "…"` |
| a typed turn | `./mm text "…"` |
| silent preload | `./mm context "…"` |
| tail the log | `./mm log 50` |
| conversation history | `./mm history 20` |
| change a live setting | `./mm spec set model gpt-realtime` · `./mm spec` |
| self-test (touches no call) | `./mm test` |
| stop | Ctrl-C in the `live.py` window |

---

## What is NOT included, and what is inert

**Removed from the bundle** (personal material, and anything that only makes sense inside the
author's own system):

- `docs/` in its entirety — including the author's personal task-board records.
- `bin/asks`, `bin/asks-dispatch` — the board CLI and its dispatcher; both hard-depend on the
  author's other trees.
- `lab/`, `probes/`, `probe/`, `patches/`, `.deify/`, `__pycache__`, `.git` — experiments,
  probe harnesses, review artefacts, build litter, history.
- `src/mm-caps` (the compiled sensor) — build it yourself in §5; only the `.swift` source ships.
- `XO/.github/` — CI workflows and release notes.
- `mini-mouth/CONTINUE.md`, `XO/ECOSYSTEM.md`, `XO/origins.md` — session pointers, machine
  paths and a verbatim personal prompt archive. Links to them were removed from the shipped
  READMEs and from `XO/pyproject.toml`'s sdist list.

**Example data is placeholder data.** The app-resolver tests and comments used the author's
real project names and real first names; they ship here as `ExampleApp` /
`ExampleApp_ULTIMATE` / `ExampleAppBoard` / `Sidenote` and invented person names. Behaviour is
unchanged — the resolver selftest leg was extracted from the bundle copy and run green.

**Present but inert without the author's other projects** — each fails *honestly* (a spoken
refusal or a log line); none stops the mouth from working:

| Surface | Wants | Without it |
|---|---|---|
| `quick` tool (open app/url, clipboard, screenshot, emoji, volume…) | an `lm-quick` CLI | falls back to a hard-coded action list, then every call fails; the model says so |
| `dictate` tool (type at your caret) | a `ccvoice-type` binary | refuses with its exit-code reason |
| `relay` tool ("tell the Mind") | an `lm-connect` CLI | refuses |
| `load_context` tool | `~/.livemind/context-brief.txt` | loads nothing |
| `open_app` fallback chain, `atlas`/`accounts` tools | the author's project/account trees | inert |
| `mm asks …` and the board views | the author's board CLI at `~/Creations/LiveMind/memory/asks` + the excluded `docs/` records | inert; the verb raises `FileNotFoundError` on the missing CLI |
| `mm probe speaking-hold` | `probes/speaking_hold.py` (excluded) | that one subcommand errors |
| `src/tick_queue.py` drain | the author's board writer | appends to a queue file nobody drains |
| `src/keeper.py` (`mm keeper`) | `lm-connect` for its alerts | off by default already (`MM_KEEPER=1` arms it) |
| vision row in `tui.py` | a `vision_view` module **not in the source tree at all** | only reached when vision is on; leave it off |
| WezTerm inline images / pane control in `tui.py` | WezTerm | the TUI detects the missing socket and turns the feature off |
| word-level karaoke, garbled-speech re-read | `pip install mlx-whisper` (Apple Silicon) | log says `whisper worker FAILED TO WARM`; everything else runs |

**`mm test` is not all-green in this bundle.** Three selftest legs read fixtures under `docs/`,
which is excluded: the garble leg (`docs/asks-noask.jsonl` — observed: `FileNotFoundError`),
and legs that read `docs/TUI-ROWS.json` and `docs/TICK-MAP.json` (file references read from the
source; their failure was not run here). Other legs spawn Redis clients and processes, so the
whole battery was deliberately not run on the build machine.

**Also inherited from the original system, harmless:** the runtime directory is `~/.livemind/`
(log, pidfile, recordings, control files) — just a directory name. The persona in `live.py`
mentions "The Mind", a deep agent that watched the author's calls. There is none here; the
sentence is only prompt text and can be deleted.

**Simplest way to drop the dead tools entirely:** in `live.py`, shorten the `spec(rt.spec,
"tools", …)` JSON list and trim the tool paragraphs out of the `instructions` string just below
it. The mouth then never tries to call them.

---

## Verification status (honest)

Verified while building **r2**:

- every file copied from the **current working tree** (tracked files only), then the r2 edits
  applied to the bundle copy — the source trees were never modified;
- the bundle contains **no** `__pycache__`/`.pyc`, no `/Users/<name>` path, and none of the
  removed personal files (a build-time audit fails the build otherwise);
- every shipped `.py` file, plus `mm`, compiles; `bash -n` passes on `app/run.sh`,
  `app/build.sh`;
- in a clean venv, `pip install -e ./XO -e ./mini-mouth` then `import xo, xomouth, rt_driver,
  app_resolver, audio_io` from `/tmp` — works;
- `load_token()`: env key → returned; no key + no `auth.json` → the one-line message above;
  no key + a valid `auth.json` → the JWT path still works;
- the app-resolver selftest leg, extracted from the bundle's `mm` and run standalone with the
  renamed fixtures: **ok**; the renamed people-name fixtures still classify as not-garble;
- the scoped `ffplay` pattern matches the app's own player argv and skips a plain
  `ffplay song.mp3`.

**Not verified:** no live call was ever started from this bundle — the build ran on a machine
whose microphone, speaker and realtime session belong to a production system that must not be
disturbed. §6–§9 are read from the code, not observed end to end. Expect the first run to need
the microphone permission prompt and, possibly, one round of the caps-gate footgun in §5.

> r3 (MIND, 23:43): repacked with numeric owner 0 (tar headers no longer carry a username), mini-mouth/VISION.md removed (his verbatim founding message), 155 files, sha256 06fae1f4…. macOS only until the Windows port lane lands.
