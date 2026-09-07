# MCP research and implementation decisions — 2026-09-07

Primary GitHub README/source and repository metadata were checked on this date. Push dates are repository activity, not compatibility certification. Stars were used for discovery only. No third-party MCP source was vendored or copied.

| Repository | Latest push checked | Features considered | Decision here |
| --- | --- | --- | --- |
| [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp) | 2026-09-05 | Main-thread RPC, batch Python, text-only intermediate feedback, explicit snapshots | Use its separately installed MIT addon at `3da6db5f71a7b74d1b69d295d1ba89233ad622b5`; a small original client validates/exports named solids. |
| [blwfish/freecad-mcp](https://github.com/blwfish/freecad-mcp) | 2026-09-01 | 32 tools spanning parametric design, mesh and CNC toolpaths; macOS focus | Keep broad trusted FreeCAD scripting, defer CNC and a large always-loaded tool surface. LGPL-2.1 metadata. |
| [tessalabs-space/freecad-mcp](https://github.com/tessalabs-space/freecad-mcp) | 2026-04-17 | Typed engineering tools, drawings, sweeps and CAE handoff | Adopt the idea of structured geometry evidence; defer FEM/CAE. README says MIT, API reports NOASSERTION; no source reused. |
| [gurul/gencad](https://github.com/gurul/gencad) | 2026-08-31 | Two core tools, file-backed headless builds and section-render feedback | Adopt compact tools/file-backed work and explicit visual checks; use the existing GUI addon, defer headless/section renderer. MIT metadata. |
| [DMontgomery40/bambu-printer-mcp](https://github.com/DMontgomery40/bambu-printer-mcp) | 2026-07-30 | STL operations, named slicing templates, AMS mapping, MQTT/FTPS upload and print control | Reuse concepts, not GPL-2.0 source. Installed 1.1.1 has model-dependent start branches that can return success without observed RUNNING; our job engine separates dispatch from telemetry. |
| [griches/bambu-mcp](https://github.com/griches/bambu-mcp) | 2026-03-08 | Printer aliases/fleet, status, file operations, AMS and camera control | Add configured aliases and shared physical-device locks; defer remote deletion/camera/fleet automation. No license confirmed in API metadata. |
| [synman/bambu-mcp](https://github.com/synman/bambu-mcp) | 2026-06-28 | Self-contained LAN MQTT/FTPS control | Implement a small original LAN adapter with explicit certificate settings. No license confirmed in API metadata. |
| [DMontgomery40/mcp-3D-printer-server](https://github.com/DMontgomery40/mcp-3D-printer-server) | 2026-07-30 | Broader multi-vendor printer integrations | Keep CAD/slicer/transport modules separate for future adapters; no unsupported vendor claims in 0.1. GPL-2.0 metadata. |

## What was customized

The public package combines parametric script execution, validated FCStd/STL/STEP exports, GUI/CLI slicing checkpoints, bounded archive inspection, exact A1-versus-mini checks, explicit AMS positions, immutable slice snapshots, hash-bound review, durable dispatch intent, device-wide leases and filename-correlated status. A server restart does not replay a print. An error-paused matching job can still be stopped.

[Bambu Studio's official CLI guide](https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage) and installed 2.8.2 `--help` were checked. The CLI adapter passes explicit full profiles and keeps normal validity checks; a raw project-settings dump failed preset validation locally. GUI Slice → Preview → plate export is the validated first-release route. Computer use belongs to the agent/client, not an extra background UI daemon in this package.

The scope is deliberately declared: single-plate A1/A1 mini/P1P/P1S/X1C/X1E LAN transport is experimental; physical printing, additional firmware/model combinations, cloud/H2, FEM, CNC and multi-plate dispatch are not certified by this research. See [verification](verification.md).
