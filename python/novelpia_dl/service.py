"""Background downloader: a detached worker process plus a shared queue on disk.

Files (python/.state/):
  queue.json   pending/running jobs, finished history, when the next novel may start
  status.json  live worker state (heartbeat, progress, countdowns, recent log)
  log.txt      full log
  stop         present = worker should stop (current chapter is cached; resumes later)
Any terminal can add jobs or attach to watch; the worker keeps going when you detach.
"""

import dataclasses
import json
import os
import random
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import config, textproc
from .client import Novelpia
from .downloader import Downloader, Job, Options, Result
from rich.markup import escape

from .ui import UI

STATE = config.HOME / ".state"
QUEUE = STATE / "queue.json"
STATUS = STATE / "status.json"
LOG = STATE / "log.txt"
STOP = STATE / "stop"
LOCK = STATE / "queue.lock"
HEARTBEAT_STALE = 15          # seconds without a heartbeat = worker is gone
LOG_KEEP = 300


# -- small file helpers -------------------------------------------------------------

def _read_json(path, default):
    for _ in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except (ValueError, PermissionError):
            time.sleep(0.05)          # mid-replace on Windows; try again
    return default


def _write_json(path, data):
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for _ in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:       # reader has it open (Windows)
            time.sleep(0.05)
    tmp.unlink(missing_ok=True)


@contextmanager
def _locked():
    STATE.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + 15
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - LOCK.stat().st_mtime > 30:   # left behind by a crash
                    LOCK.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() > deadline:
                raise TimeoutError("queue is locked")
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        LOCK.unlink(missing_ok=True)


def _load_queue():
    q = _read_json(QUEUE, {})
    q.setdefault("next_id", 1)
    q.setdefault("jobs", [])
    q.setdefault("history", [])
    q.setdefault("next_allowed_at", 0)
    return q


# -- queue API (used by any terminal) -------------------------------------------------

def read_queue():
    return _load_queue()


def read_status():
    return _read_json(STATUS, {})


def worker_alive(status=None):
    s = status if status is not None else read_status()
    return bool(s) and s.get("phase") != "exited" and time.time() - s.get("heartbeat", 0) < HEARTBEAT_STALE


def job_label(entry):
    return Job(entry["novel_no"], entry.get("from_n"), entry.get("to_n"), entry.get("bonus", "range"),
               entry.get("title")).label()


def add_jobs(jobs, opts):
    """Append jobs (skipping ones already waiting). Returns the entries added."""
    o = dataclasses.asdict(opts)
    o["output_dir"] = str(Path(opts.output_dir).expanduser().resolve())
    if opts.font_map:
        o["font_map"] = str(Path(opts.font_map).expanduser().resolve())
    added = []
    with _locked():
        q = _load_queue()
        for job in jobs:
            if any(e["novel_no"] == job.novel_no and e.get("from_n") == job.from_n
                   and e.get("to_n") == job.to_n and e.get("bonus") == job.bonus for e in q["jobs"]):
                continue
            entry = {"id": q["next_id"], "novel_no": job.novel_no, "from_n": job.from_n, "to_n": job.to_n,
                     "bonus": job.bonus, "title": job.title, "opts": o, "state": "pending",
                     "added_at": time.time()}
            q["next_id"] += 1
            q["jobs"].append(entry)
            added.append(entry)
        _write_json(QUEUE, q)
    return added


def remove_job(job_id):
    """Remove a waiting job. Returns the entry, or None (unknown id / currently running)."""
    with _locked():
        q = _load_queue()
        for e in q["jobs"]:
            if e["id"] == job_id and e["state"] == "pending":
                q["jobs"].remove(e)
                _write_json(QUEUE, q)
                return e
    return None


def clear_history():
    with _locked():
        q = _load_queue()
        q["history"] = []
        _write_json(QUEUE, q)


def request_stop():
    STATE.mkdir(parents=True, exist_ok=True)
    STOP.write_text("stop", encoding="utf-8")


def start_worker(config_path, loginkey=None, wait=8.0):
    """Start the background worker if it isn't running. Returns True if one is running."""
    if worker_alive():
        return True
    STATE.mkdir(parents=True, exist_ok=True)
    STOP.unlink(missing_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               PYTHONPATH=os.pathsep.join(filter(None, [str(config.HOME), os.environ.get("PYTHONPATH")])))
    if loginkey:
        env["NOVELPIA_SESSION_LOGINKEY"] = loginkey
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    with open(STATE / "worker.out", "ab") as out:
        subprocess.Popen([sys.executable, "-m", "novelpia_dl", "worker", "-c", str(config_path)],
                         cwd=str(config.HOME), env=env, stdin=subprocess.DEVNULL, stdout=out,
                         stderr=subprocess.STDOUT, close_fds=True, **kwargs)
    end = time.time() + wait
    while time.time() < end:
        if worker_alive():
            return True
        time.sleep(0.2)
    return worker_alive()


