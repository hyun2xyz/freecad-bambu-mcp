# Portable pipeline setup and recovery

Read this for installation, CLI profiles or uncertain dispatch. Public source:
[hyun2xyz/freecad-bambu-mcp](https://github.com/hyun2xyz/freecad-bambu-mcp).
The repository's `docs/setup.md` owns detailed platform installation steps.

## Setup

Install Python 3.11+ and uv, clone the repository and run `uv sync --frozen`.
Install the FreeCADMCP addon from `neka-nat/freecad-mcp` at the revision documented
in the repository; keep RPC on localhost and start it from FreeCAD's MCP workbench.
Install Bambu Studio. Copy `examples/config.example.json` to `config.local.json` and
set `workspace` to the actual working directory (relative paths resolve beside config).
Set the printer model/nozzle/bed/material explicitly. Credentials are environment
variables named by the local config; `.env` files are not automatically loaded.
Use a trusted local printer CA, or an explicitly selected self-signed LAN option.
Never change printer firmware security modes or TLS settings silently.

Register the venv's `freecad-bambu-mcp --config /absolute/config.local.json serve`
with the current MCP client. On Windows the executable is under `.venv/Scripts`;
on macOS/Linux under `.venv/bin`. Use the client's installed configuration tool or
UI; do not replace its entire config file. A new task/restart may be needed.

## Commands

Run `freecad-bambu-mcp --config /absolute/config.local.json COMMAND`:

| Command | Result |
| --- | --- |
| `doctor` | RPC, slicer and credential-presence diagnosis; no printing |
| `prepare examples/plate-job.json` | New persisted job, CAD export and optional CLI slice |
| `attach JOB sliced.3mf` | Immutable slice snapshot and bounded preflight |
| `preview JOB` | One active FreeCAD view PNG |
| `review JOB SHA --preview-checked --hardware-checked` | Bind actual checks to file/settings/target |
| `print JOB SHA --start-authorized` | Upload then at-most-once automatic dispatch |
| `status JOB --refresh` | Fresh observed state and reconciliation |
| `control JOB pause --authorized` | Matching job control; also resume/stop |
| `close JOB --operator-confirmed` | Resolve an uncertain inactive job; never marks it printed |

The flags record real checks/authorization, not a shortcut around them. Review expires
after one hour or when target/settings/file changes. The job state is under the workspace's
`.freecad-bambu`; persistent printer leases are in the user's cache. Do not delete a lease
to retry an uncertain print. Use the explicit reconciliation flow.

## CLI profiles and GUI checkpoint

For repeat jobs set `slicing.mode="cli"` with `settings` (full machine + process JSON)
and `filaments` (full filament JSON). Paths must lie inside the workspace.
A vendor preset that only contains `inherits` may not contain enough information.
The command uses a private slicer datadir, explicit profile files, arrangement and
normal validity checks. It never passes `--no-check` or permits mixed temperatures.
Validate generated output again; a zero slicer exit code is insufficient.

For first-time, complex or unsupported jobs use `slicing.mode="gui"`. Open the exported
STL in Bambu Studio through the current computer-use tool, select exact printer/profile,
slice and inspect Preview, then export the plate sliced file and attach it. This is a
resumable stage inside one user-requested workflow, not an abandoned task.

## Output limits

Native dispatch currently requires a single plate, explicit project filament layout,
an exact material/profile match and supported conventional AMS mappings or one external
spool. This preflight is not a full G-code safety proof. Use trusted slicer exports.
Actual compatibility depends on model, firmware, authorized LAN access and certificate
settings. Do not fetch proprietary client keys or claim H2/cloud support.

On timeout, retain the job and inspect state. A matching FINISH without previously
observed RUNNING does not prove this job was printed. Operator reconciliation can close
an unobserved job but must be reported as operator-closed, not automatically verified.
