from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from ensure_python_dependencies import ensure_import  # noqa: E402


class DependencyBootstrapTests(unittest.TestCase):
    def test_missing_allowlisted_dependency_is_installed_with_selected_python(self):
        imports = []

        def importer(name: str):
            imports.append(name)
            if len(imports) == 1:
                error = ModuleNotFoundError(name)
                error.name = name
                raise error
            return Mock(__version__="6.0.2")

        commands = []

        def runner(command, **kwargs):
            commands.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        report = ensure_import(
            "yaml",
            importer=importer,
            runner=runner,
            executable=r"C:\SelectedPython\python.exe",
        )

        self.assertEqual(imports, ["yaml", "yaml"])
        self.assertEqual(
            commands[0][0],
            [
                r"C:\SelectedPython\python.exe",
                "-m",
                "pip",
                "install",
                "PyYAML",
            ],
        )
        self.assertTrue(commands[0][1]["check"])
        self.assertEqual(report["distribution"], "PyYAML")
        self.assertEqual(report["version"], "6.0.2")
        self.assertTrue(report["installed"])

    def test_unknown_dependency_is_not_installed(self):
        with self.assertRaisesRegex(ValueError, "not allow-listed"):
            ensure_import("untrusted-package")


if __name__ == "__main__":
    unittest.main()
