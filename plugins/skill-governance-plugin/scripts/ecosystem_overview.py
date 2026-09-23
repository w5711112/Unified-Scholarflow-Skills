from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


AUTO_BEGIN = "<!-- ECOSYSTEM:AUTO:BEGIN -->"
AUTO_END = "<!-- ECOSYSTEM:AUTO:END -->"
CARD_RE = re.compile(
    r"<!-- ECOSYSTEM:SKILL id=([^\s]+) source_sha256=([0-9a-f]{64}) -->"
)
GUIDE_RE = re.compile(
    r"<!-- ECOSYSTEM:GUIDE id=([^\s]+) source_sha256=([0-9a-f]{64}) -->"
)


@dataclass(frozen=True)
class OverviewFinding:
    code: str
    component_id: str
    message: str


def load_registry(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("ecosystem registry schema_version must be 1")
    return data


def _component_path(component: dict[str, object], data: dict[str, object]) -> Path:
    root_id = str(component["root"])
    roots = data.get("roots")
    if not isinstance(roots, dict) or root_id not in roots:
        raise ValueError("OVERVIEW_ROOT_UNKNOWN")
    root = Path(str(roots[root_id]["path"])).resolve()
    result = (root / str(component["relative_path"])).resolve()
    if result != root and root not in result.parents:
        raise ValueError("OVERVIEW_PATH_OUTSIDE_ROOT")
    return result


def _semantic_files(source: Path) -> list[Path]:
    files = [source / "SKILL.md"]
    references = source / "references"
    if references.is_dir():
        files.extend(path for path in references.rglob("*") if path.is_file())
    return sorted(path for path in files if path.is_file())


def source_tree_sha256(
    component: dict[str, object], data: dict[str, object]
) -> str:
    source = _component_path(component, data)
    files = _semantic_files(source)
    if source / "SKILL.md" not in files:
        raise FileNotFoundError(source / "SKILL.md")
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(source).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def resolve_overview_path(registry_path: Path) -> Path:
    data = load_registry(registry_path)
    config = data.get("overview")
    return _resolve_vault_relative_path(data, config, "OVERVIEW")


def _resolve_vault_relative_path(
    data: dict[str, object], config: object, label: str
) -> Path:
    if not isinstance(config, dict):
        raise ValueError(f"{label}_CONFIG_MISSING")
    root_id = str(config.get("anchor_root", ""))
    roots = data.get("roots")
    if not isinstance(roots, dict) or root_id not in roots:
        raise ValueError(f"{label}_ANCHOR_UNKNOWN")
    marker = str(config.get("vault_marker", ".obsidian"))
    relative = Path(str(config.get("relative_path", "")))
    if not relative.name or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label}_PATH_INVALID")
    anchor = Path(str(roots[root_id]["path"])).resolve()
    for candidate in (anchor, *anchor.parents):
        if (candidate / marker).is_dir():
            return candidate / relative
    raise FileNotFoundError(marker)


def resolve_guides_root(registry_path: Path) -> Path:
    data = load_registry(registry_path)
    return _resolve_vault_relative_path(data, data.get("guides"), "GUIDES")


def _active_skills(data: dict[str, object]) -> list[dict[str, object]]:
    components = data.get("components")
    if not isinstance(components, list):
        raise ValueError("OVERVIEW_COMPONENTS_INVALID")
    return sorted(
        (
            item for item in components
            if isinstance(item, dict)
            and item.get("kind") == "skill"
            and item.get("status") == "active"
        ),
        key=lambda item: str(item["id"]),
    )


