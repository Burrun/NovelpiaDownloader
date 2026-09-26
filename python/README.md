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

Settings are saved to `config.json` in the current folder. The password is saved only if you say yes.

## Command line

```bash
python -m novelpia_dl 12345                        # one novel, EPUB
python -m novelpia_dl 12345 67890:1-50 111:100-    # a queue of three novels
python -m novelpia_dl -q list.txt --txt -o books   # queue from a file, TXT, into ./books
python -m novelpia_dl --email me@x.com 12345       # password from NOVELPIA_PASSWORD or config.json
python -m novelpia_dl --help                       # all options
```

Each novel is `NUMBER`, a novel URL, or `NUMBER:FROM-TO` (`12345:1-50`, `12345:10-`, `12345:-30`).
A queue file has one novel per line. `#` starts a comment.

## How it paces requests

- **Always one thread.** Chapters are downloaded one at a time.
- **Between chapters** it waits a random delay averaging `--interval` seconds (default 22.3).
  This is the same drifting random delay the Windows version uses.
- **Between novels in a queue** it takes a random **5–10 minute** break
  (`--gap-min` / `--gap-max`), with a countdown on screen.
- Failed requests are retried (`--retry`, default 3) after a short random wait.

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
