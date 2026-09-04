from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from typing import Any, Callable


IMPORT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
DISTRIBUTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
Probe = Callable[[str, str], bool]
TargetProbe = Callable[[str, str, str], bool]
Runner = Callable[[list[str]], dict[str, Any]]


def _default_probe(interpreter: str, import_name: str) -> bool:
    if interpreter == sys.executable:
        return importlib.util.find_spec(import_name) is not None
    code = (
        "import importlib.util,sys;"
        f"sys.exit(0 if importlib.util.find_spec({import_name!r}) else 1)"
    )
    completed = subprocess.run(
        [interpreter, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode == 0


def _default_runner(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _default_target_probe(
    interpreter: str, import_name: str, install_target: str
) -> bool:
    code = (
        "from importlib.machinery import PathFinder;import sys;"
        f"sys.exit(0 if PathFinder.find_spec({import_name!r},[{install_target!r}]) else 1)"
    )
    completed = subprocess.run(
        [interpreter, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode == 0


def _validate_mapping(import_name: str, distribution: str) -> None:
    if not IMPORT_NAME.fullmatch(import_name):
        raise ValueError(f"unsafe import name: {import_name!r}")
    if not distribution or not DISTRIBUTION_NAME.fullmatch(distribution):
        raise ValueError(
            f"an explicit safe distribution is required for {import_name!r}"
        )


def plan_dependencies(
    requirements: dict[str, str],
    *,
    interpreter: str = sys.executable,
    probe: Probe = _default_probe,
) -> list[dict[str, str]]:
    plan: list[dict[str, str]] = []
    for import_name, distribution in sorted(requirements.items()):
        _validate_mapping(import_name, distribution)
        present = probe(interpreter, import_name)
        plan.append(
            {
                "import_name": import_name,
                "distribution": distribution,
                "interpreter": interpreter,
                "status": "present" if present else "missing",
            }
        )
    return plan


def ensure_dependencies(
    requirements: dict[str, str],
    *,
    interpreter: str = sys.executable,
    install: bool = True,
    install_target: str | None = None,
    probe: Probe = _default_probe,
    target_probe: TargetProbe | None = None,
    runner: Runner = _default_runner,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if install_target is not None and not install_target.strip():
        raise ValueError("install_target must not be empty")
    if install_target is None:
        plan = plan_dependencies(
            requirements,
            interpreter=interpreter,
            probe=probe,
        )
    else:
        effective_target_probe = target_probe
        if effective_target_probe is None:
            if probe is _default_probe:
                effective_target_probe = _default_target_probe
            else:
                effective_target_probe = (
                    lambda current_interpreter, import_name, _target: probe(
                        current_interpreter, import_name
                    )
                )
        plan = []
        for import_name, distribution in sorted(requirements.items()):
            _validate_mapping(import_name, distribution)
            present = effective_target_probe(
                interpreter, import_name, install_target
            )
            plan.append(
                {
                    "import_name": import_name,
                    "distribution": distribution,
                    "interpreter": interpreter,
                    "status": "present" if present else "missing",
                }
            )

    for item in plan:
        result: dict[str, Any] = dict(item)
        if install_target is not None:
            result["install_target"] = install_target
        if item["status"] == "present":
            results.append(result)
            continue
        if not install:
            results.append(result)
            continue

        install_command = [
            interpreter,
            "-m",
            "pip",
            "install",
        ]
        if install_target is not None:
            install_command.extend(["--target", install_target])
        install_command.append(item["distribution"])
        install_result = runner(install_command)
        if int(install_result.get("returncode", 1)) != 0:
            raise RuntimeError(
                f"dependency install failed for {item['distribution']}: "
                f"{install_result.get('stderr', '')}"
            )

        verify_prefix = (
            f"import sys;sys.path.insert(0,{install_target!r});"
            if install_target is not None
            else ""
        )
        verify_code = (
            verify_prefix
            + "import importlib;"
            f"m=importlib.import_module({item['import_name']!r});"
            "print(getattr(m,'__version__','unknown'))"
        )
        verify_command = [interpreter, "-c", verify_code]
        verify_result = runner(verify_command)
        if int(verify_result.get("returncode", 1)) != 0:
            raise RuntimeError(
                f"dependency import verification failed for {item['import_name']}: "
                f"{verify_result.get('stderr', '')}"
            )
        if install_target is None:
            verified = probe(interpreter, item["import_name"])
        else:
            verified = effective_target_probe(
                interpreter, item["import_name"], install_target
            )
        if not verified:
            raise RuntimeError(
                f"dependency probe still fails for {item['import_name']}"
            )
        result.update(
            {
                "status": "installed",
                "install_command": install_command,
                "verify_command": verify_command,
                "version": str(verify_result.get("stdout", "")).strip()
                or "unknown",
            }
        )
        results.append(result)
    return results


def _parse_requirements(values: list[str]) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"requirement must be import=distribution: {value}")
        import_name, distribution = value.split("=", 1)
        requirements[import_name] = distribution
    return requirements


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install explicitly mapped missing Python dependencies."
    )
    parser.add_argument(
        "--require",
        action="append",
        required=True,
        help="Explicit import=distribution mapping, for example yaml=PyYAML.",
    )
    parser.add_argument("--interpreter", default=sys.executable)
    parser.add_argument(
        "--target",
        help="Explicit pip --target directory that the active interpreter can read.",
    )
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args(argv)
    results = ensure_dependencies(
        _parse_requirements(args.require),
        interpreter=args.interpreter,
        install=not args.probe_only,
        install_target=args.target,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
