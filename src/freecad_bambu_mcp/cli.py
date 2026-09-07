"""CLI shares the same guarded engine as the MCP server."""
import argparse
import json
import sys

from .config import Config
from .workflow import Workflow


def main(argv=None):
    parser = argparse.ArgumentParser(description="FreeCAD → Bambu Studio → LAN print")
    parser.add_argument("--config", help="Local JSON config; defaults to FREECAD_BAMBU_CONFIG or config.local.json")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "doctor", "capabilities"):
        commands.add_parser(name)
    p = commands.add_parser("cad"); p.add_argument("script")
    p = commands.add_parser("prepare"); p.add_argument("spec")
    p = commands.add_parser("attach"); p.add_argument("job"); p.add_argument("file")
    p = commands.add_parser("review"); p.add_argument("job"); p.add_argument("sha256")
    p.add_argument("--preview-checked", action="store_true"); p.add_argument("--hardware-checked", action="store_true")
    p = commands.add_parser("print"); p.add_argument("job"); p.add_argument("sha256")
    p.add_argument("--start-authorized", action="store_true")
    p = commands.add_parser("status"); p.add_argument("job"); p.add_argument("--refresh", action="store_true")
    p = commands.add_parser("printer-status"); p.add_argument("printer")
    p = commands.add_parser("preview"); p.add_argument("job")
    p = commands.add_parser("control"); p.add_argument("job"); p.add_argument("action", choices=["pause", "resume", "stop"])
    p.add_argument("--authorized", action="store_true")
    p = commands.add_parser("close"); p.add_argument("job"); p.add_argument("--operator-confirmed", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = Config(args.config)
        if args.command == "serve":
            from .server import create_server
            create_server(config).run(transport="stdio")
            return 0
        wf = Workflow(config)
        if args.command == "doctor": result = wf.doctor()
        elif args.command == "capabilities": result = wf.capabilities()
        elif args.command == "cad": result = wf.cad_execute(args.script)
        elif args.command == "prepare": result = wf.prepare(args.spec)
        elif args.command == "attach": result = wf.attach_slice(args.job, args.file)
        elif args.command == "review": result = wf.review(args.job, args.sha256, preview_checked=args.preview_checked, hardware_checked=args.hardware_checked)
        elif args.command == "print": result = wf.start_print(args.job, args.sha256, start_authorized=args.start_authorized)
        elif args.command == "status": result = wf.status(args.job, args.refresh)
        elif args.command == "printer-status": result = wf.printer_status(args.printer)
        elif args.command == "preview": result = wf.preview(args.job)
        elif args.command == "control": result = wf.control(args.job, args.action, authorized=args.authorized)
        elif args.command == "close": result = wf.close_job(args.job, operator_confirmed=args.operator_confirmed)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 1 if result.get("error") or result.get("state") in {"prepare_failed", "slice_failed", "slice_rejected", "upload_failed", "start_rejected"} else 0
    except Exception as exc:
        # Validation errors may include raw input values. Keep them out of shared logs.
        print(json.dumps({"error": type(exc).__name__, "message": "Operation could not complete. Check local config, job state and the documented prerequisites."}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
