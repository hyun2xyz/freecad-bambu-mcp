"""Small, conservative client for the FreeCADMCP XML-RPC add-on."""
from __future__ import annotations

import base64
import json
import re
import threading
import xmlrpc.client
from pathlib import Path
from typing import Any

MAX_CODE = 1024 * 1024
MAX_TEXT = 4096
MAX_SCREENSHOT = 8 * 1024 * 1024
_LOCK = threading.RLock()


class _SingleRequestTransport(xmlrpc.client.Transport):
    """Transport whose request path has exactly one HTTP request."""
    def __init__(self, timeout: float):
        super().__init__()
        self.timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self.timeout
        return conn

    def request(self, host, handler, request_body, verbose=False):
        return self.single_request(host, handler, request_body, verbose)


def _short(value: Any) -> str:
    text = str(value)
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "...(truncated)"


def _failure(message: Any, **extra: Any) -> dict[str, Any]:
    return {"success": False, "error": _short(message), **extra}


class FreeCADClient:
    """Thread-serialized, localhost-only FreeCAD RPC client."""
    def __init__(self, timeout: float = 60, port: int = 9875):
        self.timeout = timeout
        self.port = port
        self._proxy = xmlrpc.client.ServerProxy(
            f"http://127.0.0.1:{port}", allow_none=True,
            transport=_SingleRequestTransport(timeout),
        )

    def _call(self, name: str, *args: Any) -> Any:
        with _LOCK:
            return getattr(self._proxy, name)(*args)

    def status(self) -> dict[str, Any]:
        try:
            result = self._call("get_rpc_status")
            if not isinstance(result, dict):
                return _failure("malformed status reply")
            if result.get("success") is False:
                return _failure(result.get("error", "RPC status failed"))
            return result
        except Exception as exc:
            return _failure(exc)

    def execute_file(self, path: Path) -> dict[str, Any]:
        path = Path(path)
        try:
            if not path.is_file():
                return _failure(f"file not found: {path}")
            if path.stat().st_size > MAX_CODE:
                return _failure("code file exceeds 1 MiB")
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except (OSError, UnicodeError, SyntaxError) as exc:
            return _failure(exc)
        try:
            result = self._call("execute_code", source)
            if not isinstance(result, dict):
                return _failure("malformed execute reply")
            if result.get("success") is False:
                return _failure(result.get("error", result.get("message", "execution failed")))
            out = dict(result)
            for key in ("message", "output"):
                if key in out:
                    out[key] = _short(out[key])
            out.setdefault("success", True)
            return out
        except Exception as exc:
            return _failure(exc)

    def export(self, document: str, objects: list[str], output_dir: Path) -> dict[str, Any]:
        output_dir = Path(output_dir)
        if not document or not isinstance(objects, list) or not objects:
            return _failure("document and at least one object are required")
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            paths = {k: output_dir / f"model.{ext}" for k, ext in (("model", "FCStd"), ("stl", "stl"), ("step", "step"))}
            if any(p.exists() for p in paths.values()):
                return _failure("refusing to overwrite an existing export")
        except OSError as exc:
            return _failure(exc)
        # The marker lets one synchronous execute_code RPC carry validation and export.
        payload = json.dumps(objects, ensure_ascii=True)
        script = f'''import json, FreeCAD, Part, Mesh
_doc = FreeCAD.getDocument({document!r})
if _doc is None:
    raise ValueError("document not found: " + {document!r})
_names = json.loads({payload!r})
_doc.recompute()
_items = []
_vol = 0.0
_solid_count = 0
_bounds = [float("inf"), float("inf"), float("inf"), float("-inf"), float("-inf"), float("-inf")]
for _name in _names:
    _o = _doc.getObject(_name)
    if _o is None or not hasattr(_o, "Shape") or _o.Shape.isNull() or not _o.Shape.isValid() or not _o.Shape.Solids or _o.Shape.Volume <= 0:
        raise ValueError("invalid or non-solid shape: " + str(_name))
    _items.append(_o)
    _vol += float(_o.Shape.Volume)
    _solid_count += len(_o.Shape.Solids)
    _b = _o.Shape.BoundBox
    _bounds = [min(_bounds[0], _b.XMin), min(_bounds[1], _b.YMin), min(_bounds[2], _b.ZMin), max(_bounds[3], _b.XMax), max(_bounds[4], _b.YMax), max(_bounds[5], _b.ZMax)]
_model = {str(paths['model'])!r}
for _p in ({str(paths['model'])!r}, {str(paths['stl'])!r}, {str(paths['step'])!r}):
    import os
    if os.path.exists(_p): raise FileExistsError("refusing to overwrite: " + _p)
if hasattr(_doc, "saveCopy"):
    _doc.saveCopy(_model)
else:
    raise RuntimeError("FreeCAD does not provide saveCopy; refusing to mutate source")
Mesh.export(_items, {str(paths['stl'])!r})
Part.export(_items, {str(paths['step'])!r})
if not all(__import__('math').isfinite(float(_x)) for _x in _bounds) or not __import__('math').isfinite(_vol) or _vol <= 0 or _solid_count <= 0:
    raise ValueError("invalid export measurements")
print("__MCP_EXPORT__" + json.dumps({{"bounds": _bounds, "volume": _vol, "solid_count": _solid_count}}))
'''
        try:
            result = self._call("execute_code", script)
            if not isinstance(result, dict):
                return _failure("malformed export reply")
            if result.get("success") is False:
                return _failure(result.get("error", result.get("message", "export failed")))
            message = str(result.get("message", result.get("output", "")))
            match = re.search(r"__MCP_EXPORT__(\{.*\})", message)
            if not match:
                return _failure("export reply did not contain validation evidence")
            evidence = json.loads(match.group(1))
            bounds = evidence.get("bounds") if isinstance(evidence, dict) else None
            if not isinstance(evidence, dict) or not isinstance(bounds, list) or len(bounds) != 6:
                return _failure("malformed export evidence")
            import math
            if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in bounds) or not isinstance(evidence.get("volume"), (int, float)) or not math.isfinite(evidence["volume"]) or evidence["volume"] <= 0 or evidence.get("solid_count", 0) <= 0:
                return _failure("invalid export measurements")
            for p in paths.values():
                if not p.is_file() or p.stat().st_size == 0:
                    return _failure("export did not produce non-empty files")
            exported = {k: str(v) for k, v in paths.items()}
            exported["fcstd"] = exported["model"]
            return {"success": True, "paths": exported, "bounds_mm": evidence["bounds"], "volume_mm3": evidence.get("volume")}
        except Exception as exc:
            return _failure(exc)

    def screenshot(self, path: Path, view: str = "Isometric") -> dict[str, Any]:
        path = Path(path)
        if path.exists():
            return _failure("refusing to overwrite screenshot")
        try:
            data = self._call("get_active_screenshot", view, 800, 600, None)
            if not isinstance(data, str):
                return _failure("malformed or empty screenshot reply")
            raw = base64.b64decode(data, validate=True)
            if len(raw) > MAX_SCREENSHOT or raw[:8] != b"\x89PNG\r\n\x1a\n":
                return _failure("invalid or oversized PNG screenshot")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            return {"success": True, "path": str(path), "bytes": len(raw)}
        except Exception as exc:
            return _failure(exc)
