"""Live view of the background worker. Ctrl+C opens a menu; detaching leaves it running."""

import time

from rich import box
from rich.console import Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from . import config, service, textproc
from .client import Novelpia
from .downloader import Job, parse_novel_ref
from .ui import STATUS_STYLE, eta_seconds, fmt_eta, fmt_secs


def _markup(line):
    try:
        t = Text.from_markup(line)
    except Exception:
        t = Text(line)
    t.no_wrap = True                  # one line each, so the screen height stays predictable
    t.overflow = "ellipsis"
    return t


def _log_view(lines):
    out = []
    for ln in lines:
        if ln.startswith("\x00rule "):
            out.append(Rule(_markup(ln[6:]), style="magenta"))
        else:
            out.append(_markup(ln))
    return out


MARKS = {"ok": "[ok]✓[/]", "cached": "[ok]✓[/]", "fail": "[fail]✗[/]", "now": "[title]▶[/]"}


def ep_page(s, size, page=None):
    """One page of the current novel's EP list. page=None follows the chapter being downloaded.
    Returns (renderables, page_index, page_count)."""
    labels = s.get("chapters") or []
    if not labels:
        return [], 0, 0
    marks = s.get("marks") or {}
    size = max(1, size)
    pages = (len(labels) + size - 1) // size
    current = max((int(k) for k in marks), default=0)
    p = current // size if page is None else max(0, min(page, pages - 1))
    out = []
    for i in range(p * size, min(len(labels), (p + 1) * size)):
        m = marks.get(str(i))
        text = escape(labels[i])
        if m == "now":
            text = f"[title]{text}[/]  [dim]← now[/]"
        elif m == "cached":
            text += "  [dim](cached)[/]"
        elif m is None:
            text = f"[dim]{text}[/]"
        out.append(_markup(f" {MARKS.get(m, '[dim]·[/]')} {text}"))
    done = sum(v != "now" for v in marks.values())
    out.append(_markup(f"[dim]  EP list · page [/][bold]{p + 1}[/][dim]/{pages} · {done}/{len(labels)} done[/]"))
    return out, p, pages


def queue_table(q):
    jobs = q["jobs"]
    t = Table(box=box.SIMPLE_HEAVY, header_style="accent", title_style="title", pad_edge=False,
              title=f"Queue · {sum(e['state'] == 'pending' for e in jobs)} waiting")
    t.add_column("ID", justify="right", style="dim")
    t.add_column("Novel", style="title")
    t.add_column("Title", overflow="ellipsis", no_wrap=True, max_width=40)
    t.add_column("Range")
    t.add_column("BONUS")
    t.add_column("Format")
    t.add_column("")
    for e in jobs:
        job = Job(e["novel_no"], e.get("from_n"), e.get("to_n"))
        t.add_row(str(e["id"]), e["novel_no"], escape(e.get("title") or "?"), job.range_text(),
                  e.get("bonus", "range"), e["opts"].get("fmt", "epub"),
                  "[ok]▶ now[/]" if e["state"] == "running" else "")
    return t


def history_table(q, limit=8):
    t = Table(box=box.SIMPLE, header_style="accent", title="Finished", title_style="title", pad_edge=False)
    t.add_column("ID", justify="right", style="dim")
    t.add_column("Title", overflow="ellipsis", no_wrap=True, max_width=40)
    t.add_column("Result")
    t.add_column("✓", justify="right", style="ok")
    t.add_column("✗", justify="right", style="fail")
    t.add_column("File / note", overflow="ellipsis", no_wrap=True, max_width=60)
    for h in q["history"][-limit:]:
        style = STATUS_STYLE.get(h["status"], "")
        t.add_row(str(h["id"]), escape(h.get("title") or h["novel_no"]), f"[{style}]{h['status']}[/]",
                  str(h["ok"]), str(h["failed"]), escape(h.get("path") or h.get("message") or ""))
    return t


