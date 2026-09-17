from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProjectMetadataTest(unittest.TestCase):
    def test_targets_exact_endstone_01111_and_python_310(self) -> None:
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
            project = tomllib.load(stream)["project"]

        self.assertEqual(project["requires-python"], ">=3.10")
        self.assertIn("endstone==0.11.11", project["dependencies"])
        self.assertIn("tomli>=2; python_version < '3.11'", project["dependencies"])

    def test_plugin_uses_endstone_011_api(self) -> None:
        source = (PROJECT_ROOT / "show_status.py").read_text(encoding="utf-8")

        self.assertIn('api_version = "0.11"', source)
        self.assertIn('soft_depend: ClassVar[list[str]] = ["papi"]', source)


if __name__ == "__main__":
    unittest.main()
