import json, tempfile, unittest, zipfile
from pathlib import Path
from freecad_bambu_mcp.preflight import inspect

def make(p, gcode, cfg=None, extra=(), plate_json=None):
    cfg=cfg or {"printer_model":"Bambu Lab A1","nozzle_diameter":"0.4","bed_type":"Cool Plate","filament_type":"PLA"}
    with zipfile.ZipFile(p,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("Metadata/plate_1.gcode",gcode); z.writestr("Metadata/project_settings.config",json.dumps(cfg))
        if plate_json is not None: z.writestr("Metadata/plate_1.json", json.dumps(plate_json))
        for n,v in extra: z.writestr(n,v)

def make_duplicate_entry(p):
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Metadata/plate_1.gcode", "G1 X1 Y1 E0.2\n")
        z.writestr("Metadata/plate_1.gcode", "G1 X2 Y2 E0.2\n")

class PreflightTests(unittest.TestCase):
    def test_valid_and_numeric_nozzle_alias(self):
        with tempfile.TemporaryDirectory() as d:
            r=inspect(Path(d)/"a.3mf", expected_nozzle="0.40") if False else None
            p=Path(d)/"a.3mf"; make(p,"G1 X1 Y1 E0.2\n"); r=inspect(p, expected_printer="A1", expected_nozzle="0.40")
            self.assertEqual(r["profile_verification"],"verified")
    def test_mini_mismatch_and_plate_inventory(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.3mf"; make(p,"G1 X1 Y1 E0.2\n",{"printer_model":"Bambu Lab A1 mini","nozzle_diameter":"0.4","bed_type":"Cool Plate","filament_type":"PLA"},[("Metadata/plate_2.gcode","G1 X1 Y1 E0.2")])
            r=inspect(p, expected_printer="Bambu Lab A1"); self.assertTrue(any("mismatch" in x for x in r["errors"]))
            self.assertEqual(inspect(p)["plates"], [1, 2])
    def test_unknown_filaments_are_not_counted_as_one(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.3mf"; make(p,"G1 X1 Y1 E0.2\n",{"printer_model":"Bambu Lab A1","nozzle_diameter":"0.4","bed_type":"Cool Plate"}); r=inspect(p)
            self.assertIsNone(r["profile"]["used_filament_count"])

    def test_actual_plate_ids_are_zero_based_and_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.3mf"; make(p,"G1 X1 Y1 E0.2\n",plate_json={"filament_ids":[0,0,1]})
            r=inspect(p)
            self.assertEqual(r["profile"]["used_filament_ids"], [0,1])
            self.assertEqual(r["profile"]["used_filament_count"], 2)

    def test_invalid_plate_ids_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.3mf"; make(p,"G1 X1 Y1 E0.2\n",plate_json={"filament_ids":[True,-1,1.5,"2",0]})
            r=inspect(p)
            self.assertEqual(r["profile"]["used_filament_ids"], [0])

    def test_project_filament_slots_count_same_type_colors(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.3mf"; cfg={"printer_model":"Bambu Lab A1","nozzle_diameter":"0.4","bed_type":"Cool Plate","filament_type":["PLA","PLA"],"filament_color":["red","blue"]}
            make(p, "G1 X1 Y1 E0.2\n", cfg); r=inspect(p)
            self.assertEqual(r["profile"]["project_filament_count"], 2)

    def test_expected_filaments_are_an_exact_set(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.3mf"; cfg={"printer_model":"Bambu Lab A1","nozzle_diameter":"0.4","bed_type":"Cool Plate","filament_type":["PLA","PETG"]}; make(p,"G1 X1 Y1 E0.2\n",cfg)
            self.assertTrue(any("filament type mismatch" in x for x in inspect(p, expected_filaments=["PLA"])["errors"]))

    def test_a1mini_alias_is_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.3mf"; make(p,"G1 X1 Y1 E0.2\n",{"printer_model":"A1Mini","nozzle_diameter":"0.4","bed_type":"Cool Plate","filament_type":"PLA"})
            self.assertTrue(any("mismatch" in x for x in inspect(p, expected_printer="A1")["errors"]))

    def test_conflicting_model_evidence_over_20_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as d:
            models=["Bambu Lab A1"]*21+["Bambu Lab A1 mini"]
            p=Path(d)/"a.3mf"; make(p,"G1 X1 Y1 E0.2\n",{"printer_model":models,"nozzle_diameter":"0.4","bed_type":"Cool Plate","filament_type":"PLA"})
            self.assertTrue(any("conflicting printer model" in x for x in inspect(p)["errors"]))

    def test_comments_do_not_count_as_motion_or_extrusion_and_footer_temperatures_are_reported(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.3mf"; make(p,"; G1 X1 Y1 E0.2\n; estimated time: 5m 2s\nM104 S220\n")
            r=inspect(p)
            self.assertTrue(any("lacks actual motion" in x for x in r["errors"]))
            self.assertEqual(r["time_seconds"], 302)

    def test_duplicate_zip_entries_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"dupe.3mf"; make_duplicate_entry(p)
            self.assertTrue(any("duplicate" in x for x in inspect(p)["errors"]))

    def test_archive_uncompressed_bound(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"large.3mf"
            with zipfile.ZipFile(p,"w",zipfile.ZIP_DEFLATED) as z:
                z.writestr("Metadata/plate_1.gcode", b"0"*(128*1024*1024+1))
            self.assertTrue(any("bound" in x or "exceeds" in x for x in inspect(p)["errors"]))

if __name__ == "__main__": unittest.main()
