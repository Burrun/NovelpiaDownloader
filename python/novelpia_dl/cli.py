"""Command line flags and the interactive wizard."""

import argparse
import os
import re
import sys

from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt

from . import config, textproc
from .client import Novelpia
from .downloader import Downloader, Job, parse_novel_ref
from .ui import UI

RANGE_RE = re.compile(r"^(.*):(\d*)-(\d*)$")


# -- shared ------------------------------------------------------------------------

def parse_job(text, from_n=None, to_n=None, bonus="range"):
    """'12345', a novel URL, or with a range: '12345:1-50', '12345:10-', '12345:-30'."""
    text = text.strip()
    m = RANGE_RE.match(text)
    no = parse_novel_ref(m.group(1) if m else text)
    if not no:
        raise ValueError(f"not a novel number or URL: {text!r}")
    if m:
        from_n = int(m.group(2)) if m.group(2) else None
        to_n = int(m.group(3)) if m.group(3) else None
    return Job(no, from_n, to_n, bonus)


def login(client, ui, email=None, password=None, loginkey=None):
    """Returns a short description of the login state."""
    if email and password:
        with ui.status("[title]Logging in…"):
            try:
                ok = client.login(email, password)
            except Exception as e:
                ok = False
                ui.error(f"login request failed: {e}")
        if ok:
            ui.print(f"[ok]✓ Logged in[/] as {escape(email)}")
            return "email"
        ui.error("Login failed (check email / password).")
    if loginkey:
        client.loginkey = loginkey
        ui.print("[ok]✓ Using LOGINKEY[/]")
        return "loginkey"
    ui.warn("Not logged in — only free chapters can be downloaded.")
    return "none"


def dedupe(jobs, job):
    return any(j.novel_no == job.novel_no and j.from_n == job.from_n and j.to_n == job.to_n
               and j.bonus == job.bonus for j in jobs)


def settings_panel(ui, opts, login_state):
    rows = [
        ("Format", opts.fmt.upper()),
        ("Save to", os.path.abspath(opts.output_dir)),
        ("Login", login_state),
        ("Pacing", f"1 thread · ~{opts.interval:g}s between chapters · retry {opts.retry}"),
        ("Queue gap", f"{opts.gap_min:g}–{opts.gap_max:g} min (random)"),
    ]
    if opts.fmt == "epub":
        flags = [n for n, on in [("images", opts.download_image), ("styling", opts.keep_html),
                                 ("compress", opts.compress), ("vertical", opts.vertical),
                                 ("gothic", opts.gothic)] if on]
        rows.append(("EPUB", ", ".join(flags) or "-"))
    extra = [n for n, on in [("notices", opts.include_notice), ("remove blank lines", opts.remove_blank),
                             ("stop on error", opts.stop_on_error)] if on]
    if extra:
        rows.append(("Also", ", ".join(extra)))
    body = "\n".join(f"[dim]{k:<10}[/] {escape(v)}" for k, v in rows)
    ui.console.print(Panel(body, title="[title]Settings", border_style="magenta", expand=False))


# -- wizard ------------------------------------------------------------------------

def ask_int(ui, prompt):
    """Optional number: blank -> None."""
    while True:
        raw = Prompt.ask(prompt, default="", show_default=False).strip()
        if not raw:
            return None
        if raw.isdigit():
            return int(raw)
        ui.warn("Enter a number, or leave it blank.")


def wizard_login(client, ui, cfg):
    ui.rule("[title]1 · Login")
    if cfg.get("email") and cfg.get("wd"):
        if login(client, ui, cfg["email"], cfg["wd"]) == "email":
            cfg["loginkey"] = client.loginkey
            return "email"
    if cfg.get("loginkey") and Confirm.ask("Use the saved LOGINKEY?", default=True):
        return login(client, ui, loginkey=cfg["loginkey"])
    choice = Prompt.ask("How do you want to log in? [bold]1[/] email  [bold]2[/] LOGINKEY  [bold]3[/] skip",
                        choices=["1", "2", "3"], default="1")
    if choice == "1":
        email = Prompt.ask("Email", default=cfg.get("email") or None)
        password = Prompt.ask("Password", password=True)
        state = login(client, ui, email, password)
        if state == "email":
            cfg["email"] = email
            cfg["loginkey"] = client.loginkey
            if Confirm.ask("Save the password in config.json? [dim](plain text)[/]", default=False):
                cfg["wd"] = password
        return state
    if choice == "2":
        key = Prompt.ask("LOGINKEY [dim](browser dev tools → cookies)[/]").strip()
        cfg["loginkey"] = key
        return login(client, ui, loginkey=key)
    return login(client, ui)


