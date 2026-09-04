from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.error import URLError
import zipfile

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.duckdb_runtime import (
    DUCKDB_RELEASE,
    DuckDBRelease,
    ResourceSnapshot,
    _download_file,
    choose_resource_profile,
    ensure_duckdb,
    run_duckdb,
)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class DuckDBRuntimeTests(unittest.TestCase):
    def test_release_is_pinned_to_verified_windows_asset(self):
        self.assertEqual(
            DUCKDB_RELEASE,
            DuckDBRelease(
                version="1.5.5",
                asset_url=(
                    "https://github.com/duckdb/duckdb/releases/download/"
                    "v1.5.5/duckdb_cli-windows-amd64.zip"
                ),
                sha256=(
                    "e1428b7114a841626b5054723731cbf45"
                    "c6df91b42ae1a6c355f88fad1f6dc4c"
                ),
                executable_name="duckdb.exe",
            ),
        )

    def test_broad_query_gets_more_resources_without_absolute_fixed_cap(self):
        snapshot = ResourceSnapshot(16, 64 << 30, 48 << 30, 2 << 40)
        narrow = choose_resource_profile(
            snapshot,
            scope="prefix",
            raw_result_limit=500,
            remaining_seconds=300,
        )
        broad = choose_resource_profile(
            snapshot,
            scope="domain",
            raw_result_limit=20_000,
            remaining_seconds=540,
        )
        self.assertGreater(broad.threads, narrow.threads)
        self.assertGreater(broad.memory_limit_bytes, narrow.memory_limit_bytes)
        self.assertGreater(
            broad.max_temp_directory_size_bytes,
            narrow.max_temp_directory_size_bytes,
        )
        self.assertLessEqual(broad.threads, snapshot.logical_cpus)
        self.assertLess(broad.memory_limit_bytes, snapshot.available_memory_bytes)
        self.assertLess(
            broad.max_temp_directory_size_bytes, snapshot.free_disk_bytes
        )

    def test_low_memory_and_disk_downshift_and_timeout_is_ten_minutes(self):
        healthy = ResourceSnapshot(16, 64 << 30, 48 << 30, 2 << 40)
        pressured = ResourceSnapshot(16, 64 << 30, 6 << 30, 20 << 30)
        high = choose_resource_profile(
            healthy,
            scope="domain",
            raw_result_limit=20_000,
            remaining_seconds=900,
        )
        low = choose_resource_profile(
            pressured,
            scope="domain",
            raw_result_limit=20_000,
            remaining_seconds=900,
        )
        self.assertLess(low.threads, high.threads)
        self.assertLess(low.memory_limit_bytes, high.memory_limit_bytes)
        self.assertLess(
            low.max_temp_directory_size_bytes,
            high.max_temp_directory_size_bytes,
        )
        self.assertLess(low.memory_limit_bytes, pressured.available_memory_bytes)
        self.assertLess(
            low.max_temp_directory_size_bytes, pressured.free_disk_bytes
        )
        self.assertEqual(low.timeout_seconds, 600.0)

    def test_explicit_executable_is_verified_without_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "custom-duckdb.exe"
            executable.write_bytes(b"local")
            downloader = mock.Mock(side_effect=AssertionError("must not download"))
            resolved = ensure_duckdb(
                duckdb_path=executable,
                downloader=downloader,
                version_probe=lambda _: "v1.5.5 (test)",
            )
        self.assertEqual(resolved, executable.resolve())
        downloader.assert_not_called()

    def test_urllib_network_failure_uses_fixed_windows_curl_fallback(self):
        for network_error in (
            URLError("redirect timeout"),
            ConnectionResetError("connection reset"),
        ):
            with self.subTest(error=type(network_error).__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                windows_root = root / "Windows"
                curl = windows_root / "System32" / "curl.exe"
                curl.parent.mkdir(parents=True)
                curl.write_bytes(b"system curl")
                destination = root / "duckdb.zip.partial"
                calls: list[tuple[list[str], dict[str, object]]] = []

                def run(args, **kwargs):
                    calls.append((args, kwargs))
                    output_index = args.index("--output") + 1
                    Path(args[output_index]).write_bytes(b"downloaded by curl")
                    return mock.Mock(returncode=0, stderr="")

                with (
                    mock.patch(
                        "scripts.duckdb_runtime.urlopen",
                        side_effect=network_error,
                    ),
                    mock.patch.dict(
                        "os.environ", {"SystemRoot": str(windows_root)}
                    ),
                    mock.patch(
                        "scripts.duckdb_runtime.subprocess.run", side_effect=run
                    ),
                ):
                    _download_file(
                        "https://example.invalid/duckdb.zip", destination
                    )

                self.assertEqual(
                    destination.read_bytes(), b"downloaded by curl"
                )
                self.assertEqual(Path(calls[0][0][0]), curl)
                self.assertIn("--location", calls[0][0])
                self.assertIn("--max-time", calls[0][0])
                self.assertIs(calls[0][1]["shell"], False)

    def test_wrong_hash_does_not_install_or_leave_partial_files(self):
        archive = _zip_bytes({"duckdb.exe": b"binary"})
        release = DuckDBRelease(
            "1.5.5",
            "https://example.invalid/duckdb.zip",
            "0" * 64,
            "duckdb.exe",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def downloader(_url: str, destination: Path) -> None:
                destination.write_bytes(archive)

            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                ensure_duckdb(
                    cache_root=root,
                    release=release,
                    downloader=downloader,
                    version_probe=lambda _: "v1.5.5",
                )
            self.assertFalse((root / "duckdb" / "1.5.5" / "duckdb.exe").exists())
            self.assertEqual(list(root.rglob("*.partial")), [])
            self.assertEqual(list(root.rglob("*.lock")), [])

    def test_zip_path_traversal_is_rejected(self):
        archive = _zip_bytes(
            {"../duckdb.exe": b"attacker", "duckdb.exe": b"binary"}
        )
        release = DuckDBRelease(
            "1.5.5",
            "https://example.invalid/duckdb.zip",
            hashlib.sha256(archive).hexdigest(),
            "duckdb.exe",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def downloader(_url: str, destination: Path) -> None:
                destination.write_bytes(archive)

            with self.assertRaisesRegex(RuntimeError, "unsafe ZIP member"):
                ensure_duckdb(
                    cache_root=root,
                    release=release,
                    downloader=downloader,
                    version_probe=lambda _: "v1.5.5",
                )
            self.assertFalse((root / "duckdb" / "1.5.5" / "duckdb.exe").exists())

    def test_install_lock_allows_only_one_concurrent_download(self):
        archive = _zip_bytes({"duckdb.exe": b"binary"})
        release = DuckDBRelease(
            "1.5.5",
            "https://example.invalid/duckdb.zip",
            hashlib.sha256(archive).hexdigest(),
            "duckdb.exe",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = 0
            calls_lock = threading.Lock()
            started = threading.Event()

            def downloader(_url: str, destination: Path) -> None:
                nonlocal calls
                with calls_lock:
                    calls += 1
                started.set()
                time.sleep(0.08)
                destination.write_bytes(archive)

            results: list[Path] = []
            failures: list[BaseException] = []

            def install() -> None:
                try:
                    results.append(
                        ensure_duckdb(
                            cache_root=root,
                            release=release,
                            downloader=downloader,
                            version_probe=lambda _: "v1.5.5",
                            lock_poll_seconds=0.01,
                        )
                    )
                except BaseException as exc:
                    failures.append(exc)

            first = threading.Thread(target=install)
            second = threading.Thread(target=install)
            first.start()
            self.assertTrue(started.wait(1.0))
            second.start()
            first.join(2.0)
            second.join(2.0)

            self.assertEqual(failures, [])
            self.assertEqual(calls, 1)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0], results[1])
            self.assertTrue(results[0].is_file())

    def test_interrupted_install_leaves_no_official_executable_or_lock(self):
        release = DuckDBRelease(
            "1.5.5",
            "https://example.invalid/duckdb.zip",
            "0" * 64,
            "duckdb.exe",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def downloader(_url: str, destination: Path) -> None:
                destination.write_bytes(b"partial")
                raise KeyboardInterrupt()

            with self.assertRaises(KeyboardInterrupt):
                ensure_duckdb(
                    cache_root=root,
                    release=release,
                    downloader=downloader,
                    version_probe=lambda _: "v1.5.5",
                )
            self.assertFalse((root / "duckdb" / "1.5.5" / "duckdb.exe").exists())
            self.assertEqual(list(root.rglob("*.partial")), [])
            self.assertEqual(list(root.rglob("*.lock")), [])

    def test_timeout_terminates_only_the_registered_pid(self):
        class FakeProcess:
            pid = 48123
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

        process = FakeProcess()
        popen_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def popen_factory(*args, **kwargs):
            popen_calls.append((args, kwargs))
            return process

        killed: list[int] = []

        def kill_tree(candidate) -> None:
            killed.append(candidate.pid)
            candidate.returncode = -9

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / "duckdb.exe"
            executable.write_bytes(b"fake")
            sql = root / "query.sql"
            sql.write_text("SELECT 1;", encoding="utf-8")
            result = run_duckdb(
                executable,
                sql,
                root / "stdout.log",
                root / "stderr.log",
                timeout_seconds=0.01,
                popen_factory=popen_factory,
                process_tree_killer=kill_tree,
                poll_interval_seconds=0.001,
            )
        self.assertTrue(result.timed_out)
        self.assertFalse(result.cancelled)
        self.assertEqual(result.returncode, -9)
        self.assertEqual(killed, [48123])
        self.assertEqual(popen_calls[0][0][0], [str(executable.resolve())])
        self.assertIs(popen_calls[0][1]["shell"], False)

    def test_pre_cancelled_execution_still_cleans_the_exact_process(self):
        class FakeProcess:
            pid = 49123
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

        process = FakeProcess()
        cancelled = threading.Event()
        cancelled.set()
        killed: list[int] = []

        def kill_tree(candidate) -> None:
            killed.append(candidate.pid)
            candidate.returncode = -15

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / "duckdb.exe"
            executable.write_bytes(b"fake")
            sql = root / "query.sql"
            sql.write_text("SELECT 1;", encoding="utf-8")
            result = run_duckdb(
                executable,
                sql,
                root / "stdout.log",
                root / "stderr.log",
                timeout_seconds=30,
                cancel_event=cancelled,
                popen_factory=lambda *args, **kwargs: process,
                process_tree_killer=kill_tree,
                poll_interval_seconds=0.001,
            )
        self.assertFalse(result.timed_out)
        self.assertTrue(result.cancelled)
        self.assertEqual(killed, [49123])


if __name__ == "__main__":
    unittest.main()
