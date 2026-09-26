"""config.json (key names shared with the Windows version where they overlap)."""

import json
from pathlib import Path

from .downloader import Options

# config key -> Options attribute
KEYS = {
    "format": "fmt",
    "output_dir": "output_dir",
    "include_notice": "include_notice",
    "remove_blank": "remove_blank",
    "keep_html": "keep_html",
    "compress": "compress",
    "download_image": "download_image",
    "stop_on_error": "stop_on_error",
    "include_novel_no": "name_with_no",
    "include_chapter_range": "name_with_range",
    "vertical": "vertical",
    "gothic": "gothic",
    "interval_num": "interval",
    "retry_num": "retry",
    "gap_min": "gap_min",
    "gap_max": "gap_max",
    "mapping_path": "font_map",
}


def load(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def options_from(cfg):
    opts = Options()
    for key, attr in KEYS.items():
        if cfg.get(key) not in (None, ""):
            default = getattr(opts, attr)
            setattr(opts, attr, type(default)(cfg[key]))
    if opts.fmt not in ("epub", "txt"):
        opts.fmt = "epub"
    return opts


def default_bonus(cfg):
    if cfg.get("bonus_never"):
        return "never"
    if cfg.get("bonus_always"):
        return "always"
    return "range"


def save(path, cfg, opts, bonus=None):
    """Merge into the existing file so unknown keys (e.g. from the Windows app) survive."""
    data = load(path)
    data.update(cfg)
    for key, attr in KEYS.items():
        data[key] = getattr(opts, attr)
    if bonus:
        data["bonus_never"] = bonus == "never"
        data["bonus_always"] = bonus == "always"
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
