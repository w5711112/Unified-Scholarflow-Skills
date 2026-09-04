"""Launcher tests: input validation and the isolation/pipe launch contract."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

import scripts.launch_edge_profile as launcher


class LaunchEdgeProfileTests(unittest.TestCase):
    def test_invalid_profile_path_is_rejected_without_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(launcher.subprocess, "Popen") as popen:
                code = launcher.main(["--profile", os.path.join(tmp, "plain-dir")])
        self.assertEqual(code, 2)
        popen.assert_not_called()

    def test_explicit_profile_sets_isolation_pipe_and_extension_flags(self) -> None:
        pipe_name = None

        def fake_probe(timeout: float) -> dict[str, object]:
            return {"ok": True, "pipe": pipe_name}

        with tempfile.TemporaryDirectory() as tmp:
            profile = os.path.join(tmp, "edge-profile")
            env_snapshot: dict[str, str] = {}

            class FakeChild:
                pid = 12345

            def fake_popen(cmd, **kwargs):
                env_snapshot["cmd"] = cmd
                env_snapshot.update(kwargs.get("env", {}))
                return FakeChild()

            with patch.object(launcher, "_locate_edge", return_value=r"C:\Edge\msedge.exe"), \
                 patch.object(launcher.subprocess, "Popen", side_effect=fake_popen), \
                 patch.object(launcher, "probe_edge_background_bridge", side_effect=fake_probe):
                pipe_name = launcher.edge_pipe_name(profile)
                code = launcher.main(["--profile", profile])

            self.assertEqual(code, 0)
            cmd = env_snapshot["cmd"]
            self.assertTrue(any("--load-extension=" in part for part in cmd))
            self.assertIn("--disable-sync", cmd)
            self.assertIn("--enable-unsafe-extension-debugging", cmd)
            self.assertEqual(
                env_snapshot["SEARCHING_AT_SCALE_PIPE_NAME"],
                pipe_name,
            )
            self.assertEqual(
                env_snapshot["SAT_EDGE_PIPE_PATH"],
                rf"\\.\pipe\{pipe_name}",
            )

    def test_verbose_reports_command_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = os.path.join(tmp, "edge-profile")
            captured: dict[str, object] = {}

            class FakeChild:
                pid = 12345

            def fake_probe(timeout: float) -> dict[str, object]:
                return {"ok": True, "pipe": launcher.edge_pipe_name(profile)}

            def fake_popen(cmd, **kwargs):
                captured["cmd"] = cmd
                return FakeChild()

            with patch.object(launcher, "_locate_edge", return_value=r"C:\Edge\msedge.exe"), \
                 patch.object(launcher.subprocess, "Popen", side_effect=fake_popen), \
                 patch.object(launcher, "probe_edge_background_bridge", side_effect=fake_probe):
                code = launcher.main(["--profile", profile, "--verbose"])

            self.assertEqual(code, 0)
            self.assertIn("--load-extension=", " ".join(captured["cmd"]))


if __name__ == "__main__":
    unittest.main()
