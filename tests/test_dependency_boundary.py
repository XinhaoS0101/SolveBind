import unittest
from pathlib import Path


class DependencyBoundaryTests(unittest.TestCase):
    def test_hll_framework_does_not_import_mobileagent_or_ui_tars(self):
        forbidden = ("MobileAgent", "agent_system", "ui_tars", "UITARS", "UI-TARS")
        offenders = []
        for path in Path("hll").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    offenders.append(f"{path}:{token}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
