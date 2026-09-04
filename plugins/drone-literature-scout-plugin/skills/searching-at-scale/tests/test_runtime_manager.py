from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.runtime_manager import (
    DOMESTIC_ENGINE_PROFILE,
    RuntimeManager,
    render_searxng_settings,
)


@dataclass
class Result:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class DockerFixture:
    def __init__(self, *, docker=True, image=True, start=True):
        self.docker = docker
        self.image = image
        self.start = start
        self.calls: list[list[str]] = []
        self.stopped = False

    def __call__(self, arguments, **kwargs):
        del kwargs
        args = list(arguments)
        self.calls.append(args)
        if args[:2] == ["docker", "version"]:
            return Result(0 if self.docker else 1)
        if args[:3] == ["docker", "image", "inspect"]:
            return Result(0 if self.image else 1)
        if args[:2] == ["docker", "run"]:
            return Result(0 if self.start else 1, "abc123def456\n" if self.start else "")
        if args[:2] == ["docker", "stop"]:
            self.stopped = True
            return Result(0)
        if args[:2] == ["docker", "inspect"]:
            return Result(1 if self.stopped else 0)
        raise AssertionError(f"unexpected command: {args}")


class RuntimeManagerTests(unittest.TestCase):
    def test_settings_renderer_uses_a_closed_explicit_engine_allowlist(self):
        value = render_searxng_settings(
            "fixed-test-secret", DOMESTIC_ENGINE_PROFILE
        )
        self.assertIn(
            """use_default_settings:
  engines:
    keep_only:
      - 360search
      - baidu
      - sogou
      - quark
      - bing
      - brave""",
            value,
        )
        for engine in DOMESTIC_ENGINE_PROFILE:
            with self.subTest(engine=engine):
                self.assertIn(
                    f"  - name: {engine}\n    disabled: false",
                    value,
                )
        self.assertEqual(value.count("disabled: false"), 6)

    def test_settings_renderer_rejects_unknown_duplicate_or_multiline_values(self):
        for engines in (
            ("google",),
            ("baidu\nsecret",),
            ("baidu", "baidu"),
            (),
        ):
            with self.subTest(engines=engines), self.assertRaises(ValueError):
                render_searxng_settings("fixed-test-secret", engines)
        with self.assertRaises(ValueError):
            render_searxng_settings("secret\nserver: injected", ("baidu",))

    def test_docker_unavailable_never_attempts_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = DockerFixture(docker=False)
            with RuntimeManager(
                run_id="run-1",
                temp_parent=tmp,
                command_runner=runner,
                url_probe=lambda url: True,
                sleep=lambda seconds: None,
            ).searxng() as runtime:
                self.assertFalse(runtime.available)
                self.assertEqual(runtime.reason, "docker_unavailable")
            self.assertFalse(any(call[:2] == ["docker", "run"] for call in runner.calls))

    def test_missing_image_is_reported_without_automatic_pull(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = DockerFixture(image=False)
            with RuntimeManager(
                run_id="run-1",
                temp_parent=tmp,
                command_runner=runner,
                url_probe=lambda url: True,
                sleep=lambda seconds: None,
            ).searxng() as runtime:
                self.assertFalse(runtime.available)
                self.assertEqual(runtime.reason, "image_unavailable")
            self.assertFalse(any("pull" in call for call in runner.calls))

    def test_launch_is_resource_bounded_and_cleanup_uses_exact_container_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = DockerFixture()
            manager = RuntimeManager(
                run_id="run-1",
                temp_parent=tmp,
                command_runner=runner,
                url_probe=lambda url: True,
                sleep=lambda seconds: None,
            )
            with manager.searxng() as runtime:
                self.assertTrue(runtime.available)
                self.assertEqual(runtime.container_id, "abc123def456")
                run = next(call for call in runner.calls if call[:2] == ["docker", "run"])
                self.assertIn("--rm", run)
                self.assertEqual(run[run.index("--memory") + 1], "768m")
                self.assertEqual(run[run.index("--cpus") + 1], "2")
                self.assertIn("io.openai.searching-at-scale.run-id=run-1", run)
                publish = run[run.index("--publish") + 1]
                self.assertTrue(publish.startswith("127.0.0.1:"))
                mount = run[run.index("--mount") + 1]
                self.assertIn("readonly", mount)
                settings = runtime.task_temp_dir / "settings" / "settings.yml"
                value = settings.read_text(encoding="utf-8")
                self.assertIn("- json", value)
                self.assertNotIn("<由 secrets", value)
                for engine in DOMESTIC_ENGINE_PROFILE:
                    self.assertIn(f"  - name: {engine}", value)
                self.assertEqual(value.count("disabled: false"), 6)
            self.assertIn(["docker", "stop", "abc123def456"], runner.calls)
            self.assertIn(["docker", "inspect", "abc123def456"], runner.calls)
            self.assertFalse(runtime.task_temp_dir.exists())
            calls = len(runner.calls)
            report = manager.cleanup()
            self.assertEqual(len(runner.calls), calls)
            self.assertTrue(report.temp_dir_removed)

    def test_health_failure_and_context_failures_always_cleanup(self):
        for mode in ("health", "exception", "interrupt"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                runner = DockerFixture()
                manager = RuntimeManager(
                    run_id=f"run-{mode}",
                    temp_parent=tmp,
                    command_runner=runner,
                    url_probe=(lambda url: mode != "health"),
                    sleep=lambda seconds: None,
                )
                if mode == "health":
                    with manager.searxng() as runtime:
                        self.assertFalse(runtime.available)
                        self.assertEqual(runtime.reason, "healthcheck_failed")
                elif mode == "exception":
                    with self.assertRaises(RuntimeError):
                        with manager.searxng():
                            raise RuntimeError("boom")
                else:
                    with self.assertRaises(KeyboardInterrupt):
                        with manager.searxng():
                            raise KeyboardInterrupt
                self.assertTrue(runner.stopped)
                self.assertFalse(manager.task_temp_dir.exists())

    def test_cleanup_refuses_to_delete_an_unowned_directory(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            runner = DockerFixture(docker=False)
            manager = RuntimeManager(
                run_id="run-1",
                temp_parent=tmp,
                command_runner=runner,
                url_probe=lambda url: False,
                sleep=lambda seconds: None,
            )
            manager._task_temp_dir = Path(outside)
            report = manager.cleanup()
            self.assertFalse(report.temp_dir_removed)
            self.assertTrue(Path(outside).exists())


if __name__ == "__main__":
    unittest.main()
