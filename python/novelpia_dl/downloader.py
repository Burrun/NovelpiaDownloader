"""Download one novel / a queue of novels. Single-threaded by design."""

import hashlib
import json
import random
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from rich.markup import escape as _esc

from . import epub, textproc

INVALID_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
NOTICE_LABEL = "공지"


@dataclass
class Options:
    fmt: str = "epub"                 # "epub" | "txt"
    output_dir: str = "."
    include_notice: bool = False
    remove_blank: bool = False
    keep_html: bool = True            # keep bold/italic etc. in EPUB
    compress: bool = True
    download_image: bool = True
    stop_on_error: bool = False
    name_with_no: bool = False
    name_with_range: bool = False
    vertical: bool = False
    gothic: bool = False
    interval: float = 22.3            # mean seconds between chapters
    retry: int = 3
    gap_min: float = 5.0              # minutes between novels in a queue
    gap_max: float = 10.0
    font_map: str = ""


@dataclass
class Job:
    novel_no: str
    from_n: int | None = None
    to_n: int | None = None
    bonus: str = "range"              # "range" | "never" | "always"
    title: str | None = None

    def range_text(self):
        if self.from_n is None and self.to_n is None:
            return "all"
        return f"{self.from_n or 0}-{self.to_n if self.to_n is not None else 'end'}"

    def label(self):
        return f"[{self.novel_no}] {self.title or self.novel_no} ({self.range_text()})"


@dataclass
class Result:
    job: Job
    status: str                       # done | partial | failed | cancelled | skipped
    ok: int = 0
    failed: int = 0
    path: str = ""
    message: str = ""


@dataclass
class Chapter:
    kind: str                         # EP | BONUS | NOTICE
    chapter_id: str
    name: str
    ep_no: int
    stem: str = ""
    toc_title: str = ""
    log_label: str = ""


class Aborted(Exception):
    """stop_on_error tripped."""


def parse_novel_ref(text):
    """'12345', 'https://novelpia.com/novel/12345' -> '12345' (or None)."""
    m = re.search(r"novel/(\d+)", text)
    if m:
        return m.group(1)
    m = re.search(r"\d+", text)
    return m.group(0) if m else None


def safe_filename(name):
    return INVALID_NAME_RE.sub("_", name).strip().rstrip(".") or "novel"


class Pacer:
    """Random delays that look less like a bot."""

    def __init__(self, interval):
        self.interval = interval
        self.offset = 0.0

    @staticmethod
    def short(maximum=5.0):
        return random.uniform(1.0, maximum)

    def chapter(self):
        # Bounded AR(1), rho = 0.8. min of three uniforms has mean 0.25 so the
        # asymmetric innovation has mean zero; offset stays within [-5, 15].
        self.offset = 0.8 * self.offset + 4 * min(random.random(), random.random(), random.random()) - 1
        return max(0.0, self.interval + self.offset)


