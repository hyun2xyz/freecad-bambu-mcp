# FreeCAD → Bambu Studio → Print MCP

Portable Python 3.11+ MCP and CLI for a reviewable FreeCAD-to-Bambu workflow. It keeps CAD execution, bounded 3MF preflight, explicit review, LAN upload, and status/control in one durable job record.

## Scope

- FreeCAD scripting through the separately installed `neka-nat/freecad-mcp` addon, using localhost XML-RPC and pinned revision `3da6db5f71a7b74d1b69d295d1ba89233ad622b5`.
- Bambu Studio GUI slicing with a human preview checkpoint, or CLI slicing only with explicit machine/process/filament profiles.
- Native single-plate dispatch for A1, A1 mini, P1P/P1S, X1C/X1E profiles. AMS mapping, fresh status, pause, resume, and stop are explicit workflow operations.
- Experimental LAN MQTT/FTPS transport. H2, cloud, FEM and proprietary client-certificate extraction are outside this release.

FreeCAD 1.1.3 CAD export and Bambu Studio 2.8.2 GUI slicing/preflight were exercised with the bundled sample on macOS. The LAN transport has offline tests; **no physical print has been verified**. See [verification](docs/verification.md) for exact limits.

## Install

```sh
git clone https://github.com/hyun2xyz/freecad-bambu-mcp.git
cd freecad-bambu-mcp
uv sync --frozen
cp examples/config.example.json config.local.json
```

Edit `config.local.json`. Set `workspace` to `.` when the file is in the repository root. Set printer environment variables in the local shell; credentials are never read from JSON, `.env`, or this repository.

```sh
uv run freecad-bambu-mcp --config config.local.json doctor
uv run freecad-bambu-mcp --config config.local.json capabilities
```

FreeCAD must be running with the pinned addon and its RPC server on `127.0.0.1:9875`. On Windows, use `.venv\Scripts\freecad-bambu-mcp.exe`; macOS, Linux, and Windows share the same Python package layout.

## CLI lifecycle

```text
prepare → attach JOB sliced.3mf → review JOB SHA256 --preview-checked --hardware-checked
print JOB SHA256 --start-authorized → status JOB --refresh
```

`preview`, `printer-status`, `control JOB pause|resume|stop --authorized`, and `close JOB --operator-confirmed` are available. A review binds the artifact hash, hardware profile and printer target. Start dispatch is attempted at most once per job; an uncertain result holds a persistent printer lease and must be inspected rather than resent.

The MCP server exposes the same engine through stdio. `examples/mcp.json` is a template; replace its absolute paths locally.

Install [the portable skill](skills/freecad-bambu/SKILL.md) into your client's skill directory. Then ask, for example: “Use freecad-bambu to create an 80 × 40 × 4 mm plate with a 10 mm center hole, check the first layer, and print on my configured A1.” One request coordinates all stages and retains existing authorization; missing physical checks remain checkpoints. The package makes no LLM calls itself. Twelve compact tools, saved scripts and resumable jobs reduce repeated context and work.

## Security and operator boundary

FreeCAD Python is trusted code and is disabled by default. LAN TLS verification remains enabled; use an operator-owned CA or explicitly configure self-signed trust for a trusted LAN. The package does not change security settings automatically. Keep `config.local.json`, credentials, job state, and sliced files private.

## Development

```sh
uv run pytest
```

The tests are offline and do not prove hardware or physical-print behavior. See [docs/setup.md](docs/setup.md), [docs/research.md](docs/research.md), and [THIRD_PARTY.md](THIRD_PARTY.md).