def render_generated_block(data: dict[str, object]) -> str:
    active = _active_skills(data)
    lines = [
        "<!-- 由 skillctl.py sync-overview 更新，不要手工编辑此区 -->",
        "",
        "### 当前活动 Skill",
        "",
        "| 组件 ID | 版本 | 权威根 |",
        "| --- | --- | --- |",
    ]
    for item in active:
        lines.append(f"| `{item['id']}` | `{item['version']}` | `{item['root']}` |")
    edges = sorted(
        (str(provider), str(item["id"]))
        for item in active
        for provider in item.get("requires", [])
    )
    lines.extend(["", "### 稳定协作关系", "", "```mermaid", "flowchart LR"])
    if edges:
        lines.extend(f"    {provider} --> {consumer}" for provider, consumer in edges)
    else:
        lines.append("    isolated[暂无依赖边]")
    lines.append("```")
    if data.get("overview", {}).get("source_roles"):
        lines.extend(["", "### 当前源文件职责入口", "", "以下触发说明逐字取自当前 SKILL.md；完整规则、输入输出及边界见对应完整指南。"])
        for item in active:
            payload = (_component_path(item, data) / "SKILL.md").read_text(encoding="utf-8")
            match = re.search(r"(?m)^description:\s*(.*)$", payload)
            description = match.group(1).strip() if match else "参见完整指南中的入口说明。"
            if description in {"|", ">", "|-", ">-"}:
                tail = payload[match.end():].splitlines()
                block = []
                for line in tail:
                    if not line.strip() and not block:
                        continue
                    if not line.startswith((" ", "\t")):
                        break
                    block.append(line.strip())
                description = " ".join(block)
            short = str(item["id"]).split(".")[-1]
            directory = data["guides"]["owner_directories"][item["owner"]]
            lines.extend(["", f"#### {short}", "", description, "", f"[[Skill完整指南/{directory}/{short}-完整指南|完整规则与全部参考]]"])
    return "\n".join(lines)


def _replace_auto_block(text: str, generated: str) -> str:
    if text.count(AUTO_BEGIN) != 1 or text.count(AUTO_END) != 1:
        raise ValueError("OVERVIEW_AUTO_MARKERS_INVALID")
    before, tail = text.split(AUTO_BEGIN, 1)
    _, after = tail.split(AUTO_END, 1)
    return f"{before}{AUTO_BEGIN}\n{generated.rstrip()}\n{AUTO_END}{after}"


def sync_overview(registry_path: Path) -> dict[str, object]:
    data = load_registry(registry_path)
    note = resolve_overview_path(registry_path)
    current = note.read_text(encoding="utf-8")
    updated = _replace_auto_block(current, render_generated_block(data))
    if updated == current:
        return {"path": str(note), "component_count": len(_active_skills(data)), "changed": False}
    temporary = note.with_name(f".{note.name}.next")
    temporary.write_text(updated, encoding="utf-8", newline="\n")
    temporary.replace(note)
    return {"path": str(note), "component_count": len(_active_skills(data)), "changed": True}


def _guide_path(
    guides_root: Path,
    component: dict[str, object],
    config: dict[str, object],
) -> Path:
    owner_directories = config.get("owner_directories")
    owner = str(component.get("owner", ""))
    if not isinstance(owner_directories, dict) or owner not in owner_directories:
        raise ValueError("GUIDE_OWNER_DIRECTORY_UNKNOWN")
    directory = Path(str(owner_directories[owner]))
    if directory.is_absolute() or ".." in directory.parts or not directory.name:
        raise ValueError("GUIDE_OWNER_DIRECTORY_INVALID")
    short_name = str(component["id"]).split(".")[-1]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", short_name):
        raise ValueError("GUIDE_COMPONENT_NAME_INVALID")
    return guides_root / directory / f"{short_name}-完整指南.md"


FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})")
INLINE_LINK_RE = re.compile(r"(!?)\[([^\]]+)\]\(([^)]+)\)")


def _rewrite_source_links(
    payload: str,
    path: Path,
    source: Path,
    semantic: dict[Path, str],
    strict: bool = False,
) -> str:
    def replace(match: re.Match[str]) -> str:
        image_prefix, label, raw_target = match.groups()
        target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
        if not target or target.startswith("#") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
            return match.group(0)
        path_part = target.split("#", 1)[0]
        candidate = (path.parent / path_part).resolve()
        if candidate in semantic:
            return f"[{label}](#{semantic[candidate]})"
        if candidate.is_file():
            return f"{image_prefix}[{label}]({candidate.as_uri()})"
        if strict:
            raise ValueError(f"GUIDE_LINK_MISSING:{path}:{target}")
        prefix = "图像：" if image_prefix else ""
        return f"{prefix}{label}（源路径：`{target}`）"

    lines = payload.splitlines(keepends=True)
    out: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0

    for line in lines:
        stripped = line.rstrip("\r\n")
        if not in_fence:
            m = FENCE_RE.match(stripped)
            if m:
                in_fence = True
                fence_char = m.group(2)[0]
                fence_len = len(m.group(2))
                out.append(line)
            else:
                out.append(INLINE_LINK_RE.sub(replace, line))
        else:
            m = FENCE_RE.match(stripped)
            if m and m.group(2)[0] == fence_char and len(m.group(2)) >= fence_len:
                after_fence = stripped[m.end():].strip()
                if not after_fence:
                    in_fence = False
            out.append(line)

    return "".join(out)


