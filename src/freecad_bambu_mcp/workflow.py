"""Durable workflow state, review binding, and at-most-once automatic dispatch."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import uuid

from filelock import FileLock

from .cad import FreeCADClient
from .config import BED_NAMES, MODEL_NAMES, Config, JobSpec, read_json
from .preflight import inspect
from .printer import BambuLAN
from .slicer import find_slicer, slice_model


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path: Path, data):
    fd, temp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def require_success(result, stage):
    if not isinstance(result, dict) or result.get("success") is False or result.get("error"):
        detail = result.get("error", "invalid result") if isinstance(result, dict) else "invalid result"
        raise RuntimeError(f"{stage}: {str(detail)[:1000]}")
    return result


class Workflow:
    def __init__(self, config: Config, *, cad=None, printer_factory=BambuLAN, slicer=slice_model):
        self.config = config
        self.cad = cad or FreeCADClient(port=config.settings.freecad_port)
        self.printer_factory = printer_factory
        self.slicer = slicer

    def _jobdir(self, job_id):
        if not re.fullmatch(r"[0-9a-f]{20}", job_id):
            raise ValueError("invalid job ID")
        p = self.config.state_dir / job_id
        if p.is_symlink():
            raise ValueError("job directory must not be a symlink")
        return p

    @contextmanager
    def _lock(self, name):
        # A shared per-user lock covers different MCP processes AND workspaces.
        locks = self._locks_root()
        locks.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = hashlib.sha256(name.encode()).hexdigest()
        with FileLock(str(locks / (key + ".lock")), timeout=0):
            yield

    def _locks_root(self):
        return Path.home() / ".cache" / "freecad-bambu-mcp" / "locks"

    def _device_key(self, alias):
        # A physical serial, not host aliases or mutable nozzle/profile settings.
        p = self.config.transport_config(alias)
        return hashlib.sha256(p.serial.strip().upper().encode()).hexdigest()

    def _lease_path(self, alias):
        return self._locks_root() / (self._device_key(alias) + ".lease.json")

    def _lease_owner(self, job):
        return {"job_id": job["id"], "workspace": fingerprint(str(self.config.state_dir))}

    def _claim_printer(self, job, alias):
        path = self._lease_path(alias)
        owner = self._lease_owner(job)
        if path.exists() and read_json(path) != owner:
            raise ValueError("another job holds this printer; reconcile its status before starting another")
        atomic_json(path, owner)

    def _release_printer(self, job, alias):
        path = self._lease_path(alias)
        if path.exists() and read_json(path) == self._lease_owner(job):
            path.unlink()

    def _load(self, job_id):
        job = read_json(self._jobdir(job_id) / "job.json")
        if job.get("id") != job_id:
            raise ValueError("job ID does not match persisted state")
        return job

    def _save(self, job):
        job["updated_at"] = time.time()
        atomic_json(self._jobdir(job["id"]) / "job.json", job)

    def _profile(self, spec):
        configured = self.config.printer(spec.printer)
        hardware = {k: getattr(configured, k) for k in ("model", "nozzle_mm", "bed", "filaments")}
        if hardware != spec.hardware.model_dump():
            raise ValueError("job hardware differs from configured printer hardware")
        return configured

    def _target(self, alias):
        p = self.config.transport_config(alias)
        return fingerprint({"host": p.host, "serial": p.serial, "model": p.model,
                            "profile": self.config.printer(alias).model_dump()})

    def _printer(self, alias):
        return self.printer_factory(self.config.transport_config(alias))

    def capabilities(self):
        return {"version": "0.1.0", "freecad_rpc": "localhost", "trusted_python": self.config.settings.allow_freecad_python,
                "slicer": find_slicer(self.config.settings.slicer_path),
                "printers": {k: {"model": v.model, "nozzle_mm": v.nozzle_mm, "bed": v.bed}
                             for k, v in self.config.settings.printers.items()},
                "modes": ["gui_checkpoint", "explicit_profile_cli", "lan_print"],
                "native_print_scope": "one plate (plate_1); A1/A1 mini/P1/X1 LAN; no H2/cloud/certificate bypass",
                "hardware_testing": "transport is experimental until verified with your printer and firmware"}

    def doctor(self):
        result = self.capabilities()
        result["freecad"] = self.cad.status()
        result["printer_credentials"] = {k: all(os.environ.get(name) for name in (v.host_env, v.serial_env, v.access_code_env))
                                         for k, v in self.config.settings.printers.items()}
        return result

    def cad_execute(self, script):
        if not self.config.settings.allow_freecad_python:
            raise ValueError("trusted FreeCAD Python is disabled; enable it in your local config")
        path = self.config.inside(script)
        if path.suffix.lower() != ".py":
            raise ValueError("CAD script must be a .py file")
        with self._lock(f"freecad:{self.config.settings.freecad_port}"):
            return require_success(self.cad.execute_file(path), "cad_execute")

    def prepare(self, spec_file):
        spec_path = self.config.inside(spec_file)
        spec = JobSpec.model_validate(read_json(spec_path))
        self._profile(spec)
        script = self.config.inside(spec.cad.script) if spec.cad.script else None
        if script and (not self.config.settings.allow_freecad_python or script.suffix.lower() != ".py"):
            raise ValueError("trusted .py execution must be enabled before preparing this job")
        job_id = uuid.uuid4().hex[:20]
        directory = self._jobdir(job_id)
        directory.mkdir(mode=0o700)
        job = {"id": job_id, "spec": spec.model_dump(), "state": "preparing", "created_at": time.time(),
               "dispatch_attempted": False, "observed_running": False, "review": None}
        self._save(job)
        try:
            with self._lock(f"freecad:{self.config.settings.freecad_port}"):
                if script:
                    snapshot = directory / "source.py"
                    if script.stat().st_size > 1_000_000:
                        raise ValueError("CAD script exceeds 1 MB")
                    shutil.copyfile(script, snapshot)
                    job["script_sha256"] = digest(snapshot)
                    require_success(self.cad.execute_file(snapshot), "cad_execute")
                job["cad"] = require_success(self.cad.export(spec.cad.document, spec.cad.objects, directory / "cad"), "cad_export")
            job["state"] = "awaiting_slice"
            self._save(job)
            if spec.slicing.mode == "cli":
                executable = find_slicer(self.config.settings.slicer_path)
                if not executable:
                    raise ValueError("Bambu Studio CLI was not found")
                output = directory / "cli-output.3mf"
                self.slicer(executable, Path(job["cad"]["paths"]["stl"]), output,
                            [self.config.inside(x) for x in spec.slicing.settings],
                            [self.config.inside(x) for x in spec.slicing.filaments])
                return self.attach_slice(job_id, output)
            return self.summary(job)
        except Exception as exc:
            job["state"] = "slice_failed" if "cad" in job else "prepare_failed"
            job["error"] = str(exc)[:1200]
            job["next"] = ("CAD export is ready. Slice cad.paths.stl in Bambu Studio and attach the export to THIS job; do not rerun CAD."
                           if "cad" in job else "Inspect job files and FreeCAD document state before preparing again; no automatic CAD retry.")
            self._save(job)
            return self.summary(job)

    def _inspect(self, path, spec):
        r = inspect(path, MODEL_NAMES[spec.hardware.model], 1, str(spec.hardware.nozzle_mm),
                    BED_NAMES[spec.hardware.bed], spec.hardware.filaments)
        if r.get("plates") != [1]:
            r["errors"].append("native dispatch requires exactly one plate: Metadata/plate_1.gcode")
        # Unknown slot layout must not silently choose a spool.
        profile = r.get("profile", {})
        used = profile.get("used_filament_ids")
        count = profile.get("project_filament_count")
        if not used or not isinstance(count, int) or count < 1:
            r["errors"].append("missing proven project/used filament layout")
        elif any(not isinstance(x, int) or x < 0 or x >= count for x in used):
            r["errors"].append("invalid used filament positions")
        elif spec.print_options.use_ams:
            mapping = spec.print_options.ams_mapping
            if len(mapping) != count or any(mapping[i] < 0 for i in used):
                r["errors"].append("AMS mapping does not cover each used project filament")
        elif len(used) != 1:
            r["errors"].append("external spool mode requires exactly one used filament")
        if r["errors"]:
            r["profile_verification"] = "unverified"
        return r

    def attach_slice(self, job_id, sliced_file):
        with self._lock(f"job:{self.config.state_dir}:{job_id}"):
            job = self._load(job_id)
            if job["dispatch_attempted"]:
                raise ValueError("cannot change a job after dispatch was attempted")
            source = self.config.inside(sliced_file)
            if source.stat().st_size > 128 * 1024 * 1024 or source.suffix.lower() != ".3mf":
                raise ValueError("slice must be a bounded .3mf archive")
            directory = self._jobdir(job_id)
            # Versioned immutable snapshot: review never binds to a GUI's mutable source.
            snapshot = directory / f"slice-{uuid.uuid4().hex[:8]}.3mf"
            shutil.copyfile(source, snapshot)
            spec = JobSpec.model_validate(job["spec"])
            report = self._inspect(snapshot, spec)
            report_path = snapshot.with_suffix(".preflight.json")
            atomic_json(report_path, report)
            job["slice"] = {"path": str(snapshot), "sha256": report["sha256"], "report": str(report_path)}
            job["preflight"] = report
            job["state"] = "slice_rejected" if report["errors"] else "awaiting_review"
            job["review"] = None
            job.pop("error", None)
            snapshot.chmod(0o444)
            self._save(job)
            return self.summary(job)

    def _revalidate(self, job):
        spec = JobSpec.model_validate(job["spec"])
        self._profile(spec)
        path = self.config.inside(job["slice"]["path"])
        report = self._inspect(path, spec)
        if report["errors"] or report["sha256"] != job["slice"]["sha256"]:
            raise ValueError("slice changed or failed preflight; attach and review the correct file")
        return spec, path, report

    def review(self, job_id, sha256, *, preview_checked, hardware_checked):
        with self._lock(f"job:{self.config.state_dir}:{job_id}"):
            job = self._load(job_id)
            if job["state"] not in {"awaiting_review", "ready"} or job["dispatch_attempted"]:
                raise ValueError("job is not reviewable")
            if preview_checked is not True or hardware_checked is not True:
                raise ValueError("review requires actual model/first-layer preview and hardware/material checks")
            spec, _, report = self._revalidate(job)
            if sha256 != report["sha256"]:
                raise ValueError("review SHA256 mismatch")
            job["review"] = {"sha256": sha256, "spec_sha256": fingerprint(job["spec"]),
                             "target": self._target(spec.printer), "at": time.time()}
            job["state"] = "ready"
            self._save(job)
            return self.summary(job)

    def start_print(self, job_id, sha256, *, start_authorized=False):
        if start_authorized is not True:
            raise ValueError("printing requires the user's authorization for this job")
        with self._lock(f"job:{self.config.state_dir}:{job_id}"):
            job = self._load(job_id)
            if job["dispatch_attempted"]:
                # Never call upload or start again after an uncertain or accepted request.
                return self.summary(job)
            if job["state"] != "ready" or not job["review"]:
                raise ValueError("review this job before printing")
            spec, path, report = self._revalidate(job)
            review = job["review"]
            if sha256 != report["sha256"] or sha256 != review["sha256"] or fingerprint(job["spec"]) != review["spec_sha256"]:
                raise ValueError("print request differs from reviewed file/settings")
            target = self._target(spec.printer)
            if review["target"] != target or time.time() - review["at"] > 3600:
                raise ValueError("printer target changed or review is older than one hour; recheck hardware")
            with self._lock(f"printer:{self._device_key(spec.printer)}"):
                printer = self._printer(spec.printer)
                live = printer.status()
                self._check_live(live, spec, idle=True)
                self._claim_printer(job, spec.printer)
                remote = f"fcb-{job_id}-{sha256[:10]}.3mf"
                job["remote_name"] = remote
                job["state"] = "uploading"
                self._save(job)
                try:
                    upload = printer.upload(path, remote)
                    if upload.get("uploaded") is not True:
                        raise RuntimeError("upload did not report success")
                    # Files are immutable to this API, nevertheless recheck after network I/O.
                    if digest(path) != sha256:
                        raise ValueError("slice changed during upload; print was not dispatched")
                    self._check_live(printer.status(), spec, idle=True)
                    mapping = spec.print_options.ams_mapping
                    if not spec.print_options.use_ams:
                        mapping = [-1] * report["profile"]["project_filament_count"]
                        for position in report["profile"]["used_filament_ids"]:
                            mapping[position] = 254
                    options = {"gcode_md5": report["embedded_gcode"]["md5"], "bed_type": spec.hardware.bed,
                               "use_ams": spec.print_options.use_ams, "ams_mapping": mapping,
                               "bed_leveling": spec.print_options.bed_leveling,
                               "flow_cali": spec.print_options.flow_calibration,
                               "vibration_cali": spec.print_options.vibration_calibration,
                               "timelapse": spec.print_options.timelapse}
                    # Persist intent BEFORE the first packet. A crash stays ambiguous, never retries.
                    job["state"] = "dispatching"
                    job["dispatch_attempted"] = True
                    job["dispatch_at"] = time.time()
                    job["target"] = target
                    self._save(job)
                    result = printer.start(remote, options)
                    job["dispatch"] = {k: result.get(k) for k in ("accepted", "accepted_unknown", "sequence_id", "command", "rejected")}
                    job["state"] = "accepted" if result.get("accepted") is True else "start_unknown"
                    if result.get("rejected"):
                        job["state"] = "start_rejected"
                except Exception as exc:
                    job["state"] = "start_unknown" if job["dispatch_attempted"] else "upload_failed"
                    # No raw transport exception or credential contents in durable logs.
                    job["error"] = f"{type(exc).__name__}: operation outcome needs inspection"
                    if not job["dispatch_attempted"]:
                        self._release_printer(job, spec.printer)
                self._save(job)
                return self.summary(job)

    @staticmethod
    def _check_live(live, spec, idle=False, require_no_error=False):
        if live.get("connected") is not True or live.get("state") == "UNKNOWN":
            raise ValueError("fresh printer state is unavailable")
        now = time.time()
        timestamp = live.get("timestamp")
        if not isinstance(timestamp, (int, float)) or not -5 <= now - timestamp <= 60:
            raise ValueError("printer report is stale")
        model = live.get("model")
        if model:
            normalized = re.sub(r"[^a-z0-9]", "", str(model).lower().replace("bambu lab", ""))
            if normalized != spec.hardware.model:
                raise ValueError("live printer model differs from the reviewed hardware")
        # Some A1 firmware omits the model; exact serial target + manual hardware review is required.
        if idle and live.get("state") not in {"IDLE", "FINISH"}:
            raise ValueError("printer is not idle")
        if (idle or require_no_error) and live.get("errors") not in (None, 0, "0", [], {}):
            raise ValueError("printer reports an error")

    def printer_status(self, alias):
        return self._printer(alias).status()

    def status(self, job_id, refresh=False):
        with self._lock(f"job:{self.config.state_dir}:{job_id}"):
            job = self._load(job_id)
            if refresh and job["dispatch_attempted"]:
                spec = JobSpec.model_validate(job["spec"])
                if job.get("target") != self._target(spec.printer):
                    raise ValueError("printer target changed; refusing to attribute this job's status")
                try:
                    live = self._printer(spec.printer).status()
                    self._check_live(live, spec)
                    job["last_live"] = {k: live.get(k) for k in ("state", "filename", "progress", "timestamp")}
                    if self._same_file(job, live):
                        state = live["state"]
                        if state == "RUNNING":
                            job["state"], job["observed_running"] = "running", True
                        elif state == "PAUSE":
                            job["state"] = "paused"
                        elif state == "FINISH" and job["observed_running"]:
                            job["state"] = "complete"
                            with self._lock(f"printer:{self._device_key(spec.printer)}"):
                                self._release_printer(job, spec.printer)
                        elif state == "FAILED":
                            job["state"] = "failed"
                    else:
                        job["status_note"] = "Live filename does not match this job; no start/completion inferred."
                    job.pop("status_error", None)
                except Exception as exc:
                    job["status_error"] = f"{type(exc).__name__}: fresh status unavailable"
                self._save(job)
            return self.summary(job)

    @staticmethod
    def _same_file(job, live):
        name = str(live.get("filename") or "").replace("\\", "/").rsplit("/", 1)[-1]
        remote = job.get("remote_name", "")
        return bool(remote) and name in {remote, Path(remote).stem}

    def control(self, job_id, action, *, authorized=False):
        if authorized is not True or action not in {"pause", "resume", "stop"}:
            raise ValueError("explicit job control authorization and a supported action are required")
        with self._lock(f"job:{self.config.state_dir}:{job_id}"):
            job = self._load(job_id)
            spec = JobSpec.model_validate(job["spec"])
            target = self._target(spec.printer)
            if not job["dispatch_attempted"] or target != job.get("target"):
                raise ValueError("job was not dispatched to this printer")
            with self._lock(f"printer:{self._device_key(spec.printer)}"):
                printer = self._printer(spec.printer)
                live = printer.status()
                self._check_live(live, spec, require_no_error=(action == "resume"))
                if not self._same_file(job, live) or live["state"] not in {"RUNNING", "PAUSE"}:
                    raise ValueError("active printer job does not match; refusing to control another job")
                result = printer.control(action)
                job["last_control"] = {"action": action, "accepted": result.get("accepted"), "at": time.time()}
                self._save(job)
                return {"job_id": job_id, "action": action, "accepted": result.get("accepted"),
                        "next": "Read live status to confirm the effect; do not automatically repeat."}

    def close_job(self, job_id, *, operator_confirmed=False):
        """Release an ambiguous job only after operator reconciliation and fresh idle."""
        if operator_confirmed is not True:
            raise ValueError("operator must confirm that this job is no longer pending or active")
        with self._lock(f"job:{self.config.state_dir}:{job_id}"):
            job = self._load(job_id)
            spec = JobSpec.model_validate(job["spec"])
            target = job.get("target") or (job.get("review") or {}).get("target")
            if not target or target != self._target(spec.printer):
                raise ValueError("original printer target is required for reconciliation")
            with self._lock(f"printer:{self._device_key(spec.printer)}"):
                self._check_live(self._printer(spec.printer).status(), spec, idle=True)
                self._release_printer(job, spec.printer)
                job["state"] = "closed_by_operator"
                job["dispatch_attempted"] = True  # A closed job can never be dispatched again.
                job["operator_closed_at"] = time.time()
                self._save(job)
                return self.summary(job)

    def preview(self, job_id):
        job = self._load(job_id)
        path = self._jobdir(job_id) / f"cad-preview-{uuid.uuid4().hex[:8]}.png"
        with self._lock(f"freecad:{self.config.settings.freecad_port}"):
            # Screenshot is of the current active FreeCAD view; caller must verify document identity.
            return require_success(self.cad.screenshot(path), "cad_screenshot")

    @staticmethod
    def summary(job):
        r = {"job_id": job["id"], "state": job["state"], "printer": job["spec"]["printer"],
             "dispatch_attempted": job["dispatch_attempted"], "observed_running": job["observed_running"]}
        for key in ("cad", "slice", "error", "status_error", "status_note", "last_live", "dispatch"):
            if key in job:
                r[key] = job[key]
        if "preflight" in job:
            p = job["preflight"]
            r["preflight"] = {k: p.get(k) for k in ("profile_verification", "profile", "errors", "layer_count", "time_seconds", "first_layer")}
        r["next"] = {"awaiting_slice": "Import cad.paths.stl in Bambu Studio, slice and inspect Preview, export plate sliced file, then attach_slice.",
                     "awaiting_review": "Inspect CAD and Bambu first-layer/support preview; verify actual hardware and spool mapping, then review_job with SHA256.",
                     "ready": "start_print only if the user authorized this exact job.",
                     "accepted": "Command accepted is not RUNNING; refresh job status.",
                     "dispatching": "Dispatch outcome is unknown after interruption. Refresh status; never resend this job.",
                     "start_unknown": "Read printer state; never automatically resend. Check the official Bambu Studio Device view if needed.",
                     "running": "Refresh at a useful interval; completed means matching FINISH after observed RUNNING.",
                     "slice_rejected": "Correct profile/plate/layout in Bambu Studio and attach a new export."}.get(job["state"], job.get("next"))
        return r