def render(s, q, height=40, show_log=True):
    alive = service.worker_alive(s)
    now = time.time()
    rows = []
    if not alive:
        pending = len(q["jobs"])
        head = "[warn]● not running[/]" + (f" · {pending} novel(s) waiting — choose [bold]start[/] in the menu"
                                         if pending else " · queue empty")
    else:
        head = f"[ok]● running[/] [dim](pid {s.get('pid')})[/]"
    rows.append(Text.from_markup(head))

    if alive and s.get("phase") == "gap":
        total = s.get("countdown_total") or 1
        left = max(0, (s.get("countdown_end") or now) - now)
        rows.append(Text.from_markup("[accent]☕ Break before next novel[/]  "
                                     f"[title]{fmt_secs(left)}[/] left  [dim]→ {s.get('status', '')}[/]"))
        rows.append(ProgressBar(total=total, completed=total - left, complete_style="magenta"))
    elif alive and s.get("job"):
        rows.append(Text.from_markup(f"[title]{escape(s['job']['label'])}[/]"))
        total, ok, fail = s.get("total", 0), s.get("ok", 0), s.get("fail", 0)
        if total:
            done = ok + fail
            elapsed = now - (s.get("started") or now)
            eta = eta_seconds(done, total, elapsed, s.get("interval") or 20)
            grid = Table.grid(padding=(0, 2), expand=True)
            grid.add_column(ratio=1)
            grid.add_column(no_wrap=True)
            grid.add_row(ProgressBar(total=total, completed=done, complete_style="cyan"), Text.from_markup(
                f"{done}/{total}  [ok]✓{ok}[/] [fail]✗{fail}[/]  [dim]elapsed[/] {fmt_secs(elapsed)}  "
                f"[dim]eta[/] {fmt_eta(eta)}"))
            rows.append(grid)
        line = s.get("status", "")
        if s.get("countdown_end"):
            line = f"⏳ {s.get('countdown_label', '')} {fmt_secs(max(0, s['countdown_end'] - now))}"
        rows.append(_markup(f"[dim]{line}[/]" if line else ""))

    parts = [Panel(Group(*rows), title="[title]Novelpia Downloader", border_style="magenta",
                   box=box.ROUNDED)]
    table = queue_table(q) if q["jobs"] else Text.from_markup("[dim]Queue is empty.[/]")
    # lines left after the panel, queue table and hint
    budget = height - (len(rows) + 2) - (len(q["jobs"]) + 5 if q["jobs"] else 1) - 2
    if show_log and budget > 2:
        has_eps = alive and bool(s.get("chapters"))
        log_lines = min(4, budget // 3) if has_eps else budget
        parts += _log_view(s.get("log", [])[-log_lines:]) if log_lines > 0 else []
        if has_eps:
            page, _, _ = ep_page(s, min(40, budget - log_lines - 1))
            parts += page
    parts.append(table)
    parts.append(Text.from_markup("[dim]Ctrl+C → menu: add novel · remove · EP pages · stop · detach[/]"))
    return Group(*parts)


def show_status(console):
    console.print(render(service.read_status(), service.read_queue(), height=10 ** 6, show_log=False))
    q = service.read_queue()
    if q["history"]:
        console.print(history_table(q))


# -- menu -------------------------------------------------------------------------------

def _ask_int(console, prompt):
    while True:
        raw = Prompt.ask(prompt, default="", show_default=False).strip()
        if not raw:
            return None
        if raw.isdigit():
            return int(raw)
        console.print("[warn]Enter a number, or leave it blank.[/]")


def menu_add(console, config_path):
    cfg = config.load(config_path)
    opts = config.options_from(cfg)
    ref = Prompt.ask("Novel URL or number").strip()
    no = parse_novel_ref(ref)
    if not no:
        console.print("[fail]That doesn't look like a novel number or URL.[/]")
        return
    title = None
    with console.status(f"[title]Looking up {no}…"):
        try:
            title = textproc.novel_title(Novelpia(cfg.get("loginkey") or None).novel_page(no))
        except Exception:
            pass
    console.print(f"  [title]{escape(title)}[/]" if title else "  [warn]title not found (added anyway)[/]")
    from_n = _ask_int(console, "From EP [dim](blank = first)[/]")
    to_n = _ask_int(console, "To EP [dim](blank = last)[/]")
    bonus = Prompt.ask("BONUS episodes", choices=["range", "never", "always"],
                       default=config.default_bonus(cfg))
    opts.fmt = Prompt.ask("Format", choices=["epub", "txt"], default=opts.fmt)
    added = service.add_jobs([Job(no, from_n, to_n, bonus, title)], opts)
    if added:
        console.print(f"[ok]+ queued[/] #{added[0]['id']} {escape(service.job_label(added[0]))}")
    else:
        console.print("[warn]Already in the queue.[/]")
    if not service.worker_alive():
        service.start_worker(config_path)


def browse_pages(console):
    size = max(5, min(40, console.size.height - 4))
    page = None
    while True:
        lines, page, pages = ep_page(service.read_status(), size, page)
        if not lines:
            console.print("[dim]No novel is downloading right now.[/]")
            return
        console.rule("[title]EP list", style="magenta")
        console.print(Group(*lines))
        try:
            key = Prompt.ask("[bold]n[/]ext · [bold]p[/]rev · [bold]f[/]ollow current · [bold]number[/] · "
                             "[bold]q[/] back", default="n", show_default=False).strip().lower()
        except (KeyboardInterrupt, EOFError):
            return
        if key == "q":
            return
        if key == "p":
            page = max(0, page - 1)
        elif key == "f":
            page = None
        elif key.isdigit():
            page = int(key) - 1
        else:
            page = min(pages - 1, page + 1)


def menu(console, config_path):
    """Returns True to keep watching, False to leave."""
    alive = service.worker_alive()
    q = service.read_queue()
    console.print(queue_table(q) if q["jobs"] else "[dim]Queue is empty.[/]")
    choices = {"a": "add novel", "r": "remove", "s": "stop downloader" if alive else "start downloader",
               "p": "EP pages", "h": "finished list", "d": "detach (keeps running)" if alive else "exit", "c": "continue watching"}
    console.print("  ".join(f"[bold]{k}[/] {v}" for k, v in choices.items()))
    try:
        action = Prompt.ask("Choose", choices=list(choices), default="c", show_choices=False)
    except (KeyboardInterrupt, EOFError):
        return False
    if action == "a":
        menu_add(console, config_path)
    elif action == "r":
        waiting = [e for e in q["jobs"] if e["state"] == "pending"]
        if not waiting:
            console.print("[dim]Nothing waiting to remove.[/]")
        else:
            job_id = IntPrompt.ask("Remove ID", choices=[str(e["id"]) for e in waiting])
            e = service.remove_job(job_id)
            console.print(f"[warn]- removed[/] {escape(service.job_label(e))}" if e else
                          "[warn]That one is already running; stop it instead.[/]")
    elif action == "s":
        if alive:
            if Confirm.ask("Stop after the current chapter? [dim](progress is cached; start again to resume)[/]",
                           default=True):
                service.request_stop()
                console.print("[warn]Stopping…[/]")
        else:
            if service.start_worker(config_path):
                console.print("[ok]Downloader started.[/]")
            else:
                console.print(f"[fail]Could not start the downloader. See {service.STATE / 'worker.out'}[/]")
    elif action == "p":
        browse_pages(console)
    elif action == "h":
        console.print(history_table(q, limit=50))
        Prompt.ask("[dim]Enter to go back[/]", default="", show_default=False)
    elif action == "d":
        return False
    return True


def attach(console, config_path):
    console.print("[dim]Watching the downloader. Ctrl+C for the menu.[/]")
    was_alive = service.worker_alive()
    while True:
        try:
            with Live(console=console, refresh_per_second=4, transient=True) as live:
                while True:
                    s, q = service.read_status(), service.read_queue()
                    live.update(render(s, q, console.size.height))
                    alive = service.worker_alive(s)
                    if was_alive and not alive and not any(e["state"] == "pending" for e in q["jobs"]):
                        break           # worker finished everything
                    was_alive = was_alive or alive
                    time.sleep(0.25)
            console.print(render(service.read_status(), service.read_queue(), height=24, show_log=False))
            q = service.read_queue()
            if q["history"]:
                console.print(history_table(q))
            console.print("[ok]All done.[/]")
            return 0
        except KeyboardInterrupt:
            pass
        if not menu(console, config_path):
            if service.worker_alive():
                console.print("[dim]Detached — the download continues in the background.\n"
                              "Come back with:[/] python -m novelpia_dl attach")
            return 0
        was_alive = service.worker_alive()
