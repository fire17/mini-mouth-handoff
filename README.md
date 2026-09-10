# mini-mouth handoff

Clean bundles of **mini-mouth**, a realtime voice assistant with a Python driver, XO state on Redis, FFmpeg audio, and an OpenAI realtime connection. Use your own Codex login or OpenAI API key. These bundles contain no personal board data or credentials.

- **Windows**: [v0.1.3 release](https://github.com/fire17/mini-mouth-handoff/releases/tag/v0.1.3), with the r5 bundle and [setup instructions](SETUP-WINDOWS.md). It includes LiveMind-lite, corrected status reporting, and playback metadata updates. Launchers accept the driver's existing Codex login path, and setup reuses Python 3.11 or newer.
- **macOS**: the r3 archive is in the [original handoff release](https://github.com/fire17/mini-mouth-handoff/releases/tag/v0.1.0-2026-09-11), with [setup instructions](SETUP-MACOS.md).

Verify downloads against the release's `SHA256SUMS.txt`. Requirements: Python 3.11+, ffmpeg + ffplay, and local Redis on `127.0.0.1:6379`. The driver prefers `OPENAI_API_KEY` when set, otherwise reads the local Codex login. A login file alone does not prove realtime access: the endpoint must accept that account. Credentials stay on your machine.

Windows package installation and imports have been tested on a real Windows 11 machine with Python 3.11.9. The owner's Codex login connected to realtime, and the owner heard generated speech and the answer to a typed request. Acoustic input remains unproven on that PC, whose microphone returned a flat noise floor. See the setup guide for platform diagnostics and the Caps Lock limitation.

LiveMind-lite lets an existing coding agent monitor the local user's spoken and typed inputs. Read [MIND.md](livemind-lite/MIND.md); its wrappers default to a persistent monitor and have passed actual Windows PowerShell 5.1 and 7 tests, including UTF-8 delivery, log truncation, and error exits. It does not start a language-model agent by itself.

To download, verify, and install the Windows bundle from PowerShell:

```powershell
irm https://raw.githubusercontent.com/fire17/mini-mouth-handoff/main/init.ps1 | iex
```

This creates a versioned directory under `%LOCALAPPDATA%\mini-mouth`. It reuses Python, FFmpeg, and Redis already installed on your machine. To install missing system dependencies, pass `-InstallSystemDependencies`; select `-RedisMode Memurai` or `-RedisMode Docker` if needed. Audio starts only when you run the printed `Start.cmd` command or explicitly pass `-Start`.

Companion: [Agent Tunnel](https://github.com/fire17/p2p) connects agents on different computers.
