import json, tempfile, time, zipfile
from pathlib import Path
from contextlib import contextmanager

import pytest

from freecad_bambu_mcp.config import Config
from freecad_bambu_mcp.workflow import Workflow


GCODE = "; estimated time: 1m 2s\nG1 X1 Y1 E0.2\n"


def write_slice(path, *, model="Bambu Lab A1", nozzle="0.4", bed="Textured PEI Plate", filaments=None, ids=None, extra=()):
    filaments = ["PLA"] if filaments is None else filaments
    ids = [0] if ids is None else ids
    cfg = {"printer_model": model, "nozzle_diameter": nozzle, "bed_type": bed, "filament_type": filaments}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Metadata/plate_1.gcode", GCODE)
        z.writestr("Metadata/plate_1.json", json.dumps({"filament_ids": ids}))
        z.writestr("Metadata/project_settings.config", json.dumps(cfg))
        for name, value in extra:
            z.writestr(name, value)


class FakeCAD:
    def __init__(self):
        self.executed = []

    def status(self):
        return {"success": True, "rpc_server": "running"}

    def execute_file(self, path):
        self.executed.append(Path(path))
        return {"success": True, "message": "ok"}

    def export(self, document, objects, output_dir):
        output_dir = Path(output_dir); output_dir.mkdir()
        paths = {}
        for key, suffix in (("model", "FCStd"), ("stl", "stl"), ("step", "step")):
            p = output_dir / f"model.{suffix}"; p.write_bytes(b"fixture"); paths[key] = str(p)
        paths["fcstd"] = paths["model"]
        return {"success": True, "paths": paths, "bounds_mm": [0, 0, 0, 10, 10, 2], "volume_mm3": 200}


class FakePrinter:
    def __init__(self, config, statuses=None, *, start_error=False):
        self.config = config; self.statuses = list(statuses or []); self.start_error = start_error
        self.upload_calls = 0; self.start_calls = 0; self.control_calls = []

    def status(self):
        if self.statuses: return dict(self.statuses.pop(0))
        return self.live("IDLE")

    def live(self, state, filename=None, **extra):
        d = {"connected": True, "state": state, "model": "A1", "filename": filename,
             "progress": 0, "errors": None, "timestamp": time.time()}
        d.update(extra); return d

    def upload(self, path, remote):
        self.upload_calls += 1
        return {"uploaded": True, "remote_name": remote}

    def start(self, remote, options):
        self.start_calls += 1
        if self.start_error: raise RuntimeError("synthetic start failure")
        return {"accepted": True, "command": "project_file"}

    def control(self, action):
        self.control_calls.append(action); return {"accepted": True}


@pytest.fixture
def harness(monkeypatch):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp); (root / "scripts").mkdir()
        (root / "scripts" / "plate.py").write_text("print('ok')", encoding="utf8")
        config_path = root / "config.json"
        config_path.write_text(json.dumps({"workspace": str(root), "allow_freecad_python": True,
            "printers": {"main": {"model": "a1", "nozzle_mm": 0.4, "bed": "textured_plate", "filaments": ["PLA"],
                "host_env": "TEST_BAMBU_HOST", "serial_env": "TEST_BAMBU_SERIAL", "access_code_env": "TEST_BAMBU_CODE"}}}), encoding="utf8")
        monkeypatch.setenv("TEST_BAMBU_HOST", "fake-host")
        monkeypatch.setenv("TEST_BAMBU_SERIAL", "FAKE123")
        monkeypatch.setenv("TEST_BAMBU_CODE", "00000000")
        monkeypatch.setattr(Workflow, "_locks_root", lambda self: root / "locks", raising=False)
        cad = FakeCAD(); printer = FakePrinter(None)
        wf = Workflow(Config(config_path), cad=cad, printer_factory=lambda cfg: printer)
        spec = {"name": "plate-job", "printer": "main", "hardware": {"model": "a1", "nozzle_mm": 0.4, "bed": "textured_plate", "filaments": ["PLA"]},
                "cad": {"document": "PipelinePlate", "objects": ["PlateWithHole"], "script": "scripts/plate.py"}, "slicing": {"mode": "gui"}, "print_options": {}}
        (root / "job.json").write_text(json.dumps(spec), encoding="utf8")
        yield root, wf, printer, cad, root / "job.json"


