import json
from types import SimpleNamespace

import pytest

from freecad_bambu_mcp.printer import BambuError, BambuLAN, PrinterConfig, _ImplicitFTP_TLS


class FakeMQTT:
    def __init__(self, payloads=()): self.payloads=list(payloads); self.published=[]; self.on_message=None; self.reconnect_on_failure=False
    def username_pw_set(self, *a): self.credentials=a
    def tls_set_context(self, context): self.context=context
    def connect(self, *a, **k):
        if self.on_connect: self.on_connect(self, None, {}, 0)
    def loop_start(self): pass
    def loop_stop(self): pass
    def disconnect(self): pass
    def subscribe(self, *a, **k):
        self.topic=a[0]
        if self.on_subscribe: self.on_subscribe(self, None, 1, [0])
    def publish(self, topic, payload, **kwargs):
        self.published.append((topic, json.loads(payload)))
        if self.on_message:
            for p in self.payloads: self.on_message(self, None, SimpleNamespace(topic=self.topic, retain=False, payload=json.dumps(p).encode()))

def cfg(**kw): return PrinterConfig("printer.local", "SERIAL", "secret", "A1", **{"timeout": .01, **kw})

def test_wrong_serial_ignored_and_status_unknown():
    f=FakeMQTT([{"serial":"OTHER","print":{"gcode_state":"RUNNING"}}])
    out=BambuLAN(cfg(), mqtt_factory=lambda:f).status()
    assert out["state"] == "UNKNOWN" and out["connected"] is False

def test_ack_does_not_mean_running():
    f=FakeMQTT([{"print":{"sequence_id":"never"}}])
    out=BambuLAN(cfg(), mqtt_factory=lambda:f).start("x.3mf")
    assert out["accepted_unknown"] and "RUNNING" not in out

def test_timeout_publishes_once():
    f=FakeMQTT()
    BambuLAN(cfg(), mqtt_factory=lambda:f).control("pause")
    assert len(f.published) == 1

@pytest.mark.parametrize("name", ["../x.gcode", "a/b.gcode", "", "."])
def test_unsafe_names(name):
    with pytest.raises(BambuError) as e: BambuLAN(cfg()).start(name)
    assert e.value.code == "INVALID_REMOTE_NAME"

def test_tls_secure_default():
    f=FakeMQTT(); BambuLAN(cfg(), mqtt_factory=lambda:f).status()
    assert f.context.verify_mode != 0 and f.context.check_hostname

def test_failed_connect_is_sanitized():
    class Bad(FakeMQTT):
        def connect(self, *a, **k): raise RuntimeError("secret")
    out = BambuLAN(cfg(), mqtt_factory=Bad).status()
    assert out["connected"] is False and "secret" not in str(out)

def test_publish_waits_for_connack_and_disables_reconnect():
    f=FakeMQTT(); out=BambuLAN(cfg(), mqtt_factory=lambda:f).control("pause")
    assert f.reconnect_on_failure is False and len(f.published) == 1 and out["accepted_unknown"]

def test_failure_ack_is_rejected():
    class Ack(FakeMQTT):
        def publish(self, topic, payload, **kwargs):
            packet=json.loads(payload); self.published.append((topic, packet))
            p=packet["print"]
            self.on_message(self, None, SimpleNamespace(topic=self.topic, retain=False,
                payload=json.dumps({"print":{"sequence_id":p["sequence_id"],"command":p["command"],"result":"failed"}}).encode()))
    out=BambuLAN(cfg(), mqtt_factory=Ack).control("stop")
    assert out["accepted"] is False and out["rejected"] is True and not out["accepted_unknown"]

def test_implicit_tls_wraps_before_greeting(monkeypatch):
    events=[]
    class Sock:
        family=2
        session=object()
        def makefile(self, *a, **k): events.append("makefile"); return object()
    class Context:
        def wrap_socket(self, sock, **kw): events.append("wrap"); return sock
    monkeypatch.setattr("freecad_bambu_mcp.printer.socket.create_connection", lambda *a: (events.append("connect") or Sock()))
    ftp=_ImplicitFTP_TLS(); ftp.context=Context(); ftp.getresp=lambda: (events.append("greeting") or "220 ready")
    ftp.connect("printer.local", 990, timeout=.1)
    assert events[:3] == ["connect", "wrap", "makefile"] and events[3] == "greeting"

def test_implicit_tls_login_and_data_reuses_control_session(monkeypatch):
    ftp=_ImplicitFTP_TLS(); commands=[]
    replies=iter(["331 password", "230 logged in"])
    ftp.putcmd=lambda *args: commands.append(args)
    ftp.getresp=lambda: next(replies)
    assert ftp.login("bblp", "secret").startswith("230")
    assert commands == [("USER bblp",), ("PASS secret",)]
    class Control:
        session=object()
    ftp.sock=Control(); ftp.host="printer.local"; ftp._prot_p=True
    data=object(); wrapped=[]
    monkeypatch.setattr("ftplib.FTP.ntransfercmd", lambda self, cmd, rest=None: (data, None))
    class Context:
        def wrap_socket(self, sock, **kwargs): wrapped.append((sock, kwargs)); return "tls-data"
    ftp.context=Context()
    sock, size=ftp.ntransfercmd("STOR file.3mf")
    assert sock == "tls-data" and wrapped[0][1]["session"] is ftp.sock.session

def test_timeout_before_connack_sends_no_request():
    class NoConn(FakeMQTT):
        def connect(self, *args, **kwargs): pass
    f=NoConn(); out=BambuLAN(cfg(timeout=.001), mqtt_factory=lambda:f).status()
    assert out["connected"] is False and f.published == []

def test_crlf_remote_name_and_numeric_sequence():
    with pytest.raises(BambuError): BambuLAN(cfg()).start("bad\r\nname.3mf")
    f=FakeMQTT(); out=BambuLAN(cfg(), mqtt_factory=lambda:f).control("pause")
    sequence=f.published[0][1]["print"]["sequence_id"]
    assert sequence.isdigit() and 0 <= int(sequence) <= 0xFFFFFFFF

def test_model_id_mapping_from_fresh_report():
    f=FakeMQTT([{"serial":"SERIAL", "print":{"gcode_state":"IDLE", "model_id":"N2S"}}])
    assert BambuLAN(cfg(), mqtt_factory=lambda:f).status()["model"] == "A1"