def wizard_add(dl, ui, jobs, bonus_default):
    ref = Prompt.ask("Novel URL or number").strip()
    no = parse_novel_ref(ref)
    if not no:
        ui.error("That doesn't look like a novel number or URL.")
        return
    with ui.status(f"[title]Looking up {no}…"):
        title = dl.fetch_title(no)
    if not title:
        ui.warn(f"Couldn't read the title of {no} (wrong number, adult-only without login, or network).")
        if not Confirm.ask("Add it anyway?", default=False):
            return
    else:
        ui.print(f"  [title]{escape(title)}[/]")
    from_n = ask_int(ui, "From EP [dim](blank = first)[/]")
    to_n = ask_int(ui, "To EP [dim](blank = last)[/]")
    bonus = Prompt.ask("BONUS episodes", choices=["range", "never", "always"], default=bonus_default)
    job = Job(no, from_n, to_n, bonus, title)
    if dedupe(jobs, job):
        ui.warn("Already in the queue.")
        return
    jobs.append(job)
    ui.print(f"[ok]+ queued[/] {escape(job.label())}")


def wizard_options(opts):
    opts.fmt = Prompt.ask("Format", choices=["epub", "txt"], default=opts.fmt)
    opts.output_dir = Prompt.ask("Save to folder", default=opts.output_dir)
    if not Confirm.ask("Change advanced options?", default=False):
        return
    b = lambda q, v: Confirm.ask(q, default=v)  # noqa: E731
    if opts.fmt == "epub":
        opts.download_image = b("Download cover & illustrations?", opts.download_image)
        opts.keep_html = b("Keep bold/italic styling?", opts.keep_html)
        opts.compress = b("Compress EPUB?", opts.compress)
        opts.vertical = b("Vertical writing?", opts.vertical)
        opts.gothic = b("Gothic (sans-serif) font?", opts.gothic)
    opts.include_notice = b("Include author notices?", opts.include_notice)
    opts.remove_blank = b("Remove blank lines?", opts.remove_blank)
    opts.name_with_no = b("Put novel number in file name?", opts.name_with_no)
    opts.name_with_range = b("Put episode range in file name?", opts.name_with_range)
    opts.stop_on_error = b("Stop a novel on the first failed chapter?", opts.stop_on_error)
    opts.interval = FloatPrompt.ask("Mean seconds between chapters", default=opts.interval)
    opts.retry = IntPrompt.ask("Retries per request", default=opts.retry)
    opts.gap_min = FloatPrompt.ask("Break between novels — min minutes", default=opts.gap_min)
    opts.gap_max = max(opts.gap_min, FloatPrompt.ask("Break between novels — max minutes", default=opts.gap_max))
    opts.font_map = Prompt.ask("Font mapping JSON [dim](blank = none)[/]", default=opts.font_map or "") or ""


def run_wizard(args, ui, cfg, opts):
    client = Novelpia()
    state = wizard_login(client, ui, cfg)
    dl = Downloader(client, opts, ui)
    bonus_default = config.default_bonus(cfg)

    ui.rule("[title]2 · Queue")
    jobs = []
    while True:
        if not jobs:
            wizard_add(dl, ui, jobs, bonus_default)
            continue
        ui.queue_table(jobs)
        action = Prompt.ask("[bold]a[/]dd novel · [bold]r[/]emove · [bold]s[/]tart · [bold]q[/]uit",
                            choices=["a", "r", "s", "q"], default="s")
        if action == "a":
            wizard_add(dl, ui, jobs, bonus_default)
        elif action == "r":
            idx = IntPrompt.ask("Remove #", choices=[str(i) for i in range(1, len(jobs) + 1)])
            ui.print(f"[warn]- removed[/] {escape(jobs.pop(idx - 1).label())}")
        elif action == "q":
            return 0
        else:
            break

    ui.rule("[title]3 · Options")
    wizard_options(opts)
    settings_panel(ui, opts, state)
    config.save(args.config, cfg, opts)
    if not Confirm.ask(f"Start downloading {len(jobs)} novel(s)?", default=True):
        return 0
    return execute(dl, ui, jobs, opts)


