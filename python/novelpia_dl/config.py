"""Settings and login in python/config.json.

Key names match the Windows version where they overlap, so a Windows
config.json can be dropped in as-is.
"""

import json
from pathlib import Path

from .downloader import Options

# python/ — the folder that holds config.json, wherever you run from.
HOME = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = HOME / "config.json"

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
    "name_ep_range": "name_with_range",
    "mark_finished": "mark_finished",
    "vertical": "vertical",
    "gothic": "gothic",
    "interval_num": "interval",
    "retry_num": "retry",
    "gap_min": "gap_min",
    "gap_max": "gap_max",
    "mapping_path": "font_map",
}

def load(path=None):
    path = Path(path or DEFAULT_CONFIG)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def options_from(cfg):
    opts = Options()
    if "name_ep_range" not in cfg and "include_chapter_range" in cfg:  # Windows key
        cfg = {**cfg, "name_ep_range": cfg["include_chapter_range"]}
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
    path = Path(path or DEFAULT_CONFIG)
    data = load(path)
    data.update(cfg)
    for key, attr in KEYS.items():
        data[key] = getattr(opts, attr)
    if bonus:
        data["bonus_never"] = bonus == "never"
        data["bonus_always"] = bonus == "always"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
