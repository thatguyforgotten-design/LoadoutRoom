"""Consent-driven updates. No update source is enabled until configured."""
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
import requests

VERSION = "1.0.20"
DEFAULT_FEED = "https://github.com/thatguyforgotten-design/LoadoutRoom/releases/latest/download/update.json"
MAX_DOWNLOAD = 60 * 1024 * 1024
MAX_EXPANDED = 300 * 1024 * 1024

def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}", value):
        raise ValueError("Invalid release version.")
    return tuple(map(int, value.split(".")))

def https_url(value):
    p = urlparse(value or "")
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError("The update address must use HTTPS without credentials.")
    return value

def settings_path():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "LoadoutRoom" / "updates.json"

def read_settings():
    try:
        value = json.loads(settings_path().read_text(encoding="utf-8"))
        https_url(value.get("feed", ""))
        return {"feed": value["feed"], "check_on_start": bool(value.get("check_on_start", True))}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"feed": DEFAULT_FEED, "check_on_start": True}

def save_settings(feed, check_on_start=True):
    https_url(feed)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"feed": feed, "check_on_start": bool(check_on_start)}), encoding="utf-8")

def read_https(url, limit):
    https_url(url)
    # Redirects are handled explicitly so every hop retains HTTPS.
    for _ in range(6):
        with requests.get(url, timeout=(5, 15), stream=True, allow_redirects=False) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                from urllib.parse import urljoin
                url = https_url(urljoin(url, response.headers.get("Location", "")))
                continue
            response.raise_for_status()
            parts, size = [], 0
            for part in response.iter_content(65536):
                size += len(part)
                if size > limit:
                    raise ValueError("Update download exceeds the size limit.")
                parts.append(part)
            return b"".join(parts)
    raise ValueError("Too many update redirects.")

def check_update(feed):
    release = json.loads(read_https(feed, 64 * 1024))
    version_tuple(release.get("version"))
    https_url(release.get("url"))
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(release.get("sha256", ""))):
        raise ValueError("The publisher did not supply a valid SHA-256 checksum.")
    if not isinstance(release.get("notes", ""), str):
        raise ValueError("Invalid release notes.")
    return release if version_tuple(release["version"]) > version_tuple(VERSION) else None

def extract_release(archive, destination):
    """Validate every member before writing any file; retain the old installation."""
    destination = Path(destination)
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 12000 or sum(m.file_size for m in members) > MAX_EXPANDED:
            raise ValueError("Update contents exceed the size limit.")
        names = set()
        for member in members:
            name = member.filename
            parts = PurePosixPath(name).parts
            if (not parts or name.startswith("/") or "\\" in name or ":" in name
                    or any(part in (".", "..") or part.endswith((" ", ".")) for part in parts)
                    or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError("The update contains an unsafe path.")
            reserved = {"CON", "PRN", "AUX", "NUL"} | {p + str(n) for p in ("COM", "LPT") for n in range(1, 10)}
            if any(part.split(".")[0].upper() in reserved for part in parts):
                raise ValueError("The update contains a reserved Windows path.")
            resolved = (destination / name).resolve()
            if not resolved.is_relative_to(destination.resolve()):
                raise ValueError("The update path escapes its destination.")
            key = name.casefold().rstrip("/")
            if key in names:
                raise ValueError("The update contains duplicate file paths.")
            names.add(key)
        launcher = "LoadoutRoom.exe" if "loadoutroom.exe" in names else "LoadoutRoom1.0.exe"
        required = {launcher.casefold(), "app/desktop.py", "runtime/pythonw.exe"}
        if not required.issubset(names):
            raise ValueError("This ZIP is not a complete LoadoutRoom desktop release.")
        if not bundle.read(launcher).startswith(b"MZ"):
            raise ValueError("The update launcher is invalid.")
        destination.mkdir(parents=True, exist_ok=True)
        bundle.extractall(destination)
    return destination / launcher

def install_release(release):
    version_tuple(release["version"])
    data = read_https(release["url"], MAX_DOWNLOAD)
    if hashlib.sha256(data).hexdigest().lower() != release["sha256"].lower():
        raise ValueError("Checksum mismatch. Nothing was installed.")
    parent = settings_path().parent / "releases"
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=release["version"] + "-", dir=parent))
    try:
        import io
        return extract_release(io.BytesIO(data), stage)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise