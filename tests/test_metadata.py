from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProjectMetadataTest(unittest.TestCase):
    def test_targets_endstone_012_and_python_311(self) -> None:
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]

        self.assertEqual(project["requires-python"], ">=3.11")
        self.assertIn("endstone>=0.12,<0.13", project["dependencies"])

    def test_plugin_uses_endstone_012_api(self) -> None:
        source = (PROJECT_ROOT / "show_status.py").read_text(encoding="utf-8")

        self.assertIn('api_version = "0.12"', source)
        self.assertIn('soft_depend: ClassVar[list[str]] = ["papi"]', source)


if __name__ == "__main__":
    unittest.main()
