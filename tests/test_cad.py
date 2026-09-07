import base64, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from freecad_bambu_mcp.cad import FreeCADClient

class FakeClient(FreeCADClient):
    def __init__(self, reply): self.reply=reply
    def _call(self, name, *args): return self.reply

class CadTests(unittest.TestCase):
    def test_compile_rejects_invalid_without_rpc(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.py"; p.write_text("if", encoding="utf8")
            c=FakeClient({"success":True})
            with patch.object(c,"_call") as call: self.assertFalse(c.execute_file(p)["success"]); call.assert_not_called()
    def test_screenshot_validates_png_and_refuses_overwrite(self):
        png=base64.b64encode(b"\x89PNG\r\n\x1a\nabc").decode()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.png"; c=FakeClient(png); self.assertTrue(c.screenshot(p)["success"]); self.assertFalse(c.screenshot(p)["success"])
    def test_status_rejects_false_reply(self):
        self.assertFalse(FakeClient({"success":False,"error":"no"}).status()["success"])

if __name__ == "__main__": unittest.main()
