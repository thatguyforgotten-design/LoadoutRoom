"""User-selected window background; stored separately from update preferences."""
import json
import os
import re
from .desktop_updates import settings_path


def normalize_color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Choose a color in #RRGGBB format.")
    return value.lower()


def load_background(default):
    try:
        path = settings_path().with_name("appearance.json")
        return normalize_color(json.loads(path.read_text(encoding="utf-8"))["background"])
    except (OSError, ValueError, TypeError, KeyError):
        return default


def save_background(color):
    color = normalize_color(color)
    path = settings_path().with_name("appearance.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"background": color}), encoding="utf-8")
    os.replace(temporary, path)


def text_colors(background):
    red, green, blue = (int(background[i:i+2], 16) for i in (1, 3, 5))
    light = .2126 * red + .7152 * green + .0722 * blue > 150
    return ("#101827", "#475569") if light else ("#f2f4fc", "#9aa8c0")
