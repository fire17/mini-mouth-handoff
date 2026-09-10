# mini-mouth handoff

Clean, self-contained bundles of **mini-mouth** (a small realtime voice assistant: Python driver + XO state on Redis + ffmpeg/ffplay audio + the OpenAI realtime API) for running on your own machine with your own OpenAI key. No board data, no personal files, no credentials are in these bundles.

- **Windows** (candidate, 2026-09-11): `mini-mouth-windows-candidate-2026-09-11.zip` + [SETUP-WINDOWS.md](SETUP-WINDOWS.md). Real-Windows validation is in progress; report what breaks.
- **macOS** (r3, 2026-09-10): `mini-mouth-handoff-2026-09-10-r3.tar.gz` + [SETUP-MACOS.md](SETUP-MACOS.md).

Verify downloads against `SHA256SUMS.txt`. Requirements: Python 3.11+, ffmpeg + ffplay, a local Redis on 127.0.0.1:6379, your own `OPENAI_API_KEY`. Companion: [fire17/p2p](https://github.com/fire17/p2p) (Agent Tunnel, v0.3.4).
