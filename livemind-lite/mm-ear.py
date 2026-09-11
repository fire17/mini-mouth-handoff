#!/usr/bin/env python3
"""lm-ear — the MIND's ears on the live mini-mouth, ONE INDEPENDENT MONITOR PER THING.

His orders (typed into the MIND session, 2026-09-08):
  canon 373 11:58:15 — "starting the ear to mini-mouth is a simple command as can be … it should just work"
  canon 375 12:05:18 — "lm-ear also adds another independent monitor for the asks-board"
  canon 376/377 12:08:58 — "the monitor listens to too many things - i want one monitor for every thing
    independently - calling lm-ear should make it so - and we want it to be with a config file so that we
    can make changes when we want - or add params to use only certain ones (all by default unless
    requested otherwise)"
  canon 378 12:18:58 — "lets unify threads&board (they come from the same place), unify driver&errors -
    they are compatible to one monitor (system events) , unify voice&typed (they come from the same
    place, indicated which is which when you get it [Spoken/Typed] but in the same monitor"
  canon 379 12:30:03 — rename `him` → `user-inputs`; Cmd+Enter in the MagicUI text box arrives here
    "indicated as [from MagicUI] … like i spoke it … mechanistically … auto via code"
  bus ear (MIND, 2026-09-08 13:1x, after SPEAKSIM's dispatch line sat unread on `limbs`): the ORGAN MONITOR LAW
    ear — body + limbs + own channel, ONE LINE PER MESSAGE (canon 234: head + `lm-read <id>` pull, no chunks),
    and it writes the presence heartbeat `$BUS/.readers/<me>.hb` so `lm-connect who` shows the organ LIVE.
  the `mirror` ear (2026-09-11, his cross-machine board ask): OFF on the Mac (the single WRITER) — a REMOTE
    machine turns it on and hears the board PROJECTION the Mac pushes over the Agent Tunnel.
  So FOUR ears, each one monitor: `user-inputs` (his words — [Spoken] from the live log, [Typed ⌨] and
  [from MagicUI] typed turns, [Typed] from the board feed), `system` (driver run headers + pid changes + ⚠ errors), `board` (asks events targeting
  me + his thread comments on my asks). An ear may read several files; it is one process, one stream.

    lm-ear                      # the PLAN: one Monitor line per enabled ear — arm each as its own monitor
    lm-ear --json               # the same plan as JSON (for a harness that arms them by code)
    lm-ear user-inputs          # run ONE ear (its own process = its own monitor stream)
    lm-ear all [--only a,b]     # every enabled ear in one process, lines tagged [ear] (no-Monitor harness)
    lm-ear list                 # ears from the config with enabled state + params
    lm-ear config [init]        # show the config (init = write the defaults)
    lm-ear config enable|disable <ear>   # flip one ear in the config file and print the re-arm line
    lm-ear --mirror-selftest    # EXECUTE the board-mirror rule on fixtures (own temp state); rc 0/1
    lm-ear --selftest [ear]     # replay each ear's filter over its LAST REAL LINES; rc 0 if every ear fires
    lm-ear ack <ASK-ID> [note]  # the MIND's `ack` event on the board
    lm-ear --profile eva …      # PROFILES (his order to EVA 2026-09-08 sha:9f781406, board A202): the same ears
                                # for another organ — every line, selftest, ARMED banner and Monitor description
                                # carries the profile tag ([eva]); `me` becomes the profile's board name; any ear
                                # param may be overridden per profile. LM_EAR_PROFILE=eva is the env form.
    lm-ear profiles             # list the profiles in the config
    lm-ear coverage             # his canon 394: every profile × ear — last DELIVERED line vs the source's newest; rc = listeners BEHIND

WHY ONE PROCESS PER EAR: the harness Monitor tool gives one notification stream per command, and a
noisy stream is auto-stopped — so a combined ear can go deaf on everything because one thing was loud.
The harness cannot be told to arm monitors from inside a process, so `lm-ear` PLANS (one line per ear)
and the agent arms each line; nothing else is guessed. RE-ARM PROOF: every ear prints `selftest:`
replays over its last real lines and `EAR ARMED <ear>` before the first live line — never a synthetic
line written into his log. Config: ~/.livemind/ears.json (LM_EARS overrides); missing = defaults,
written once so the file exists to edit.

Born of two misses in one hour: a shell-pipeline ear deaf by construction (BSD `sed` has no `-u`;
`tr`/`cut` block-buffer) and an assignment + thread comment + priority raise that never reached the
MIND because no ear watched the board.
"""
import subprocess, re, os, sys, time, json, glob

CONFIG = os.environ.get("LM_EARS") or os.path.expanduser("~/.livemind/ears.json")
SEEN_DIR = os.path.expanduser(os.environ.get("LM_EAR_SEEN_DIR") or "~/.livemind/ears/seen")
MIRROR_PATH = os.path.join(os.path.dirname(CONFIG), "board-mirror.json")   # the last board mirror this machine received (the mirror ear diffs against it)
H = os.path.expanduser
DEFAULTS = {
    "version": 3, "me": "mind",
    "ears": {
        "user-inputs": {"enabled": True, "desc": "user inputs — [Spoken] 🗣 lines of the live log, [Typed ⌨]/[from MagicUI] 🗣⌨ typed turns, [Typed] rows of docs/asks-typed.jsonl",
                   "log": H("~/.livemind/mini-mouth-live.log"), "typed": None, "om": None, "cut": 700},
        "system": {"enabled": True, "desc": "system events — driver run headers + pidfile changes + ⚠ error lines",
                   "log": H("~/.livemind/mini-mouth-live.log"), "pidfile": H("~/.livemind/mini-mouth.pid"), "cut": 700},
        "board":  {"enabled": False, "desc": "the asks board — disabled in LiveMind-lite; belongs to the full LiveMind body",
                   "docs": H("~/Creations/mini-mouth/docs"), "cut": 700},
        "mirror": {"enabled": False, "desc": "the asks-board MIRROR pushed over the Agent Tunnel (remote machines only) — [Board mirror] <id> <status> <title> on change",
                   "inbox": None, "cut": 400},   # OFF on the Mac (the writer); a remote MIND-lite turns it on with `lm-ear config enable mirror`
        "bus":    {"enabled": False, "desc": "the organ bus — disabled in LiveMind-lite; belongs to the full LiveMind body",
                   "bus": H("~/.livemind/bus"), "channels": ["body", "limbs"], "cut": 400},   # own channel = the profile's `me` unless the profile overrides
    },
    # A profile = {me, tag, ears-overrides}. The mind is the untagged default; every other organ gets a tag on
    # EVERYTHING it hears so two organs' monitors are never confused ("with a [eva] indicator for everything").
    "profiles": {
        "mind": {"me": "mind", "tag": "", "ears": {"bus": {"own": "livemind-bigpicture"}}},   # the MIND's bus name differs from its board name
        "eva":  {"me": "eva-memory", "tag": "[eva] ", "ears": {}},
    },
}

