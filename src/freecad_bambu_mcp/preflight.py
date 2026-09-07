"""Bounded, read-only inspection of Bambu ``.gcode.3mf`` archives."""
from __future__ import annotations
import hashlib, json, re, zipfile
from pathlib import Path

MAX_ENTRIES = 5000
MAX_TOTAL_UNCOMPRESSED = 128 * 1024 * 1024
MAX_GCODE = 64 * 1024 * 1024
MAX_CONFIG = 8 * 1024 * 1024

def _norm(s): return re.sub(r"\s+", " ", str(s).strip()).lower()
def _walk(obj, keys, out):
    keys = {str(k).lower() for k in keys}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in keys:
                if isinstance(v, (str, int, float)): out.append(str(v))
                elif isinstance(v, list): out.extend(str(x) for x in v if isinstance(x, (str, int, float)))
            _walk(v, keys, out)
    elif isinstance(obj, list):
        for v in obj: _walk(v, keys, out)
def _values(config, keys):
    out=[]
    try: _walk(json.loads(config), keys, out)
    except (ValueError, TypeError): pass
    return list(dict.fromkeys(x for x in out if x))
def _comments(text, names):
    pat = r"^\s*;\s*(?:" + "|".join(map(re.escape, names)) + r")\s*[:=]\s*(.*?)\s*$"
    return list(dict.fromkeys(m.group(1).strip() for m in (re.match(pat, x, re.I) for x in text.splitlines()) if m and m.group(1).strip()))
def _uniq(xs): return list(dict.fromkeys(x for x in xs if x))
def _display(xs): return xs[:20]
def _identity(v):
    v = _norm(v).replace("bambu lab", "").strip(" -_:;")
    if re.search(r"\ba1\s*[-_]?\s*mini\b", v): return "a1 mini"
    m = re.search(r"\b(a1|p1s|p1p|x1c|x1e)\b", v)
    return m.group(1) if m else v