def prepare_attach_review(harness):
    root, wf, printer, cad, spec = harness
    job = wf.prepare(spec)
    assert job["state"] == "awaiting_slice"
    sliced = root / "slice.3mf"; write_slice(sliced)
    attached = wf.attach_slice(job["job_id"], sliced); assert attached["state"] == "awaiting_review"
    sha = attached["slice"]["sha256"]
    reviewed = wf.review(job["job_id"], sha, preview_checked=True, hardware_checked=True)
    assert reviewed["state"] == "ready"
    return job["job_id"], sha


def test_prepare_attach_review_start_refresh_full_flow(harness):
    root, wf, printer, cad, spec = harness
    job_id, sha = prepare_attach_review(harness)
    printer.statuses = [printer.live("IDLE"), printer.live("IDLE"), printer.live("RUNNING", f"fcb-{job_id}-{sha[:10]}.3mf"), printer.live("FINISH", f"fcb-{job_id}-{sha[:10]}.3mf")]
    accepted = wf.start_print(job_id, sha, start_authorized=True)
    assert accepted["state"] == "accepted" and printer.upload_calls == printer.start_calls == 1
    assert wf.status(job_id, refresh=True)["state"] == "running"
    assert wf.status(job_id, refresh=True)["state"] == "complete"


def test_start_requires_review_and_authorization(harness):
    root, wf, printer, cad, spec = harness
    job = wf.prepare(spec); sliced = root / "slice.3mf"; write_slice(sliced); attached = wf.attach_slice(job["job_id"], sliced)
    with pytest.raises(ValueError): wf.start_print(job["job_id"], attached["slice"]["sha256"], start_authorized=True)
    with pytest.raises(ValueError): wf.start_print(job["job_id"], "0" * 64, start_authorized=False)


def test_repeated_start_is_at_most_once(harness):
    job_id, sha = prepare_attach_review(harness); root, wf, printer, cad, spec = harness
    printer.statuses = [printer.live("IDLE"), printer.live("IDLE")]
    wf.start_print(job_id, sha, start_authorized=True); wf.start_print(job_id, sha, start_authorized=True)
    assert printer.upload_calls == printer.start_calls == 1


@pytest.mark.parametrize("kind", ["badsha", "wrongmodel", "nozzlemismatch", "busy", "stale"])
def test_review_or_start_blocks_invalid_artifact_or_live_state(harness, kind):
    root, wf, printer, cad, spec = harness
    if kind == "wrongmodel":
        write_slice(root / "slice.3mf", model="Bambu Lab A1 mini")
    elif kind == "nozzlemismatch":
        write_slice(root / "slice.3mf", nozzle="0.6")
    else: write_slice(root / "slice.3mf")
    job = wf.prepare(spec); attached = wf.attach_slice(job["job_id"], root / "slice.3mf")
    if kind in {"wrongmodel", "nozzlemismatch"}:
        assert attached["state"] == "slice_rejected"; return
    sha = attached["slice"]["sha256"]
    if kind == "badsha":
        with pytest.raises(ValueError): wf.review(job["job_id"], "0" * 64, preview_checked=True, hardware_checked=True)
    else:
        wf.review(job["job_id"], sha, preview_checked=True, hardware_checked=True)
        if kind == "busy": printer.statuses = [printer.live("RUNNING")]
        if kind == "stale": printer.statuses = [{**printer.live("IDLE"), "timestamp": time.time() - 100}]
        with pytest.raises(ValueError):
            wf.start_print(job["job_id"], sha, start_authorized=True)


def test_changed_artifact_invalidates_review(harness):
    root, wf, printer, cad, spec = harness; job_id, sha = prepare_attach_review(harness)
    job = wf._load(job_id); Path(job["slice"]["path"]).chmod(0o600); Path(job["slice"]["path"]).write_bytes(b"changed"); Path(job["slice"]["path"]).chmod(0o444)
    with pytest.raises(ValueError): wf.start_print(job_id, sha, start_authorized=True)