def out(s):
    try: sys.stdout.write(s + "\n"); sys.stdout.flush()
    except BrokenPipeError: raise SystemExit(0)

def load_config():
    try:
        with open(CONFIG) as f: cfg = json.load(f)
    except FileNotFoundError:
        cfg = json.loads(json.dumps(DEFAULTS))
        try:
            os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
            with open(CONFIG, "w") as f: json.dump(cfg, f, indent=2, ensure_ascii=False)
        except OSError: pass
        return cfg
    except Exception as e:
        out(f"CONFIG UNREADABLE ({CONFIG}: {e!r}) — using defaults"); return json.loads(json.dumps(DEFAULTS))
    if int(cfg.get("version", 1)) < DEFAULTS["version"]:   # v1 = six ears; canon 378 unified them into three
        try:
            os.replace(CONFIG, CONFIG + ".v1.bak")
            with open(CONFIG, "w") as f: json.dump(DEFAULTS, f, indent=2, ensure_ascii=False)
            out(f"CONFIG upgraded to v{DEFAULTS['version']} (three ears); the old file is {CONFIG}.v1.bak")
        except OSError: pass
        return json.loads(json.dumps(DEFAULTS))
    # missing ears/params fall back to defaults so an old config never silently disables a new ear
    merged = json.loads(json.dumps(DEFAULTS)); merged["me"] = cfg.get("me", merged["me"])
    for name, e in (cfg.get("ears") or {}).items():
        merged["ears"].setdefault(name, {}).update(e or {})
    for name, pr in (cfg.get("profiles") or {}).items():
        dst = merged["profiles"].setdefault(name, {}); pr = pr or {}
        for k, v in pr.items():
            if k == "ears":   # per-ear deep merge: an empty on-disk `ears: {}` must not erase a default override (EVA's own-channel bug, 14:1x)
                for ear, over in (v or {}).items(): dst.setdefault("ears", {}).setdefault(ear, {}).update(over or {})
            else: dst[k] = v
    return merged

def apply_profile(cfg, name):
    """Return (cfg', me, tag) for a profile: `me` and per-ear overrides applied, tag for every output line."""
    pr = (cfg.get("profiles") or {}).get(name)
    if pr is None:
        out(f"unknown profile '{name}' — profiles: {', '.join(cfg.get('profiles') or {})}"); return None
    c = json.loads(json.dumps(cfg)); c["me"] = pr.get("me", c.get("me", "mind"))
    for ear, over in (pr.get("ears") or {}).items():
        c["ears"].setdefault(ear, {}).update(over or {})
    c["profile"] = name
    return c, c["me"], pr.get("tag", "" if name == "mind" else f"[{name}] ")

# ---------------------------------------------------------------- shared
def _tail_lines(path, nbytes=400_000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - nbytes))
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError: return []

POS = {}   # path -> byte offset this process has CONSUMED (stamped into every receipt so `coverage` compares position, not text)

def _follow(path, poll=0.2, start=None):
    """Yield complete appended UTF-8 lines; retain partial writes until newline."""
    f = ino = None; pending = b""; next_start = start
    while True:
        try:
            if f is None:
                f = open(path, "rb")
                f.seek(0, 2)
                if next_start is not None: f.seek(min(next_start, f.tell()))
                next_start = 0
                ino = os.fstat(f.fileno()).st_ino; POS[path] = f.tell()
            line = f.readline()
            if line:
                pending += line
                if pending.endswith(b"\n"):
                    POS[path] = f.tell()
                    yield pending.decode("utf-8", "replace").rstrip("\r\n")
                    pending = b""
                continue
            time.sleep(poll)
            st = os.stat(path)
            if st.st_ino != ino or st.st_size < f.tell():
                f.close(); f = None; pending = b""; out("EAR: file rotated — reopened")
        except FileNotFoundError:
            if f is not None: f.close()
            f = None; pending = b""; next_start = 0; time.sleep(1.0)

HIM = ("him", "user")   # his A210: the writer says `user` from 13:3x on; old ledger rows keep `him` forever (EVA: never rewrite history) — match both

def _owner_map(docs):
    m = {}
    for fpath in sorted(glob.glob(os.path.join(docs, "ASKS-*.json"))):
        try:
            d = json.load(open(fpath)); rows = d if isinstance(d, list) else (d.get("asks") or d.get("items") or [])
            for r in rows:
                if isinstance(r, dict) and r.get("id"):
                    m[r["id"]] = (str(r.get("owner", "")), str(r.get("assigned_to", "")), str(r.get("title", ""))[:80])
        except Exception: pass
    return m

def _sub_counts(docs, aid):
    for fpath in sorted(glob.glob(os.path.join(docs, "ASKS-*.json"))):
        try:
            d = json.load(open(fpath)); rows = d if isinstance(d, list) else (d.get("asks") or d.get("items") or [])
            for r in rows:
                if isinstance(r, dict) and r.get("id") == aid:
                    subs = [x for x in (r.get("subtasks") or []) if isinstance(x, dict)]
                    return sum(1 for x in subs if x.get("done")), len(subs)
        except Exception: pass
    return 0, 0

def stale_via_eva(docs):
    """EVA's `asks stale` (2026-09-08 15:3x) is the instrument of record — it names CONTRADICTIONS between a record and
    its subtasks (done with open subs, open with all ticked, work log with nothing ticked). The ear prints its ids and
    falls back to its own reading only when the verb is missing, so one instrument is never two."""
    try:
        r = subprocess.run([sys.executable, os.path.expanduser("~/Creations/LiveMind/memory/asks"), "stale"], capture_output=True, text=True, timeout=20)
        if r.returncode in (0, 1) and "unknown verb" not in (r.stdout + r.stderr):
            ids = [l.split()[0] for l in r.stdout.splitlines() if l[:1] == "A" and len(l.split()) > 2]
            return ids, "asks stale"
    except Exception: pass
    return None, None

def stale_subitems(docs):
    """Records whose subitems are stale on the record's own evidence: status done with open subitems, or a work log
    line that says DONE while subitems sit open. His A227 thread 15:2x: "I DONT WANT SUB-ASKS TO BE STALE"."""
    out_ = []
    for fpath in sorted(glob.glob(os.path.join(docs, "ASKS-*.json"))):
        try:
            d = json.load(open(fpath)); rows = d if isinstance(d, list) else (d.get("asks") or d.get("items") or [])
            for r in rows:
                if not isinstance(r, dict) or not r.get("id"): continue
                subs = [x for x in (r.get("subtasks") or []) if isinstance(x, dict)]
                if not subs: continue
                open_ = sum(1 for x in subs if not x.get("done"))
                if not open_: continue
                done_log = any(str(w.get("what", "")).upper().startswith("DONE") for w in (r.get("worklog") or []) if isinstance(w, dict))
                if r.get("status") == "done" or done_log:
                    out_.append(f"{r['id']} ({len(subs) - open_}/{len(subs)}{', status done' if r.get('status') == 'done' else ', work log says DONE'})")
        except Exception: pass
    return out_

