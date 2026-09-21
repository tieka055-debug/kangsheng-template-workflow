import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "auto_layout.py"
SPEC = importlib.util.spec_from_file_location("auto_layout", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AutoLayoutTests(unittest.TestCase):
    def test_semantic_pack_is_repeatable_and_non_overlapping(self):
        items = [
            {"id": "table", "kind": "table", "width": 420, "height": 69, "order": 7},
            {"id": "pcb", "kind": "pcb", "width": 166, "height": 204, "order": 6,
             "maximum_scale": 1.1},
            {"id": "performance", "kind": "performance", "width": 184, "height": 176,
             "order": 3, "maximum_scale": 1.0},
            {"id": "front", "kind": "view", "width": 137, "height": 178, "order": 0,
             "maximum_scale": 1.3},
            {"id": "side", "kind": "view", "width": 146, "height": 116, "order": 1,
             "maximum_scale": 1.3},
            {"id": "iso", "kind": "isometric", "width": 116, "height": 93, "order": 2,
             "maximum_scale": 1.25},
        ]
        canvas = [30, 36, 810, 444]
        first = MODULE.pack(items, canvas, 12, 1.2)
        second = MODULE.pack(items, canvas, 12, 1.2)
        self.assertEqual(first, second)
        self.assertIsNotNone(first)
        boxes = [value["box"] for value in first.values()]
        for box in boxes:
            self.assertTrue(MODULE.contains(canvas, box))
        for index, left in enumerate(boxes):
            for right in boxes[index + 1:]:
                self.assertFalse(MODULE.intersects(left, right))


if __name__ == "__main__":
    unittest.main()