def inspect(path, expected_printer="Bambu Lab A1", plate=1, expected_nozzle=None, expected_bed=None, expected_filaments=None):
    path = Path(path)
    r = {"file": str(path), "sha256": None, "selected_plate": plate, "plates": [], "embedded_gcode": {}, "profile": {}, "first_layer": {}, "startup_commands": {}, "layer_count": None, "time_seconds": None, "time_raw": None, "errors": [], "warnings": [], "profile_verification": "unverified"}
    try:
        if path.stat().st_size > MAX_TOTAL_UNCOMPRESSED: raise ValueError("archive file exceeds bound")
        h = hashlib.sha256()
        with path.open("rb") as f:
            for c in iter(lambda: f.read(1024*1024), b""): h.update(c)
        r["sha256"] = h.hexdigest()
        with zipfile.ZipFile(path) as z:
            infos = z.infolist(); names = {i.filename:i for i in infos}
            if len(infos) > MAX_ENTRIES: raise ValueError("archive has too many entries")
            if len(names) != len(infos): raise ValueError("duplicate archive entries are ambiguous")
            if sum(max(0,i.file_size) for i in infos) > MAX_TOTAL_UNCOMPRESSED: raise ValueError("archive uncompressed size exceeds bound")
            r["plates"] = sorted(int(m.group(1)) for n in names if (m:=re.fullmatch(r"Metadata/plate_(\d+)\.gcode", n)))
            target = f"Metadata/plate_{plate}.gcode"
            if target not in names: r["errors"].append(f"missing required {target}"); return r
            if names[target].file_size <= 0 or names[target].file_size > MAX_GCODE: r["errors"].append("selected G-code is empty or exceeds bound"); return r
            raw_gcode = z.read(names[target])
            text = raw_gcode.decode("utf-8", "replace")
            r["embedded_gcode"] = {"entry": target, "size": names[target].file_size, "md5": hashlib.md5(raw_gcode).hexdigest()}
            executable = "\n".join(x.split(";",1)[0].strip() for x in text.splitlines())
            if not re.search(r"^G(?:0|1|2|3)\b[^\n]*(?:[XYZ])", executable, re.I|re.M) or not re.search(r"^G(?:0|1)\b[^\n]*\bE[-+]?\d*\.?\d+", executable, re.I|re.M): r["errors"].append("G-code lacks actual motion and extrusion")
            cfg=""
            for n in ("Metadata/project_settings.config","Metadata/project_settings.json"):
                if n in names and names[n].file_size <= MAX_CONFIG: cfg=z.read(names[n]).decode("utf-8","replace"); break
            models=_uniq(_values(cfg,("printer_model","printer_model_id","printer_name","model_id"))+_comments(text,("printer_model","printer_model_id")))
            nozzle_fields=_values(cfg,("nozzle_diameter",))+_comments(text,("nozzle_diameter",)); nozzles=[]
            for field in nozzle_fields: nozzles.extend(x.strip() for x in str(field).split(';') if x.strip())
            nozzles=_uniq(nozzles)
            beds=_uniq(_values(cfg,("bed_type","curr_bed_type","plate_type"))+_comments(text,("bed_type","curr_bed_type","plate_type")))
            filaments=[]
            for v in _values(cfg,("filament_type",))+_comments(text,("filament_type",)): filaments.extend(x.strip() for x in v.split(";") if x.strip())
            filaments=_uniq(filaments)
            plate_ids=[]
            if "Metadata/plate_1.json" in names and names["Metadata/plate_1.json"].file_size <= MAX_CONFIG:
                try:
                    pj=json.loads(z.read(names["Metadata/plate_1.json"]))
                    raw_ids = pj.get("filament_ids", [])
                    if not isinstance(raw_ids, list): raise ValueError("invalid filament IDs")
                    plate_ids = [x for x in raw_ids if type(x) is int and 0 <= x < 16]
                    if len(plate_ids) != len(raw_ids): r["errors"].append("invalid used filament IDs")
                except (ValueError, TypeError, UnicodeError, AttributeError): r["errors"].append("invalid plate_1.json")
            ids=sorted(set(plate_ids))
            colors=_uniq(_values(cfg,("filament_color","filament_colour"))+_comments(text,("filament_color","filament_colour")))
            # Project positions are array slots, including repeated identical PLA/colors.
            # Never count a deduplicated list of material names as the AMS layout.
            count = None
            try:
                settings_obj = json.loads(cfg)
                raw_types = settings_obj.get("filament_type")
                if isinstance(raw_types, list) and raw_types and all(isinstance(x, str) and x for x in raw_types):
                    count = len(raw_types)
                elif isinstance(raw_types, str) and raw_types.strip():
                    count = len(raw_types.split(";"))
                if count is not None and not 1 <= count <= 16:
                    r["errors"].append("unsupported project filament count")
                    count = None
                if count and any(i >= count for i in ids): r["errors"].append("used filament position exceeds project layout")
            except (ValueError, TypeError, AttributeError):
                pass
            r["profile"]={"printer_models":_display(models),"printer_model":models[0] if models else None,"nozzles":_display(nozzles),"beds":_display(beds),"filament_types":_display(filaments),"filament_colors":_display(colors),"project_filament_count":count,"used_filament_ids":ids if ids else None,"filament_ids":ids if ids else None,"used_filament_count":len(ids) if ids else None}
            if not models or not (nozzles or beds or filaments): r["errors"].append("missing explicit printer/profile evidence")
            if len({_identity(x) for x in models})>1: r["errors"].append("conflicting printer model profile evidence")
            if models and not any(_identity(x)==_identity(expected_printer) for x in models): r["errors"].append(f"printer mismatch: observed {models[0]!r}, expected {expected_printer!r}")
            def num(v):
                try:
                    s=str(v).strip()
                    return float(s) if re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", s) else None
                except (AttributeError, ValueError): return None
            if any(num(x) is None for x in nozzles): r["errors"].append("invalid nozzle evidence")
            if expected_nozzle is not None and (not nozzles or any(num(expected_nozzle)!=num(x) for x in nozzles)): r["errors"].append("nozzle mismatch or conflicting evidence")
            if expected_bed and (not beds or any(_norm(expected_bed)!=_norm(x) for x in beds)): r["errors"].append("bed mismatch or conflicting evidence")
            if expected_filaments and {_norm(x) for x in filaments} != {_norm(x) for x in expected_filaments}: r["errors"].append("filament type mismatch")
            for key,names2,cmd in (("nozzle",("first_layer_nozzle_temperature","nozzle_temperature_initial_layer","first_layer_temperature"),r"\bM(?:104|109)\b[^;\n]*\bS(\d+(?:\.\d+)?)"),("bed",("first_layer_bed_temperature","bed_temperature_initial_layer"),r"\bM(?:140|190)\b[^;\n]*\bS(\d+(?:\.\d+)?)")):
                vals=_values(cfg,names2)+_comments(text,names2)
                if vals: r["first_layer"][key]=vals[0]
                found=re.findall(cmd,executable,re.I)
                if found: r["startup_commands"][key]=found[:20]
            if "bed" not in r["first_layer"] and len(beds)==1:
                temp_key={"textured pei plate":"textured_plate_temp_initial_layer","cool plate":"cool_plate_temp_initial_layer","smooth pei plate":"hot_plate_temp_initial_layer","engineering plate":"eng_plate_temp_initial_layer"}.get(_norm(beds[0]))
                vals=_values(cfg,(temp_key,)) if temp_key else []
                if vals: r["first_layer"]["bed_profile_targets"]=vals
            lm=re.search(r"^\s*;\s*(?:LAYER_COUNT|total layer number)\s*[:=]\s*(\d+)",text,re.I|re.M); r["layer_count"]=int(lm.group(1)) if lm else (len(re.findall(r";\s*LAYER_CHANGE",text,re.I)) or None)
            tm=re.search(r";\s*total\s+estimated\s+time\s*[:=]\s*([^;\r\n]+)",text,re.I) or re.search(r"^\s*;\s*estimated\s+time\s*[:=]\s*([^;\r\n]+)",text,re.I|re.M)
            if tm:
                raw=tm.group(1).strip(); r["time_raw"]=raw[:80]; q=re.fullmatch(r"(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?(?:(\d+)\s*(?:seconds|sec|s)\s*)?",raw,re.I)
                if q and any(q.groups()): r["time_seconds"]=sum(int(v or 0)*m for v,m in zip(q.groups(),(3600,60,1)))
            if not r["errors"]: r["profile_verification"]="verified"
    except (OSError, zipfile.BadZipFile, ValueError, UnicodeError) as exc: r["errors"].append(f"read failure: {exc}")
    return r