# -- flags -------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="novelpia_dl",
        description="Download Novelpia novels as EPUB (default) or TXT. "
                    "Run without novels for the interactive wizard.",
        epilog="examples:\n"
               "  python -m novelpia_dl                      # wizard\n"
               "  python -m novelpia_dl 12345 67890:1-50     # queue two novels\n"
               "  python -m novelpia_dl -q list.txt --txt    # one novel per line",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("novels", nargs="*", help="novel number or URL, optionally NO:FROM-TO (e.g. 12345:1-50)")
    p.add_argument("-i", "--interactive", action="store_true", help="force the wizard")
    p.add_argument("-q", "--queue-file", help="text file, one novel (NO or NO:FROM-TO) per line")
    p.add_argument("-c", "--config", default="config.json", help="config file (default: ./config.json)")

    g = p.add_argument_group("login")
    g.add_argument("--email")
    g.add_argument("--password", help="or set NOVELPIA_PASSWORD")
    g.add_argument("--loginkey")

    g = p.add_argument_group("what to download")
    g.add_argument("--from", dest="from_n", type=int, help="first EP (for novels without their own range)")
    g.add_argument("--to", dest="to_n", type=int, help="last EP")
    g.add_argument("--bonus", choices=["range", "never", "always"], help="BONUS episodes (default: range)")
    g.add_argument("--notice", action=argparse.BooleanOptionalAction, default=None, help="include author notices")

    g = p.add_argument_group("output")
    fmt = g.add_mutually_exclusive_group()
    fmt.add_argument("--epub", dest="fmt", action="store_const", const="epub", help="EPUB (default)")
    fmt.add_argument("--txt", dest="fmt", action="store_const", const="txt", help="plain text")
    g.add_argument("-o", "--output", help="output folder")
    g.add_argument("--images", action=argparse.BooleanOptionalAction, default=None, help="cover & illustrations")
    g.add_argument("--styling", action=argparse.BooleanOptionalAction, default=None, help="keep bold/italic (EPUB)")
    g.add_argument("--compress", action=argparse.BooleanOptionalAction, default=None)
    g.add_argument("--vertical", action=argparse.BooleanOptionalAction, default=None)
    g.add_argument("--gothic", action=argparse.BooleanOptionalAction, default=None)
    g.add_argument("--remove-blank", action=argparse.BooleanOptionalAction, default=None)
    g.add_argument("--name-no", action=argparse.BooleanOptionalAction, default=None, help="novel no. in file name")
    g.add_argument("--name-range", action=argparse.BooleanOptionalAction, default=None, help="range in file name")
    g.add_argument("--font-map", help="font mapping JSON")

    g = p.add_argument_group("pacing (always 1 thread)")
    g.add_argument("--interval", type=float, help="mean seconds between chapters (default 22.3)")
    g.add_argument("--retry", type=int, help="retries per request (default 3)")
    g.add_argument("--gap-min", type=float, help="min minutes between novels (default 5)")
    g.add_argument("--gap-max", type=float, help="max minutes between novels (default 10)")
    g.add_argument("--stop-on-error", action=argparse.BooleanOptionalAction, default=None)
    g.add_argument("--save-config", action="store_true", help="write these settings to the config file")
    return p


FLAG_TO_OPT = {
    "fmt": "fmt", "output": "output_dir", "notice": "include_notice", "images": "download_image",
    "styling": "keep_html", "compress": "compress", "vertical": "vertical", "gothic": "gothic",
    "remove_blank": "remove_blank", "name_no": "name_with_no", "name_range": "name_with_range",
    "font_map": "font_map", "interval": "interval", "retry": "retry", "gap_min": "gap_min",
    "gap_max": "gap_max", "stop_on_error": "stop_on_error",
}


def run_flags(args, ui, cfg, opts):
    bonus = args.bonus or config.default_bonus(cfg)
    lines = list(args.novels)
    if args.queue_file:
        with open(args.queue_file, encoding="utf-8") as f:
            lines += [ln.split("#", 1)[0].strip() for ln in f]
    jobs = []
    for ln in filter(None, lines):
        try:
            job = parse_job(ln, args.from_n, args.to_n, bonus)
        except ValueError as e:
            ui.error(str(e))
            return 2
        if not dedupe(jobs, job):
            jobs.append(job)
    if not jobs:
        ui.error("No novels given.")
        return 2

    client = Novelpia()
    state = login(client, ui,
                  args.email or cfg.get("email"),
                  args.password or os.environ.get("NOVELPIA_PASSWORD") or cfg.get("wd"),
                  args.loginkey or cfg.get("loginkey"))
    if args.save_config:
        if state == "email":
            cfg["loginkey"] = client.loginkey
        elif args.loginkey:
            cfg["loginkey"] = args.loginkey
        config.save(args.config, cfg, opts, args.bonus)
        ui.print(f"[dim]settings saved to {escape(args.config)}[/]")
    dl = Downloader(client, opts, ui)
    settings_panel(ui, opts, state)
    ui.queue_table(jobs)
    return execute(dl, ui, jobs, opts)


def execute(dl, ui, jobs, opts):
    if opts.font_map:
        try:
            dl.fonts = textproc.FontMapping(opts.font_map)
        except (OSError, ValueError) as e:
            ui.error(f"font mapping: {e}")
            return 2
    results = dl.run_queue(jobs)
    ui.summary(results)
    return 0 if all(r.status == "done" for r in results) else 1


def main(argv=None):
    args = build_parser().parse_args(argv)
    ui = UI()
    ui.banner()
    cfg = config.load(args.config)
    opts = config.options_from(cfg)
    for flag, attr in FLAG_TO_OPT.items():
        if getattr(args, flag) is not None:
            setattr(opts, attr, getattr(args, flag))
    opts.gap_max = max(opts.gap_min, opts.gap_max)
    try:
        if args.interactive or not (args.novels or args.queue_file):
            if not sys.stdin.isatty():
                ui.error("No novels given and no terminal for the wizard. See --help.")
                return 2
            return run_wizard(args, ui, cfg, opts)
        return run_flags(args, ui, cfg, opts)
    except KeyboardInterrupt:
        ui.warn("Interrupted.")
        return 130
