"""Terminal presentation with rich."""

import time
from contextlib import contextmanager

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn,
                           TimeElapsedColumn, TimeRemainingColumn)
from rich.table import Table
from rich.theme import Theme

from . import __version__

THEME = Theme({
    "ok": "bold green", "fail": "bold red", "warn": "yellow", "dim": "grey50",
    "accent": "bold magenta", "title": "bold cyan",
})

STATUS_STYLE = {"done": "ok", "partial": "warn", "failed": "fail", "cancelled": "warn", "skipped": "dim"}


def fmt_secs(s):
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s}s"


class UI:
    def __init__(self, console=None):
        self.console = console or Console(theme=THEME, highlight=False)
        self._progress = None
        self._task = None

    # -- plain messages --------------------------------------------------------
    def print(self, *a, **kw):
        (self._progress.console if self._progress else self.console).print(*a, **kw)

    def info(self, msg):
        self.print(f"[title]›[/] {msg}")

    def warn(self, msg):
        self.print(f"[warn]![/] {msg}")

    def error(self, msg):
        self.print(f"[fail]✗[/] {msg}")

    def item_ok(self, text, cached=False):
        self.print(f"  [ok]✓[/] {escape(text)}" + ("  [dim](cached)[/]" if cached else ""))

    def item_fail(self, text, why=""):
        self.print(f"  [fail]✗[/] {escape(text)}" + (f"  [dim]({escape(why)})[/]" if why else ""))

    def item_retry(self, what, attempt, total):
        self.print(f"  [warn]↻[/] [dim]{escape(what)}: retry {attempt}/{total}[/]")

    def banner(self):
        self.console.print(Panel.fit(
            "[title]Novelpia Downloader[/]  [dim]terminal edition v" + __version__ + "[/]\n"
            "[dim]EPUB / TXT · queue · single thread with human-like pacing[/]",
            border_style="magenta", box=box.ROUNDED))

    def rule(self, text):
        self.console.rule(text, style="magenta")

    @contextmanager
    def status(self, text):
        with self.console.status(text, spinner="dots") as st:
            yield st

    # -- chapter progress --------------------------------------------------------
    @contextmanager
    def chapter_progress(self, total):
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[title]{task.description}"),
            BarColumn(bar_width=None),
            MofNCompleteColumn(),
            TextColumn("[ok]✓{task.fields[ok]}[/] [fail]✗{task.fields[fail]}[/]"),
            TimeElapsedColumn(),
            TextColumn("[dim]eta[/]"),
            TimeRemainingColumn(),
            TextColumn("{task.fields[status]}"),
            console=self.console, transient=False,
        )
        with progress:
            self._progress = progress
            self._task = progress.add_task("chapters", total=total, ok=0, fail=0, status="")
            try:
                yield self
            finally:
                self._progress = None
                self._task = None

    def advance(self, ok, fail):
        if self._progress:
            self._progress.update(self._task, advance=1, ok=ok, fail=fail, status="")

    def set_status(self, text):
        if self._progress:
            self._progress.update(self._task, status=text)

    def sleep(self, seconds, reason):
        """Wait, showing a countdown in the active progress bar (Ctrl+C aborts)."""
        end = time.monotonic() + seconds
        if not self._progress:
            with self.status("") as st:
                while (left := end - time.monotonic()) > 0:
                    st.update(f"[dim]{reason} {fmt_secs(left)}[/]")
                    time.sleep(min(0.25, left))
            return
        while (left := end - time.monotonic()) > 0:
            self.set_status(f"[dim]⏳ {reason} {fmt_secs(left)}[/]")
            time.sleep(min(0.25, left))
        self.set_status("")

    def gap(self, seconds, next_label):
        """Countdown between novels."""
        progress = Progress(
            TextColumn("[accent]☕ Break before next novel[/]"),
            BarColumn(bar_width=None, complete_style="magenta"),
            TextColumn("[title]{task.fields[left]}[/] left"),
            TextColumn("[dim]→ {task.fields[next]}[/]", markup=False),
            console=self.console, transient=True,
        )
        with progress:
            task = progress.add_task("gap", total=seconds, left=fmt_secs(seconds), next=next_label)
            start = time.monotonic()
            while (done := time.monotonic() - start) < seconds:
                progress.update(task, completed=done, left=fmt_secs(seconds - done))
                time.sleep(0.5)
        self.print(f"[dim]  rested {fmt_secs(seconds)}[/]")

    # -- tables ----------------------------------------------------------------
    def queue_table(self, jobs, title="Queue"):
        t = Table(title=title, box=box.SIMPLE_HEAVY, title_style="title", header_style="accent")
        t.add_column("#", justify="right", style="dim")
        t.add_column("Novel", style="title")
        t.add_column("Title")
        t.add_column("Range")
        t.add_column("BONUS")
        for i, j in enumerate(jobs, 1):
            t.add_row(str(i), j.novel_no, escape(j.title) if j.title else "[dim]?[/]", j.range_text(), j.bonus)
        self.console.print(t)

    def summary(self, results):
        t = Table(title="Summary", box=box.ROUNDED, title_style="title", header_style="accent")
        t.add_column("Novel", style="title")
        t.add_column("Title")
        t.add_column("Result")
        t.add_column("✓", justify="right", style="ok")
        t.add_column("✗", justify="right", style="fail")
        t.add_column("File / note", overflow="fold")
        for r in results:
            style = STATUS_STYLE.get(r.status, "")
            t.add_row(r.job.novel_no, escape(r.job.title or ""), f"[{style}]{r.status}[/]",
                      str(r.ok), str(r.failed), escape(r.path or r.message))
        self.console.print(t)
