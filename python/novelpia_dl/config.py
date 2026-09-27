"""Settings: python/config.json (defaults, no secrets) + python/.env (login).

config.json key names match the Windows version where they overlap, so a
Windows config.json can be dropped in; any email/password/loginkey found in
it is moved to .env the next time settings are saved.
"""

import json
import os
from pathlib import Path

from .downloader import Options

# python/ — the folder that holds config.json and .env, wherever you run from.
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

# cfg key -> .env / environment variable
SECRETS = {
    "email": "NOVELPIA_EMAIL",
    "wd": "NOVELPIA_PASSWORD",
    "loginkey": "NOVELPIA_LOGINKEY",
}


def env_path(config_path):
    return Path(config_path).parent / ".env"


def read_env(path):
    values = {}
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export "), value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def write_env(path, updates):
    """Set/replace the given KEY=value lines, keeping everything else in the file."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    quote = lambda v: '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'  # noqa: E731
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in updates:
            lines[i] = f"{key}={quote(updates[key])}"
            done.add(key)
    lines += [f"{k}={quote(v)}" for k, v in updates.items() if k not in done]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load(path=None):
    """Settings from config.json, with login from .env; real environment variables win."""
    path = Path(path or DEFAULT_CONFIG)
    cfg = {}
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            cfg = {}
    env = read_env(env_path(path))
    for key, var in SECRETS.items():
        value = os.environ.get(var) or env.get(var)
        if value:
            cfg[key] = value
    return cfg


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
    """Settings -> config.json (secrets stripped), login -> .env next to it."""
    path = Path(path or DEFAULT_CONFIG)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
    data.update({k: v for k, v in cfg.items() if k not in SECRETS})
    for key in SECRETS:
        data.pop(key, None)
    for key, attr in KEYS.items():
        data[key] = getattr(opts, attr)
    if bonus:
        data["bonus_never"] = bonus == "never"
        data["bonus_always"] = bonus == "always"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    secrets = {var: cfg[key] for key, var in SECRETS.items() if cfg.get(key)}
    if secrets:
        write_env(env_path(path), secrets)
