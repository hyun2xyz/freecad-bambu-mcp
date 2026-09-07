---
name: freecad-bambu
description: "FreeCAD 설계와 MCP, Bambu Studio 슬라이싱·미리보기, Bambu 프린터 실제 출력까지 연결하는 작업에 사용한다."
---

# FreeCAD → Bambu Studio → Print

Turn one authorized design/print request into editable CAD, a checked sliced file,
and observed printer state. Follow the current workspace's AGENTS.md and file layout.
Preserve source documents and existing jobs. Read [references/pipeline.md](references/pipeline.md)
only for setup, CLI commands, profile preparation or recovery.

## Choose the route

Use the `freecad-bambu` MCP's compact workflow tools when installed.
Start with `capabilities` or `doctor`; discover only tools needed for the current stage.
The same operations are available through the `freecad-bambu-mcp` CLI.
If the unified server is unavailable, the existing FreeCAD MCP and Bambu Studio GUI
can prepare the same artifacts; finish setup before claiming automated dispatch.

- FreeCAD: run a trusted workspace Python file once; use parametric features and
  named objects. Python has full host access, so inspect newly obtained code first.
- Bambu Studio: use computer use for a new model, support strategy, material or color
  layout. Slice → Preview → export the plate's sliced 3MF.
- CLI slicing: use complete machine/process/filament JSON profiles already validated
  with this installed slicer. Failed profiles become a GUI checkpoint.
- Printing: the unified LAN transport handles one `plate_1` job on configured
  A1/A1 mini/P1/X1 devices. H2, cloud-only and unverified firmware use the official
  Bambu Studio flow after observing its actual UI; never bypass authorization modes.

## Complete the request

1. Read relevant project instructions, dimensions and exact hardware information.
   Resolve missing dimensions, nozzle, physical bed or material together only when
   they affect the result. Never infer A1 versus A1 mini from a similar name.
2. Write a short job spec and a trusted CAD script in the workspace. `prepare_job`
   runs the script and validates named solids before exporting FCStd/STL/STEP.
   A failed CAD call may have changed the document; inspect before retrying.
3. Inspect CAD dimensions and one useful view. `cad_preview` shows the current active
   FreeCAD view, so verify the document identity. Check holes, thickness and fit.
4. Complete the CLI slice or GUI checkpoint. Inspect the actual model, first layer,
   orientation, supports, build plate and filament mapping in Bambu Preview.
5. `attach_slice` snapshots the export, checks the profile and records SHA256.
   A `.3mf` extension or upload success alone does not establish print readiness.
6. After actual preview and hardware/spool checks, call `review_job` using the exact
   hash. Do not assert checks that were not performed. The target must be configured
   locally; never request credentials in chat or save them in a shared artifact.
7. If the user already authorized this exact print, call `start_print` with that hash
   and `start_authorized=true`. Do not ask again solely because this is a new stage.
   A setup/research/skill request does not authorize printing an arbitrary test object.
8. Read `job_status(refresh=true)` to distinguish accepted, unknown, RUNNING and
   completion. Refresh at useful milestones; do not fill context with telemetry.
   Report completion only for the matching filename after observed RUNNING → FINISH.

For pauses/stops, use the matching job and current user authorization. Keep the
physical printer's own emergency controls available; network automation is not an
emergency stop. Do not issue temperature, homing or motion commands as connection tests.

## Resume without duplicate printing

Keep the job ID. `job_status` resumes work without replaying CAD, slicing or dispatch.
An uncertain start retains a persistent printer lease across processes/workspaces.
Inspect the printer and official Device view; never repeat a start or switch to a
second transport to send the same job. `close_job` releases the lease only after the
operator reconciles the job and fresh telemetry is idle; it does not claim a print
completed. Reprinting is a new, explicitly authorized job with fresh review.

## Minimize total work and context

Use file-backed scripts/specs and compact numeric results. No intermediate screenshots
unless they resolve geometry or UI uncertainty; no full G-code, ZIP content or tool catalog.
Handle short sequential work locally. Delegate only a substantial independent draft or
read to one cheaper supported model (for example `gpt-5.6-luna`, medium, when available).
Send a bounded file/acceptance card without conversation history; keep writer ownership
separate. The main agent checks geometry, tolerances, profiles and physical commands.
Escalate once if needed. Do not change global model settings or silently use external
model accounts. Smaller models do not inherently consume fewer tokens; reduce context,
round trips and repeated work, and do not invent a savings percentage.

## Evidence

Return exact artifact paths and the furthest verified stage. Separate local tests,
CAD/UI verification, upload, command acceptance, actual motion and finished output.
Never label mocked printer tests as a real successful print.