class Downloader:
    def __init__(self, client, opts, ui, fonts=None):
        self.client = client
        self.opts = opts
        self.ui = ui
        self.fonts = fonts or textproc.FontMapping()
        self.pacer = Pacer(opts.interval)

    # -- helpers -----------------------------------------------------------------
    def _retry(self, what, fn, validate=None):
        """Run fn with retries. Returns its value, or None after the last failure."""
        last = ""
        for attempt in range(self.opts.retry + 1):
            if attempt:
                self.ui.item_retry(what, attempt, self.opts.retry)
                self.ui.sleep(self.pacer.short(), "retry in")
            try:
                value = fn()
                if validate:
                    validate(value)
                return value
            except (KeyboardInterrupt, Aborted):
                raise
            except Exception as e:  # network / parse
                last = str(e) or type(e).__name__
        self.ui.item_fail(what, last)
        return None

    def target_path(self, job):
        title = safe_filename(job.title or job.novel_no)
        if self.opts.name_with_no:
            title = f"{job.novel_no}_{title}"
        if self.opts.name_with_range and (job.from_n is not None or job.to_n is not None):
            title = f"{title}_{job.range_text()}"
        return Path(self.opts.output_dir) / f"{title}.{self.opts.fmt}"

    def fetch_title(self, novel_no):
        try:
            return textproc.novel_title(self.client.novel_page(novel_no))
        except Exception:
            return None

    # -- chapter list ------------------------------------------------------------
    def list_chapters(self, job):
        to = job.to_n if job.to_n is not None else float("inf")
        seen, found = set(), []
        page = 0
        with self.ui.status("[title]Fetching episode list…") as st:
            while True:
                time.sleep(self.pacer.short(3.0))
                resp = self._retry(f"episode list page {page}",
                                   lambda: self.client.episode_list(job.novel_no, page))
                if resp is None:
                    raise RuntimeError("could not load the episode list")
                items = textproc.episodes(resp)
                if not items or items[0][1] in seen:
                    break
                stop = False
                for kind, cid, name, ep_no in items:
                    if cid in seen:
                        continue
                    seen.add(cid)
                    found.append(Chapter(kind, cid, name, ep_no))
                    # Past the EP cap: stop, unless "always BONUS" must sweep trailing BONUS.
                    if kind == "EP" and ep_no > to and job.bonus != "always":
                        stop = True
                        break
                st.update(f"[title]Fetching episode list…[/] [dim]{len(found)} found (page {page + 1})[/]")
                if stop:
                    break
                page += 1
        return found

    @staticmethod
    def select(job, chapters):
        """Apply the range/BONUS rules of the original program.

        A BONUS after the final EP gets a virtual number (last EP + 1, + 2, ...)
        so a bounded range can reach it; a mid-story BONUS follows the range
        membership of the EP before it and does not use an EP number.
        """
        lo = job.from_n or 0
        hi = job.to_n if job.to_n is not None else float("inf")
        max_ep = max((c.ep_no for c in chapters if c.kind == "EP"), default=0)
        out = []
        bonus_idx = tail_idx = running_max = last_ep = 0
        for c in chapters:
            if c.kind == "BONUS":
                bonus_idx += 1
                if job.bonus == "never":
                    continue
                if job.bonus != "always":
                    if max_ep > 0 and running_max >= max_ep:
                        tail_idx += 1
                        virtual = max_ep + tail_idx
                        if virtual < lo:
                            continue
                        if virtual > hi:
                            break
                    elif last_ep < lo or last_ep > hi:
                        continue
                c.stem = f"bonus_{bonus_idx:04d}"
                c.log_label = f"BONUS {c.name}"
                c.toc_title = c.name
            else:
                running_max = max(running_max, c.ep_no)
                last_ep = c.ep_no
                if not lo <= c.ep_no <= hi:
                    continue
                c.stem = f"{c.ep_no:04d}"
                c.log_label = f"EP.{c.ep_no:04d} {c.name}"
                c.toc_title = c.name
            out.append(c)
        return out

    # -- one novel -----------------------------------------------------------------
    def run(self, job):
        opts = self.opts
        with self.ui.status(f"[title]Opening novel {job.novel_no}…"):
            page = self._retry("novel page", lambda: self.client.novel_page(job.novel_no))
        if page is None:
            return Result(job, "failed", message="novel page could not be loaded")
        job.title = textproc.novel_title(page) or job.title or job.novel_no
        author = textproc.novel_author(page)
        self.ui.info(f"[title]{_esc(job.title)}[/]" + (f" [dim]· {_esc(author)}[/]" if author else ""))

        chapters = []
        if opts.include_notice:
            for i, (cid, name) in enumerate(textproc.notices(page), 1):
                label = f"[{NOTICE_LABEL}] {name}"
                chapters.append(Chapter("NOTICE", cid, name, 0, f"notice_{i:04d}", label, label))

        chapters += self.select(job, self.list_chapters(job))
        if not any(c.kind != "NOTICE" for c in chapters):
            return Result(job, "failed", message="no chapters in the selected range")
        if opts.fmt == "epub":
            for c in chapters:
                if c.kind != "NOTICE":
                    c.toc_title = textproc.epub_chapter_title(c.name, c.kind == "BONUS", c.ep_no)
        self.ui.info(f"{len(chapters)} chapter(s) selected")

        out_dir = Path(opts.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        cache = out_dir / ".novelpia_cache" / job.novel_no
        cache.mkdir(parents=True, exist_ok=True)
        path = self.target_path(job)

        cover = None
        if opts.fmt == "epub" and opts.download_image:
            url = textproc.cover_url(page)
            if url:
                cover = self._cached_bytes(cache / "cover.bin", "cover", url)

        images = {}                   # url -> (name, bytes)
        built = []                    # (toc_title, stem, body)
        ok = failed = 0
        aborted = False
        fetched_any = False

        def add_image(url):
            if url in images:
                return f"../Images/{images[url][0]}"
            key = hashlib.sha1(url.encode()).hexdigest()[:16]
            data = self._cached_bytes(cache / f"img_{key}.bin", "illustration", url, pace=True)
            if data is None:
                return None
            name = f"{len(images) + 1}.{epub.image_type(data)[0]}"
            images[url] = (name, data)
            return f"../Images/{name}"

        try:
            with self.ui.chapter_progress(len(chapters)):
                for c in chapters:
                    jpath = cache / f"{c.stem}.json"
                    data, cached = None, False
                    if jpath.exists():
                        data = jpath.read_text(encoding="utf-8")
                        cached = True
                    else:
                        if fetched_any:
                            self.ui.sleep(self.pacer.chapter(), "next chapter in")
                        fetched_any = True
                        self.ui.set_status(f"[dim]{_esc(c.log_label[:30])}[/]")
                        data = self._retry(c.log_label, lambda: self.client.viewer_data(c.chapter_id),
                                           validate=_check_viewer)
                        if data is not None:
                            jpath.write_text(data, encoding="utf-8")
                    if data is None:
                        failed += 1
                        self.ui.advance(ok, failed)
                        if opts.stop_on_error:
                            raise Aborted()
                        continue
                    try:
                        if opts.fmt == "epub":
                            body = textproc.chapter_xhtml(c.toc_title, data, opts, self.fonts, add_image)
                        else:
                            body = textproc.chapter_txt(c.toc_title, data, opts, self.fonts)
                    except (KeyboardInterrupt, Aborted):
                        raise
                    except Exception as e:
                        failed += 1
                        self.ui.item_fail(c.log_label, f"parse error: {e}")
                        self.ui.advance(ok, failed)
                        jpath.unlink(missing_ok=True)
                        if opts.stop_on_error:
                            raise Aborted()
                        continue
                    built.append((c.toc_title, c.stem, body))
                    ok += 1
                    self.ui.item_ok(c.log_label, cached)
                    self.ui.advance(ok, failed)
        except Aborted:
            aborted = True
            self.ui.warn("Stopped on error (stop-on-error is on).")
        except KeyboardInterrupt:
            self.ui.warn(f"Cancelled. Downloaded chapters are cached in {cache} — run again to resume.")
            raise

        if not built:
            return Result(job, "failed", ok, failed, message="nothing downloaded")

        if opts.fmt == "epub":
            epub.write_epub(path, novel_no=job.novel_no, title=job.title, author=author, chapters=built,
                            images=list(images.values()), cover=cover, compress=opts.compress,
                            vertical=opts.vertical, gothic=opts.gothic)
        else:
            path.write_text("".join(b for _, _, b in built), encoding="utf-8")

        if failed == 0 and not aborted:
            shutil.rmtree(cache, ignore_errors=True)
            _rmdir_if_empty(cache.parent)
            status = "done"
        else:
            status = "partial"
            self.ui.warn(f"{failed} chapter(s) failed; cache kept in {cache} — run again to retry them.")
        self.ui.print(f"[ok]Saved[/] {_esc(str(path))}")
        return Result(job, status, ok, failed, str(path))

    def _cached_bytes(self, file, what, url, pace=False):
        if file.exists():
            return file.read_bytes()
        if pace:
            self.ui.sleep(self.pacer.short(), f"{what} in")
        data = self._retry(f"{what} {url}", lambda: self.client.fetch_bytes(url))
        if data is not None:
            file.write_bytes(data)
        return data

    # -- queue -----------------------------------------------------------------------
    def run_queue(self, jobs):
        results = []
        for i, job in enumerate(jobs):
            try:
                if i:
                    gap = random.uniform(self.opts.gap_min, self.opts.gap_max) * 60
                    if gap > 0:
                        self.ui.gap(gap, job.label())
                self.ui.rule(f"[accent][{i + 1}/{len(jobs)}][/] {_esc(job.label())}")
                results.append(self.run(job))
            except KeyboardInterrupt:
                results.append(Result(job, "cancelled", message="cancelled by user"))
                results += [Result(j, "skipped", message="not started") for j in jobs[i + 1:]]
                break
            except Exception as e:
                self.ui.error(f"{job.label()}: {e}")
                results.append(Result(job, "failed", message=str(e)))
        return results


def _check_viewer(resp):
    if not resp or "본인인증" in resp:
        raise ValueError("empty response or identity verification required")
    json.loads(resp)["s"]


def _rmdir_if_empty(p):
    try:
        p.rmdir()
    except OSError:
        pass