def test_changed_reviewed_config_invalidates_review(harness):
    root, wf, printer, cad, spec = harness; job_id, sha = prepare_attach_review(harness)
    job = wf._load(job_id); job["spec"]["hardware"]["nozzle_mm"] = 0.6; wf._save(job)
    with pytest.raises(ValueError): wf.start_print(job_id, sha, start_authorized=True)


def test_different_filename_does_not_complete_and_control_requires_match(harness):
    root, wf, printer, cad, spec = harness; job_id, sha = prepare_attach_review(harness)
    printer.statuses = [printer.live("IDLE"), printer.live("IDLE"), printer.live("RUNNING", "other.3mf")]
    wf.start_print(job_id, sha, start_authorized=True)
    assert wf.status(job_id, refresh=True)["state"] == "accepted"
    with pytest.raises(ValueError): wf.control(job_id, "pause", authorized=True)


def test_failed_start_is_not_retried_and_pause_stop_control(harness):
    root, wf, printer, cad, spec = harness; job_id, sha = prepare_attach_review(harness); printer.start_error = True
    printer.statuses = [printer.live("IDLE"), printer.live("IDLE")]
    result = wf.start_print(job_id, sha, start_authorized=True)
    assert result["state"] in {"start_unknown", "upload_failed"} and printer.start_calls == 1
    assert wf.start_print(job_id, sha, start_authorized=True)["state"] == result["state"]


def test_cross_job_leases_are_exposed_by_locking(harness):
    root, wf, printer, cad, spec = harness
    # The workflow owns the lease namespace; this assertion ensures tests never
    # silently fall back to the real user's home directory.
    assert wf._locks_root() == root / "locks"


def test_lease_blocks_another_job_even_if_printer_still_reports_idle(harness):
    root, wf, printer, cad, spec = harness
    first, sha1 = prepare_attach_review(harness)
    second, sha2 = prepare_attach_review(harness)
    wf.start_print(first, sha1, start_authorized=True)
    with pytest.raises(ValueError, match="holds this printer"):
        wf.start_print(second, sha2, start_authorized=True)
    assert printer.start_calls == 1


def test_restart_does_not_retry_and_operator_close_releases_lease(harness):
    root, wf, printer, cad, spec = harness
    first, sha1 = prepare_attach_review(harness)
    second, sha2 = prepare_attach_review(harness)
    printer.start_error = True
    wf.start_print(first, sha1, start_authorized=True)
    restarted = Workflow(wf.config, cad=cad, printer_factory=lambda cfg: printer)
    assert restarted.start_print(first, sha1, start_authorized=True)["state"] == "start_unknown"
    assert printer.start_calls == 1
    with pytest.raises(ValueError): restarted.close_job(first)
    assert restarted.close_job(first, operator_confirmed=True)["state"] == "closed_by_operator"
    printer.start_error = False
    assert restarted.start_print(second, sha2, start_authorized=True)["state"] == "accepted"
    assert printer.start_calls == 2


def test_matching_errored_pause_can_stop_but_cannot_resume(harness):
    root, wf, printer, cad, spec = harness
    job, sha = prepare_attach_review(harness)
    wf.start_print(job, sha, start_authorized=True)
    remote = f"fcb-{job}-{sha[:10]}.3mf"
    printer.statuses = [printer.live("PAUSE", remote, errors=1)]
    assert wf.control(job, "stop", authorized=True)["accepted"]
    printer.statuses = [printer.live("PAUSE", remote, errors=1)]
    with pytest.raises(ValueError): wf.control(job, "resume", authorized=True)
    assert printer.control_calls == ["stop"]


def test_finish_without_observed_running_is_not_completion(harness):
    root, wf, printer, cad, spec = harness
    job, sha = prepare_attach_review(harness)
    wf.start_print(job, sha, start_authorized=True)
    printer.statuses = [printer.live("FINISH", f"fcb-{job}-{sha[:10]}.3mf")]
    assert wf.status(job, refresh=True)["state"] == "accepted"
    assert wf._lease_path("main").exists()
