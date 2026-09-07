# Portable setup

## 1. Python package

Use Python 3.11 or newer and install the locked environment:

```sh
uv sync --frozen
```

The console entry point is `freecad-bambu-mcp`. With a Windows virtual environment use `.venv\Scripts\freecad-bambu-mcp.exe`; with macOS/Linux use `.venv/bin/freecad-bambu-mcp`. No API key or internal LLM service is required.

## 2. FreeCAD

Install the separately maintained [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp) addon in FreeCAD. This project expects the tested upstream revision `3da6db5f71a7b74d1b69d295d1ba89233ad622b5` and its main-thread RPC server on `127.0.0.1:9875`. The addon is not vendored here and must be installed and upgraded by the operator.

Enable trusted FreeCAD Python only when the local CAD scripts are trusted:

```json
"allow_freecad_python": true
```

The example `examples/plate.py` creates `PipelinePlate` and `PlateWithHole`; it refuses to create a duplicate document. Run `doctor` before a job.

## 3. Local configuration

```sh
cp examples/config.example.json config.local.json
```

When copying this file to the repository root, set:

```json
"workspace": "."
```

The example's `..` is convenient only when the config remains under `examples/`. Keep the workspace dedicated to the job inputs and state. Printer aliases are strict: model, nozzle, bed, and filament list in the job must match the configured alias.

Only environment variable names are stored in JSON. Set the referenced values in the process environment:

```sh
export BAMBU_HOST=printer.local
export BAMBU_SERIAL=YOUR_SERIAL
export BAMBU_ACCESS_CODE=YOUR_ACCESS_CODE
```

The process does not auto-load `.env`. Do not paste credentials into chat, commit them, or place them in public fixtures. TLS verification is on by default. For a trusted LAN, provide an operator-owned CA or deliberately set the documented self-signed option; the tool does not make that choice for you.

## 4. FreeCAD → Bambu workflow

1. Start FreeCAD and its RPC addon, then run `doctor`.
2. Run `prepare examples/plate-job.json`.
3. Slice the exported STL in Bambu Studio. Check the model and first layer/support preview. Export a `.gcode.3mf`.
4. Run `attach JOB exported.gcode.3mf`. Preflight checks the archive without extracting it, requires `Metadata/plate_1.gcode`, and records SHA-256 and MD5 evidence.
5. Review the actual previews and hardware/material selection. Run `review JOB SHA256 --preview-checked --hardware-checked`.
6. Only after the user authorizes this exact job, run `print JOB SHA256 --start-authorized`.
7. Refresh with `status JOB --refresh`. A matching FINISH is completion only after matching RUNNING was observed.

Use `control` only with explicit authorization and a matching live filename. An uncertain upload/start outcome is persisted and is never automatically retried.

## 5. MCP client

Copy `examples/mcp.json`, replace absolute paths, and point the client to `serve`. One instruction coordinates the full workflow; it must preserve the preview and hardware checks and may proceed without repeating approval questions when the user already authorized the exact action.

## 6. Verification limits

`uv run pytest` uses offline protocol/transport/workflow fixtures and a real stdio MCP round trip. It does not prove physical printing or LAN firmware compatibility. FreeCAD 1.1.3 export and Bambu Studio 2.8.2 GUI slicing have been exercised on macOS; see [verification.md](verification.md).

## 7. Profiles, skills and recovery

For repeated CLI slices, set `slicing` to `{"mode":"cli","settings":["profiles/machine.json","profiles/process.json"],"filaments":["profiles/pla.json"]}`. Supply complete CLI-compatible presets, including type, origin, name and compatibility metadata. A raw `project_settings.config` renamed to JSON is **not** a valid CLI preset. The first-release tested path is the GUI checkpoint; CLI preset compatibility needs validation in your installed Studio. A CLI failure preserves the CAD export and job ID: slice in the GUI and attach to that same job.

Copy the complete `skills/freecad-bambu` directory into your agent's user skill directory, preserving its `references` folder. For Codex, install this repository path through its skill installer, or copy into `~/.codex/skills` only if your own configuration uses that root. Users with a managed harness should update its canonical source and installer rather than overwriting an installed copy.

The example MCP entry works for JSON-configured MCP clients. Codex users can register the installed executable with `codex mcp add freecad-bambu -- /absolute/path/to/.venv/bin/freecad-bambu-mcp --config /absolute/config.local.json serve`; replace the executable with `.venv/Scripts/freecad-bambu-mcp.exe` on Windows. Start a new task/client session to discover newly installed tools. Credentials must be present in the server's actual environment; a GUI-launched app may not inherit a terminal's exported variables.

After uncertain dispatch, use fresh telemetry and the printer/official Device view. Do not clear state files or send a second transport command. Once the operator has established that the job is neither pending nor active and the printer is idle, `close JOB --operator-confirmed` releases the lease without claiming a successful print. Another print requires a new reviewed job. To reuse an already-open CAD document, set `cad.script` to `null` and provide its exact document/object names.