def unprocessed(docs):
    """Asks still carrying `needs_processing` (set by code when a record is born from N / MagicUI / voice without
    EVA's pass — his canon 386). Printed at every board-ear arm so a returning organ sees the backlog first."""
    out_ = []
    for fpath in sorted(glob.glob(os.path.join(docs, "ASKS-*.json"))):
        try:
            d = json.load(open(fpath)); rows = d if isinstance(d, list) else (d.get("asks") or d.get("items") or [])
            for r in rows:
                if isinstance(r, dict) and r.get("needs_processing") and r.get("status") not in ("done", "closed"):
                    out_.append(f"{r.get('id')} ({str(r.get('title',''))[:40]})")
        except Exception as ex: out_.append(f"UNREADABLE {os.path.basename(fpath)}: {ex!r}")
    return out_

def _mine(aid, owners, me):
    o, a, _ = owners.get(aid, ("", "", "")); return me in o.split() or me in a.split()

# ---------------------------------------------------------------- ears
# An ear = list of sources [(path, classify)] followed together in ONE process, plus a selftest window
# over each source's last real lines. `system` also polls the pidfile.
def _voice_cls(cfg):
    """🗣 = spoken; 🗣⌨ = typed as him (mm text); 🗣⌨ [from X] = typed from a named surface (his canon 379:
    Cmd+Enter in the MagicUI text box arrives as [from MagicUI])."""
    def cls(l):
        if not l.startswith("🗣"): return None
        body = l[1:]
        if body.startswith("⌨"):
            body = body[1:].strip()
            if body.startswith("[from "):
                src = body[6: body.index("]")] if "]" in body else "?"
                return f"[from {src}] you: " + body[body.index("]") + 1:].strip()[: cfg["cut"]]
            return "[Typed ⌨] you: " + body[: cfg["cut"]]
        return "[Spoken] you: " + body.strip()[: cfg["cut"]]
    return cls

def _typed_cls(cfg):
    def cls(l):
        if not l.strip(): return None
        try: e = json.loads(l)
        except Exception: return "[Typed] you (unparsed): " + l[: cfg["cut"]]
        return f"[Typed] you ({e.get('source','?')} sha:{e.get('sha','-')}): {e.get('text','')}"[: cfg["cut"]]
    return cls

def _om_cls(cfg):
    # his words typed into Oh My Pi, mirrored by om-ingest (who==him only; relays already refused at the source)
    def cls(l):
        if not l.strip(): return None
        try: e = json.loads(l)
        except Exception: return None
        if e.get("who") != "him": return None
        return f"[Typed OM] you (sha:{e.get('sha','-')}): {e.get('text','')}"[: cfg["cut"]]
    return cls

def _driver_cls(cfg):
    # match ANYWHERE in the line: run headers land 13-30 lines after boot and get spliced mid-karaoke-line
    # (A16 audit 13:40: 1 of 47 headers today was invisible to a startswith match)
    return lambda l: ("[Driver] " + l[l.find("=== "):][:300]) if any(header in l for header in ("=== run", "=== driver", "=== Windows launcher")) else None

def _errors_cls(cfg):
    return lambda l: ("[Error] " + l[: cfg["cut"]]) if "⚠ error" in l else None


def _quick(aid, owners):
    """His A223 (typed-board 14:40): an ask the * shortcut handed to a spawned `ucode -p` agent is that
    agent's — its thread and its rows never reach the mind/eva ears ("make sure that thread sent to these
    are not sent in the monitor to livemind etc"). Owner strings starting quick- are that class."""
    o, a, _ = owners.get(aid, ("", "", ""))
    # EITHER owner or assignee: an ask born to mind/eva and HANDED to a quick agent is the normal case (EVA probe 2026-09-10, A223 subtask 6)
    return any(x.strip().lower().startswith("quick-") for x in (o, a) if x)
_NAMED = re.compile(r"\b(mind|eva|livemind|המוח|אווה)\b", re.I)

def _board_cls(cfg, me):
    docs = cfg["docs"]
    def cls(l):
        try: e = json.loads(l)
        except Exception: return None
        owners = _owner_map(docs); aid = e.get("id", "?"); ev = e.get("event"); who = e.get("who", "")
        to = str(e.get("to", "")).split(" ")[0]; title = e.get("title") or owners.get(aid, ("", "", ""))[2]
        if _quick(aid, owners) and ev == "stall": return f"[Board] {aid} STALL quick agent silent — {e.get('why') or ''}: {title}"[: cfg["cut"]]   # A223 addendum: the one mechanistic exception
        if _quick(aid, owners) and not (ev in ("assign", "handed") and to == me): return None   # A223: a quick agent's ask is silent here
        if ev in ("assign", "handed") and to == me:
            return f"[Board] {aid} {ev.upper()} to {me} by {who}: {title}"[: cfg["cut"]]
        if ev == "create" and (who in HIM or _mine(aid, owners, me)):   # EVA 69f0c2e4: the ledger CREATE row (his N / MagicUI / voice)
            return f"[Board] {aid} CREATED by {who} ({e.get('source','?')}, {e.get('bytes','?')} bytes): {title}"[: cfg["cut"]]
        if _mine(aid, owners, me) and who != me and ev in ("tier", "priority", "reorder", "retitle", "enrich", "status", "tick", "close"):
            return f"[Board] {aid} {ev.upper()} {e.get('tier') or e.get('priority') or e.get('status') or ''} by {who}: {title}"[: cfg["cut"]]
        return None
    return cls

def _threads_cls(cfg, me):
    docs = cfg["docs"]
    def cls(l):
        try: e = json.loads(l)
        except Exception: return None
        if e.get("who") in HIM:   # his A217 (14:13): EVERY comment of his reaches this ear, owner named — an owner without a board ear (the builder) left A211 unanswered
            owners = _owner_map(docs); own = owners.get(e.get("id", "?"), ("", "", ""))[0] or "?"
            if _quick(e.get("id", "?"), owners) and not _NAMED.search(e.get("text", "")): return None   # A223: unless he names mind/eva in the comment
            mine = _mine(e.get("id", "?"), owners, me)
            line = f"[Thread] {e.get('id')} (owner {own}{', MINE' if mine else ''}) his comment: {e.get('text','')}"[: cfg["cut"]]
            sd, sn = _sub_counts(docs, e.get("id", "?"))
            if sn and sd < sn:   # his A227 thread 15:2x: "I DONT WANT SUB-ASKS TO BE STALE … MECHANISTICLY REMINDED TO THE MIND AND EVA"
                line += f"  [subitems {sd}/{sn} done — tick what is done]"
            if me == "eva-memory":   # his A227 thread 15:15:01, verbatim: "for evas monitor alone (not the mind no pollution) it should say in the monitor [remember to process the ask correclty and update all the items and subitems involved]"
                line += "  [remember to process the ask correctly and update all the items and subitems involved]"
            return line
        return None
    return cls

