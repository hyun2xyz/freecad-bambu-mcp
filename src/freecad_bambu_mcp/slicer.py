"""Bambu Studio CLI with explicit profiles; GUI remains a resumable checkpoint."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


def find_slicer(configured: str | None = None) -> str | None:
    if configured:
        return str(Path(configured).expanduser().resolve()) if Path(configured).expanduser().is_file() else shutil.which(configured)
    candidates = (["/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"] if sys.platform == "darwin" else
                  [str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Bambu Studio/bambu-studio.exe")] if sys.platform == "win32" else [])
    return next((p for p in candidates if Path(p).is_file()), None) or shutil.which("bambu-studio")


def slice_model(executable: str, stl: Path, output: Path, settings: list[Path], filaments: list[Path], timeout=300):
    if output.exists():
        raise ValueError("sliced output already exists")
    for p in [*settings, *filaments]:
        if p.suffix.lower() != ".json" or not p.is_file() or ";" in str(p):
            raise ValueError("profiles must be existing JSON files with no semicolon in their paths")
    # A private datadir prevents CLI settings from modifying the user's open GUI.
    data = output.parent / "slicer-data"
    data.mkdir(mode=0o700, exist_ok=True)
    cmd = [executable, "--datadir", str(data), "--debug", "1",
           "--load-settings", ";".join(map(str, settings)),
           "--load-filaments", ";".join(map(str, filaments)),
           "--arrange", "1", "--ensure-on-bed", "--slice", "0",
           "--export-3mf", str(output), str(stl)]
    log = output.parent / "slicer.log"
    with log.open("xb") as stream:
        try:
            result = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout, check=False,
                                    cwd=output.parent)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("slicer_timeout: inspect the local log before retrying") from exc
    if result.returncode or not output.is_file():
        raise RuntimeError("slicer_failed: inspect slicer.log; use Bambu Studio GUI if profiles are incomplete")
    return {"file": str(output), "log": str(log), "returncode": result.returncode}
