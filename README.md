# mini-mouth handoff

Clean bundles of **mini-mouth**, a realtime voice assistant with a Python driver, XO state on Redis, FFmpeg audio, and an OpenAI realtime connection. Use your own Codex login or OpenAI API key. These bundles contain no personal board data or credentials.

- **Windows**: [v0.1.1 release](https://github.com/fire17/mini-mouth-handoff/releases/tag/v0.1.1), with the corrected r3 bundle and [setup instructions](SETUP-WINDOWS.md). Launchers accept the driver's existing Codex login path, and setup reuses Python 3.11 or newer.
- **macOS** (r3, 2026-09-10): `mini-mouth-handoff-2026-09-10-r3.tar.gz` + [SETUP-MACOS.md](SETUP-MACOS.md).

Verify downloads against the release's `SHA256SUMS.txt`. Requirements: Python 3.11+, ffmpeg + ffplay, and local Redis on `127.0.0.1:6379`. The driver prefers `OPENAI_API_KEY` when set, otherwise reads the local Codex login. A login file alone does not prove realtime access: the endpoint must accept that account. Credentials stay on your machine.

Windows package installation and imports have been tested on a real Windows 11 machine with Python 3.11.9. A full voice call, microphone/playback behavior, and realtime access for that account remain to be verified. See the setup guide for platform diagnostics and the Caps Lock limitation.

Companion: [Agent Tunnel](https://github.com/fire17/p2p) connects agents on different computers.
