# NovelpiaDownloader — Python / terminal edition

A cross-platform (Windows / macOS / Linux) terminal version of NovelpiaDownloader.
It saves Novelpia novels as **EPUB** (default) or **TXT**, can download **several novels
in a queue**, and has a [rich](https://github.com/Textualize/rich) interface.

## Install

Python 3.10+:

```bash
cd python
pip install -r requirements.txt
```

## Wizard (interactive)

```bash
python -m novelpia_dl
```

The wizard has three steps:

1. **Login**: email/password, a LOGINKEY (from your browser's cookies), or skip (free chapters only).
2. **Queue**: add as many novels as you like (URL or number, EP range, BONUS mode), then remove or start.
3. **Options**: format (EPUB by default), output folder, and optional advanced settings.

Your settings and login are saved to `python/config.json`.
The password is saved only if you say yes.

## Settings: `config.json`

Everything, including your login, is in `python/config.json`.
It's used no matter which folder you run the program from.
You can also copy in your `config.json` from the Windows version.

| Key | Meaning |
|---|---|
| `email`, `wd` | login email / password (or pass `--password`, or set `NOVELPIA_PASSWORD`) |
| `loginkey` | LOGINKEY cookie, instead of email/password |
| `format` | `"epub"` or `"txt"` |
| `output_dir` | where files are saved (relative paths start from the folder you run in) |
| `include_notice`, `download_image`, `keep_html`, `remove_blank`, `compress`, `vertical`, `gothic` | same as the Windows options |
| `mapping_path` | font mapping JSON |
| `include_novel_no`, `name_ep_range`, `mark_finished` | file name parts (`12345_Title 1~250 (완)`) |
| `bonus_never`, `bonus_always` | default BONUS mode |
| `interval_num`, `retry_num` | mean seconds between chapters, retries per request |
| `gap_min`, `gap_max` | break between novels, in minutes |
| `stop_on_error` | stop a novel at the first failed chapter |

Keys the Python version doesn't use, such as `language` and `thread_num`, are ignored and kept as they are.
Use `-c other.json` for a different settings file.

> ⚠️ Once you fill in `email` / `wd`, don't commit `config.json` to a public repo.

## Command line

```bash
python -m novelpia_dl 12345                        # one novel, EPUB
python -m novelpia_dl 12345 67890:1-50 111:100-    # a queue of three novels
python -m novelpia_dl -q list.txt --txt -o books   # queue from a file, TXT, into ./books
python -m novelpia_dl --email me@x.com 12345       # password from config.json or NOVELPIA_PASSWORD
python -m novelpia_dl --help                       # all options
```

Each novel is `NUMBER`, a novel URL, or `NUMBER:FROM-TO` (`12345:1-50`, `12345:10-`, `12345:-30`).
A queue file has one novel per line. `#` starts a comment.

## Background downloading (attach / detach)

Downloads run in a **background process**, so you can close the window,
come back later, or add novels while it's running.

```bash
python -m novelpia_dl 12345 67890     # queue, start in the background, watch it
python -m novelpia_dl attach          # watch again from any terminal
python -m novelpia_dl status          # one-time status + finished list
python -m novelpia_dl stop            # stop after the current chapter (resumes later)
python -m novelpia_dl start           # start it again
python -m novelpia_dl 777 -d          # add a novel to the queue without watching
```

While watching, press **Ctrl+C** for the menu:

| Key | Action |
|---|---|
| `a` | add a novel to the queue (while the current one keeps downloading) |
| `r` | remove a waiting novel |
| `p` | flip through the EP list pages (`n` / `p` / page number / `f` follow current) |
| `h` | finished novels |
| `s` | stop (or start) the downloader |
| `d` | detach: leave the view, keep downloading |
| `c` | go back to watching |

The watch screen shows:
- the current novel with a progress bar and a steady ETA (your interval until a few chapters are done, then the real pace)
- the current **page** of the EP list (`✓` done, `▶` now, `·` waiting), which follows the chapter being downloaded
- recent messages and the queue

Running `python -m novelpia_dl` with no arguments opens the watch screen if something is queued or running.
Otherwise it starts the wizard.
`--foreground` runs the old way, all in the current terminal.

The queue, status and full log (`log.txt`) are kept in `python/.state/`.
If the computer restarts in the middle of a novel, `python -m novelpia_dl start` continues it from the cache.

## How it paces requests

- **Always one thread.** Chapters are downloaded one at a time.
- **Between chapters** it waits a random delay averaging `--interval` seconds (default 22.3).
  This is the same drifting random delay the Windows version uses.
- **Between novels in a queue** it takes a random **5–10 minute** break
  (`--gap-min` / `--gap-max`), with a countdown on screen.
  This also holds if a novel is added after the downloader has already finished.
- Failed requests are retried (`--retry`, default 3) after a short random wait.

## File names

Files are named `Title FIRST~LAST.epub` using **EP numbers**. BONUS episodes and notices don't count.
If the novel is finished (완결) and the file includes its last EP, ` (완)` is added:

```
전생했더니 슬라임 1~250 (완).epub   # finished, whole novel
전생했더니 슬라임 1~50.epub         # only part of it
```

Turn these off with `--no-name-range` / `--no-mark-finished`, or in the wizard's advanced options.
`--name-no` puts the novel number in front (`12345_Title 1~250.epub`).

## Resume

Downloaded chapters are cached in `<output>/.novelpia_cache/<novel no>/`.
If a run is cancelled (Ctrl+C) or some chapters fail, run the same command again.
Chapters already in the cache are not downloaded again.
The cache is deleted after a novel finishes with no failures.

## BONUS rules

These are the same as the Windows version:

- A BONUS episode after the last EP counts as the next numbers after the last EP.
  For example, if the last EP is 100, then `101` is the first trailing BONUS.
- A BONUS in the middle of the story follows the range of the EP before it.
- `--bonus never` / `--bonus always` ignore the range for BONUS episodes.

## Differences from the Windows version

- Only one thread (by design), plus the queue break between novels.
- Chapters that fail are left out of the EPUB, so there are no broken table-of-contents entries.
  A failed illustration becomes a blank line.
- TXT output is always plain text. The "keep HTML" option only affects EPUB styling.
- Interrupted or partial downloads can be resumed from the cache.
