"""Launch Edge on an owned profile with the searching-at-scale extension loaded.

Fresh profiles have no unpacked extension installed by hand; the extension is
bundled with the skill, and Edge stable refuses to persist command-line-loaded
extensions across restarts. This launcher therefore starts Edge on the chosen
profile with ``--load-extension`` every time, gives the profile its own broker
pipe (``SEARCHING_AT_SCALE_PIPE_NAME``) so it coexists with the user's real
Edge, and leaves Edge running for the sustained driver.

Usage (from the skill root, on Windows conda Python):

    python scripts\\launch_edge_profile.py --profile <dir\\...\\edge-profile>
    python scripts\\launch_edge_profile.py --profile <dir> --replace

Exit 0 with JSON on success (pipe name, Edge PID, probe result); exit 2 on
invalid input; exit 3 when Edge/bridge could not be brought up.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


if __package__ in {None, ""}:
    skill_root = str(Path(__file__).resolve().parents[1])
    if skill_root not in sys.path:
        sys.path.insert(0, skill_root)

from scripts.domestic_marketplace_query import (
    DEFAULT_EDGE_USER_DATA_DIR,
    SAT_EDGE_PIPE_PATH_ENV,
    edge_pipe_name,
)
from scripts.edge_marketplace_query import probe_edge_background_bridge


_EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
_WSL_DRIVE = re.compile(r"^/([a-zA-Z])/")


def _to_windows_path(value: str) -> str:
    """Convert a WSL ``/mnt/c/...`` path to ``C:\\...`` (no-op on Windows)."""
    match = _WSL_DRIVE.match(value)
    if match:
        return f"{match.group(1).upper()}:\\{value[3:].replace('/', '\\')}"
    return value


def _locate_edge() -> str:
    env_edge = os.environ.get("EDGE_EXE")
    candidates = ([env_edge] if env_edge else []) + list(_EDGE_CANDIDATES)
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    raise SystemExit("msedge.exe not found; set EDGE_EXE or install Edge")


def _live_profile_pids(profile_dir: str) -> list[int]:
    """Return PIDs of msedge processes using ``profile_dir`` as user-data-dir."""
    results: list[int] = []
    try:
        output = subprocess.run(
            ["wmic", "process", "where", "name='msedge.exe'", "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
    except Exception:
        return results
    probe = _to_windows_path(profile_dir).lower()
    for line in output.splitlines():
        if "msedge.exe" not in line.lower():
            continue
        if probe not in line.lower():
            continue
        fields = line.strip().split(",")
        for field in fields:
            if field.strip().isdigit() and int(field.strip()) > 0:
                results.append(int(field.strip()))
                break
    return results


def _kill_pids(pids: list[int]) -> None:
    if not pids:
        return
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pids[0])], capture_output=True, timeout=20)
    time.sleep(2.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        default=DEFAULT_EDGE_USER_DATA_DIR,
        help="Edge user-data-dir (path must end in edge-profile)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="kill any Edge already running on this profile first",
    )
    parser.add_argument(
        "--wait-bridge",
        type=float,
        default=150.0,
        help="seconds to wait for the extension broker pipe (cold first-run can exceed 75s)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print the Edge command line",
    )
    args = parser.parse_args(argv)

    profile_dir = _to_windows_path(os.path.abspath(args.profile))
    root = Path(profile_dir)
    if root.name.lower() != "edge-profile":
        print(json.dumps({
            "ok": False,
            "category": "edge_profile_invalid",
            "detail": "profile path must end in edge-profile",
        }, ensure_ascii=False))
        return 2
    root.mkdir(parents=True, exist_ok=True)

    pipe_name = edge_pipe_name(args.profile)
    extension_dir = str(Path(__file__).resolve().parents[1] / "edge-extension")
    edge = _locate_edge()

    if args.replace:
        _kill_pids(_live_profile_pids(profile_dir))

    # Edge restores the signed-in Microsoft account, synced cookies, and
    # synced extensions into any new user-data-dir by default, which would
    # carry the same JD risk-relevant state into every "fresh" profile. A
    # dedicated owned profile must be isolated: disable sync so the profile
    # stays anonymous and never restores the prior session.
    cmd = [
        edge,
        f"--user-data-dir={profile_dir}",
        "--remote-debugging-port=0",
        "--remote-debugging-address=127.0.0.1",
        f"--load-extension={_to_windows_path(extension_dir)}",
        "--enable-unsafe-extension-debugging",
        "--enable-features=LoadExtensionCommandLineSwitch",
        "--remote-allow-origins=*",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-minimized",
        "about:blank",
    ]
    if args.verbose:
        print("CMD: " + " ".join(f'"{part}"' if " " in part else part for part in cmd))

    # Set the pipe override on this launcher process too, so the bridge probe
    # (probe_edge_background_bridge reads SAT_EDGE_PIPE_PATH from os.environ)
    # targets the same custom pipe the Edge child's native host will serve.
    if pipe_name:
        os.environ["SEARCHING_AT_SCALE_PIPE_NAME"] = pipe_name
        os.environ[SAT_EDGE_PIPE_PATH_ENV] = rf"\\.\pipe\{pipe_name}"
    else:
        os.environ.pop("SEARCHING_AT_SCALE_PIPE_NAME", None)
        os.environ.pop(SAT_EDGE_PIPE_PATH_ENV, None)
    env = os.environ.copy()

    creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        child = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            close_fds=True,
            env=env,
            creationflags=creationflags,
        )
    except OSError as error:
        print(json.dumps({
            "ok": False,
            "category": "edge_spawn_failed",
            "detail": str(error),
        }, ensure_ascii=False))
        return 3

    # Cold starts (fresh profile, Edge first-run) can take well over a minute
    # before the extension loads and the native host owns the pipe. Probe in a
    # short retry loop instead of one long blocking wait.
    deadline = time.time() + args.wait_bridge
    result = None
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            result = probe_edge_background_bridge(min(20.0, max(5.0, deadline - time.time())))
            break
        except Exception as error:
            last_error = error
            time.sleep(4.0)
    if result is None:
        detail = getattr(last_error, "detail", None) or getattr(last_error, "category", None) or "bridge timeout"
        print(json.dumps({
            "ok": False,
            "category": "edge_bridge_unavailable",
            "pipe": rf"\\.\pipe\{pipe_name}" if pipe_name else None,
            "edge_pid": child.pid,
            "detail": str(detail),
        }, ensure_ascii=False))
        return 3

    print(json.dumps({
        "ok": True,
        "profile": profile_dir,
        "pipe": result.get("pipe"),
        "edge_pid": child.pid,
        "probe": result,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
