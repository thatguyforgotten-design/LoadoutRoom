"""Build a tested portable Windows ZIP using the verified v1.0.23 runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://github.com/thatguyforgotten-design/LoadoutRoom/releases/download/v1.0.23/LoadoutRoom-v1.0.23.zip"
BASE_SHA256 = "82cf2dea02747ccd6173d95a6ee026764358984d3597820eeb6d40496de96dd8"


def build(base_zip=None):
    if sys.platform != "win32":
        raise RuntimeError("Build this Windows application on Windows.")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    base_zip = Path(base_zip) if base_zip else dist / "base-v1.0.23.zip"
    if not base_zip.exists():
        with urllib.request.urlopen(BASE_URL, timeout=60) as response, base_zip.open("wb") as output:
            shutil.copyfileobj(response, output)
    if hashlib.sha256(base_zip.read_bytes()).hexdigest() != BASE_SHA256:
        raise ValueError("The base runtime archive checksum does not match v1.0.23.")

    stage = Path(tempfile.mkdtemp(prefix="package-", dir=dist))
    # This archive is pinned by SHA256 above. Bootstrap its bundled dependencies
    # before importing the updater, so a clean build host needs only Python.
    with zipfile.ZipFile(base_zip) as bundle:
        for member in bundle.infolist():
            if not (stage / member.filename).resolve().is_relative_to(stage.resolve()):
                raise ValueError("Unsafe path in the base archive.")
        bundle.extractall(stage)
    sys.path.insert(0, str(stage / "runtime/Lib/site-packages"))
    sys.path.insert(0, str(ROOT / "app"))
    from src.desktop_updates import VERSION, extract_release

    # Replace code and tests with the reviewed repository snapshot, not older source.
    for name in ("app", "source"):
        target = (stage / name).resolve()
        if not target.is_relative_to(stage.resolve()):
            raise ValueError("Package directory escaped the build staging folder.")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(ROOT / name, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("README.md", "READ_ME_FIRST.txt", "LICENSE.txt", "Credits", "More info", "requirements.txt"):
        shutil.copy2(ROOT / name, stage / name)
    for name in ("desktop-error.txt", "desktop-self-test.txt", "update.json"):
        (stage / name).unlink(missing_ok=True)

    compiler = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64",
                    "/win32icon:" + str(stage / "app/assets/Logo.ico"),
                    "/reference:System.Windows.Forms.dll",
                    "/out:" + str(stage / "LoadoutRoom.exe"),
                    str(stage / "source/DesktopLauncher.cs")], check=True)
    # Older installed shortcuts accept this filename in active-release.txt.
    shutil.copy2(stage / "LoadoutRoom.exe", stage / "LoadoutRoom1.0.exe")
    env = {**os.environ, "PYTHONPATH": str(stage / "app"), "PYTHONDONTWRITEBYTECODE": "1"}
    env["TCL_LIBRARY"] = str(stage / "runtime/tcl/tcl8.6")
    env["TK_LIBRARY"] = str(stage / "runtime/tcl/tk8.6")
    subprocess.run([str(stage / "runtime/python.exe"), "-B", "-m", "unittest", "discover",
                    "-s", str(stage / "source/tests")], cwd=stage, env=env, check=True)
    subprocess.run([str(stage / "LoadoutRoom.exe"), "--self-test"], cwd=stage, check=True)
    print((stage / "desktop-self-test.txt").read_text(encoding="utf-8"))

    archive = dist / ("LoadoutRoom-v" + VERSION + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(stage.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                bundle.write(path, path.relative_to(stage).as_posix())
    manifest = {
        "version": VERSION,
        "url": "https://github.com/thatguyforgotten-design/LoadoutRoom/releases/download/v" + VERSION + "/" + archive.name,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "notes": (ROOT / "source/release-notes.md").read_text(encoding="utf-8").strip(),
    }
    (dist / "update.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # Also validate the final archive through the same safety checks as app updates.
    with tempfile.TemporaryDirectory(dir=dist, prefix="verify-") as check:
        extract_release(archive, check)
    print("Built", archive.name, archive.stat().st_size, "bytes; SHA256", manifest["sha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-zip", type=Path)
    build(parser.parse_args().base_zip)
