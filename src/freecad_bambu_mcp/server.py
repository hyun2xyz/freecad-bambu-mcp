"""Small MCP surface; job manifests carry details outside model context."""
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .workflow import Workflow


def create_server(config):
    workflow = Workflow(config)
    app = FastMCP("freecad-bambu", instructions="Prepare CAD and inspect slices. Actual printing requires an authorized, reviewed job. Never infer RUNNING from an acknowledgement or retry an ambiguous start.")
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    local = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
    hardware = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)
    code_execution = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)

    @app.tool(annotations=read)
    def capabilities() -> dict:
        """Return compact configured CAD/slicer/printer capabilities; no printer connection."""
        return workflow.capabilities()

    @app.tool(annotations=read)
    def doctor() -> dict:
        """Check local FreeCAD RPC, slicer executable and credential presence; no printing."""
        return workflow.doctor()

    @app.tool(annotations=code_execution)
    def cad_execute(script_file: str) -> dict:
        """Execute one trusted workspace Python file in FreeCAD, once. Opt-in full Python access."""
        return workflow.cad_execute(script_file)

    @app.tool(annotations=code_execution)
    def prepare_job(spec_file: str) -> dict:
        """Build/export CAD and optionally CLI-slice from a workspace JSON spec. Never prints."""
        return workflow.prepare(spec_file)

    @app.tool(annotations=local)
    def attach_slice(job_id: str, sliced_file: str) -> dict:
        """Snapshot and preflight a Bambu sliced 3MF for a prepared job; invalidates prior review."""
        return workflow.attach_slice(job_id, sliced_file)

    @app.tool(annotations=local)
    def review_job(job_id: str, sha256: str, preview_checked: bool, hardware_checked: bool) -> dict:
        """Record actual CAD/first-layer preview and hardware/spool checks against an exact slice hash."""
        return workflow.review(job_id, sha256, preview_checked=preview_checked, hardware_checked=hardware_checked)

    @app.tool(annotations=hardware)
    def start_print(job_id: str, sha256: str, start_authorized: bool = False) -> dict:
        """Upload and dispatch an authorized reviewed job once. Read status afterward; never auto-retry."""
        return workflow.start_print(job_id, sha256, start_authorized=start_authorized)

    @app.tool(annotations=read)
    def job_status(job_id: str, refresh: bool = False) -> dict:
        """Read compact persisted state; refresh reads fresh printer telemetry and reconciles it."""
        return workflow.status(job_id, refresh)

    @app.tool(annotations=read)
    def printer_status(printer: str) -> dict:
        """Read fresh LAN printer telemetry using a configured alias, without exposing credentials."""
        return workflow.printer_status(printer)

    @app.tool(annotations=local)
    def cad_preview(job_id: str) -> dict:
        """Save one current active FreeCAD view PNG; verify the active document matches this job."""
        return workflow.preview(job_id)

    @app.tool(annotations=hardware)
    def control_print(job_id: str, action: str, authorized: bool = False) -> dict:
        """Pause/resume/stop only a matching live job; requires authorization for that action."""
        return workflow.control(job_id, action, authorized=authorized)

    @app.tool(annotations=hardware)
    def close_job(job_id: str, operator_confirmed: bool = False) -> dict:
        """Release an uncertain job after operator reconciliation and fresh idle telemetry; never mark printed."""
        return workflow.close_job(job_id, operator_confirmed=operator_confirmed)

    return app