# -- the worker's UI: same calls as the terminal UI, but written to status.json -------------

class _Status:
    def __init__(self, ui):
        self.ui = ui

    def update(self, text):
        self.ui.set_status(text)


class StateUI(UI):
    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._pending = []
        self._done = threading.Event()
        self.s = {"pid": os.getpid(), "heartbeat": time.time(), "phase": "starting", "job": None,
                  "total": 0, "ok": 0, "fail": 0, "started": None, "interval": 0, "status": "",
                  "countdown_end": None, "countdown_label": "", "countdown_total": 0, "log": [],
                  "chapters": [], "marks": {}}
        self._thread = threading.Thread(target=self._writer, daemon=True)

    def start(self):
        self.flush()
        self._thread.start()

    def close(self, phase="exited"):
        self.set(phase=phase, status="", countdown_end=None)
        self._done.set()
        self._thread.join(timeout=3)
        self.flush()

    def _writer(self):
        while not self._done.wait(0.5):
            self.flush()

    def flush(self):
        with self._lock:
            self.s["heartbeat"] = time.time()
            snapshot = dict(self.s, log=list(self.s["log"]), marks=dict(self.s["marks"]))
            lines, self._pending = self._pending, []
        _write_json(STATUS, snapshot)
        if lines:
            with open(LOG, "a", encoding="utf-8") as f:
                f.writelines(time.strftime("%Y-%m-%d %H:%M:%S ") + ln.replace("\x00rule ", "── ") + "\n"
                             for ln in lines)

    def set(self, **kw):
        with self._lock:
            self.s.update(kw)

    @staticmethod
    def check_stop():
        if STOP.exists():
            raise KeyboardInterrupt

    def job_title(self, job):
        """Title is known once the novel page loads: show it in the view and the queue."""
        with self._lock:
            if self.s.get("job"):
                self.s["job"] = dict(self.s["job"], label=job.label())
            job_id = (self.s.get("job") or {}).get("id")
        if job_id is None:
            return
        with _locked():
            q = _load_queue()
            for e in q["jobs"]:
                if e["id"] == job_id:
                    e["title"] = job.title
            _write_json(QUEUE, q)

    # UI overrides ---------------------------------------------------------------
    def print(self, msg="", screen=True, **_):
        msg = str(msg)
        with self._lock:
            if screen:
                self.s["log"] = (self.s["log"] + [msg])[-LOG_KEEP:]
            self._pending.append(msg)

    def item_ok(self, text, cached=False):
        # shown in the paged EP list instead of the scrolling log
        self.print(f"  [ok]✓[/] {escape(text)}" + ("  [dim](cached)[/]" if cached else ""), screen=False)

    def chapters_init(self, labels):
        self.set(chapters=list(labels), marks={})

    def chapter_mark(self, index, state):
        with self._lock:
            self.s["marks"][str(index)] = state

    def rule(self, text):
        self.print("\x00rule " + text)

    @contextmanager
    def status(self, text):
        self.check_stop()
        self.set(status=text)
        try:
            yield _Status(self)
        finally:
            self.set(status="")

    @contextmanager
    def chapter_progress(self, total, interval=0):
        self.set(phase="downloading", total=total, ok=0, fail=0, started=time.time(), interval=interval)
        try:
            yield self
        finally:
            self.set(phase="working", status="", chapters=[], marks={})

    def advance(self, ok, fail):
        self.set(ok=ok, fail=fail, status="")
        self.check_stop()

    def set_status(self, text):
        self.set(status=text)
        self.check_stop()

    def _countdown(self, seconds, label):
        end = time.time() + seconds
        self.set(countdown_end=end, countdown_label=label, countdown_total=seconds)
        try:
            while time.time() < end:
                self.check_stop()
                time.sleep(min(0.25, max(0.0, end - time.time())))
        finally:
            self.set(countdown_end=None, countdown_label="")

    def sleep(self, seconds, reason):
        self._countdown(seconds, reason)

    def gap(self, seconds, next_label):
        prev = self.s["phase"]
        self.set(phase="gap", status=escape(next_label))
        try:
            self._countdown(seconds, "break before next novel")
        finally:
            self.set(phase=prev, status="")
        self.print(f"[dim]  rested {int(seconds) // 60}m {int(seconds) % 60}s[/]")


