from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from typing import Callable, Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen
import zipfile


@dataclass(frozen=True)
class DuckDBRelease:
    version: str
    asset_url: str
    sha256: str
    executable_name: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"\d+\.\d+\.\d+", self.version):
            raise ValueError("DuckDB version must be a numeric semantic version")
        if not self.asset_url.startswith("https://"):
            raise ValueError("DuckDB asset URL must use HTTPS")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("DuckDB SHA-256 must be 64 lowercase hexadecimal digits")
        if Path(self.executable_name).name != self.executable_name:
            raise ValueError("DuckDB executable name must be a root filename")


DUCKDB_RELEASE = DuckDBRelease(
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
)


@dataclass(frozen=True)
class ResourceSnapshot:
    logical_cpus: int
    total_memory_bytes: int
    available_memory_bytes: int
    free_disk_bytes: int

    def __post_init__(self) -> None:
        for name in (
            "logical_cpus",
            "total_memory_bytes",
            "available_memory_bytes",
            "free_disk_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.available_memory_bytes > self.total_memory_bytes:
            raise ValueError("available memory cannot exceed total memory")


@dataclass(frozen=True)
class DuckDBResourceProfile:
    threads: int
    memory_limit_bytes: int
    max_temp_directory_size_bytes: int
    timeout_seconds: float


@dataclass(frozen=True)
class DuckDBExecutionResult:
    returncode: int | None
    timed_out: bool
    cancelled: bool
    elapsed_seconds: float
    peak_rss_bytes: int | None


class _CancelEvent(Protocol):
    def is_set(self) -> bool: ...


def default_cache_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "searching-at-scale"
    return Path.home() / "AppData" / "Local" / "searching-at-scale"


def _windows_memory() -> tuple[int, int]:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


def _portable_memory() -> tuple[int, int]:
    if hasattr(os, "sysconf"):
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        total = page_size * int(os.sysconf("SC_PHYS_PAGES"))
        available = page_size * int(os.sysconf("SC_AVPHYS_PAGES"))
        return total, available
    raise OSError("physical memory probing is unsupported on this platform")


def probe_resources(task_temp_parent: Path | str) -> ResourceSnapshot:
    parent = Path(task_temp_parent).resolve(strict=False)
    parent.mkdir(parents=True, exist_ok=True)
    logical_cpus = os.cpu_count() or 1
    total_memory, available_memory = (
        _windows_memory() if os.name == "nt" else _portable_memory()
    )
    free_disk = shutil.disk_usage(parent).free
    return ResourceSnapshot(
        logical_cpus=logical_cpus,
        total_memory_bytes=total_memory,
        available_memory_bytes=available_memory,
        free_disk_bytes=free_disk,
    )


def choose_resource_profile(
    snapshot: ResourceSnapshot,
    *,
    scope: str,
    raw_result_limit: int,
    remaining_seconds: float,
) -> DuckDBResourceProfile:
    if not isinstance(snapshot, ResourceSnapshot):
        raise TypeError("snapshot must be a ResourceSnapshot")
    if scope not in {"domain", "subdomain", "prefix"}:
        raise ValueError("scope must be domain, subdomain, or prefix")
    if (
        isinstance(raw_result_limit, bool)
        or not isinstance(raw_result_limit, int)
        or raw_result_limit <= 0
    ):
        raise ValueError("raw_result_limit must be a positive integer")
    if (
        isinstance(remaining_seconds, bool)
        or not isinstance(remaining_seconds, (int, float))
        or not math.isfinite(float(remaining_seconds))
        or remaining_seconds <= 0
    ):
        raise ValueError("remaining_seconds must be positive and finite")

    broad = (
        scope in {"domain", "subdomain"}
        and raw_result_limit >= 5_000
        and remaining_seconds >= 300
    )
    cpu_fraction = 0.75 if broad else 0.50
    memory_fraction = 0.40 if broad else 0.25
    disk_fraction = 0.05 if broad else 0.02
    if snapshot.available_memory_bytes / snapshot.total_memory_bytes < 0.20:
        cpu_fraction = min(cpu_fraction, 0.25)
        memory_fraction = min(memory_fraction, 0.10)
        disk_fraction = min(disk_fraction, 0.01)

    threads = max(1, min(snapshot.logical_cpus, int(snapshot.logical_cpus * cpu_fraction)))
    memory = max(
        1,
        min(
            snapshot.available_memory_bytes - 1,
            int(snapshot.available_memory_bytes * memory_fraction),
        ),
    )
    temp_size = max(
        1,
        min(
            snapshot.free_disk_bytes - 1,
            int(snapshot.free_disk_bytes * disk_fraction),
        ),
    )
    return DuckDBResourceProfile(
        threads=threads,
        memory_limit_bytes=memory,
        max_temp_directory_size_bytes=temp_size,
        timeout_seconds=float(min(600.0, remaining_seconds)),
    )


def _download_file(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "searching-at-scale/duckdb-runtime"})
    try:
        with urlopen(request, timeout=60) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output, length=1 << 20)
        return
    except (URLError, TimeoutError, socket.timeout, ConnectionError) as primary_error:
        if os.name != "nt":
            raise
        system_root = os.environ.get("SystemRoot")
        if not system_root:
            raise
        curl = Path(system_root) / "System32" / "curl.exe"
        if not curl.is_file():
            raise
        completed = subprocess.run(
            [
                str(curl),
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--connect-timeout",
                "30",
                "--max-time",
                "180",
                "--retry",
                "2",
                "--retry-delay",
                "2",
                "--retry-all-errors",
                "--output",
                str(destination),
                url,
            ],
            shell=False,
            check=False,
            capture_output=True,
            text=True,
            timeout=210,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not destination.is_file():
            detail = completed.stderr.strip()[-500:]
            raise URLError(
                f"urllib failed ({primary_error}); curl exit "
                f"{completed.returncode}: {detail}"
            ) from primary_error


def _probe_version(executable: Path) -> str:
    completed = subprocess.run(
        [str(executable), "--version"],
        shell=False,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    if completed.returncode != 0:
        raise RuntimeError(
            f"DuckDB version probe failed with exit code {completed.returncode}: {output}"
        )
    return output


def _verify_version(
    executable: Path,
    release: DuckDBRelease,
    version_probe: Callable[[Path], str],
) -> None:
    output = version_probe(executable)
    if not isinstance(output, str) or f"v{release.version}" not in output:
        raise RuntimeError(
            f"DuckDB executable did not report required version v{release.version}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_zip_member(
    archive: zipfile.ZipFile, executable_name: str
) -> zipfile.ZipInfo:
    executable_member: zipfile.ZipInfo | None = None
    for member in archive.infolist():
        normalized = member.filename.replace("\\", "/")
        pure = PurePosixPath(normalized)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or re.match(r"^[A-Za-z]:", normalized)
        ):
            raise RuntimeError(f"unsafe ZIP member: {member.filename}")
        if normalized == executable_name and not member.is_dir():
            executable_member = member
    if executable_member is None:
        raise RuntimeError(f"DuckDB ZIP does not contain root {executable_name}")
    return executable_member


def ensure_duckdb(
    *,
    cache_root: Path | str | None = None,
    duckdb_path: Path | str | None = None,
    release: DuckDBRelease = DUCKDB_RELEASE,
    downloader: Callable[[str, Path], None] = _download_file,
    version_probe: Callable[[Path], str] = _probe_version,
    lock_timeout_seconds: float = 60.0,
    lock_poll_seconds: float = 0.1,
) -> Path:
    """Return a verified DuckDB executable, installing the pinned build if needed."""

    if not isinstance(release, DuckDBRelease):
        raise TypeError("release must be a DuckDBRelease")
    if lock_timeout_seconds <= 0 or lock_poll_seconds <= 0:
        raise ValueError("lock timing must be positive")
    if duckdb_path is not None:
        explicit = Path(duckdb_path).resolve(strict=False)
        if not explicit.is_file():
            raise FileNotFoundError(f"DuckDB executable not found: {explicit}")
        _verify_version(explicit, release, version_probe)
        return explicit

    root = Path(cache_root) if cache_root is not None else default_cache_root()
    root = root.resolve(strict=False)
    install_parent = root / "duckdb"
    version_directory = install_parent / release.version
    target = version_directory / release.executable_name
    lock_path = install_parent / f"{release.version}.install.lock"
    install_parent.mkdir(parents=True, exist_ok=True)

    if target.is_file():
        _verify_version(target, release, version_probe)
        return target.resolve()

    deadline = time.monotonic() + lock_timeout_seconds
    lock_fd: int | None = None
    while lock_fd is None:
        try:
            lock_fd = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            os.write(lock_fd, f"pid={os.getpid()}\n".encode("ascii"))
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for DuckDB install lock: {lock_path}")
            time.sleep(lock_poll_seconds)

    staging_directory: Path | None = None
    try:
        if target.is_file():
            _verify_version(target, release, version_probe)
            return target.resolve()

        staging_directory = Path(
            tempfile.mkdtemp(prefix=f".{release.version}-", dir=install_parent)
        )
        partial_zip = staging_directory / "download.zip.partial"
        staged_executable = staging_directory / release.executable_name
        downloader(release.asset_url, partial_zip)
        actual_hash = _sha256(partial_zip)
        if actual_hash != release.sha256:
            raise RuntimeError(
                "DuckDB archive SHA-256 mismatch: "
                f"expected {release.sha256}, got {actual_hash}"
            )

        try:
            with zipfile.ZipFile(partial_zip) as archive:
                member = _validated_zip_member(archive, release.executable_name)
                with archive.open(member) as source, staged_executable.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1 << 20)
        except zipfile.BadZipFile as exc:
            raise RuntimeError("DuckDB archive is not a valid ZIP file") from exc

        _verify_version(staged_executable, release, version_probe)
        version_directory.mkdir(parents=True, exist_ok=True)
        os.replace(staged_executable, target)
        _verify_version(target, release, version_probe)
        return target.resolve()
    finally:
        if staging_directory is not None:
            shutil.rmtree(staging_directory, ignore_errors=True)
        if lock_fd is not None:
            os.close(lock_fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            shell=False,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except ProcessLookupError:
        return


def run_duckdb(
    duckdb_path: Path | str,
    sql_path: Path | str,
    stdout_path: Path | str,
    stderr_path: Path | str,
    *,
    timeout_seconds: float,
    cancel_event: _CancelEvent | None = None,
    popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    process_tree_killer: Callable[[subprocess.Popen[bytes]], None] = _terminate_process_tree,
    poll_interval_seconds: float = 0.05,
) -> DuckDBExecutionResult:
    """Run one DuckDB CLI process and clean only its registered process tree."""

    executable = Path(duckdb_path).resolve(strict=False)
    query = Path(sql_path).resolve(strict=False)
    if not executable.is_file():
        raise FileNotFoundError(f"DuckDB executable not found: {executable}")
    if not query.is_file():
        raise FileNotFoundError(f"DuckDB SQL file not found: {query}")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be positive and finite")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")

    stdout_file_path = Path(stdout_path).resolve(strict=False)
    stderr_file_path = Path(stderr_path).resolve(strict=False)
    stdout_file_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_file_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    timed_out = False
    cancelled = False

    popen_kwargs: dict[str, object] = {"shell": False}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    with (
        query.open("rb") as sql_input,
        stdout_file_path.open("wb") as stdout_output,
        stderr_file_path.open("wb") as stderr_output,
    ):
        process = popen_factory(
            [str(executable)],
            stdin=sql_input,
            stdout=stdout_output,
            stderr=stderr_output,
            **popen_kwargs,
        )
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            elapsed = time.monotonic() - start
            if elapsed >= timeout_seconds:
                timed_out = True
                break
            time.sleep(min(poll_interval_seconds, timeout_seconds - elapsed))

        if timed_out or cancelled:
            process_tree_killer(process)
        try:
            returncode = process.wait(timeout=30 if (timed_out or cancelled) else None)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = process.wait(timeout=10)

    return DuckDBExecutionResult(
        returncode=returncode,
        timed_out=timed_out,
        cancelled=cancelled,
        elapsed_seconds=max(0.0, time.monotonic() - start),
        peak_rss_bytes=None,
    )


__all__ = [
    "DUCKDB_RELEASE",
    "DuckDBExecutionResult",
    "DuckDBRelease",
    "DuckDBResourceProfile",
    "ResourceSnapshot",
    "choose_resource_profile",
    "default_cache_root",
    "ensure_duckdb",
    "probe_resources",
    "run_duckdb",
]
