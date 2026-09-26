"""Parsing Novelpia HTML and turning viewer_data JSON into EPUB/TXT text."""

import html
import json
import re

# --- novel page / episode list -------------------------------------------------

PRODUCT_NAME_RE = re.compile(r"productName = '(.+?)';")
AUTHOR_RE = re.compile(r"""<meta[^]>]+name=["']author["'][^]>]+content=["']([^"']+)["']""")
COVER_HREF_RE = re.compile(r'href="(//images\.novelpia\.com/imagebox/cover/.+?\.file)"')
COVER_SRC_RE = re.compile(r'src="(//images\.novelpia\.com/imagebox/cover/.+?\.file)"')
NOTICE_TABLE_RE = re.compile(r'<table[^>]*class="[^"]*notice_table[^"]*"[^>]*>(.+?)</table>', re.S)
NOTICE_RE = re.compile(r"""location='/viewer/(\d+)';"[^>]*><b>(.+?)</b>""", re.S)
EPISODE_RE = re.compile(r'id="bookmark_(\d+)"></i>(.+?)</b>.+?>(EP\.(\d+)|BONUS)<', re.S)

TAG_RE = re.compile(r"</?[^>]+>")


def plain(s):
    """HTML fragment -> plain display text."""
    return html.unescape(TAG_RE.sub("", s)).strip()


def novel_title(page):
    m = PRODUCT_NAME_RE.search(page)
    return html.unescape(m.group(1)) if m else None


def novel_author(page):
    m = AUTHOR_RE.search(page)
    return html.unescape(m.group(1)) if m else ""


def cover_url(page):
    m = COVER_HREF_RE.search(page) or COVER_SRC_RE.search(page)
    return m.group(1) if m else None


def notices(page):
    table = NOTICE_TABLE_RE.search(page)
    if not table:
        return []
    return [(m.group(1), plain(m.group(2))) for m in NOTICE_RE.finditer(table.group(1))]


def episodes(resp):
    """-> [(kind, chapter_id, name, ep_no)] where kind is 'EP' or 'BONUS'."""
    out = []
    for m in EPISODE_RE.finditer(resp):
        is_bonus = m.group(3) == "BONUS"
        out.append(("BONUS" if is_bonus else "EP", m.group(1), plain(m.group(2)),
                    0 if is_bonus else int(m.group(4))))
    return out


# --- chapter titles ------------------------------------------------------------

TITLE_RANGE_RE = re.compile(r"(\d+\s*~\s*\d+)화\b")
HAS_EP_NO_RE = re.compile(
    r"(?:\bEP\.?\s*\d+\b|(?:제\s*)?\d+\s*(?:화|회|장|편)\b|^\s*\d+(?:\s*~\s*\d+)?(?:\s|\.|$))",
    re.I,
)


def epub_chapter_title(name, is_bonus, ep_no):
    """Prefix 'EP n.' unless the title already carries an episode number."""
    name = TITLE_RANGE_RE.sub(r"\1", name)
    if not is_bonus and not HAS_EP_NO_RE.search(name):
        name = f"EP {ep_no}. {name}"
    return name


# --- chapter body --------------------------------------------------------------

HIDDEN_P_RE = re.compile(r"<p style='height: 0px; width: 0px;.+?>.*?</p>")
TAG_PARTS_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>")
IMG_RE = re.compile(r'<img.+?src="(.+?)".+?>')
IMG_ANY_RE = re.compile(r"<img.+?>")


class FontMapping:
    """Optional char->char table (JSON) to undo Novelpia's obfuscated font."""

    def __init__(self, path=None):
        self.table = None
        if path:
            with open(path, encoding="utf-8") as f:
                self.table = str.maketrans({k[0]: v[0] for k, v in json.load(f).items()})

    def decode(self, text):
        return text.translate(self.table) if self.table else text


def _tag_name(open_tag):
    return open_tag.split(" ", 1)[0]


def clean_text(text, keep_html, carry):
    """Clean one viewer segment. Returns (text, carry).

    With keep_html, Novelpia splits one styled span across segments (a bare
    "<b><i>" line, a text line, then "</i></b>"), so tags still open from the
    previous segment are reopened here and everything is closed again at the
    end, keeping each <p> self-balanced XHTML.
    """
    text = HIDDEN_P_RE.sub("", text)
    if not keep_html:
        text = TAG_RE.sub("", text)
    else:
        stack = list(carry)
        out = [f"<{t}>" for t in carry]
        pos = 0
        for m in TAG_PARTS_RE.finditer(text):
            out.append(text[pos:m.start()])
            name = m.group(2).lower()
            if m.group(0).endswith("/>") or name in ("img", "br", "hr"):
                out.append(m.group(0))
            elif m.group(1) == "/":
                idx = next((k for k in range(len(stack) - 1, -1, -1) if _tag_name(stack[k]) == name), -1)
                if idx >= 0:
                    out.extend(f"</{_tag_name(t)}>" for t in reversed(stack[idx:]))
                    del stack[idx:]
            else:
                stack.append(name + m.group(3))
                out.append(m.group(0))
            pos = m.end()
        out.append(text[pos:])
        out.extend(f"</{_tag_name(t)}>" for t in reversed(stack))
        carry = stack
        text = "".join(out)
    return text.replace("\n", "").replace("\r", ""), carry


def segments(viewer_json):
    return [s["text"] for s in json.loads(viewer_json)["s"]]


CHAPTER_HEAD = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"
"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">

<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<title></title>
<style type="text/css">
html, body { margin:0; padding:0; }
</style>
<link href="../Styles/sgc-toc.css" type="text/css" rel="stylesheet"/>
<link href="../Styles/Stylesheet.css" type="text/css" rel="stylesheet"/>
</head>
<body>
"""


def chapter_xhtml(title, viewer_json, opts, fonts, add_image):
    """Build one EPUB chapter.

    add_image(url) downloads an illustration and returns its EPUB path
    (e.g. "../Images/3.png"), or None if it failed / images are off.
    """
    parts = [CHAPTER_HEAD, f"<h1>{html.escape(title)}</h1>\n<p>&nbsp;</p>\n"]
    blank = "<p>&#160;</p>\n"
    carry = []
    for text in segments(viewer_json):
        img = IMG_RE.search(text)
        if img:
            if "cover-wrapper" in text:
                continue
            src = add_image(img.group(1)) if opts.download_image else None
            if src:
                text = IMG_RE.sub(lambda _: f'<img alt="illustration" src="{src}" width="100%"/>', text)
                parts.append(f"<p>{text}</p>\n")
            elif not opts.remove_blank:
                parts.append(blank)
            continue
        text, carry = clean_text(text, opts.keep_html, carry)
        if not text:
            if not opts.remove_blank:
                parts.append(blank)
            continue
        parts.append(f"<p>{fonts.decode(text)}</p>\n")
    parts.append("</body>\n</html>\n")
    return "".join(parts)


def chapter_txt(title, viewer_json, opts, fonts):
    lines = [title, ""]
    carry = []
    for text in segments(viewer_json):
        if "cover-wrapper" in text:
            continue
        text = IMG_ANY_RE.sub("", text)
        text, carry = clean_text(text, False, carry)
        if not text:
            if not opts.remove_blank:
                lines.append("")
            continue
        lines.append(fonts.decode(html.unescape(text)))
    return "\n".join(lines) + "\n\n"
