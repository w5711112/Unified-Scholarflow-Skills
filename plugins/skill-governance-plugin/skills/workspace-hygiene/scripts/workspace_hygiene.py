from __future__ import annotations

import hashlib
import json
import os
import ctypes
from contextlib import ExitStack
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path


AUTO_PARTS = {"__pycache__", ".pytest_cache"}
AUTO_SUFFIXES = {".pyc", ".pyo"}
HARD_PROTECTED_PARTS = {"python-packages", ".git", ".skill-contract"}
SOFT_PROTECTED_PARTS = {"tests"}
PROPOSAL_PARTS = {"legacy", "backup", "backups", "archive", "old", "output", "node_modules"}
_REPORT_POLICIES: dict[str, dict[str, object]] = {}
_PROPOSALS: dict[str, dict[str, object]] = {}
_QUARANTINES: dict[str, dict[str, object]] = {}
MANIFEST_NAME = ".workspace-hygiene-manifest.json"


if os.name == "nt":
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _NTDLL = ctypes.WinDLL("ntdll")
    _DELETE = 0x00010000
    _GENERIC_READ = 0x80000000
    _FILE_READ_ATTRIBUTES = 0x00000080
    _FILE_TRAVERSE = 0x00000020
    _SYNCHRONIZE = 0x00100000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _OPEN_EXISTING = 3
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_DISPOSITION_INFO_CLASS = 4
    _FILE_RENAME_INFORMATION_CLASS = 10
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    _KERNEL32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    _KERNEL32.CreateFileW.restype = wintypes.HANDLE
    _KERNEL32.GetFileInformationByHandle.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
    _KERNEL32.GetFileInformationByHandle.restype = wintypes.BOOL
    _KERNEL32.GetFinalPathNameByHandleW.argtypes = (
        wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
    )
    _KERNEL32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _KERNEL32.ReadFile.argtypes = (
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.LPDWORD, wintypes.LPVOID,
    )
    _KERNEL32.ReadFile.restype = wintypes.BOOL
    _KERNEL32.SetFileInformationByHandle.argtypes = (
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    )
    _KERNEL32.SetFileInformationByHandle.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _KERNEL32.CloseHandle.restype = wintypes.BOOL


    class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = (
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        )


    class _FILE_RENAME_INFO_LAYOUT(ctypes.Structure):
        _fields_ = (
            ("Flags", wintypes.DWORD),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        )


    class _FILE_DISPOSITION_INFO(ctypes.Structure):
        _fields_ = (("DeleteFile", wintypes.BOOLEAN),)


    class _IO_STATUS_BLOCK(ctypes.Structure):
        _fields_ = (("Status", wintypes.LONG), ("Information", ctypes.c_size_t))


    _NTDLL.NtSetInformationFile.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(_IO_STATUS_BLOCK), wintypes.LPVOID,
        wintypes.ULONG, ctypes.c_int,
    )
    _NTDLL.NtSetInformationFile.restype = wintypes.LONG
    _NTDLL.RtlNtStatusToDosError.argtypes = (wintypes.LONG,)
    _NTDLL.RtlNtStatusToDosError.restype = wintypes.ULONG


@dataclass(frozen=True)
class Candidate:
    relative_path: str
    size: int
    category: str
    reason: str
    action: str


@dataclass(frozen=True)
class ScanReport:
    root: str
    auto_candidates: list[Candidate]
    proposal_candidates: list[Candidate]
    protected_paths: list[str]
    total_bytes: int


@dataclass(frozen=True)
class HygieneProposal:
    root: str
    candidates: list[Candidate]
    protected_paths: list[str]
    expected_bytes: int


@dataclass(frozen=True)
class HygieneResult:
    paths: list[str]
    action: str
    reasons: list[str]
    before_bytes: int
    after_bytes: int
    rollback_path: str | None
    residual_risks: list[str]


def _inside(root: Path, candidate: Path) -> bool:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    return candidate_resolved == root_resolved or root_resolved in candidate_resolved.parents


def _candidate(relative: Path, size: int, category: str, reason: str, action: str) -> Candidate:
    return Candidate(relative.as_posix(), size, category, reason, action)


def _bounded_entries(root: Path) -> list[tuple[Path, bool]]:
    pending = [root]
    discovered: list[tuple[Path, bool]] = []
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    try:
                        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                        boundary = bool(attributes & 0x400) or _reparse(path)
                    except OSError:
                        boundary = True
                    discovered.append((path, boundary))
                    if boundary:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
        except OSError:
            if directory != root:
                discovered.append((directory, True))
    return sorted(discovered, key=lambda item: item[0])