def _render_source_file(
    path: Path,
    source: Path,
    semantic: dict[Path, str],
    strict: bool = False,
) -> str:
    relative = path.relative_to(source).as_posix()
    payload = path.read_text(encoding="utf-8")
    payload = _rewrite_source_links(payload, path, source, semantic, strict)
    anchor = semantic[path.resolve()]
    return f"## {relative}\n\n{anchor}\n\n{payload.rstrip()}"


def render_guide(component: dict[str, object], data: dict[str, object]) -> str:
    source = _component_path(component, data)
    digest = source_tree_sha256(component, data)
    component_id = str(component["id"])
    short_name = component_id.split(".")[-1]
    files = sorted(_semantic_files(source), key=lambda p: (p != source / "SKILL.md", p.as_posix()))
    semantic = {path.resolve(): "^source-" + hashlib.sha256(path.relative_to(source).as_posix().encode()).hexdigest()[:16] for path in files}
    parts = [
        f"# {short_name} 完整指南",
        "",
        f"<!-- ECOSYSTEM:GUIDE id={component_id} source_sha256={digest} -->",
        "",
        "> [!note] 阅读说明",
        "> 本页是权威 Skill 与其 references 的可读镜像，便于在 Obsidian 中集中查阅。真正执行时仍以权威目录中的原文件为准；请勿直接修改本页。",
        "",
        f"- 组件 ID：`{component_id}`",
        f"- 版本：`{component['version']}`",
        f"- 权威路径：`{source}`",
        f"- 语义指纹：`{digest}`",
    ]
    for path in files:
        try:
            rendered = _render_source_file(path, source, semantic, bool(data.get("guides", {}).get("strict_links")))
        except UnicodeDecodeError:
            relative = path.relative_to(source).as_posix()
            rendered = f"## {relative}\n\n该文件不是 UTF-8 文本，未嵌入正文。"
        parts.extend(["", rendered])
    return "\n".join(parts).rstrip() + "\n"


def sync_guides(
    registry_path: Path, component_ids: list[str] | None = None
) -> dict[str, object]:
    data = load_registry(registry_path)
    config = data.get("guides")
    if not isinstance(config, dict):
        raise ValueError("GUIDES_CONFIG_MISSING")
    guides_root = resolve_guides_root(registry_path)
    active = {str(item["id"]): item for item in _active_skills(data)}
    selected_ids = sorted(active) if component_ids is None else list(dict.fromkeys(component_ids))
    unknown = [component_id for component_id in selected_ids if component_id not in active]
    if unknown:
        raise ValueError(f"GUIDE_COMPONENT_UNKNOWN:{','.join(unknown)}")
    changed: list[str] = []
    unchanged: list[str] = []
    # Render every selected guide before any write; invalid links cannot leave a partial batch.
    prepared = {component_id: render_guide(active[component_id], data) for component_id in selected_ids}
    for component_id in selected_ids:
        component = active[component_id]
        guide = _guide_path(guides_root, component, config)
        rendered = prepared[component_id]
        if guide.is_file() and guide.read_text(encoding="utf-8") == rendered:
            unchanged.append(component_id)
            continue
        guide.parent.mkdir(parents=True, exist_ok=True)
        temporary = guide.with_name(f".{guide.name}.next")
        temporary.write_text(rendered, encoding="utf-8", newline="\n")
        temporary.replace(guide)
        changed.append(component_id)
    return {
        "path": str(guides_root),
        "component_count": len(selected_ids),
        "changed": changed,
        "unchanged": unchanged,
    }