# -- worker process ----------------------------------------------------------------------

def _claim(job_id):
    with _locked():
        q = _load_queue()
        for e in q["jobs"]:
            if e["id"] == job_id and e["state"] == "pending":
                e["state"] = "running"
                _write_json(QUEUE, q)
                return e
    return None


def _finish(entry, result=None, gap=None):
    """result None = put the job back (stopped); it resumes from the cache next time."""
    with _locked():
        q = _load_queue()
        for e in q["jobs"]:
            if e["id"] == entry["id"]:
                if result is None:
                    e["state"] = "pending"
                else:
                    q["jobs"].remove(e)
                    q["history"] = (q["history"] + [{
                        "id": e["id"], "novel_no": e["novel_no"], "title": result.job.title,
                        "status": result.status, "ok": result.ok, "failed": result.failed,
                        "path": result.path, "message": result.message, "finished_at": time.time()}])[-50:]
                break
        if gap is not None:
            q["next_allowed_at"] = time.time() + gap
        _write_json(QUEUE, q)


def _login(client, ui, cfg):
    key = os.environ.get("NOVELPIA_SESSION_LOGINKEY")
    if key:
        client.loginkey = key
        ui.info("Using the login from the terminal that started the worker")
        return
    if cfg.get("email") and cfg.get("wd"):
        try:
            if client.login(cfg["email"], cfg["wd"]):
                ui.info(f"Logged in as {escape(cfg['email'])}")
                return
        except Exception as e:
            ui.error(escape(f"login request failed: {e}"))
        ui.error("Login failed (email / password in config.json)")
    if cfg.get("loginkey"):
        client.loginkey = cfg["loginkey"]
        ui.info("Using LOGINKEY from config.json")
        return
    ui.warn("Not logged in — only free chapters can be downloaded.")


def worker_main(config_path):
    STATE.mkdir(parents=True, exist_ok=True)
    ui = StateUI()
    with _locked():
        if worker_alive() and read_status().get("pid") != os.getpid():
            return 0                  # another worker is already running
        STOP.unlink(missing_ok=True)
        ui.flush()                    # claim the heartbeat while holding the lock
        q = _load_queue()
        for e in q["jobs"]:           # a previous worker died mid-job: run it again (cache resumes)
            if e["state"] == "running":
                e["state"] = "pending"
        _write_json(QUEUE, q)
    ui.start()
    ui.print("\x00rule [accent]worker started[/]")
    client = Novelpia()
    try:
        _login(client, ui, config.load(config_path))
        while True:
            ui.check_stop()
            q = _load_queue()
            waiting = [e for e in q["jobs"] if e["state"] == "pending"]
            if not waiting:
                ui.info("Queue is empty — worker finished.")
                break
            entry = waiting[0]
            wait = q["next_allowed_at"] - time.time()
            if wait > 1:
                ui.set(job=None)
                ui.gap(wait, job_label(entry))
                continue                  # the queue may have changed during the break
            if not _claim(entry["id"]):
                continue
            opts = Options(**{k: v for k, v in entry["opts"].items() if k in Options.__dataclass_fields__})
            job = Job(entry["novel_no"], entry.get("from_n"), entry.get("to_n"), entry.get("bonus", "range"),
                      entry.get("title"))
            ui.set(phase="working", job={"id": entry["id"], "label": job.label()}, total=0, ok=0, fail=0,
                   interval=opts.interval)
            ui.rule(f"[accent]#{entry['id']}[/] {escape(job.label())}")
            try:
                fonts = textproc.FontMapping(opts.font_map or None)
                result = Downloader(client, opts, ui, fonts).run(job)
            except KeyboardInterrupt:
                _finish(entry, None)
                ui.warn("Stopped. This novel stays in the queue and resumes from the cache.")
                break
            except Exception as e:
                ui.error(escape(f"{job.label()}: {e}"))
                result = Result(job, "failed", message=str(e))
            touched = result.ok + result.failed > 0
            _finish(entry, result, random.uniform(opts.gap_min, opts.gap_max) * 60 if touched else None)
            ui.set(job=None)
    except KeyboardInterrupt:
        ui.warn("Stopped.")
    except Exception as e:
        ui.error(escape(f"worker crashed: {e}"))
        raise
    finally:
        STOP.unlink(missing_ok=True)
        ui.close()
    return 0