def ear_user_inputs(cfg, me):
    sources = [(cfg["log"], _voice_cls(cfg), lambda: [l for l in _tail_lines(cfg["log"]) if l.startswith("🗣")][-3:])]
    if cfg.get("typed"):
        sources.append((cfg["typed"], _typed_cls(cfg), lambda: [l for l in _tail_lines(cfg["typed"]) if l.strip()][-2:]))
    if cfg.get("om"):
        sources.append((cfg["om"], _om_cls(cfg), lambda: [l for l in _tail_lines(cfg["om"]) if l.strip()][-2:]))
    return sources

def ear_system(cfg, me):
    # errors are rare: scan 20 MB back so the filter is proven on REAL past errors, never a vacuous 0
    driver = _driver_cls(cfg)
    return [(cfg["log"], driver, lambda: [l for l in _tail_lines(cfg["log"]) if driver(l)][-2:]),
            (cfg["log"], _errors_cls(cfg), lambda: [l for l in _tail_lines(cfg["log"], 20_000_000) if "⚠ error" in l][-2:])]

def ear_board(cfg, me):
    ev = os.path.join(cfg["docs"], "asks-events.jsonl"); th = os.path.join(cfg["docs"], "asks-threads.jsonl")
    bc, tc = _board_cls(cfg, me), _threads_cls(cfg, me)
    return [(ev, bc, lambda: [l for l in _tail_lines(ev)[-300:] if bc(l)][-3:]),
            (th, tc, lambda: [l for l in _tail_lines(th)[-300:] if tc(l)][-2:])]

def _bus_cls(cfg, ch, me):
    def cls(l):
        try: e = json.loads(l)
        except Exception: return None
        fr = e.get("from", "?")
        if fr == me: return None                       # my own sends are not news to me
        text = str(e.get("text", "")); first = text.split("\n", 1)[0]
        more = "" if len(text) <= cfg["cut"] and "\n" not in text else f" …(+{len(text)} chars) lm-read {e.get('id','?')}"
        return f"[Bus {ch}] {fr}: {first[: cfg['cut']]}{more}"
    return cls

def ear_bus(cfg, me):
    chans = list(cfg.get("channels") or []) + [cfg.get("own") or me]
    srcs = []
    for ch in chans:
        path = os.path.join(cfg["bus"], ch + ".jsonl"); c = _bus_cls(cfg, ch, me)
        srcs.append((path, c, (lambda path=path, c=c: [l for l in _tail_lines(path)[-200:] if c(l)][-2:])))
    return srcs

def bus_heartbeat(cfg, me):
    """Presence (canon 061): senders check `.readers/<me>.hb` mtime (<25 s = LIVE). Written every loop tick."""
    import hashlib
    try:
        chans = list(cfg.get("channels") or []) + [cfg.get("own") or me]
        hb = os.path.join(cfg["bus"], ".readers", me + ".hb"); os.makedirs(os.path.dirname(hb), exist_ok=True)
        rsha = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:12]
        with open(hb, "w") as f:
            json.dump({"channels": chans, "recipe_sha": rsha, "recipe": "lm-ear bus", "render": "head", "chunk": cfg["cut"],
                       "max_parts": 1, "inline": cfg["cut"], "pace_ms": 0, "pull": "lm-read <id>"}, f)
    except OSError as ex: out(f"bus heartbeat FAILED: {ex!r}")

# ---------------------------------------------------------------- the board mirror (remote machines)
# The Mac is the single WRITER of the asks board; an allowed machine receives a PROJECTION of it over the
# Agent Tunnel as one inbox line `BOARD-MIRROR {json}` (`lm-tunnels board push <label>`). This ear turns that
# into ONE line naming what changed, and keeps the last mirror on disk so the next diff has something to
# compare against. It never writes the board — a remote has no board to write.
# Inbox layout OPENED, not assumed: p2p-stable-v0.3.6/src/tunnel.js:259-269 `tunnelDir` =
#   <P2P_HOME | (win ? %USERPROFILE% : ~)/.p2p>/tunnel/<name>/ ; bin/p2p-tunnel.js:76-83 `current.json` -> {id},
#   session dir <root>/<id>/, bin/p2p-tunnel.js:74 files() -> inbox.jsonl ; `--name` defaults to 'default'
#   (bin/p2p-tunnel.js:278). Rows: {v,id,t,text,from,rx[,channel]}; channel is absent for chat and 'term' for
#   terminal output (bin/p2p-tunnel.js:204-212) — term rows are skipped here as they are everywhere else.
# `recv` keeps its own cursor in offset.json (bin/p2p-tunnel.js:409-416), so reading inbox.jsonl by our own
# byte offset never disturbs the remote agent's own reads.
def _mirror_inbox(cfg):
    """The tunnel inbox this machine receives on. Explicit `inbox` wins; else the NEWEST session inbox under
    <P2P_HOME|~/.p2p or %USERPROFILE%/.p2p>/tunnel/*/current.json -> <id>/inbox.jsonl. None = nothing to follow."""
    if cfg.get("inbox"): return H(cfg["inbox"])
    base = os.environ.get("P2P_HOME") or os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), ".p2p")
    best = None
    for cur in glob.glob(os.path.join(base, "tunnel", "*", "current.json")):
        try:
            with open(cur) as f: ptr = json.load(f)
            inbox = os.path.join(os.path.dirname(cur), str(ptr.get("id", "")), "inbox.jsonl")
            mt = os.path.getmtime(inbox)
        except Exception: continue
        if best is None or mt > best[0]: best = (mt, inbox)
    return best[1] if best else None

def _mirror_key(r):
    return (str(r.get("status", "")), str(r.get("title", "")), str(r.get("owner", "")))

def _mirror_load():
    """The last mirror on disk as {id: record}. Unreadable/absent = {} (the first mirror then reads as all-new)."""
    try:
        with open(MIRROR_PATH, encoding="utf-8") as f: d = json.load(f)
        return {str(r.get("id")): r for r in (d.get("records") or []) if isinstance(r, dict) and r.get("id")}
    except Exception: return {}

def _mirror_write(payload):
    d = os.path.dirname(MIRROR_PATH)
    if d: os.makedirs(d, exist_ok=True)
    tmp = MIRROR_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, MIRROR_PATH)