def audit_guides(
    registry_path: Path, component_ids: list[str] | None = None
) -> list[OverviewFinding]:
    data = load_registry(registry_path)
    config = data.get("guides")
    if not isinstance(config, dict):
        return [OverviewFinding("GUIDES_CONFIG_MISSING", "guides", str(registry_path))]
    try:
        guides_root = resolve_guides_root(registry_path)
    except (FileNotFoundError, ValueError) as error:
        return [OverviewFinding("GUIDES_PATH_INVALID", "guides", str(error))]
    active = {str(item["id"]): item for item in _active_skills(data)}
    selected_ids = sorted(active) if component_ids is None else list(dict.fromkeys(component_ids))
    findings: list[OverviewFinding] = []
    for component_id in selected_ids:
        component = active.get(component_id)
        if component is None:
            continue
        try:
            guide = _guide_path(guides_root, component, config)
        except ValueError as error:
            findings.append(OverviewFinding(str(error), component_id, str(error)))
            continue
        if not guide.is_file():
            findings.append(OverviewFinding("GUIDE_MISSING", component_id, str(guide)))
            continue
        try:
            text = guide.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(OverviewFinding("GUIDE_NOT_UTF8", component_id, str(guide)))
            continue
        markers = GUIDE_RE.findall(text)
        own_markers = [digest for marked_id, digest in markers if marked_id == component_id]
        if not own_markers:
            findings.append(OverviewFinding("GUIDE_MARKER_MISSING", component_id, str(guide)))
            continue
        if len(markers) != 1 or len(own_markers) != 1:
            findings.append(OverviewFinding("GUIDE_MARKER_INVALID", component_id, str(guide)))
        expected_hash = source_tree_sha256(component, data)
        if any(digest != expected_hash for digest in own_markers):
            findings.append(OverviewFinding("GUIDE_SOURCE_STALE", component_id, expected_hash))
        if text != render_guide(component, data):
            findings.append(OverviewFinding("GUIDE_RENDER_DRIFT", component_id, str(guide)))
    return findings


def audit_overview(
    registry_path: Path, component_ids: list[str] | None = None
) -> list[OverviewFinding]:
    data = load_registry(registry_path)
    try:
        note = resolve_overview_path(registry_path)
    except (FileNotFoundError, ValueError) as error:
        return [OverviewFinding("OVERVIEW_PATH_INVALID", "overview", str(error))]
    if not note.is_file():
        return [OverviewFinding("OVERVIEW_MISSING", "overview", str(note))]
    text = note.read_text(encoding="utf-8")
    markers = CARD_RE.findall(text)
    active = {str(item["id"]): item for item in _active_skills(data)}
    selected_ids = sorted(active) if component_ids is None else list(dict.fromkeys(component_ids))
    expected = {component_id: active[component_id] for component_id in selected_ids if component_id in active}
    findings: list[OverviewFinding] = []
    for component_id, component in expected.items():
        matches = [digest for marked_id, digest in markers if marked_id == component_id]
        if not matches:
            findings.append(OverviewFinding("OVERVIEW_COMPONENT_MISSING", component_id, str(note)))
            continue
        if len(matches) > 1:
            findings.append(OverviewFinding("OVERVIEW_COMPONENT_DUPLICATE", component_id, str(len(matches))))
        expected_hash = source_tree_sha256(component, data)
        if any(digest != expected_hash for digest in matches):
            findings.append(OverviewFinding("OVERVIEW_SOURCE_STALE", component_id, expected_hash))
    if component_ids is None:
        for component_id, _ in markers:
            if component_id not in expected:
                findings.append(OverviewFinding("OVERVIEW_COMPONENT_UNKNOWN", component_id, str(note)))
        try:
            synchronized = _replace_auto_block(text, render_generated_block(data))
        except ValueError as error:
            findings.append(OverviewFinding("OVERVIEW_AUTO_MARKERS_INVALID", "overview", str(error)))
        else:
            if synchronized != text:
                findings.append(OverviewFinding("OVERVIEW_AUTO_DRIFT", "overview", str(note)))
    return findings
