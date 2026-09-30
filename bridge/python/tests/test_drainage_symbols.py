import importlib.util
from pathlib import Path
import unittest
import ezdxf

spec = importlib.util.spec_from_file_location("drainage_symbols", Path(__file__).parents[1] / "skills" / "drainage_symbols.py")
symbols = importlib.util.module_from_spec(spec)
spec.loader.exec_module(symbols)


class DrainageSymbolsTests(unittest.TestCase):
    def test_unknown_block_is_not_pipe(self):
        self.assertEqual(symbols.classify("RP", {}, {})["kind"], "unknown")

    def test_rule_requires_evidence(self):
        self.assertEqual(symbols.classify("RP", {}, {"RP": {"kind": "pipe"}})["kind"], "unknown")

    def test_explicit_attribute_direction(self):
        legend = {"RP": {"kind": "pipe", "directionAttribute": "FLOW", "directionValues": {"D": "down"}, "evidence": "approved project legend"}}
        self.assertEqual(symbols.classify("RP", {"FLOW": "D"}, legend)["direction"], "down")
        self.assertEqual(symbols.classify("RP", {"FLOW": "?"}, legend)["direction"], "unknown")

    def test_direction_connections(self):
        self.assertTrue(symbols.compatible("down", "both"))
        self.assertFalse(symbols.compatible("down", "down"))
        self.assertFalse(symbols.compatible("up", "both"))
        self.assertIsNone(symbols.compatible("unknown", "both"))

    def test_nested_transform_and_layer(self):
        doc = ezdxf.new()
        child = doc.blocks.new("CHILD")
        child.add_circle((1, 0), 2)
        parent = doc.blocks.new("PARENT")
        parent.add_blockref("CHILD", (10, 0))
        doc.modelspace().add_blockref("PARENT", (100, 0), dxfattribs={"rotation": 90, "layer": "RAIN"})
        result = symbols.inventory(doc)
        circle = result["circles"][0]
        self.assertAlmostEqual(circle["center"][0], 100)
        self.assertAlmostEqual(circle["center"][1], 11)
        self.assertEqual(circle["layer"], "RAIN")
        self.assertEqual(circle["symbolRadius"], 2)

    def test_nonuniform_scale_is_not_circle(self):
        doc = ezdxf.new()
        doc.blocks.new("B").add_circle((0, 0), 1)
        doc.modelspace().add_blockref("B", (0, 0), dxfattribs={"xscale": 2})
        result = symbols.inventory(doc)
        self.assertEqual(result["circles"], [])
        self.assertTrue(result["warnings"])

    def test_text_not_assigned_by_proximity(self):
        doc = ezdxf.new()
        doc.modelspace().add_circle((0, 0), 1)
        doc.modelspace().add_text('6" RP')
        self.assertIsNone(symbols.inventory(doc)["texts"][0]["circleAssignment"])

    def test_budget_fails_closed(self):
        doc = ezdxf.new()
        doc.modelspace().add_circle((0, 0), 1)
        with self.assertRaises(ValueError):
            symbols.inventory(doc, limit=0)


if __name__ == "__main__":
    unittest.main()
