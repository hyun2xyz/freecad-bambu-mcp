"""Small, offline-testable transport for Bambu LAN printers.

This module deliberately reports command acceptance separately from printer
state.  It does not retry packets: a disconnected session must be inspected
by the caller before another command is sent.
"""

from __future__ import annotations

import ftplib
import hashlib
import json
import os
import re
import socket
import ssl
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class BambuError(RuntimeError):
    """A safe, non-secret transport error identified by a stable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PrinterConfig:
    host: str
    serial: str
    access_code: str
    model: str
    tls_ca_file: str | None = None
    allow_self_signed: bool = False
    timeout: float = 15


def _name(value: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise BambuError("INVALID_REMOTE_NAME")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}", value):
        raise BambuError("INVALID_REMOTE_NAME")
    return value


def _seq() -> str:
    return str((time.time_ns() ^ uuid.uuid4().int) & 0xFFFFFFFF)


def _nested(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


class _ImplicitFTP_TLS(ftplib.FTP_TLS):
    """Implicit FTPS: TLS wraps the socket before the server greeting."""
    def connect(self, host="", port=0, timeout=-999, source_address=None):
        if timeout == -999: timeout = self.timeout
        self.timeout = timeout
        self.source_address = source_address
        self.host, self.port = host, port or 990
        self.sock = socket.create_connection((host, self.port), timeout, source_address)
        self.af = self.sock.family
        self.sock = self.context.wrap_socket(self.sock, server_hostname=host)
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome
    def login(self, user="anonymous", passwd="", acct=""):
        return ftplib.FTP.login(self, user, passwd, acct)
    def ntransfercmd(self, cmd, rest=None):
        sock, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if getattr(self, "_prot_p", False):
            sock = self.context.wrap_socket(sock, server_hostname=self.host, session=self.sock.session)
        return sock, size


class BambuLAN:
    def __init__(self, config: PrinterConfig, *, mqtt_factory: Callable[..., Any] | None = None,
                 ftp_factory: Callable[..., Any] | None = None):
        if (config.timeout <= 0 or not config.host or not config.serial or not config.access_code
                or any(c in config.host for c in "\r\n\x00")
                or not re.fullmatch(r"[A-Za-z0-9._-]+", config.serial)):
            raise BambuError("INVALID_CONFIG")
        self.config = config
        self._mqtt_factory = mqtt_factory
        self._ftp_factory = ftp_factory

    def _supported(self) -> None:
        model = self.config.model.upper().replace(" ", "")
        if model not in {"A1", "A1MINI", "P1S", "P1P", "X1C", "X1E"}:
            raise BambuError("UNSUPPORTED_MODEL")

    def _mqtt(self) -> Any:
        try:
            if self._mqtt_factory:
                return self._mqtt_factory()
            import paho.mqtt.client as mqtt
            return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, reconnect_on_failure=False)
        except Exception as exc:
            raise BambuError("MQTT_UNAVAILABLE") from exc

    def _connect(self, client: Any, connected: threading.Event | None = None) -> None:
        try:
            client.connect_timeout = self.config.timeout
            client.username_pw_set("bblp", self.config.access_code)
            context = ssl.create_default_context(cafile=self.config.tls_ca_file)
            if self.config.allow_self_signed:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            client.tls_set_context(context)
            client.connect(self.config.host, 8883, int(max(1, self.config.timeout)))
            client.loop_start()
            if connected is not None and not connected.wait(self.config.timeout):
                raise BambuError("MQTT_CONNACK_TIMEOUT")
        except BambuError:
            raise
        except Exception as exc:
            raise BambuError("MQTT_CONNECT_FAILED") from exc

    @staticmethod
    def _message_payload(message: Any) -> dict[str, Any] | None:
        raw = getattr(message, "payload", message)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                return None
        return raw if isinstance(raw, dict) else None

    def _with_mqtt(self, fn: Callable[[Any], Any]) -> Any:
        client = self._mqtt()
        try:
            return fn(client)
        finally:
            for method in ("loop_stop", "disconnect"):
                try:
                    getattr(client, method)()
                except Exception:
                    pass

    def status(self) -> dict[str, Any]:
        reports: dict[str, Any] = {}
        fresh = threading.Event()
        observed_receipt = [None]
        def run(client: Any) -> dict[str, Any]:
            topic = f"device/{self.config.serial}/report"
            connected = threading.Event(); subscribed = threading.Event(); failed = threading.Event()
            def on_message(_client: Any, _userdata: Any, message: Any, *args: Any) -> None:
                if getattr(message, "topic", topic) != topic or getattr(message, "retain", False): return
                payload = self._message_payload(message)
                if not payload:
                    return
                # A report can carry a serial in nested print/device info.
                reported_serial = payload.get("serial") or _nested(payload, "print", "serial")
                if reported_serial and str(reported_serial) != self.config.serial:
                    return
                for key, value in payload.items():
                    if isinstance(value, dict) and isinstance(reports.get(key), dict): reports[key].update(value)
                    else: reports[key] = value
                if _nested(payload, "print", "gcode_state") is not None or payload.get("gcode_state") is not None:
                    observed_receipt[0] = time.time()
                    fresh.set()
            def on_connect(_client: Any, _userdata: Any, _flags: Any, reason: Any, *args: Any) -> None:
                if getattr(reason, "is_failure", False) or (isinstance(reason, int) and reason != 0): failed.set(); return
                connected.set()
                try: client.subscribe(topic, qos=0)
                except Exception: failed.set()
            def on_subscribe(_client: Any, _userdata: Any, _mid: Any, reason_codes: Any, *args: Any) -> None:
                codes = reason_codes if isinstance(reason_codes, (list, tuple)) else [reason_codes]
                if any(getattr(x, "is_failure", False) or (isinstance(x, int) and x >= 128) for x in codes): failed.set()
                else: subscribed.set()
            client.on_message = on_message; client.on_connect = on_connect; client.on_subscribe = on_subscribe
            self._connect(client, connected)
            if failed.is_set() or not subscribed.wait(self.config.timeout): raise BambuError("MQTT_SUBSCRIBE_FAILED")
            try:
                info = client.publish(f"device/{self.config.serial}/request", json.dumps({"pushing": {"command": "pushall"}}), qos=0)
                if hasattr(info, "wait_for_publish"): info.wait_for_publish(timeout=self.config.timeout)
            except Exception as exc:
                raise BambuError("MQTT_REQUEST_FAILED") from exc
            fresh.wait(self.config.timeout)
            return reports
        try: reports = self._with_mqtt(run)
        except BambuError:
            return {"connected": False, "state": "UNKNOWN", "model": None, "filename": None, "progress": None,
                    "nozzle_temp": None, "bed_temp": None, "errors": None, "timestamp": time.time()}
        print_data = reports.get("print", reports)
        state = str(print_data.get("gcode_state", "UNKNOWN")).upper() if isinstance(print_data, dict) else "UNKNOWN"
        if state not in {"IDLE", "RUNNING", "PAUSE", "FINISH", "FAILED"}:
            state = "UNKNOWN"
        model = ((print_data.get("model") or print_data.get("device_model")) if isinstance(print_data, dict) else None)
        model = model or reports.get("model") or reports.get("device_model")
        model = model or print_data.get("model_id") or reports.get("model_id")
        model = {"N2S": "A1", "A1M": "A1 mini", "C11": "P1P", "C12": "P1S",
                 "BL-P001": "X1C", "C13": "X1E"}.get(str(model), model)
        result = {
            "connected": fresh.is_set(), "state": state, "model": model or None,
            "filename": print_data.get("subtask_name") or print_data.get("gcode_file") if isinstance(print_data, dict) else None,
            "progress": print_data.get("mc_percent") if isinstance(print_data, dict) else None,
            "nozzle_temp": print_data.get("nozzle_temper") if isinstance(print_data, dict) else None,
            "bed_temp": print_data.get("bed_temper") if isinstance(print_data, dict) else None,
            "errors": print_data.get("print_error") if isinstance(print_data, dict) else None,
            "timestamp": observed_receipt[0] if observed_receipt[0] is not None else time.time(),
        }
        return result

    def _ftp(self) -> Any:
        if self._ftp_factory:
            return self._ftp_factory()
        ftp = _ImplicitFTP_TLS()
        context = ssl.create_default_context(cafile=self.config.tls_ca_file)
        if self.config.allow_self_signed:
            context.check_hostname = False; context.verify_mode = ssl.CERT_NONE
        ftp.context = context
        return ftp

    def upload(self, path: Path, remote_name: str) -> dict[str, Any]:
        remote_name = _name(remote_name)
        path = Path(path)
        if not path.is_file():
            raise BambuError("LOCAL_FILE_NOT_FOUND")
        ftp = self._ftp()
        try:
            ftp.connect(self.config.host, 990, timeout=self.config.timeout)
            ftp.login("bblp", self.config.access_code)
            ftp.prot_p()
            with path.open("rb") as handle:
                ftp.storbinary("STOR " + remote_name, handle)
            return {"uploaded": True, "remote_name": remote_name, "size": path.stat().st_size,
                    "md5": self._file_md5(path)}
        except BambuError:
            raise
        except Exception as exc:
            raise BambuError("FTP_UPLOAD_FAILED") from exc
        finally:
            try: ftp.quit()
            except Exception:
                try: ftp.close()
                except Exception: pass

    @staticmethod
    def _file_md5(path: Path) -> str:
        digest = hashlib.md5()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _command(self, body: dict[str, Any], *, ack: bool = True) -> dict[str, Any]:
        sequence = _seq()
        packet = {"print": dict(body, sequence_id=sequence)}
        event = threading.Event()
        ack_payload: dict[str, Any] = {}
        def run(client: Any) -> dict[str, Any]:
            topic = f"device/{self.config.serial}/report"
            connected = threading.Event(); subscribed = threading.Event(); failed = threading.Event()
            def on_message(_client: Any, _userdata: Any, message: Any, *args: Any) -> None:
                if getattr(message, "topic", topic) != topic or getattr(message, "retain", False): return
                payload = self._message_payload(message) or {}
                reported_serial = payload.get("serial") or _nested(payload, "print", "serial")
                if reported_serial and str(reported_serial) != self.config.serial: return
                p = payload.get("print", payload)
                if (isinstance(p, dict) and str(p.get("sequence_id")) == sequence
                        and p.get("command") == body.get("command")
                        and (p.get("result") is not None or p.get("error") is not None)):
                    ack_payload.update(p); event.set()
            def on_connect(_client: Any, _userdata: Any, _flags: Any, reason: Any, *args: Any) -> None:
                if getattr(reason, "is_failure", False) or (isinstance(reason, int) and reason != 0): failed.set(); return
                connected.set()
                try: client.subscribe(topic, qos=0)
                except Exception: failed.set()
            def on_subscribe(_client: Any, _userdata: Any, _mid: Any, reason_codes: Any, *args: Any) -> None:
                codes = reason_codes if isinstance(reason_codes, (list, tuple)) else [reason_codes]
                if any(getattr(x, "is_failure", False) or (isinstance(x, int) and x >= 128) for x in codes): failed.set()
                else: subscribed.set()
            client.on_message = on_message; client.on_connect = on_connect; client.on_subscribe = on_subscribe
            self._connect(client, connected)
            if failed.is_set() or not subscribed.wait(self.config.timeout): raise BambuError("MQTT_SUBSCRIBE_FAILED")
            try:
                info = client.publish(f"device/{self.config.serial}/request", json.dumps(packet), qos=0)
                if hasattr(info, "wait_for_publish"): info.wait_for_publish(timeout=self.config.timeout)
            except Exception as exc:
                raise BambuError("MQTT_COMMAND_FAILED") from exc
            if ack: event.wait(self.config.timeout)
            return ack_payload
        ack_payload = self._with_mqtt(run)
        success = (bool(ack_payload) and str(ack_payload.get("result", "")).lower() in {"success", "ok", "accepted"}
                   and ack_payload.get("error") in (None, 0, "0"))
        rejected = bool(ack_payload) and not success
        return {"accepted": success, "accepted_unknown": not ack_payload, "rejected": rejected,
                "sequence_id": sequence, "command": body.get("command")}

    def start(self, remote_name: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        self._supported()
        remote_name = _name(remote_name); options = dict(options or {})
        if not remote_name.lower().endswith(".3mf"):
            raise BambuError("INVALID_REMOTE_NAME")
        if "bed_type" in options and options["bed_type"] not in {"cool_plate", "textured_plate", "hot_plate", "engineering_plate", "supertack_plate"}:
            raise BambuError("INVALID_BED_TYPE")
        if "secure_mode" in options or "client_cert" in options:
            raise BambuError("UNSUPPORTED_SECURITY_OPTION")
        body: dict[str, Any] = {"command": "project_file", "param": "Metadata/plate_1.gcode",
            "url": "ftp:///" + remote_name, "file": remote_name,
            "subtask_name": Path(remote_name).stem}
        if "gcode_md5" in options: body["md5"] = options["gcode_md5"]
        for key in ("md5", "bed_type", "use_ams", "ams_mapping", "bed_leveling", "flow_cali", "vibration_cali", "timelapse"):
            if key in options: body[key] = options[key]
        return self._command(body)

    def control(self, action: str) -> dict[str, Any]:
        self._supported()
        if action not in {"pause", "resume", "stop"}:
            raise BambuError("INVALID_CONTROL_ACTION")
        return self._command({"command": action})
