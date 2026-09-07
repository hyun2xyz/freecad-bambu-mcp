"""Portable, explicit configuration. Credentials are environment references only."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Model = Literal["a1", "a1mini", "p1s", "p1p", "x1c", "x1e"]
BED_NAMES = {"textured_plate": "Textured PEI Plate", "cool_plate": "Cool Plate",
             "engineering_plate": "Engineering Plate", "hot_plate": "Smooth PEI Plate",
             "supertack_plate": "Cool Plate SuperTack"}
MODEL_NAMES = {"a1": "Bambu Lab A1", "a1mini": "Bambu Lab A1 mini",
               "p1s": "Bambu Lab P1S", "p1p": "Bambu Lab P1P",
               "x1c": "Bambu Lab X1C", "x1e": "Bambu Lab X1E"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Hardware(Strict):
    model: Model
    nozzle_mm: float = Field(gt=0, le=1.2)
    bed: Literal["textured_plate", "cool_plate", "engineering_plate", "hot_plate", "supertack_plate"]
    filaments: list[str] = Field(min_length=1, max_length=16)

    @field_validator("filaments")
    @classmethod
    def filament_names(cls, v):
        if any(not x.strip() or len(x) > 30 for x in v):
            raise ValueError("filament names must be short nonempty material names")
        return v


class PrinterSettings(Hardware):
    host_env: str = "BAMBU_HOST"
    serial_env: str = "BAMBU_SERIAL"
    access_code_env: str = "BAMBU_ACCESS_CODE"
    tls_ca_file: str | None = None
    allow_self_signed: bool = False
    timeout: float = Field(default=15, ge=1, le=60)

    @field_validator("host_env", "serial_env", "access_code_env")
    @classmethod
    def env_names(cls, v):
        import re
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", v):
            raise ValueError("use an environment variable NAME, never a credential value")
        return v


class Settings(Strict):
    workspace: str
    allow_freecad_python: bool = False
    freecad_port: int = Field(default=9875, ge=1024, le=65535)
    slicer_path: str | None = None
    printers: dict[str, PrinterSettings] = Field(default_factory=dict)


class CADSpec(Strict):
    document: str = Field(min_length=1, max_length=100)
    objects: list[str] = Field(min_length=1, max_length=100)
    script: str | None = None


class SliceSpec(Strict):
    mode: Literal["gui", "cli"] = "gui"
    settings: list[str] = Field(default_factory=list, max_length=4)
    filaments: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def profiles(self):
        if self.mode == "cli" and (not self.settings or not self.filaments):
            raise ValueError("CLI slicing requires explicit full machine/process and filament JSON profiles")
        return self


class PrintOptions(Strict):
    use_ams: bool = False
    ams_mapping: list[int] | None = Field(default=None, min_length=1, max_length=16)
    bed_leveling: bool = True
    flow_calibration: bool = True
    vibration_calibration: bool = True
    timelapse: bool = False

    @model_validator(mode="after")
    def mapping(self):
        if self.use_ams and not self.ams_mapping:
            raise ValueError("AMS requires an explicit project-filament-to-tray mapping")
        if not self.use_ams and self.ams_mapping is not None:
            raise ValueError("external spool mode cannot contain an AMS mapping")
        if self.ams_mapping and any(x not in range(16) and x != -1 for x in self.ams_mapping):
            raise ValueError("this version supports ordinary AMS trays 0..15 and unused -1 only")
        return self


class JobSpec(Strict):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,59}$")
    printer: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,59}$")
    hardware: Hardware
    cad: CADSpec
    slicing: SliceSpec = Field(default_factory=SliceSpec)
    print_options: PrintOptions = Field(default_factory=PrintOptions)


def read_json(path: Path, limit=1_000_000):
    if path.stat().st_size > limit:
        raise ValueError("JSON exceeds size limit")
    return json.loads(path.read_text(encoding="utf-8"))


class Config:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get("FREECAD_BAMBU_CONFIG", "config.local.json")).expanduser().resolve()
        self.settings = Settings.model_validate(read_json(self.path))
        root = Path(self.settings.workspace).expanduser()
        self.workspace = (root if root.is_absolute() else self.path.parent / root).resolve()
        if not self.workspace.is_dir():
            raise ValueError("configured workspace must be an existing directory")
        self.state_dir = self.workspace / ".freecad-bambu"
        if self.state_dir.is_symlink():
            raise ValueError("state directory must not be a symlink")
        self.state_dir.mkdir(mode=0o700, exist_ok=True)

    def inside(self, path: str | Path, *, exists=True) -> Path:
        p = Path(path).expanduser()
        p = (p if p.is_absolute() else self.workspace / p).resolve()
        if not p.is_relative_to(self.workspace):
            raise ValueError("path is outside the configured workspace")
        if exists and not p.is_file():
            raise ValueError("input file does not exist")
        return p

    def printer(self, alias):
        if alias not in self.settings.printers:
            raise ValueError("printer alias is not configured")
        return self.settings.printers[alias]

    def transport_config(self, alias):
        from .printer import PrinterConfig
        p = self.printer(alias)
        values = {k: os.environ.get(getattr(p, f"{k}_env"), "")
                  for k in ("host", "serial", "access_code")}
        if not all(values.values()):
            raise ValueError("printer credential environment is incomplete; populate it locally")
        ca = p.tls_ca_file
        if ca:
            ca = str((self.path.parent / Path(ca).expanduser()).resolve())
        return PrinterConfig(**values, model=p.model, tls_ca_file=ca,
                             allow_self_signed=p.allow_self_signed, timeout=p.timeout)
