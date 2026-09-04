#!/usr/bin/env python3
"""Build and audit a public Skill release without touching remotes."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path


GENERATED_DIRS = {
    ".git",
    ".codex-runtime",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}
GENERATED_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
GENERATED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".bak", ".swp", ".log", ".sqlite", ".sqlite3"}
SEMANTIC_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".toml", ".txt"}
TEXT_SUFFIXES = SEMANTIC_SUFFIXES | {".cfg", ".ini", ".ps1", ".sh"}
STRUCTURAL_FILES = {"SKILL.md", "agents/openai.yaml", "agents/openai.yml"}

SECRET_PATTERNS = [
    re.compile(r"\bgh[opsu]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\b\s*[:=]\s*['\"]?[A-Za-z0-9_./+\-=]{12,}"),
]
MACHINE_PATHS = [
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.IGNORECASE),
    re.compile("/" + r"home/[^/\s]+"),
    re.compile("/" + r"Users/[^/\s]+"),
]
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_profile(path: Path | None) -> dict:
    return load_json(path) if path is not None else {}


def is_generated(relative: Path) -> bool:
    return (
        any(part in GENERATED_DIRS for part in relative.parts)
        or relative.name in GENERATED_FILES
        or relative.suffix.lower() in GENERATED_SUFFIXES
        or relative.name == ".env"
        or relative.name.startswith(".env.")
    )


def source_files(source: Path) -> list[Path]:
    return sorted(
        (path for path in source.rglob("*") if path.is_file() and not is_generated(path.relative_to(source))),
        key=lambda path: path.as_posix(),
    )


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_source_boundary(source: Path, output: Path) -> str | None:
    resolved_output = output.resolve()
    if resolved_output == source or is_within(resolved_output, source):
        return "output must be outside source"
    for path in source.rglob("*"):
        is_junction = getattr(path, "is_junction", lambda: False)()
        if path.is_symlink() or is_junction:
            return f"source contains a symbolic link or junction: {path.relative_to(source).as_posix()}"
        if not is_within(path.resolve(), source):
            return f"source entry resolves outside source: {path.relative_to(source).as_posix()}"
    return None


def referenced_semantic_files(source: Path, files: list[Path]) -> set[str]:
    relative = {path.relative_to(source).as_posix(): path for path in files}
    reachable = {name for name in STRUCTURAL_FILES if name in relative}
    reachable.add("SKILL.md")
    changed = True
    while changed:
        changed = False
        corpus = "\n".join(
            relative[name].read_text(encoding="utf-8", errors="ignore")
            for name in sorted(reachable)
            if name in relative and relative[name].suffix.lower() in SEMANTIC_SUFFIXES
        )
        for name, path in relative.items():
            if name in reachable:
                continue
            if name in corpus or path.name in corpus:
                reachable.add(name)
                changed = True
    return reachable


def unresolved_orphans(source: Path, profile: dict) -> list[str]:
    files = source_files(source)
    reachable = referenced_semantic_files(source, files)
    drop = set(profile.get("confirmed_redundant", []))
    keep = set(profile.get("keep_unreferenced", []))
    unresolved = []
    for path in files:
        name = path.relative_to(source).as_posix()
        if path.suffix.lower() not in SEMANTIC_SUFFIXES or name in STRUCTURAL_FILES:
            continue
        if name not in reachable and name not in drop and name not in keep:
            unresolved.append(name)
    return sorted(unresolved)


def build(source: Path, profile_path: Path, output: Path) -> int:
    source = source.resolve()
    profile = load_json(profile_path)
    if not (source / "SKILL.md").is_file():
        print("source does not contain SKILL.md", file=sys.stderr)
        return 3
    boundary_error = validate_source_boundary(source, output)
    if boundary_error:
        print(boundary_error, file=sys.stderr)
        return 3
    unresolved = unresolved_orphans(source, profile)
    if unresolved:
        print("unresolved semantic files: " + ", ".join(unresolved), file=sys.stderr)
        return 3
    package_name = profile["package_name"]
    target = output.resolve() / package_name
    if target.exists():
        print(f"output package already exists: {target}", file=sys.stderr)
        return 3
    target.mkdir(parents=True)
    drop = set(profile.get("confirmed_redundant", []))
    copied: dict[str, str] = {}
    excluded: list[str] = []
    for path in sorted((item for item in source.rglob("*") if item.is_file()), key=lambda p: p.as_posix()):
        relative = path.relative_to(source)
        name = relative.as_posix()
        if is_generated(relative) or name in drop:
            excluded.append(name)
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied[name] = digest(destination)
    manifest = {
        "schema_version": 1,
        "source_root": str(source),
        "package_name": package_name,
        "files": copied,
        "excluded": sorted(excluded),
        "generalization": profile.get("generalization", {}),
        "remote_mutation_performed": False,
    }
    (output / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"ok": True, "package": str(target)}, ensure_ascii=False))
    return 0


def sanitize_text(text: str, profile: dict) -> tuple[str, dict[str, int]]:
    counts = {"possible_secret": 0, "machine_specific_path": 0, "personal_email": 0, "explicit": 0}
    for pattern in SECRET_PATTERNS:
        text, count = pattern.subn("<REDACTED_SECRET>", text)
        counts["possible_secret"] += count
    for pattern in MACHINE_PATHS:
        text, count = pattern.subn("<USER_HOME>", text)
        counts["machine_specific_path"] += count
    text, counts["personal_email"] = EMAIL.subn("<YOUR_EMAIL>", text)
    for item in profile.get("redactions", []):
        find = item.get("find", "")
        if not find:
            raise ValueError("each redaction requires a non-empty 'find' value")
        replacement = item.get("replace", "<YOUR_VALUE>")
        count = text.count(find)
        text = text.replace(find, replacement)
        counts["explicit"] += count
    return text, counts


def skill_metadata(source: Path) -> tuple[str, str]:
    text = (source / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
    name_match = re.search(r"(?m)^name:\s*(.+?)\s*$", text)
    description_match = re.search(r"(?m)^description:\s*(.+?)\s*$", text)
    return (
        name_match.group(1).strip("'\"") if name_match else source.name,
        description_match.group(1).strip("'\"") if description_match else "Reusable Codex Skill.",
    )


def detected_requirements(package: Path) -> list[str]:
    requirements: list[str] = []
    python_files = sorted(package.rglob("*.py"))
    if python_files:
        requirements.append("Python source files detected; determine the supported Python version from the code")
        imports: set[str] = set()
        local_modules = {path.stem for path in python_files}
        for path in python_files:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    imports.add(node.module.split(".")[0])
        third_party = sorted(imports - set(sys.stdlib_module_names) - local_modules)
        requirements.extend(
            f"{name} (import name; verify the package/distribution name before installation)"
            for name in third_party
        )
    if (package / "package.json").is_file():
        requirements.append("Node.js (see package.json)")
    return requirements


def public_integration_requirements(profile: dict) -> list[str]:
    items: list[str] = []
    for item in profile.get("required_integrations", []):
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
            continue
        if isinstance(item, dict) and str(item.get("name", "")).strip():
            name = str(item["name"]).strip()
            requirement = str(item.get("requirement", "installation and configuration required")).strip()
            items.append(f"{name}: {requirement}")
            continue
        raise ValueError("each required_integrations entry needs a non-empty name")
    return items


def write_public_docs(package: Path, name: str, description: str, profile: dict) -> dict[str, int]:
    doc_counts = {"possible_secret": 0, "machine_specific_path": 0, "personal_email": 0, "explicit": 0}
    requirements = detected_requirements(package)
    integrations = []
    for value in public_integration_requirements(profile):
        sanitized, counts = sanitize_text(value, profile)
        integrations.append(sanitized)
        for key, count in counts.items():
            doc_counts[key] += count
    requirements.extend(f"Required integration - {item}" for item in integrations)
    requirements_text = "\n".join(f"- {item}" for item in requirements) or "- No extra runtime package was detected."
    requirements_path = package / "REQUIREMENTS.md"
    if not requirements_path.exists():
        requirements_path.write_text(
            "# Requirements\n\n"
            + requirements_text
            + "\n\nThese entries are inferred from the packaged files. Review optional desktop tools and integrations before release.\n",
            encoding="utf-8",
        )
    readme_path = package / "README.md"
    if not readme_path.exists():
        integration_section = (
            "## Integration prerequisites\n\n"
            + ("\n".join(f"- {item}" for item in integrations) if integrations else "No external application integration was declared.")
            + "\n\nFor every required integration, document the exact plugin or extension, permissions, configuration, data flow, and an end-to-end verification step.\n\n"
        )
        readme_path.write_text(
            f"# {name}\n\n{description}\n\n"
            "## Installation\n\nCopy this directory into your Codex Skills directory, then start a new task.\n\n"
            "## Usage\n\nInvoke the Skill by name or describe a task that matches its description. Review `SKILL.md` for its operating rules.\n\n"
            "## Requirements\n\nSee [REQUIREMENTS.md](REQUIREMENTS.md).\n\n"
            + integration_section
            + "## Configuration\n\nReplace public placeholders such as `<YOUR_VALUE>` with settings for your own environment. Keep credentials outside the repository.\n\n"
            "## Privacy\n\nThis package was prepared from an isolated copy. Run the included release audit again after changing local paths, identifiers, or credentials.\n",
            encoding="utf-8",
        )
    return doc_counts


def prepare(source: Path, output: Path, profile_path: Path | None) -> int:
    source = source.resolve()
    if not (source / "SKILL.md").is_file():
        print("source does not contain SKILL.md", file=sys.stderr)
        return 3
    boundary_error = validate_source_boundary(source, output)
    if boundary_error:
        print(boundary_error, file=sys.stderr)
        return 3
    profile = load_optional_profile(profile_path)
    metadata_name, description = skill_metadata(source)
    package_name = profile.get("package_name", metadata_name)
    if not isinstance(package_name, str) or not PACKAGE_NAME.fullmatch(package_name):
        print("package_name must contain only letters, digits, dot, underscore, or hyphen", file=sys.stderr)
        return 3
    target = output.resolve() / package_name
    if target.exists():
        print(f"output package already exists: {target}", file=sys.stderr)
        return 3
    target.mkdir(parents=True)
    excluded: list[str] = []
    redaction_counts = {"possible_secret": 0, "machine_specific_path": 0, "personal_email": 0, "explicit": 0}
    public_name, name_counts = sanitize_text(metadata_name, profile)
    public_description, description_counts = sanitize_text(description, profile)
    for counts in (name_counts, description_counts):
        for key, count in counts.items():
            redaction_counts[key] += count
    for path in sorted((item for item in source.rglob("*") if item.is_file()), key=lambda p: p.as_posix()):
        relative = path.relative_to(source)
        name = relative.as_posix()
        if is_generated(relative):
            excluded.append(name)
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"SKILL.md", "README.md"}:
            text = path.read_text(encoding="utf-8", errors="strict")
            try:
                sanitized, counts = sanitize_text(text, profile)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 3
            destination.write_text(sanitized, encoding="utf-8")
            for key, count in counts.items():
                redaction_counts[key] += count
        else:
            shutil.copy2(path, destination)
    try:
        doc_counts = write_public_docs(target, public_name, public_description, profile)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    for key, count in doc_counts.items():
        redaction_counts[key] += count
    copied = {
        path.relative_to(target).as_posix(): digest(path)
        for path in sorted((item for item in target.rglob("*") if item.is_file()), key=lambda p: p.as_posix())
    }
    manifest = {
        "schema_version": 1,
        "mode": "lightweight",
        "source_name": source.name,
        "package_name": package_name,
        "files": copied,
        "excluded": sorted(excluded),
        "redaction_counts": redaction_counts,
        "local_prepared": False,
        "ready_for_remote": False,
        "remote_mutation_performed": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "audit-report.json"
    result = audit(target, report_path)
    manifest["local_prepared"] = result == 0
    (output / "release-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"ok": result == 0, "package": str(target), "local_prepared": result == 0}, ensure_ascii=False))
    return result


def audit(package: Path, report_path: Path) -> int:
    blockers = []
    warnings = []
    for path in sorted((item for item in package.rglob("*") if item.is_file()), key=lambda p: p.as_posix()):
        relative = path.relative_to(package).as_posix()
        if is_generated(Path(relative)):
            blockers.append({"kind": "generated_or_private_file", "path": relative})
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                blockers.append({"kind": "possible_secret", "path": relative})
                break
        for pattern in MACHINE_PATHS:
            if pattern.search(text):
                blockers.append({"kind": "machine_specific_path", "path": relative})
                break
        emails = [value for value in EMAIL.findall(text) if not value.lower().endswith("@example.com")]
        if emails:
            blockers.append({"kind": "possible_personal_email", "path": relative})
        unfinished = ("TO" + "DO", "TB" + "D")
        if any(marker in text for marker in unfinished):
            warnings.append({"kind": "unfinished_marker", "path": relative})
    report = {"ok": not blockers, "blockers": blockers, "warnings": warnings}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not blockers else 2


def validate(release: Path) -> int:
    manifest_path = release / "release-manifest.json"
    if not manifest_path.is_file():
        print("release-manifest.json is missing", file=sys.stderr)
        return 4
    manifest = load_json(manifest_path)
    if manifest.get("mode") == "lightweight":
        print("lightweight packages must be rebuilt with the governed build workflow before remote validation", file=sys.stderr)
        return 4
    package = release / manifest["package_name"]
    report_path = release / "audit-report.json"
    if audit(package, report_path) != 0:
        print("release audit has blockers", file=sys.stderr)
        return 4
    confirmation_path = release / "publication-confirmation.json"
    if not confirmation_path.is_file():
        print("remote publication confirmation is required", file=sys.stderr)
        return 4
    confirmation = load_json(confirmation_path)
    required = {"repository", "visibility", "branch", "target_path", "license", "approved"}
    if not required.issubset(confirmation) or confirmation.get("approved") is not True:
        print("remote publication confirmation is incomplete", file=sys.stderr)
        return 4
    print(json.dumps({"ok": True, "ready_for_remote": True}, ensure_ascii=False))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="create an isolated release copy")
    build_parser.add_argument("--source", type=Path, required=True)
    build_parser.add_argument("--profile", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    prepare_parser = commands.add_parser("prepare", help="create and audit a lightweight public package")
    prepare_parser.add_argument("--source", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    prepare_parser.add_argument("--profile", type=Path)
    audit_parser = commands.add_parser("audit", help="scan a package for publication blockers")
    audit_parser.add_argument("--package", type=Path, required=True)
    audit_parser.add_argument("--report", type=Path, required=True)
    validate_parser = commands.add_parser("validate", help="run the final local publication gate")
    validate_parser.add_argument("--release", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "build":
        return build(args.source, args.profile, args.output)
    if args.command == "prepare":
        return prepare(args.source, args.output, args.profile)
    if args.command == "audit":
        return audit(args.package, args.report)
    return validate(args.release)


if __name__ == "__main__":
    raise SystemExit(main())