def _protected_parts(policy: dict[str, object]) -> set[str]:
    return HARD_PROTECTED_PARTS | {
        str(name).lower()
        for name in policy.get("protected_names", [])
        if str(name).lower() != "tests"
    }


def scan_workspace(root: Path, policy: dict[str, object]) -> ScanReport:
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        raise ValueError("workspace root must be an existing directory")
    auto: list[Candidate] = []
    proposal: list[Candidate] = []
    protected: list[str] = []
    total = 0
    protected_names = _protected_parts(policy)
    semantic_candidate_paths = {
        str(value).replace("\\", "/") for value in policy.get("semantic_candidate_paths", [])
    }
    task_temp_paths = {
        str(value).replace("\\", "/") for value in policy.get("task_temp_paths", [])
    }
    successful_producers = {
        str(value).replace("\\", "/") for value in policy.get("successful_producers", [])
    }
    automatic_cleanup = policy.get("automatic_cleanup", True) is not False
    for path, boundary in _bounded_entries(resolved_root):
        if boundary:
            protected.append(path.relative_to(resolved_root).as_posix())
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(resolved_root)
        parts = {part.lower() for part in relative.parts}
        size = path.stat().st_size
        total += size
        if parts & protected_names or path.name == "incident-registry.json":
            protected.append(relative.as_posix())
        elif "__pycache__" in parts or path.suffix.lower() in AUTO_SUFFIXES:
            if automatic_cleanup:
                auto.append(_candidate(relative, size, "generated-cache", "mechanically reproducible", "delete"))
            else:
                protected.append(relative.as_posix())
        elif ".pytest_cache" in parts:
            if automatic_cleanup and policy.get("tests_completed") is True:
                auto.append(_candidate(relative, size, "generated-cache", "tests completed successfully", "delete"))
            else:
                protected.append(relative.as_posix())
        elif relative.as_posix() in task_temp_paths:
            if automatic_cleanup and relative.as_posix() in successful_producers:
                auto.append(_candidate(relative, size, "task-temporary", "recorded successful producer", "delete"))
            else:
                protected.append(relative.as_posix())
        elif parts & SOFT_PROTECTED_PARTS:
            protected.append(relative.as_posix())
        elif relative.as_posix() in semantic_candidate_paths:
            proposal.append(
                _candidate(relative, size, "semantic-candidate", "explicit exact-path review required", "quarantine")
            )
        elif parts & PROPOSAL_PARTS:
            proposal.append(_candidate(relative, size, "semantic-candidate", "requires reference and user review", "quarantine"))
        else:
            protected.append(relative.as_posix())
    report = ScanReport(str(resolved_root), auto, proposal, protected, total)
    _REPORT_POLICIES[hashlib.sha256(json.dumps(asdict(report), sort_keys=True).encode("utf-8")).hexdigest()] = dict(policy)
    return report