def _mirror_cls(cfg):
    state = {"prev": None}   # loaded from MIRROR_PATH on the first mirror, not at import: the file may appear later
    def cls(l):
        if not l.strip(): return None
        try: e = json.loads(l)
        except Exception: return None
        if e.get("channel") == "term": return None
        text = str(e.get("text", ""))
        if not text.startswith("BOARD-MIRROR "): return None
        if state["prev"] is None: state["prev"] = _mirror_load()
        try: m = json.loads(text[len("BOARD-MIRROR "):])
        except Exception: m = None
        if not isinstance(m, dict): return "[Board mirror] REFUSED unparsable mirror"   # MIRROR_PATH untouched
        recs = [r for r in (m.get("records") or []) if isinstance(r, dict) and r.get("id")]
        cur = {str(r["id"]): r for r in recs}; prev = state["prev"]
        named = []
        for rid, r in cur.items():
            if rid not in prev or _mirror_key(r) != _mirror_key(prev[rid]):
                named.append(f"{rid} {r.get('status', '?')} {str(r.get('title', ''))[:40]}")
        for rid, r in prev.items():
            if rid not in cur: named.append(f"{rid} REMOVED {str(r.get('title', ''))[:40]}")
        try: _mirror_write(m)
        except OSError as ex: return f"[Board mirror] WRITE FAILED {MIRROR_PATH}: {ex!r}"[: cfg["cut"]]
        state["prev"] = cur
        head = f"[Board mirror] {len(recs)} records from {m.get('sender', '?')} @ {m.get('generated', '?')}: "
        if not named: return (head + "no change")[: cfg["cut"]]
        body = "; ".join(named[:6]) + (f" +{len(named) - 6} more — read {MIRROR_PATH}" if len(named) > 6 else "")
        return (head + f"{len(named)} changed — " + body)[: cfg["cut"]]
    return cls

def ear_mirror(cfg, me):
    inbox = _mirror_inbox(cfg)
    if not inbox:
        out("EAR mirror: no tunnel inbox found"); return []   # visible, never a silent empty ear
    c = _mirror_cls(cfg)
    return [(inbox, c, lambda: [l for l in _tail_lines(inbox)[-200:] if "BOARD-MIRROR " in l][-1:])]

