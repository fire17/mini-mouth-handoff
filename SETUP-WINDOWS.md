# mini-mouth for Windows — v0.1.3 candidate

Extract the complete ZIP into a folder you will keep. It contains `Install.ps1`, `Start.cmd`, `mini-mouth`, `XO`, and `livemind-lite`. Paths containing spaces are supported; there is no required home-directory layout.

In PowerShell, open the extracted folder and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -InstallSystemDependencies -RedisMode Memurai -Start
```

The installer reuses Python 3.11 or newer already installed. If Python is missing, it uses winget for Python 3.12; it also installs FFmpeg/ffplay and Memurai Developer when missing. Windows may show an installer approval dialog. It creates `mini-mouth\.venv`, installs both bundled Python packages there, verifies imports, and opens the mouth. System packages retain their own licenses; Memurai Developer is intended for development. If you already have Redis listening on `127.0.0.1:6379`, choose `-RedisMode Existing` instead. With Docker Desktop already running, choose `-RedisMode Docker`; the container binds to loopback only.

Use your own Codex login: the driver reads `%USERPROFILE%\.codex\auth.json` and checks `tokens.access_token` and its local expiry. A usable login skips the API-key prompt. An existing `OPENAI_API_KEY` environment variable takes precedence. If neither source exists, the launcher offers a hidden API-key prompt; Ctrl-C cancels so you can log in with Codex instead. A prompted key stays only in the launcher process environment, not in the command line, files, or persistent user environment. Expired or malformed Codex credentials stop with a sign-in message instead of silently changing accounts. Never copy anyone else's authentication file.

This selection follows the bundled `mini-mouth/src/rt_driver.py:load_token` implementation. Local credential validation does not prove realtime service access or subscription entitlement; a rejected service connection remains an error, reported in the log. The v0.1.2 Windows test accepted the tested owner's Codex login and completed a typed request with a spoken reply heard by that owner. Each installation still uses its own credentials.

Allow desktop apps to use your microphone in Windows Settings. Turn Caps Lock ON to unmute. Windows currently uses half-duplex: speak between replies. Global ESC requests that speech stop; Ctrl-C stops the whole application. For later runs, double-click `Start.cmd`.

In another terminal, from the extracted folder:

```powershell
.\mini-mouth\mm.cmd status
.\mini-mouth\mm.cmd say "Hello"
.\mini-mouth\mm.cmd text "What can you help me with?"
.\mini-mouth\mm.cmd selftest --platform --no-device
```

The diagnostic command above does not record or play sound. Before your first call, run `selftest --platform --interactive` to test a brief microphone sample, test tone, and an actual Caps Lock state change. Do that with the mouth stopped. The broader inherited `mm test` suite includes macOS-specific checks and fixtures omitted from this standalone bundle; use the platform check on Windows.

If the default microphone is wrong, set its exact FFmpeg DirectShow device name for this shell and start again:

```powershell
$env:MM_MIC_DEVICE = 'Microphone (your device name)'
.\Start.cmd
```

`ffmpeg -list_devices true -f dshow -i dummy` lists the device names. A missing or unreadable Caps Lock sensor keeps the microphone muted. Verify that Caps OFF/ON/OFF matches the driver's muted/live/muted log transitions on your machine: Microsoft's GetKeyState documentation ties updates to the thread's keyboard-message queue, and this port polls it. If the gate does not track your key, stop and report the mismatch. The tested PC's Realtek input produced noise without a useful response to speaking or clapping; working microphone hardware remains necessary. Typed requests and speech output are usable independently.

Optional local Whisper transcription is off when neither backend is installed; speech-to-speech still uses the remote realtime model. To add CPU local transcription, run `.\mini-mouth\.venv\Scripts\python.exe -m pip install faster-whisper`. This is optional and can download a model. It is not part of the normal install.

The log is `%USERPROFILE%\.livemind\mini-mouth-live.log`. If the driver exits, the supervisor stops its remaining children and prints the log path. Application-specific tools inherited from the source (other LiveMind programs, clipboard history, app control, relay) require software outside this bundle and may refuse requests. This candidate provides conversation, typed turns, speech, and the state watcher.

LiveMind-lite lets an existing coding agent act as this computer's MIND. Read `livemind-lite/MIND.md`; while the mouth runs, use `powershell -NoProfile -File .\livemind-lite\lm-ear.ps1 --selftest`, then keep `powershell -NoProfile -File .\livemind-lite\lm-ear.ps1 all` running through the agent's persistent monitor. PowerShell 7 (`pwsh`) also works. The ear forwards the local user's spoken and `mm text` input plus system events; it does not create or launch a language-model agent. Board and bus ears remain disabled. Selftest replays existing local log lines; an empty log is not successful input proof.

`mm status` reports `barge=unknown` when Windows cannot inspect another process's environment; it still checks the observed capture against the Windows policy. `%USERPROFILE%\.livemind\playback.json` identifies the current driver at startup and updates during playback and shutdown. Its timestamp is the last playback update, not an idle heartbeat or a microphone-sample timestamp. A metadata write failure is reported in the driver log; `mm status` remains the live state diagnostic.

The bundled XO backend uses inclusive successor IDs when replaying Redis Streams, including on Redis 5. Existing installations must reinstall the bundled XO package after upgrading this archive; editing its source directory alone does not update the virtual environment. This follows [Redis's documented iteration method for versions before 6.2](https://redis.io/docs/latest/commands/xrange/#iterating-with-earlier-versions-of-redis).

## Verification boundary

The preceding v0.1.2 bundle ran on Windows with Python 3.11.9, FFmpeg/ffplay, and Redis 5.0.14.1: its no-device platform test reported 8 OK, 2 SKIP, and 0 FAIL; the owner's Codex login connected; the owner heard `mm say` and a typed conversation reply. Acoustic microphone input remains unproven on that PC. v0.1.3 adds LiveMind-lite and isolated status/playback-metadata fixes. Local checks use actual PowerShell, synthetic Python fixtures, and clean archive inspection; these do not establish new Windows runtime behavior. Winget/Memurai installation, input hardware, gate changes, ESC, and application cleanup must be checked in the intended environment.

Package identities were checked against Microsoft's repository: [Python.Python.3.12](https://github.com/microsoft/winget-pkgs/tree/master/manifests/p/Python/Python/3/12), [Gyan.FFmpeg](https://github.com/microsoft/winget-pkgs/tree/master/manifests/g/Gyan/FFmpeg), and [Memurai.MemuraiDeveloper](https://github.com/microsoft/winget-pkgs/tree/master/manifests/m/Memurai/MemuraiDeveloper). The Caps Lock limitation follows [Microsoft's GetKeyState contract](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getkeystate).