def _proposal_digest(proposal: HygieneProposal) -> str:
    payload = json.dumps(asdict(proposal), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _execution_digest(proposal: HygieneProposal) -> str:
    payload = json.dumps(
        {
            "root": proposal.root,
            "candidates": [asdict(item) for item in proposal.candidates],
            "expected_bytes": proposal.expected_bytes,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_proposal(report: ScanReport, selected_paths: list[str]) -> HygieneProposal:
    report_key = hashlib.sha256(json.dumps(asdict(report), sort_keys=True).encode("utf-8")).hexdigest()
    if report_key not in _REPORT_POLICIES:
        raise PermissionError("proposal requires a trusted scan report")
    selected = set(selected_paths)
    known = {item.relative_path: item for item in report.proposal_candidates}
    unknown = selected - set(known)
    if unknown:
        raise ValueError(f"unknown proposal paths: {sorted(unknown)}")
    candidates = list(report.auto_candidates) + [known[path] for path in sorted(selected)]
    proposal = HygieneProposal(report.root, candidates, report.protected_paths, sum(item.size for item in candidates))
    _PROPOSALS[_execution_digest(proposal)] = {
        "policy": _REPORT_POLICIES[report_key],
        "selected_paths": sorted(selected),
    }
    return proposal


def _workspace_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path, boundary in _bounded_entries(root) if not boundary and path.is_file())


def _reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.lstat().st_file_attributes & 0x400)
    except FileNotFoundError:
        return False
    except AttributeError:
        return path.is_symlink()


def _assert_plain_path(root: Path, path: Path) -> None:
    current = path
    while True:
        if _reparse(current):
            raise ValueError("reparse points are not allowed during cleanup")
        if current == root:
            return
        if current.parent == current:
            raise ValueError("path escaped its boundary")
        current = current.parent


def _automatic_cache_directories(root: Path, policy: dict[str, object]) -> set[Path]:
    if policy.get("automatic_cleanup", True) is False:
        return set()
    protected_parts = _protected_parts(policy)
    directories: set[Path] = set()
    for path, boundary in _bounded_entries(root):
        if boundary or not path.is_dir():
            continue
        parts = {part.lower() for part in path.relative_to(root).parts}
        if parts & protected_parts:
            continue
        if "__pycache__" in parts or (
            ".pytest_cache" in parts and policy.get("tests_completed") is True
        ):
            directories.add(path)
    return directories


def _prune_empty_automatic_directories(
    root: Path,
    sources: list[Path],
    discovered: set[Path],
    protected_parts: set[str],
) -> tuple[list[str], list[str]]:
    directories = set(discovered)
    for source in sources:
        chain: list[Path] = []
        current = source.parent
        while current != root:
            chain.append(current)
            if current.name.lower() in AUTO_PARTS:
                directories.update(chain)
                break
            current = current.parent
    removed: list[str] = []
    residual: list[str] = []
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        try:
            if {
                part.lower() for part in directory.relative_to(root).parts
            } & protected_parts:
                continue
            _assert_plain_path(root, directory)
            if _reparse(directory):
                raise ValueError("reparse cache directory is protected")
            directory.rmdir()
            removed.append(str(directory))
        except FileNotFoundError:
            continue
        except OSError as error:
            residual.append(f"empty cache directory retained: {directory} ({error})")
    return removed, residual


def _win32_error(api: str) -> OSError:
    code = ctypes.get_last_error()
    return ctypes.WinError(code, f"{api} failed with Win32 error {code}")


def _native_path(path: Path) -> str:
    absolute = os.path.abspath(path)
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _mkdir_plain(path: Path) -> None:
    os.mkdir(_native_path(path))


def _open_windows_path(
    path: Path, *, rename: bool, directory: bool = False, read_data: bool = False
) -> int:
    if os.name != "nt":
        raise OSError("identity-bound Windows rename is unavailable")
    access = _FILE_READ_ATTRIBUTES | (_DELETE if rename else 0)
    if read_data:
        access |= _GENERIC_READ
    if directory:
        access |= _FILE_TRAVERSE | _SYNCHRONIZE
    flags = _FILE_FLAG_OPEN_REPARSE_POINT | (_FILE_FLAG_BACKUP_SEMANTICS if directory else 0)
    share = _FILE_SHARE_READ | _FILE_SHARE_WRITE | (0 if directory else _FILE_SHARE_DELETE)
    handle = _KERNEL32.CreateFileW(
        _native_path(path), access, share,
        None, _OPEN_EXISTING, flags, None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        raise _win32_error("CreateFileW")
    return handle


def _handle_information(handle: int) -> _BY_HANDLE_FILE_INFORMATION:
    information = _BY_HANDLE_FILE_INFORMATION()
    ctypes.set_last_error(0)
    if not _KERNEL32.GetFileInformationByHandle(handle, ctypes.byref(information)):
        raise _win32_error("GetFileInformationByHandle")
    return information


def _handle_fingerprint(handle: int) -> tuple[int, int, int, int]:
    information = _handle_information(handle)
    identity = (information.nFileIndexHigh << 32) | information.nFileIndexLow
    size = (information.nFileSizeHigh << 32) | information.nFileSizeLow
    write_time = (information.ftLastWriteTime.dwHighDateTime << 32) | information.ftLastWriteTime.dwLowDateTime
    return information.dwVolumeSerialNumber, identity, size, write_time


def _handle_identity(handle: int) -> tuple[int, int]:
    information = _handle_information(handle)
    identity = (information.nFileIndexHigh << 32) | information.nFileIndexLow
    return information.dwVolumeSerialNumber, identity


def _final_handle_path(handle: int) -> Path:
    size = _KERNEL32.GetFinalPathNameByHandleW(handle, None, 0, 0)
    if not size:
        raise _win32_error("GetFinalPathNameByHandleW")
    buffer = ctypes.create_unicode_buffer(size + 1)
    if not _KERNEL32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0):
        raise _win32_error("GetFinalPathNameByHandleW")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _fingerprint(path: Path) -> tuple[int, int, int, int]:
    if os.name != "nt":
        stat = path.stat(follow_symlinks=False)
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
    handle = _open_windows_path(path, rename=False)
    try:
        return _handle_fingerprint(handle)
    finally:
        _KERNEL32.CloseHandle(handle)


def _open_rename_handle(path: Path, expected: tuple[int, int, int, int]) -> int:
    handle = _open_windows_path(path, rename=True)
    try:
        information = _handle_information(handle)
        if information.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("reparse candidate cannot be cleaned")
        if _handle_fingerprint(handle) != expected:
            raise ValueError("candidate identity changed before handle acquisition")
        if os.path.normcase(os.path.abspath(_final_handle_path(handle))) != os.path.normcase(os.path.abspath(path)):
            raise ValueError("candidate handle resolved through a reparse ancestor")
        return handle
    except Exception:
        _KERNEL32.CloseHandle(handle)
        raise


def _open_verified_directory(path: Path) -> int:
    handle = _open_windows_path(path, rename=False, directory=True)
    try:
        information = _handle_information(handle)
        if information.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("directory handle cannot refer to a reparse point")
        if os.path.normcase(os.path.abspath(_final_handle_path(handle))) != os.path.normcase(os.path.abspath(path)):
            raise ValueError("directory handle resolved through a reparse ancestor")
        return handle
    except Exception:
        _close_windows_handle(handle)
        raise


def _open_delete_directory(path: Path) -> int:
    handle = _open_windows_path(path, rename=True, directory=True)
    try:
        information = _handle_information(handle)
        if not information.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise ValueError("directory handle must refer to a directory")
        if information.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("directory handle cannot refer to a reparse point")
        if os.path.normcase(os.path.abspath(_final_handle_path(handle))) != os.path.normcase(os.path.abspath(path)):
            raise ValueError("directory handle resolved through a reparse ancestor")
        return handle
    except Exception:
        _close_windows_handle(handle)
        raise


def _open_delete_file(path: Path, expected: tuple[int, int, int, int], *, read_data: bool = False) -> int:
    handle = _open_windows_path(path, rename=True, read_data=read_data)
    try:
        information = _handle_information(handle)
        if information.dwFileAttributes & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError("purge object must be a plain file")
        if _handle_fingerprint(handle) != expected:
            raise ValueError("purge object identity changed before handle acquisition")
        if os.path.normcase(os.path.abspath(_final_handle_path(handle))) != os.path.normcase(os.path.abspath(path)):
            raise ValueError("purge object handle resolved through a reparse ancestor")
        return handle
    except Exception:
        _close_windows_handle(handle)
        raise


def _read_open_handle(handle: int) -> bytes:
    information = _handle_information(handle)
    remaining = (information.nFileSizeHigh << 32) | information.nFileSizeLow
    chunks: list[bytes] = []
    while remaining:
        requested = min(remaining, 1024 * 1024)
        buffer = ctypes.create_string_buffer(requested)
        read = wintypes.DWORD()
        ctypes.set_last_error(0)
        if not _KERNEL32.ReadFile(handle, buffer, requested, ctypes.byref(read), None):
            raise _win32_error("ReadFile")
        if not read.value:
            raise OSError("manifest handle ended before its recorded size")
        chunks.append(buffer.raw[:read.value])
        remaining -= read.value
    return b"".join(chunks)


def _rename_open_handle(handle: int, target_dir_handle: int, leaf_name: str) -> None:
    if os.name != "nt":
        raise OSError("identity-bound Windows rename is unavailable")
    leaf = Path(leaf_name)
    if leaf.name != leaf_name or len(leaf.parts) != 1 or any(separator in leaf_name for separator in ("/", "\\")):
        raise ValueError("handle-relative rename requires one leaf name")
    encoded = leaf_name.encode("utf-16-le")
    offset = _FILE_RENAME_INFO_LAYOUT.FileName.offset
    buffer = ctypes.create_string_buffer(offset + len(encoded) + ctypes.sizeof(wintypes.WCHAR))
    information = _FILE_RENAME_INFO_LAYOUT.from_buffer(buffer)
    information.Flags = 0
    information.RootDirectory = target_dir_handle
    information.FileNameLength = len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
    status_block = _IO_STATUS_BLOCK()
    status = _NTDLL.NtSetInformationFile(
        handle, ctypes.byref(status_block), buffer, len(buffer), _FILE_RENAME_INFORMATION_CLASS,
    )
    if status < 0:
        code = _NTDLL.RtlNtStatusToDosError(status)
        raise ctypes.WinError(code, f"NtSetInformationFile(FileRenameInformation) failed with NTSTATUS 0x{status & 0xFFFFFFFF:08x}")


def _set_delete_disposition(handle: int, delete: bool) -> None:
    if os.name != "nt":
        raise OSError("identity-bound Windows deletion is unavailable")
    information = _FILE_DISPOSITION_INFO(delete)
    ctypes.set_last_error(0)
    if not _KERNEL32.SetFileInformationByHandle(
        handle, _FILE_DISPOSITION_INFO_CLASS, ctypes.byref(information), ctypes.sizeof(information)
    ):
        raise _win32_error("SetFileInformationByHandle(FileDispositionInfo)")


def _real_delete_open_handle(handle: int) -> None:
    _set_delete_disposition(handle, True)


_delete_open_handle = _real_delete_open_handle


def _cancel_delete_open_handle(handle: int) -> None:
    _set_delete_disposition(handle, False)


def _close_windows_handle(handle: int) -> None:
    if os.name == "nt" and handle != _INVALID_HANDLE_VALUE:
        _KERNEL32.CloseHandle(handle)


def _own_windows_handle(owner: ExitStack, handle: int) -> int:
    owner.callback(_close_windows_handle, handle)
    return handle


class _WindowsHandleLease:
    def __init__(self, handle: int):
        self.handle: int | None = handle

    def close(self) -> None:
        if self.handle is not None:
            _close_windows_handle(self.handle)
            self.handle = None


def _lease_windows_handle(owner: ExitStack, handle: int) -> _WindowsHandleLease:
    lease = _WindowsHandleLease(handle)
    owner.callback(lease.close)
    return lease


def _manifest_path(quarantine: Path) -> Path:
    return quarantine / MANIFEST_NAME


def _commit_manifest(quarantine: Path, manifest: dict[str, object]) -> str:
    target = _manifest_path(quarantine)
    temporary = target.with_suffix(".prepared")
    payload = dict(manifest, state="committed")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
    os.link(temporary, target)
    temporary.unlink()
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("candidate path must be a strict relative path")
    return path


def apply_proposal(proposal: HygieneProposal, quarantine_root: Path, approval_token: str | None) -> HygieneResult:
    proposal_key = _execution_digest(proposal)
    trusted = _PROPOSALS.get(proposal_key)
    if trusted is None:
        raise PermissionError("proposal was not built from a trusted scan report")
    root = Path(proposal.root).resolve()
    for relative_path in trusted["selected_paths"]:
        lexical = root / _relative_path(str(relative_path))
        _assert_plain_path(root, lexical)
        if not lexical.is_file() or _reparse(lexical):
            raise FileNotFoundError(lexical)
    fresh = scan_workspace(root, dict(trusted["policy"]))
    canonical = build_proposal(fresh, list(trusted["selected_paths"]))
    if _execution_digest(proposal) != _execution_digest(canonical):
        raise PermissionError("proposal differs from the trusted current scan")
    semantic = [item for item in canonical.candidates if item.action == "quarantine"]
    expected = f"APPROVE:{_proposal_digest(proposal)}"
    if semantic and approval_token != expected:
        raise PermissionError("semantic cleanup requires the exact proposal approval token")
    quarantine = Path(os.path.abspath(quarantine_root))
    if not root.is_dir():
        raise ValueError("workspace root must be an existing directory")
    trusted_policy = dict(trusted["policy"])
    automatic_directories = _automatic_cache_directories(root, trusted_policy)
    protected_parts = _protected_parts(trusted_policy)
    if not canonical.candidates:
        before = _workspace_bytes(root)
        removed, residual_risks = _prune_empty_automatic_directories(
            root, [], automatic_directories, protected_parts
        )
        after = _workspace_bytes(root)
        return HygieneResult(
            removed,
            "delete",
            ["empty mechanically reproducible cache directory"] * len(removed),
            before,
            after,
            None,
            residual_risks,
        )
    if quarantine == root or root in quarantine.parents:
        raise ValueError("quarantine root must be outside scanned workspace root")
    _assert_plain_path(root, root)
    if quarantine.exists():
        raise FileExistsError("quarantine root must be newly created for this transaction")
    unopened: list[tuple[Candidate, Path, Path]] = []
    planned: list[tuple[Candidate, Path, Path, tuple[int, int, int, int], int, int, int]] = []
    destinations: set[Path] = set()
    changed: list[str] = []
    reasons: list[str] = []
    moved: list[tuple[Path, Path, int, int]] = []
    target_directory_handles: dict[Path, int] = {}
    source_parent_handles: dict[Path, int] = {}
    before = _workspace_bytes(root)
    with ExitStack() as handle_owner:
        try:
            target_directory_handles[quarantine.parent] = _own_windows_handle(
                handle_owner, _open_verified_directory(quarantine.parent)
            )
            _mkdir_plain(quarantine)
            target_directory_handles[quarantine] = _own_windows_handle(
                handle_owner, _open_verified_directory(quarantine)
            )
            for manifest_path in (_manifest_path(quarantine), _manifest_path(quarantine).with_suffix(".prepared")):
                if manifest_path.exists():
                    raise FileExistsError(manifest_path)

            for item in canonical.candidates:
                if item.action not in {"delete", "quarantine"}:
                    raise ValueError("unsupported cleanup action")
                lexical = root / _relative_path(item.relative_path)
                _assert_plain_path(root, lexical)
                if item.relative_path in canonical.protected_paths:
                    raise PermissionError("protected paths cannot be cleaned")
                if not lexical.is_file() or _reparse(lexical):
                    raise ValueError("reparse candidate cannot be cleaned")
                destination = quarantine / (
                    item.relative_path if item.action == "quarantine" else Path(".automatic") / item.relative_path
                )
                if destination in destinations or destination.exists():
                    raise FileExistsError(destination)
                destinations.add(destination)
                unopened.append((item, lexical, destination))

            for _, _, destination in unopened:
                current = quarantine
                for part in destination.parent.relative_to(quarantine).parts:
                    current = current / part
                    if current in target_directory_handles:
                        continue
                    _mkdir_plain(current)
                    target_directory_handles[current] = _own_windows_handle(
                        handle_owner, _open_verified_directory(current)
                    )
                if destination.exists():
                    raise FileExistsError(destination)

            for item, source, destination in unopened:
                source_parent = source.parent
                if source_parent not in source_parent_handles:
                    source_parent_handles[source_parent] = _own_windows_handle(
                        handle_owner, _open_verified_directory(source_parent)
                    )
                fingerprint = _fingerprint(source)
                source_handle = _own_windows_handle(
                    handle_owner, _open_rename_handle(source, fingerprint)
                )
                source_parent_handle = source_parent_handles[source_parent]
                target_handle = target_directory_handles[destination.parent]
                if _handle_information(target_handle).dwVolumeSerialNumber != fingerprint[0]:
                    raise OSError("cross-volume identity-bound rename is not supported")
                planned.append(
                    (item, source, destination, fingerprint, source_handle, source_parent_handle, target_handle)
                )

            for item, source, destination, fingerprint, source_handle, source_parent_handle, target_handle in planned:
                if _handle_fingerprint(source_handle) != fingerprint:
                    raise ValueError("candidate changed after preflight")
                _rename_open_handle(source_handle, target_handle, destination.name)
                moved.append((source, destination, source_handle, source_parent_handle))
                changed.append(str(source)); reasons.append(item.reason)
            manifest = {
                "root": str(root), "quarantine": str(quarantine),
                "entries": [item.relative_path for item, _, _, _, _, _, _ in planned if item.action == "quarantine"],
                "entry_identities": {
                    item.relative_path: _handle_identity(source_handle)
                    for item, _, _, _, source_handle, _, _ in planned
                    if item.action == "quarantine"
                },
                "directories": sorted(
                    path.relative_to(quarantine).as_posix()
                    for path in target_directory_handles
                    if path != quarantine and quarantine in path.parents
                ),
                "directory_identities": {
                    path.relative_to(quarantine).as_posix(): _handle_identity(handle)
                    for path, handle in target_directory_handles.items()
                    if path != quarantine and quarantine in path.parents
                },
            }
            manifest_hash = _commit_manifest(quarantine, manifest)
            manifest_identity = _fingerprint(_manifest_path(quarantine))[:2]
            _QUARANTINES[str(quarantine)] = {
                "root": str(root),
                "manifest": manifest_hash,
                "manifest_identity": manifest_identity,
                "quarantine_identity": _handle_identity(target_directory_handles[quarantine]),
            }
        except Exception as error:
            rollback_errors: list[str] = []
            for source, destination, source_handle, source_parent_handle in reversed(moved):
                try:
                    _rename_open_handle(source_handle, source_parent_handle, source.name)
                except Exception as rollback_error:
                    rollback_errors.append(f"{destination}: {rollback_error}")
            if rollback_errors:
                raise RuntimeError(f"move failed; rollback incomplete: {rollback_errors}") from error
            raise
        for item, _, destination, _, source_handle, _, _ in planned:
            if item.action != "delete":
                continue
            try:
                _delete_open_handle(source_handle)
            except Exception as error:
                raise OSError(f"automatic cleanup failed ({error}); recovery quarantine: {quarantine}") from error
    automatic_sources = [source for item, source, *_ in planned if item.action == "delete"]
    removed_directories, residual_risks = _prune_empty_automatic_directories(
        root, automatic_sources, automatic_directories, protected_parts
    )
    changed.extend(removed_directories)
    reasons.extend(["empty mechanically reproducible cache directory"] * len(removed_directories))
    after = _workspace_bytes(root)
    result = HygieneResult(
        changed,
        "mixed" if semantic else "delete",
        reasons,
        before,
        after,
        str(quarantine),
        residual_risks,
    )
    return result


def purge_quarantine(result: HygieneResult, approval_token: str) -> HygieneResult:
    if result.rollback_path is None:
        return result
    rollback = Path(os.path.abspath(result.rollback_path))
    record = _QUARANTINES.get(str(rollback))
    if record is None:
        raise PermissionError("quarantine was not created by this hygiene run")
    root = Path(str(record["root"])).resolve()
    if _inside(root, rollback) or not rollback.is_dir() or _reparse(rollback):
        raise PermissionError("invalid quarantine boundary")
    expected = "PURGE:" + hashlib.sha256(str(rollback).encode("utf-8")).hexdigest()
    if approval_token != expected:
        raise PermissionError("quarantine purge requires explicit approval")
    manifest_path = _manifest_path(rollback)
    with ExitStack() as handle_owner:
        _lease_windows_handle(handle_owner, _open_verified_directory(rollback.parent))
        root_lease = _lease_windows_handle(handle_owner, _open_delete_directory(rollback))
        assert root_lease.handle is not None
        if _handle_identity(root_lease.handle) != tuple(record.get("quarantine_identity", ())):
            raise PermissionError("quarantine root identity changed")

        manifest_fingerprint = _fingerprint(manifest_path)
        if manifest_fingerprint[:2] != tuple(record.get("manifest_identity", ())):
            raise PermissionError("quarantine manifest identity changed")
        manifest_lease = _lease_windows_handle(
            handle_owner, _open_delete_file(manifest_path, manifest_fingerprint, read_data=True)
        )
        assert manifest_lease.handle is not None
        manifest_bytes = _read_open_handle(manifest_lease.handle)
        if hashlib.sha256(manifest_bytes).hexdigest() != record["manifest"]:
            raise PermissionError("quarantine manifest is missing or changed")
        try:
            manifest_data = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PermissionError("quarantine manifest is invalid") from error
        if not isinstance(manifest_data, dict):
            raise PermissionError("quarantine manifest is invalid")
        raw_entries = manifest_data.get("entries")
        raw_directories = manifest_data.get("directories")
        raw_entry_identities = manifest_data.get("entry_identities")
        raw_directory_identities = manifest_data.get("directory_identities")
        if (
            not isinstance(raw_entries, list)
            or not isinstance(raw_directories, list)
            or not isinstance(raw_entry_identities, dict)
            or not isinstance(raw_directory_identities, dict)
        ):
            raise PermissionError("quarantine manifest does not define its complete allowed tree")

        expected_files: set[str] = set()
        expected_directories: set[str] = set()
        for value in raw_entries:
            relative = _relative_path(str(value)).as_posix()
            if relative == MANIFEST_NAME or relative in expected_files:
                raise PermissionError("quarantine manifest contains duplicate or reserved entries")
            expected_files.add(relative)
        for value in raw_directories:
            relative = _relative_path(str(value)).as_posix()
            if relative == MANIFEST_NAME or relative in expected_directories or relative in expected_files:
                raise PermissionError("quarantine manifest contains duplicate or conflicting directories")
            expected_directories.add(relative)
        for relative in expected_files | expected_directories:
            parent = Path(relative).parent
            while parent != Path("."):
                if parent.as_posix() not in expected_directories:
                    raise PermissionError("quarantine manifest omits an ancestor directory")
                parent = parent.parent

        def manifest_identities(raw: dict[object, object], expected_paths: set[str]) -> dict[str, tuple[int, int]]:
            identities: dict[str, tuple[int, int]] = {}
            for key, value in raw.items():
                relative = _relative_path(str(key)).as_posix()
                if (
                    relative in identities
                    or not isinstance(value, list)
                    or len(value) != 2
                    or not all(isinstance(part, int) for part in value)
                ):
                    raise PermissionError("quarantine manifest contains invalid object identities")
                identities[relative] = (value[0], value[1])
            if set(identities) != expected_paths:
                raise PermissionError("quarantine manifest object identities are incomplete")
            return identities

        expected_file_identities = manifest_identities(raw_entry_identities, expected_files)
        expected_directory_identities = manifest_identities(raw_directory_identities, expected_directories)

        directory_leases: dict[str, _WindowsHandleLease] = {"": root_lease}
        file_leases: dict[str, _WindowsHandleLease] = {}
        seen_files: set[str] = set()
        seen_directories: set[str] = set()

        def open_allowed_tree(current: Path, relative_parent: Path) -> None:
            try:
                children = list(os.scandir(current))
            except OSError as error:
                raise PermissionError("quarantine tree cannot be enumerated safely") from error
            for child in children:
                child_path = current / child.name
                relative_path = relative_parent / child.name
                relative = relative_path.as_posix()
                if _reparse(child_path):
                    raise PermissionError("quarantine tree contains a reparse point")
                if child.is_dir(follow_symlinks=False):
                    if relative not in expected_directories:
                        raise PermissionError(f"quarantine tree contains unknown entry: {relative}")
                    lease = _lease_windows_handle(handle_owner, _open_delete_directory(child_path))
                    assert lease.handle is not None
                    if _handle_identity(lease.handle) != expected_directory_identities[relative]:
                        raise PermissionError(f"quarantine directory identity changed: {relative}")
                    directory_leases[relative] = lease
                    seen_directories.add(relative)
                    open_allowed_tree(child_path, relative_path)
                elif child.is_file(follow_symlinks=False):
                    if relative == MANIFEST_NAME:
                        if relative_parent != Path("."):
                            raise PermissionError("quarantine manifest is in an unexpected directory")
                    elif relative in expected_files:
                        fingerprint = _fingerprint(child_path)
                        file_leases[relative] = _lease_windows_handle(
                            handle_owner, _open_delete_file(child_path, fingerprint)
                        )
                        assert file_leases[relative].handle is not None
                        if _handle_identity(file_leases[relative].handle) != expected_file_identities[relative]:
                            raise PermissionError(f"quarantine file identity changed: {relative}")
                    else:
                        raise PermissionError(f"quarantine tree contains unknown entry: {relative}")
                    seen_files.add(relative)
                else:
                    raise PermissionError(f"quarantine tree contains unknown entry: {relative}")

        open_allowed_tree(rollback, Path("."))
        if seen_directories != expected_directories:
            raise PermissionError("quarantine directories are incomplete")
        if seen_files != expected_files | {MANIFEST_NAME}:
            raise PermissionError("quarantine files are incomplete")

        marked_files: list[_WindowsHandleLease] = []
        try:
            for relative in sorted(file_leases):
                lease = file_leases[relative]
                assert lease.handle is not None
                _delete_open_handle(lease.handle)
                marked_files.append(lease)
        except Exception as error:
            cancellation_errors: list[str] = []
            for lease in reversed(marked_files):
                assert lease.handle is not None
                try:
                    _cancel_delete_open_handle(lease.handle)
                except Exception as cancellation_error:
                    cancellation_errors.append(str(cancellation_error))
            if cancellation_errors:
                raise RuntimeError(
                    f"purge precommit failed and delete disposition cancellation was incomplete: {cancellation_errors}"
                ) from error
            raise OSError(f"purge file disposition failed; quarantine preserved: {rollback}") from error

        for lease in marked_files:
            lease.close()

        for relative in sorted(expected_directories, key=lambda value: len(Path(value).parts), reverse=True):
            lease = directory_leases[relative]
            assert lease.handle is not None
            try:
                _delete_open_handle(lease.handle)
                lease.close()
            except Exception as error:
                raise OSError(f"purge directory cleanup failed; diagnostic residual: {rollback}") from error

        assert manifest_lease.handle is not None
        try:
            _delete_open_handle(manifest_lease.handle)
            manifest_lease.close()
            assert root_lease.handle is not None
            _delete_open_handle(root_lease.handle)
            root_lease.close()
        except Exception as error:
            raise OSError(f"purge root cleanup failed; diagnostic residual: {rollback}") from error

    _QUARANTINES.pop(str(rollback), None)
    return HygieneResult(result.paths, "purge", result.reasons, result.before_bytes, result.after_bytes, None, result.residual_risks)
