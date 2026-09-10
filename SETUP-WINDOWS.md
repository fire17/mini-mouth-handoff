# mini-mouth for Windows — candidate

Extract the complete ZIP into a folder you will keep. It contains `Install.ps1`, `Start.cmd`, `mini-mouth`, and `XO`. Paths containing spaces are supported; there is no required home-directory layout.

In PowerShell, open the extracted folder and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -InstallSystemDependencies -RedisMode Memurai -Start
```

The installer reuses Python 3.11 or newer already installed. If Python is missing, it uses winget for Python 3.12; it also installs FFmpeg/ffplay and Memurai Developer when missing. Windows may show an installer approval dialog. It creates `mini-mouth\.venv`, installs both bundled Python packages there, verifies imports, and opens the mouth. System packages retain their own licenses; Memurai Developer is intended for development. If you already have Redis listening on `127.0.0.1:6379`, choose `-RedisMode Existing` instead. With Docker Desktop already running, choose `-RedisMode Docker`; the container binds to loopback only.

Use your own Codex login: the driver reads `%USERPROFILE%\.codex\auth.json` and checks `tokens.access_token` and its local expiry. A usable login skips the API-key prompt. An existing `OPENAI_API_KEY` environment variable takes precedence. If neither source exists, the launcher offers a hidden API-key prompt; Ctrl-C cancels so you can log in with Codex instead. A prompted key stays only in the launcher process environment, not in the command line, files, or persistent user environment. Expired or malformed Codex credentials stop with a sign-in message instead of silently changing accounts. Never copy anyone else's authentication file.

This selection follows the bundled `mini-mouth/src/rt_driver.py:load_token` implementation. Local credential validation does not prove realtime service access or subscription entitlement; a rejected service connection remains an error, reported in the log. A live call using the friend's account still needs to prove acceptance.

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

`ffmpeg -list_devices true -f dshow -i dummy` lists the device names. A missing or unreadable Caps Lock sensor keeps the microphone muted. The Windows Caps Lock implementation still needs verification on real hardware: Microsoft's GetKeyState documentation ties updates to the thread's keyboard-message queue, and this port polls it. Do not treat stub tests as hardware proof. If that gate does not track your key, explicitly disable it for this shell with `$env:MM_CAPS='0'` before starting; this keeps the microphone open between replies until Ctrl-C stops the app.

Optional local Whisper transcription is off when neither backend is installed; speech-to-speech still uses the remote realtime model. To add CPU local transcription, run `.\mini-mouth\.venv\Scripts\python.exe -m pip install faster-whisper`. This is optional and can download a model. It is not part of the normal install.

The log is `%USERPROFILE%\.livemind\mini-mouth-live.log`. If the driver exits, the supervisor stops its remaining children and prints the log path. Application-specific tools inherited from the source (other LiveMind programs, clipboard history, app control, relay) require software outside this bundle and may refuse requests. This candidate provides conversation, typed turns, speech, and the state watcher.

## Verification boundary

This candidate combines all six Windows work items and isolated integration fixes. Automated checks run on macOS: actual PowerShell parsing, portable Python fixtures, normal Python wheel contents/imports, process supervisor dryrun cleanup, and clean archive inspection. It has **not been run on a Windows machine or in a live OpenAI call**. First Windows execution must confirm winget/UAC, Memurai startup, FFmpeg device access, playback, Caps Lock changes, ESC, and Ctrl-C process cleanup.

Package identities were checked against Microsoft's repository: [Python.Python.3.12](https://github.com/microsoft/winget-pkgs/tree/master/manifests/p/Python/Python/3/12), [Gyan.FFmpeg](https://github.com/microsoft/winget-pkgs/tree/master/manifests/g/Gyan/FFmpeg), and [Memurai.MemuraiDeveloper](https://github.com/microsoft/winget-pkgs/tree/master/manifests/m/Memurai/MemuraiDeveloper). The Caps Lock limitation follows [Microsoft's GetKeyState contract](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getkeystate).