def mirror_selftest():
    """`lm-ear --mirror-selftest` — EXECUTE the mirror rule on fixtures: one clean row, two mirrors, a removal,
    a bad one, a term row, a repeat. Its own temp MIRROR_PATH, so it can never touch this machine's
    board-mirror.json. Non-halting: rc 0 when every leg is ok, 1 otherwise (the failing legs are named)."""
    import tempfile, shutil
    global MIRROR_PATH
    saved = MIRROR_PATH; d = tempfile.mkdtemp(prefix="lm-mirror-selftest-")
    MIRROR_PATH = os.path.join(d, "board-mirror.json")
    legs = []
    def leg(name, ok, detail=""):
        legs.append(ok); out(f"mirror-selftest: {'ok  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    def row(**kw):
        base = {"v": 1, "id": kw.pop("mid", "m"), "from": "PEER"}; base.update(kw); return json.dumps(base, ensure_ascii=False)
    def mirror(gen, records):
        return "BOARD-MIRROR " + json.dumps({"generated": gen, "sender": "mac:Test", "count": len(records), "records": records}, ensure_ascii=False)
    A1 = {"id": "A1", "title": "first", "status": "open", "owner": "mind"}
    A2o = {"id": "A2", "title": "second", "status": "open", "owner": "eva"}
    A2d = {"id": "A2", "title": "second", "status": "done", "owner": "eva"}
    try:
        cls = _mirror_cls({"cut": 400})
        r0 = cls(row(mid="m0", text="hello from the PC"))
        leg("CLEAN: a plain chat row is not a mirror", r0 is None, repr(r0))
        r1 = cls(row(mid="m1", text=mirror("T0", [A1, A2o])))
        leg("first mirror names both records as changed", bool(r1) and "2 changed" in r1 and "A1 open" in r1 and "A2 open" in r1, repr(r1))
        after1 = _mirror_load()
        leg("MIRROR_PATH rewritten by the first mirror", sorted(after1) == ["A1", "A2"] and after1.get("A2", {}).get("status") == "open", repr(sorted(after1)))
        r2 = cls(row(mid="m2", text=mirror("T1", [A1, A2d])))
        leg("second mirror names exactly A2 done", bool(r2) and "1 changed" in r2 and "A2 done" in r2 and "A1" not in r2, repr(r2))
        after2 = _mirror_load()
        leg("MIRROR_PATH rewritten to the newest", after2.get("A2", {}).get("status") == "done", repr(after2.get("A2")))
        r3 = cls(row(mid="m3", text=mirror("T2", [A1])))
        leg("a removed record is named", bool(r3) and "A2 REMOVED" in r3, repr(r3))
        def onbytes():   # a MISSING file is a value, not a crash: a sabotage that stops the write must be REPORTED, never raise
            try: return open(MIRROR_PATH, "rb").read()
            except OSError: return None
        before = onbytes()
        r4 = cls(row(mid="m4", text="BOARD-MIRROR {not json"))
        leg("REFUSED unparsable mirror", r4 == "[Board mirror] REFUSED unparsable mirror", repr(r4))
        leg("MIRROR_PATH unchanged by the unparsable mirror", onbytes() == before)
        r5 = cls(row(mid="m5", channel="term", text=mirror("T3", [A1, A2d])))
        leg("a term-channel row is skipped", r5 is None, repr(r5))
        r6 = cls(row(mid="m6", text=mirror("T4", [A1])))
        leg("an identical mirror says no change", bool(r6) and r6.endswith("no change"), repr(r6))
        # inbox RESOLUTION — a path that can fail silently otherwise (the layout is p2p's, opened above)
        home = os.path.join(d, "p2p"); sess = "deadbeef" * 4
        os.makedirs(os.path.join(home, "tunnel", "default", sess))
        with open(os.path.join(home, "tunnel", "default", "current.json"), "w") as f: json.dump({"id": sess}, f)
        inbox = os.path.join(home, "tunnel", "default", sess, "inbox.jsonl")
        with open(inbox, "w", encoding="utf-8") as f:
            f.write(row(mid="i0", text="plain hello") + "\n" + row(mid="i1", text=mirror("T5", [A1, A2d])) + "\n")
        leg("explicit cfg inbox wins", _mirror_inbox({"inbox": inbox}) == inbox)
        old_home = os.environ.get("P2P_HOME"); os.environ["P2P_HOME"] = home
        try:
            leg("inbox resolved from P2P_HOME/tunnel/<name>/current.json", _mirror_inbox({"inbox": None}) == inbox, repr(_mirror_inbox({"inbox": None})))
            srcs = ear_mirror({"inbox": None, "cut": 400}, "mind")
            hits = [s[1](l) for s in srcs for l in s[2]()]
            # one source, one hit: the window keeps only the LAST BOARD-MIRROR row, and the plain row never fires.
            # A2 (not A1) is named because a fresh cls diffs against MIRROR_PATH, which the legs above left holding {A1}.
            leg("ear_mirror's selftest window fires on the last BOARD-MIRROR row only", len(srcs) == 1 and len(hits) == 1 and bool(hits[0]) and "A2 done" in hits[0], repr(hits))
            os.environ["P2P_HOME"] = os.path.join(d, "nothing-here")
            leg("no tunnel inbox -> ear_mirror returns no sources", ear_mirror({"inbox": None, "cut": 400}, "mind") == [])
        finally:
            if old_home is None: os.environ.pop("P2P_HOME", None)
            else: os.environ["P2P_HOME"] = old_home
        # `config enable|disable <ear>` — run as a SUBPROCESS against a scratch config, never this machine's
        ecfg = os.path.join(d, "ears.json")
        with open(ecfg, "w", encoding="utf-8") as f: json.dump(DEFAULTS, f, indent=2, ensure_ascii=False)
        env = dict(os.environ, LM_EARS=ecfg)
        def run(*a):
            r = subprocess.run([sys.executable, os.path.abspath(__file__), *a], env=env, capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr
        def others(t): return [x for x in t.splitlines() if x.startswith("Monitor(") and '"lm-ear mirror"' not in x]
        rc0, base = run()
        rc1, o1 = run("config", "enable", "mirror")
        leg("config enable mirror: rc 0 + the re-arm line", rc1 == 0 and "mirror enabled=True" in o1 and 'Monitor({command:"lm-ear mirror"' in o1, o1.strip()[-90:])
        leg("config enable mirror: enabled true on disk", json.load(open(ecfg))["ears"]["mirror"]["enabled"] is True)
        rc2, o2 = run()
        leg("the plan now carries the mirror monitor", rc2 == 0 and 'command: "lm-ear mirror"' in o2)
        rc3, o3 = run("config", "disable", "mirror")
        leg("config disable mirror: rc 0", rc3 == 0 and "mirror enabled=False" in o3, o3.strip()[-90:])
        rc4, o4 = run()
        leg("the plan prints `# OFF: mirror` again", rc4 == 0 and "# OFF: mirror" in o4)
        leg("every OTHER ear's monitor line is byte-identical to the baseline", rc0 == 0 and others(o4) == others(base) and len(others(base)) >= 1)
        rc5, o5 = run("config", "enable", "nosuch")
        leg("config enable <unknown ear>: rc 2, nothing written", rc5 == 2 and "unknown ear 'nosuch'" in o5 and "mirror" not in json.dumps(json.load(open(ecfg))["ears"].get("nosuch", {})), o5.strip()[-60:])
        rc6, o6 = run("config", "enable")
        leg("config enable with no ear name: rc 2 usage", rc6 == 2 and "usage: lm-ear config enable <ear>" in o6, o6.strip()[-60:])
    finally:
        MIRROR_PATH = saved; shutil.rmtree(d, ignore_errors=True)
    bad = legs.count(False)
    out(f"mirror-selftest: {len(legs) - bad}/{len(legs)} legs ok")
    return 1 if bad else 0

EARS = {"user-inputs": ear_user_inputs, "system": ear_system, "board": ear_board, "bus": ear_bus, "mirror": ear_mirror}

def write_event(docs, me, aid, event, **extra):
    row = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "id": aid, "who": me, "event": event}; row.update(extra)
    with open(os.path.join(docs, "asks-events.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row

# ---------------------------------------------------------------- running
def selftest(name, cfg, me, tag=""):
    fired = 0
    for path, cls, window in EARS[name](cfg["ears"][name], me):
        for l in window():
            c = cls(l)
            if c: fired += 1; out(f"{tag}selftest({name}): {c[:140]}")
    out(f"{tag}selftest({name}): {fired} of the last real lines fire the filter")
    return fired

def _read(p):
    try: return open(p).read().strip()
    except OSError: return ""

GAP_MAX = 40   # bounded: a monitor that emits too many lines is auto-stopped (the chunking law) — past the bound, the count and a pull hint

def replay_gap(sources, seen_path, emit):
    """Deliver every firing line written to a source AFTER the position in the last receipt — the re-arm window.
    A re-arm (TaskStop + Monitor) takes seconds; four happened in ninety minutes today; a line of his landing in
    that window was previously never delivered while `coverage` said healthy, because the ARMED receipt set the
    position to end-of-file. Returns the number replayed. No receipt / no position for a source = nothing to
    replay from (the selftest still shows the last real lines)."""
    try: prev = json.load(open(seen_path)).get("pos") or {}
    except Exception: prev = {}
    n = 0; seen_paths = set()
    for path, cls, _w in sources:
        if path in seen_paths: continue
        seen_paths.add(path)
        p0 = prev.get(path)
        if p0 is None: continue
        try:
            size = os.path.getsize(path)
            if int(p0) > size: continue   # rotated/truncated: the follower reopens; nothing to replay from a vanished offset
            with open(path, "rb") as fh:
                fh.seek(int(p0)); rest = fh.read().decode("utf-8", "replace").splitlines()
        except OSError: continue
        hits = [h for h in (cls(l) for l in rest) if h]
        for h in hits[:GAP_MAX]: emit("[GAP — landed while this ear was down] " + h); n += 1
        if len(hits) > GAP_MAX: emit(f"[GAP] … {len(hits) - GAP_MAX} more firing lines in the arm gap — read {path} from byte {p0}")
    return n

def run_ear(name, cfg, me, tag=""):
    import threading
    ecfg = cfg["ears"][name]; sources = EARS[name](ecfg, me)
    fired = selftest(name, cfg, me, tag)
    lock = threading.Lock()
    seen_path = os.path.join(SEEN_DIR, f"{cfg.get('profile','mind')}.{name}.json")
    def emit(s):
        with lock:
            out(tag + s)
            try:   # RECEIPT (his canon 394): every delivered line stamps a seen-file so `lm-ear coverage` can prove nobody is behind
                os.makedirs(SEEN_DIR, exist_ok=True)
                with open(seen_path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump({"t": time.time(), "profile": cfg.get("profile", "mind"), "ear": name, "line": s[:200], "pos": dict(POS)}, f, ensure_ascii=False)
                os.replace(seen_path + ".tmp", seen_path)
            except OSError as ex: out(f"{tag}seen-stamp FAILED: {ex!r}")
    gap = replay_gap(sources, seen_path, emit)   # THE ARM GAP (EVA 15:1x): lines that landed between the last receipt and this arm are delivered now, never lost
    starts = {}
    for p_, _, _ in sources:   # retain this offset across ARMED and follower thread startup
        try: POS[p_] = os.path.getsize(p_)
        except OSError: POS[p_] = 0
        starts[p_] = POS[p_]
    emit(f"EAR ARMED {name} {time.strftime('%H:%M:%S')} sources={[p for p, _, _ in sources]} selftest_fired={fired} gap_replayed={gap}")
    def follow_source(path, cls):
        try:
            for line in _follow(path, start=starts[path]):
                c = cls(line)
                if not c: continue
                emit(c)
                if name == "board" and c.startswith("[Board]"):
                    try:
                        e = json.loads(line)
                        if e.get("event") == "handed" and str(e.get("to", "")).split(" ")[0] == me:
                            write_event(ecfg["docs"], me, e.get("id", "?"), "delivered", to=me, via={"ear": "lm-ear board"})
                            emit(f"[Board] {e.get('id')} receipt written: delivered")
                    except Exception as ex: emit(f"[Board] receipt FAILED: {ex!r}")
        except Exception as ex:
            emit(f"EAR {name} SOURCE DIED ({path}): {ex!r}")
    threads = [threading.Thread(target=follow_source, args=(p, c), daemon=True) for p, c, _ in sources]
    for t in threads: t.start()
    last = _read(ecfg["pidfile"]) if name == "system" else None
    if name == "bus": bus_heartbeat(ecfg, ecfg.get("own") or me); emit(f"[Bus] heartbeat live: {os.path.join(ecfg['bus'], '.readers', (ecfg.get('own') or me) + '.hb')}")
    if name == "board":   # his canon 386 (17c844ed): on return, the listener gets the list of everything not yet processed
        emit("[Board] UNPROCESSED at arm: " + (", ".join(unprocessed(ecfg["docs"])) or "none"))
        ids, src = stale_via_eva(ecfg["docs"]); st = ids if ids is not None else stale_subitems(ecfg["docs"])
        emit(f"[Board] STALE SUBITEMS at arm ({src or 'ear reading'}) — tick what is done: " + (", ".join(st[:12]) + (f" … +{len(st) - 12}" if len(st) > 12 else "") if st else "none"))
    last_backlog = time.time(); period = float(ecfg.get("backlog_every_s", 600))
    last_stale: set = set()   # the set last announced; an unchanged set is not news
    while any(t.is_alive() for t in threads):
        time.sleep(2.0)
        if name == "board" and time.time() - last_backlog >= period:   # his A217/A211 (14:1x): a PERIODIC reminder of what is still unprocessed, not only at arm
            last_backlog = time.time(); u = unprocessed(ecfg["docs"])
            if u: emit("[Board] UNPROCESSED still: " + ", ".join(u))
            ids, src = stale_via_eva(ecfg["docs"]); st = ids if ids is not None else stale_subitems(ecfg["docs"])
            # ONLY WHEN THE SET CHANGES (MIND, 2026-09-08 19:3x): the same 56 ids every few minutes is
            # noise on a WAKE channel, and a reminder nobody can act on twice teaches the reader to skip
            # the line — which is how the one that matters gets skipped too. A NEW stale id or one that
            # CLEARED is news; an unchanged set is not. The arm-time line still prints the whole set, so
            # a fresh reader is never left guessing what is outstanding.
            cur = set(st)
            if cur and cur != last_stale:
                added, gone = sorted(cur - last_stale), sorted(last_stale - cur)
                head = (", ".join(sorted(cur)[:12]) + (f" … +{len(cur) - 12}" if len(cur) > 12 else "")
                        if not last_stale else
                        (("new: " + ", ".join(added[:8])) if added else "") +
                        ((" | cleared: " + ", ".join(gone[:8])) if gone else ""))
                emit(f"[Board] STALE SUBITEMS ({src or 'ear reading'}, {len(cur)} open) — {head}")
            last_stale = cur
        if name == "bus": bus_heartbeat(ecfg, ecfg.get("own") or me)
        if name == "system":
            p = _read(ecfg["pidfile"])
            if p and p != last: emit(f"[Driver] MINI-MOUTH DRIVER CHANGED {last} -> {p}"); last = p
    emit(f"EAR {name}: every source died — exiting")

def coverage(cfg):
    """`lm-ear coverage` — his canon 394 ("nothing from user inputs is ever missed by her or you"): for every
    profile × ear, the last line that listener DELIVERED (its seen-stamp) against the newest line its source holds.
    A listener with no stamp, or whose last delivered line is not the source's newest and is older than 30 s, is
    BEHIND — printed loudly with the line it has not seen. rc = number of BEHIND listeners."""
    behind = 0
    for prof in (cfg.get("profiles") or {"mind": {}}):
        ap = apply_profile(cfg, prof)
        if ap is None: continue
        c, me, tag = ap
        for name in enabled_ears(c):
            ecfg = c["ears"][name]
            try: srcs = EARS[name](ecfg, me)
            except Exception as ex: out(f"{prof:5s} {name:12s} UNREADABLE sources: {ex!r}"); behind += 1; continue
            newest = None
            for path, cls, window in srcs:
                try: last = [l for l in window() if l][-1:]
                except Exception: last = []
                if last:
                    classified = cls(last[-1])
                    if classified: newest = classified[:200]
            sp = os.path.join(SEEN_DIR, f"{prof}.{name}.json")
            try: seen = json.load(open(sp))
            except Exception: seen = None
            if seen is None:
                out(f"{prof:5s} {name:12s} NO RECEIPT — never armed on a receipt-stamping recipe (LiveMind ≥ 90f3edd1: the ARMED line itself is the first receipt) — re-arm"); behind += 1; continue
            age = time.time() - float(seen.get("t", 0))
            delivered = seen.get("line", "")
            pos = seen.get("pos") or {}
            # POSITION, NOT TEXT (MIND 2026-09-08 15:0x — two false BEHINDs in one check: the system ear was "behind" an error
            # line older than its own arm, and the user-inputs ear was "behind" a typed row it had delivered a minute before a
            # newer MagicUI line from another source). With a receipt position, BEHIND means exactly: this source holds a line
            # the filter fires on, written past what the ear consumed, and the file kept moving for >30 s after the stamp.
            unseen = None
            if pos:
                for path, cls, _w in srcs:
                    p0 = pos.get(path)
                    if p0 is None: continue
                    try:
                        with open(path, "rb") as fh:
                            fh.seek(int(p0)); rest = fh.read().decode("utf-8", "replace").splitlines()
                        moved = os.path.getmtime(path) - float(seen.get("t", 0))
                    except OSError: continue
                    hits = [cls(l) for l in rest]; hits = [h for h in hits if h]
                    if hits and moved > 30: unseen = hits[-1][:200]
            own = delivered.startswith(("EAR ARMED", "[Board] UNPROCESSED", "[Bus] heartbeat"))
            if pos and unseen:
                out(f"{prof:5s} {name:12s} BEHIND {int(age)}s — last delivered: {delivered[:80]!r} | unseen: {unseen[:80]!r}"); behind += 1
            elif not pos and newest and not own and delivered[:120] != newest[:120] and age > 30:   # pre-position receipt (ear armed before this build): the old text compare, re-arm to get positions
                out(f"{prof:5s} {name:12s} BEHIND? {int(age)}s (text compare — re-arm for positions) — last delivered: {delivered[:60]!r} | newest in source: {newest[:60]!r}"); behind += 1
            elif delivered.startswith("EAR ARMED"):   # EVA's third bucket (14:0x): armed, alive, the room is quiet — NOT deaf
                out(f"{prof:5s} {name:12s} ARMED-QUIET — armed {int(age)}s ago, nothing to deliver since ({delivered[:60]!r})")
            else:
                out(f"{prof:5s} {name:12s} ok — last delivered {int(age)}s ago: {delivered[:80]!r}")
    return behind

def enabled_ears(cfg, only=None):
    names = [n for n in EARS if cfg["ears"].get(n, {}).get("enabled", True)]
    if only: names = [n for n in names if n in only]
    return names

def plan(cfg, only=None, as_json=False, tag=""):
    names = enabled_ears(cfg, only)
    prof = cfg.get("profile", "mind"); popt = "" if prof == "mind" else f"--profile {prof} "
    if as_json:
        out(json.dumps([{"ear": n, "profile": prof, "command": f"lm-ear {popt}{n}", "description": f"lm-ear {tag}{n}: {cfg['ears'][n]['desc']}", "persistent": True} for n in names], ensure_ascii=False, indent=2)); return
    out(f"# lm-ear plan — profile {prof} (me={cfg.get('me')}) — {len(names)} independent monitors (config {CONFIG}; edit `enabled`/params there, or --only a,b)")
    for n in names:
        out(f'Monitor({{ command: "lm-ear {popt}{n}", persistent: true, description: "lm-ear {tag}{n}: {cfg["ears"][n]["desc"]}" }})')
    for n in EARS:
        if n not in names:   # EVA's rule (2026-09-08 12:1x): a disabled/deselected ear is VISIBLE, never silently absent
            out(f"# OFF: {n} — {'disabled in config' if not cfg['ears'].get(n, {}).get('enabled', True) else 'not in --only'} — nobody is listening to: {cfg['ears'][n]['desc']}")
    out("# each prints selftest: lines + EAR ARMED before its first live line — if those did not reach you, it is not armed")

def main(argv):
    if argv[:1] == ["--mirror-selftest"]: return mirror_selftest()   # before load_config: it must never write a config
    cfg = load_config()
    prof = os.environ.get("LM_EAR_PROFILE") or "mind"
    if "--profile" in argv:
        i = argv.index("--profile")
        if i + 1 >= len(argv): out("usage: lm-ear --profile <name> …"); return 2
        prof = argv[i + 1]; del argv[i:i + 2]
    if argv[:1] == ["coverage"]:
        return 1 if coverage(cfg) else 0
    if argv[:1] == ["profiles"]:
        for n, pr in (cfg.get("profiles") or {}).items():
            out(f"{n:8s} me={pr.get('me','?'):16s} tag={pr.get('tag','')!r:10s} ear-overrides={sorted((pr.get('ears') or {}).keys())}")
        return 0
    ap = apply_profile(cfg, prof)
    if ap is None: return 2
    cfg, me, tag = ap
    only = None
    if "--only" in argv:
        i = argv.index("--only"); only = set(argv[i + 1].split(",")); del argv[i:i + 2]
    if not argv or argv == ["--json"]:
        plan(cfg, only, as_json=("--json" in argv), tag=tag); return 0
    a = argv[0]
    if a == "list":
        for n in EARS:
            e = cfg["ears"].get(n, {}); out(f"{n:8s} {'on ' if e.get('enabled', True) else 'off'}  {e.get('desc','')}")
        return 0
    if a == "config":
        if len(argv) > 2 and argv[1] in ("enable", "disable"):
            ear = argv[2]
            if ear not in EARS: out(f"unknown ear '{ear}' — ears: {', '.join(EARS)}"); return 2
            try:
                with open(CONFIG, encoding="utf-8") as f: raw = json.load(f)
            except Exception: raw = json.loads(json.dumps(DEFAULTS))
            want = argv[1] == "enable"
            raw.setdefault("ears", {}).setdefault(ear, json.loads(json.dumps(DEFAULTS["ears"][ear])))["enabled"] = want
            d = os.path.dirname(CONFIG)
            if d: os.makedirs(d, exist_ok=True)
            with open(CONFIG + ".tmp", "w", encoding="utf-8") as f: json.dump(raw, f, indent=2, ensure_ascii=False)
            os.replace(CONFIG + ".tmp", CONFIG)
            out(f'wrote {CONFIG}: {ear} enabled={want} — re-arm: Monitor({{command:"lm-ear {ear}", persistent:true}})')
            return 0
        if len(argv) > 1 and argv[1] in ("enable", "disable"):
            out(f"usage: lm-ear config {argv[1]} <ear>   (ears: {', '.join(EARS)})"); return 2
        if len(argv) > 1 and argv[1] == "init":
            os.makedirs(os.path.dirname(CONFIG), exist_ok=True); json.dump(DEFAULTS, open(CONFIG, "w"), indent=2, ensure_ascii=False); out(f"wrote {CONFIG}")
        else:
            out(CONFIG); out(json.dumps(cfg, indent=2, ensure_ascii=False))
        return 0
    if a == "--selftest":
        names = [argv[1]] if len(argv) > 1 else enabled_ears(cfg, only)
        res = {n: selftest(n, cfg, me, tag) for n in names}
        return 0 if all(res.values()) else 1
    if a == "ack":
        if len(argv) < 2: out("usage: lm-ear ack <ASK-ID> [note]"); return 2
        row = write_event(cfg["ears"]["board"]["docs"], me, argv[1], "ack", **({"note": " ".join(argv[2:])} if len(argv) > 2 else {}))
        out(tag + "ack written: " + json.dumps(row, ensure_ascii=False)); return 0
    if a == "all":
        import threading
        names = enabled_ears(cfg, only); ts = []
        for n in names:
            t = threading.Thread(target=lambda n=n: _guard(n, cfg, me, f"{tag}[{n}] "), daemon=True); t.start(); ts.append(t)
        while any(t.is_alive() for t in ts): time.sleep(1)
        out("ALL EARS DEAD — exiting"); return 1
    if a in EARS:
        try: run_ear(a, cfg, me, tag)
        except KeyboardInterrupt: return 0
        return 0
    out(f"unknown ear '{a}' — ears: {', '.join(EARS)}"); return 2

def _guard(n, cfg, me, tag):
    try: run_ear(n, cfg, me, tag)
    except Exception as ex: out(f"{tag}EAR {n} DIED: {ex!r}")

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
