#!/usr/bin/env python3
"""Host-neutral Edge bridge control for searching-at-scale.

Any agent runtime (Codex, Claude Code, Kimi Code, MiMo Desktop, plain shell)
can install the native messaging host, launch Edge with the bundled extension,
and probe the broker named pipe. No product-specific SDK is required.

Usage:
  python scripts/edge_bridge_ctl.py status
  python scripts/edge_bridge_ctl.py install [--register-existing]
  python scripts/edge_bridge_ctl.py launch --profile <dir> [--replace]
  python scripts/edge_bridge_ctl.py probe [--timeout-ms 5000]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
NATIVE_HOST_DIR = SKILL_ROOT / "native-host"
EXTENSION_DIR = SKILL_ROOT / "edge-extension"
DEFAULT_HOST_NAME = "com.codex.searching_at_scale"
DEFAULT_PIPE_NAME = "codex.searching_at_scale.v1"
EXTENSION_ID = "ackhakolgkcedgagblkfbjfnkceplcop"
REGISTRY_KEY = rf"HKCU\SOFTWARE\Microsoft\Edge\NativeMessagingHosts\{DEFAULT_HOST_NAME}"


def _json_print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _host_manifest_path() -> Path:
    return NATIVE_HOST_DIR / f"{DEFAULT_HOST_NAME}.json"


def _host_exe_path() -> Path:
    return NATIVE_HOST_DIR / "SearchingAtScaleNativeHost.v2.exe"


def cmd_status() -> int:
    manifest = _host_manifest_path()
    exe = _host_exe_path()
    registry_value = None
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-ItemProperty -Path 'Registry::{REGISTRY_KEY}' -ErrorAction Stop).'(default)'",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if completed.returncode == 0:
            registry_value = completed.stdout.strip()
    except Exception as error:  # pragma: no cover - registry probe
        registry_value = f"error:{error}"

    pipe_name = os.environ.get("SEARCHING_AT_SCALE_PIPE_NAME") or DEFAULT_PIPE_NAME
    pipe_path = os.environ.get("SAT_EDGE_PIPE_PATH") or rf"\\.\pipe\{pipe_name}"
    payload = {
        "skill_root": str(SKILL_ROOT),
        "extension_dir": str(EXTENSION_DIR),
        "extension_id": EXTENSION_ID,
        "native_host_manifest": str(manifest),
        "native_host_manifest_exists": manifest.is_file(),
        "native_host_exe": str(exe),
        "native_host_exe_exists": exe.is_file(),
        "registry_key": REGISTRY_KEY,
        "registry_manifest_path": registry_value,
        "pipe_path": pipe_path,
        "pipe_name": pipe_name,
        "host_name": DEFAULT_HOST_NAME,
        "ready_for_edge_launch": bool(manifest.is_file() and exe.is_file() and registry_value),
    }
    _json_print(payload)
    return 0 if payload["ready_for_edge_launch"] else 2


def cmd_install(register_existing: bool) -> int:
    script = SKILL_ROOT / "scripts" / "install_edge_native_host.ps1"
    if not script.is_file():
        _json_print({"ok": False, "error": "install_script_missing", "path": str(script)})
        return 2
    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-RegisterExisting" if register_existing else "-Register",
    ]
    completed = subprocess.run(args, capture_output=True, text=True, timeout=120)
    try:
        parsed = json.loads(completed.stdout.strip().splitlines()[-1])
    except Exception:
        parsed = {
            "ok": False,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
            "returncode": completed.returncode,
        }
    else:
        parsed.setdefault("ok", completed.returncode == 0)
    _json_print(parsed)
    return 0 if parsed.get("ok") and completed.returncode == 0 else 3


def cmd_launch(profile: str, replace: bool) -> int:
    if not profile:
        _json_print({"ok": False, "error": "profile_required"})
        return 2
    script = SKILL_ROOT / "scripts" / "launch_edge_profile.py"
    args = [sys.executable, str(script), "--profile", profile]
    if replace:
        args.append("--replace")
    completed = subprocess.run(args, capture_output=True, text=True, timeout=180)
    text = completed.stdout.strip()
    try:
        parsed = json.loads(text.splitlines()[-1]) if text else {"ok": False}
    except Exception:
        parsed = {"ok": False, "stdout": text[-2000:], "stderr": completed.stderr[-2000:]}
    parsed.setdefault("ok", completed.returncode == 0)
    parsed.setdefault("returncode", completed.returncode)
    _json_print(parsed)
    return 0 if completed.returncode == 0 else 3


def cmd_probe(timeout_ms: int, pipe: str | None = None, profile: str | None = None) -> int:
    client = SKILL_ROOT / "scripts" / "edge_extension_client.mjs"
    node = os.environ.get("MIMO_NODE") or "node"
    args = [node, str(client), "--probe-pipe", "--timeout-ms", str(timeout_ms)]
    override = pipe or os.environ.get("SAT_EDGE_PIPE_PATH")
    if not override and profile:
        sys.path.insert(0, str(SKILL_ROOT))
        from scripts.domestic_marketplace_query import edge_pipe_path

        override = edge_pipe_path(profile)
    if override:
        args.extend(["--pipe-path", override])
    completed = subprocess.run(args, capture_output=True, text=True, timeout=max(10, timeout_ms // 500 + 15))
    text = (completed.stdout or completed.stderr).strip()
    try:
        parsed = json.loads(text.splitlines()[-1]) if text else {"ok": False}
    except Exception:
        parsed = {"ok": False, "raw": text[-2000:], "returncode": completed.returncode}
    parsed.setdefault("ok", completed.returncode == 0)
    parsed["invoked_from"] = os.environ.get("MIMO_DESKTOP") or "agent-shell"
    _json_print(parsed)
    return 0 if parsed.get("ok") is True else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Edge bridge control for any agent host")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    install = sub.add_parser("install")
    install.add_argument("--register-existing", action="store_true")
    launch = sub.add_parser("launch")
    launch.add_argument("--profile", required=True)
    launch.add_argument("--replace", action="store_true")
    probe = sub.add_parser("probe")
    probe.add_argument("--timeout-ms", type=int, default=5000)
    probe.add_argument("--pipe", default=None, help=r"\\.\pipe\<name> or bare pipe name")
    probe.add_argument("--profile", default=None, help="owned Edge profile ending in edge-profile")
    args = parser.parse_args(argv)
    if args.command == "status":
        return cmd_status()
    if args.command == "install":
        return cmd_install(args.register_existing)
    if args.command == "launch":
        return cmd_launch(args.profile, args.replace)
    if args.command == "probe":
        pipe = args.pipe
        if pipe and not pipe.startswith("\\\\.\\pipe\\"):
            pipe = rf"\\.\pipe\{pipe}"
        return cmd_probe(args.timeout_ms, pipe=pipe, profile=args.profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
