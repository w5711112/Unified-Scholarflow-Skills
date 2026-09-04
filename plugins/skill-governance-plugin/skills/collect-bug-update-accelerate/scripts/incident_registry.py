from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator


SCHEMA_VERSION = 2
NOTICE_TOTAL_MAX_CHARS = 96
NOTICE_PREFIX = "【发现故障："
NOTICE_SUFFIX = "，已记录】"
NOTICE_GENERIC_SUMMARY = "工具执行失败，详细原因已写入故障库"
# capture 命中 verified 方案时的强制复用退出码：该故障不允许当新故障从头解决
REUSE_REQUIRED_EXIT = 42
# 复用结果回执格式：与故障回执【发现故障：…，已记录】同风格
REUSE_NOTICE_SUCCESS_PREFIX = "【故障的解决方案复用成功："
REUSE_NOTICE_FAILURE_PREFIX = "【故障的解决方案复用失败："
REUSE_NOTICE_SUFFIX = "】"
V2_DEFAULTS = {
    "owner_skill": "collect-bug-update-accelerate",
    "effect_contract": None,
    "diagnosis_evidence": "",
    "reuse_success_count": 0,
    "reuse_failure_count": 0,
    "promotion": "none",
    "regression_test": None,
    "last_verified_environment": None,
}
CAPTURE_DEFAULTS = {
    "root_cause": "unconfirmed",
    "known_good_solution": "unconfirmed",
    "verification": "not-yet-verified",
    "forbidden_retries": [],
    "preferred_route": "diagnose-before-retry",
    "status": "observed",
    "source_scope": "current-task",
}
BACKGROUND_ROUTE_ORDER = (
    "mcp-api-cli",
    "local-file-script",
    "app-internal-api",
    "mouse-free-uia-window-message",
    "foreground-computer-use",
)
ALLOWED_STATUSES = {
    "observed",
    "diagnosed",
    "verified",
    "promoted",
    "regressed",
    "retired",
}
SENSITIVE_KEY_FRAGMENTS = {
    "authorization",
    "clipboard",
    "conversation",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
}
REQUIRED_INCIDENT_FIELDS = {
    "id",
    "component",
    "symptom_signature",
    "root_cause",
    "known_good_solution",
    "verification",
    "forbidden_retries",
    "preferred_route",
    "environment",
    "first_seen",
    "last_seen",
    "occurrences",
    "status",
    "source_scope",
    *V2_DEFAULTS.keys(),
}

# 组件名规范化：同一底层问题必须使用同一规范组件名，否则 preflight/match
# 的精确组件匹配会断链。规范名以该族中已验证记录最多的组件为准。
#
# 两级规则：
# 1) 通用拼写归一：分隔符（. _ : / \ 空格）→ '-', 并小写。机械消除
#    apply_patch↔apply-patch、web.run open↔web-run-open、
#    searching-at-scale.sitemap-*↔searching-at-scale-sitemap-* 等拼写变体。
# 2) 显式映射 + 前缀规则：把仍属同一底层问题的碎片族归一到工具/领域级组件。
# 新增碎片族时在此登记，capture 入库与 preflight/match 查询都会自动归一。
COMPONENT_CANONICAL = {
    # Python 依赖 / user-site 沙箱可见性 → python-dependency
    "python-dependency-bootstrap": "python-dependency",
    "python-user-site-sandbox-visibility": "python-dependency",
    "python-user-site-dependency": "python-dependency",
    "python-user-site-inspection": "python-dependency",
    "powershell-user-site": "python-dependency",
    "unittest-matplotlib": "python-dependency",
    # quick_validate 校验器 → skill-creator-quick-validate
    "skill-quick-validate": "skill-creator-quick-validate",
    "skill-quick-validate-bundled-python": "skill-creator-quick-validate",
    "skill-creator-quick-validate-encoding": "skill-creator-quick-validate",
    "skill-creator-quick-validate-pyyaml": "skill-creator-quick-validate",
    "quick-validate-windows-encoding": "skill-creator-quick-validate",
    # Matplotlib 字体缓存 → matplotlib-font-cache
    "matplotlib-font-cache-permission": "matplotlib-font-cache",
    "matplotlib-font-cache-write": "matplotlib-font-cache",
    "matplotlib-cache": "matplotlib-font-cache",
    # apply_patch 分根沙箱 → apply-patch-windows-split-root-sandbox
    "apply-patch-windows-sandbox": "apply-patch-windows-split-root-sandbox",
    "apply-patch-cli-sandbox": "apply-patch-windows-split-root-sandbox",
    "apply-patch-windows-split-roots": "apply-patch-windows-split-root-sandbox",
    "apply-patch-windows-split-write-roots": "apply-patch-windows-split-root-sandbox",
    "apply-patch-windows-split-root": "apply-patch-windows-split-root-sandbox",
    "apply-patch-windows分根沙箱": "apply-patch-windows-split-root-sandbox",
    "windows-split-writable-roots-apply-patch": "apply-patch-windows-split-root-sandbox",
    # apply_patch 工具本体（通用失败，含 codex/workspace 变体）→ apply-patch
    "apply-patch-tool": "apply-patch",
    "apply-patch-command": "apply-patch",
    "apply-patch-executable": "apply-patch",
    "apply-patch-stdin": "apply-patch",
    "apply-patch-context": "apply-patch",
    "apply-patch-large-document": "apply-patch",
    "apply-patch-visualization": "apply-patch",
    "apply-patch-anchor-mismatch": "apply-patch",
    "apply-patch-cli-escalated": "apply-patch",
    "apply-patch-cmd-launcher": "apply-patch",
    "apply-patch-workspace-after-restart": "apply-patch",
    "workspace-apply-patch": "apply-patch",
    "codex-apply-patch": "apply-patch",
    "codex-apply-patch-direct": "apply-patch",
    "codex-apply-patch-escalated": "apply-patch",
    "codex-apply-patch-escalated-host": "apply-patch",
    "codex-apply-patch-local-helper": "apply-patch",
    "codex-apply-patch-workspace-helper": "apply-patch",
    "codex-apply-patch兼容工具": "apply-patch",
    # view_image 分根沙箱 → view-image-windows-split-root-sandbox
    "view-image-windows-split-writable-roots": "view-image-windows-split-root-sandbox",
    "view-image-windows-split-roots": "view-image-windows-split-root-sandbox",
    "view-image-windows-split-root": "view-image-windows-split-root-sandbox",
    "view-image-windows分根沙箱": "view-image-windows-split-root-sandbox",
    "view-image-split-root": "view-image-windows-split-root-sandbox",
    "imagegen-referenced-images-windows-split-roots": "view-image-windows-split-root-sandbox",
    "imagegen-local-edit-split-root": "view-image-windows-split-root-sandbox",
    # view_image 工具本体 → view-image
    "view-image-batch": "view-image",
    # Codex Thread API → codex-thread-api
    "codex-thread-list": "codex-thread-api",
    "codex-thread-read": "codex-thread-api",
    # 沙箱权限提升审批 → sandbox-escalation-review
    "sandbox-escalation-approval": "sandbox-escalation-review",
    # plugin-creator 校验 → plugin-creator-validate
    "plugin-creator-validate-plugin": "plugin-creator-validate",
    # firecrawl web 脚本 → firecrawl-web-script
    "firecrawl-web-script-location": "firecrawl-web-script",
    # builtin web 工具 → web-open / web-search
    "builtin-web-open-large-output": "web-open",
    "builtin-web-direct-sitemap-open": "web-open",
    "builtin-web-seed-search": "web-search",
    'bundled-python-scientific-stack': 'python-dependency',
    'bundled-python-scipy': 'python-dependency',
    'bundled-python-zip-probe': 'python-dependency',
    'bundled-python-pytest': 'python-dependency',
    'bundled-python-pytest-install': 'python-dependency',
    'codex-primary-python-scientific-stack': 'python-dependency',
    'codex-runtime-enumeration': 'python-dependency',
    'codex-app-load-workspace-dependencies': 'python-dependency',
    'codex-app-load-workspace-dependencies': 'python-dependency',
    'system-python-openpyxl': 'python-dependency',
    'system-python-pytest': 'python-dependency',
    'system-python-scientific-stack': 'python-dependency',
    'miniconda-python-pytest': 'python-dependency',
    'miniconda-sklearn-import': 'python-dependency',
    'ptfn-sklearn-import': 'python-dependency',
    'python314-pytest': 'python-dependency',
    'python314-scientific-stack': 'python-dependency',
    'python-pytest': 'python-dependency',
    'python-pytest-runtime': 'python-dependency',
    'python-test-runtime': 'python-dependency',
    'python-test-runtime-selection': 'python-dependency',
    'python-test-runner': 'python-dependency',
    'python-utf8-runtime': 'python-dependency',
    'python-diagnostic-quoting': 'python-dependency',
    'python-inline-structure-scan': 'python-dependency',
    'python-modeling-dependencies': 'python-dependency',
    'python-openpyxl-default-environment': 'python-dependency',
    'python-openpyxl-workbook-inspection': 'python-dependency',
    'python-scipy-import': 'python-dependency',
    'python-temp-directory-acl': 'python-dependency',
    'python-import': 'python-dependency',
    'pytest': 'python-dependency',
    'pytest-runtime': 'python-dependency',
    'pytest-full-workspace-tests': 'python-dependency',
    'pytest-q4-nodeid': 'python-dependency',
    'pytest-test-discovery-path': 'python-dependency',
    'pytest-zero-trace-import': 'python-dependency',
    'workspace-dependency-loader': 'python-dependency',
    'workspace-dependency-loader': 'python-dependency',
    'dependency-download': 'python-dependency',
    'dependency-extraction': 'python-dependency',
    'dependency-install': 'python-dependency',
    'conda-run': 'python-dependency',
    'uv-runtime-path-probe': 'python-dependency',
    'previous-bundled-python-relocation': 'python-dependency',
    'markdown-pytest-runtime': 'python-dependency',
    'paper-docx-pytest-runtime': 'python-dependency',
    'paper-full-pytest-bundled-runtime': 'python-dependency',
    'paper-full-pytest-import-path': 'python-dependency',
    'paper-test-runner': 'python-dependency',
    'task6-python314-paper-deps': 'python-dependency',
    'q1-tdd-pytest-runtime': 'python-dependency',
    'q2-focused-pytest': 'python-dependency',
    'q2-python-runtime': 'python-dependency',
    'q3-python-runtime': 'python-dependency',
    'q4-pytest-workbook-node-env': 'python-dependency',
    'q1-test-path-lookup': 'python-dependency',
    'task6-full-pytest-q4-node': 'python-dependency',
    'task6-full-pytest-runtime': 'python-dependency',
    'task8-pytest': 'python-dependency',
    'paper-model-combined-regression': 'python-dependency',
    'workspace-tests-q4-node': 'python-dependency',
    'pdfinfo-wrapper': 'pdf-render',
    'pdf-render-runtime-dependency': 'pdf-render',
    'pdf-render-temp': 'pdf-render',
    'pdf-render-output-persistence': 'pdf-render',
    'pdf-rasterization': 'pdf-render',
    'pdf-poppler': 'pdf-render',
    'pdf-text-extraction-surrogate': 'pdf-render',
    'pdf-text-unicode-extraction': 'pdf-render',
    'python-pdf-text-unicode': 'pdf-render',
    'python-pymupdf': 'pdf-render',
    'python-inline-pdf-extraction': 'pdf-render',
    'bundled-pdfinfo': 'pdf-render',
    'bundled-poppler-pdftotext': 'pdf-render',
    'poppler-pdftotext-path': 'pdf-render',
    'poppler-text-extraction': 'pdf-render',
    'research-pdf-download-validation': 'pdf-render',
    'system-python-pypdf': 'pdf-render',
    'bundled-python-missing-pymupdf': 'pdf-render',
    'office-rendering': 'office-docx-render',
    'office-rendering-conversion': 'office-docx-render',
    'office-rendering-preflight': 'office-docx-render',
    'office-rendering-runtime': 'office-docx-render',
    'documents-render-docx': 'office-docx-render',
    'canonical-docx-render': 'office-docx-render',
    'word-com-pdf-render': 'office-docx-render',
    'word-com-export': 'office-docx-render',
    'word-text-export-encoding': 'office-docx-render',
    'libreoffice-headless-docx-to-pdf': 'office-docx-render',
    'task6-formal-docx-canonical-render': 'office-docx-render',
    'task6-formal-docx-direct-render': 'office-docx-render',
    'docx-contract-mutation-test': 'office-docx-render',
    'apply-patch-context': 'apply-patch',
    'apply-patch-helper-script': 'apply-patch',
    'apply-patch-js-quoted-string': 'apply-patch',
    'apply-patch-js-template': 'apply-patch',
    'apply-patch-markdown-generator': 'apply-patch',
    'apply-patch-review-report': 'apply-patch',
    'apply-patch-workspace': 'apply-patch',
    'task7-brief-apply-patch': 'apply-patch',
    'bounded-context-patch-q4': 'apply-patch',
    'problem3-patch': 'apply-patch',
    'problem4-patch': 'apply-patch',
    'view-image-original': 'view-image',
    'view-image-sandbox': 'view-image',
    'view-image-unicode-path': 'view-image',
    'view-image-batch': 'view-image',
    'shell-command': 'shell-command',
    'shell-command-plugin-read': 'shell-command',
    'shell-command-skill-read': 'shell-command',
    'shell-command-workdir': 'shell-command',
    'shell-command-workspace-skill-read': 'shell-command',
    'shell-command-skill-read': 'shell-command',
    'shell-command-workspace-skill-read': 'shell-command',
    'task6-shell-workdir': 'shell-command',
    'rg': 'ripgrep',
    'rg-q3-compatibility': 'ripgrep',
    'rg-regex': 'ripgrep',
    'rg-windows-glob': 'ripgrep',
    'rg-windows-glob-path': 'ripgrep',
    'rg-workspace-query': 'ripgrep',
    'ripgrep-filesystem-search': 'ripgrep',
    'git': 'git',
    'git-context-probe': 'git',
    'git-diff-workspace': 'git',
    'git-scope-check': 'git',
    'git-status': 'git',
    'sandbox-elevated-output-visibility': 'windows-sandbox-visibility',
    'filesystem-sandbox': 'windows-sandbox-visibility',
    'pdf-contact-sheet-path': 'pdf-contact-sheet',
    'pdf-coordinate': 'pdf-coordinate',
    'pdf-annotation': 'pdf-annotation',
    'pdf-contact-sheet': 'pdf-contact-sheet',
    'pdf-render': 'pdf-render',
    'apply-patch-windows-split-root-sandbox': 'apply-patch-windows-split-root-sandbox',
    'view-image-windows-split-root-sandbox': 'view-image-windows-split-root-sandbox',
    'sandbox-escalation-review': 'sandbox-escalation-review',
    'sandbox-cleanup-review': 'sandbox-cleanup-review',
    'search-timeline-renderer': 'search-timeline-renderer',
}

# 前缀族规则：以该前缀开头的组件归一到工具/领域级组件（作用于拼写归一之后）。
COMPONENT_PREFIX_CANONICAL = (
    ("web-run-", "web-run"),
    ("web-open-", "web-open"),
    ("web-search-", "web-search"),
    ("web-arxiv-", "web-arxiv-fetch"),
    ("search-timeline-", "search-timeline-renderer"),
    ("functions-exec-output-", "functions-exec-output"),
    ("powershell-", "powershell"),
    ("unittest-", "unittest"),
    ("pdf-", "pdf-render"),
    ("pdfinfo-", "pdf-render"),
    ("poppler-", "pdf-render"),
    ("office-", "office-docx-render"),
    ("documents-render-", "office-docx-render"),
    ("word-", "office-docx-render"),
    ("libreoffice-", "office-docx-render"),
    ("contact-sheet-", "pdf-contact-sheet"),
    ("shell-", "shell-command"),
    ("rg-", "ripgrep"),
    ("ripgrep-", "ripgrep"),
    ("git-", "git"),
    ("pytest-", "python-dependency"),
    ("python-", "python-dependency"),
)


def _normalize_component_name(name: str) -> str:
    return re.sub(r"[._:/\\\s]+", "-", name.lower()).strip("-")


def canonical_component(component: str) -> str:
    """返回规范化组件名：先归一拼写（分隔符→'-'、小写），再按显式映射与
    前缀规则归一到工具/领域级组件。未登记组件返回归一化拼写。"""
    name = str(component or "").strip()
    if not name:
        return name
    normalized = _normalize_component_name(name)
    if normalized in COMPONENT_CANONICAL:
        return COMPONENT_CANONICAL[normalized]
    for prefix, canonical in COMPONENT_PREFIX_CANONICAL:
        if normalized.startswith(prefix):
            return canonical
    return normalized


class RetryBlockedError(RuntimeError):
    """Raised when a known failed route would be repeated unchanged."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_signature(text: str) -> str:
    value = str(text).strip().lower()
    value = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "<uuid>",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:z|[+-]\d{2}:\d{2})?\b",
        "<timestamp>",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\bline\s+\d+\b", "line <n>", value)
    value = re.sub(
        r"\b(run|tmp|temp|pid|process|attempt|retry)([-_ ]+)\d+\b",
        r"\1\2<n>",
        value,
    )
    value = re.sub(r"\s+", " ", value)
    return value


def _contains_cjk(text: str) -> bool:
    return re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text) is not None


def _classify_notice_summary(component: str, symptom: str) -> str:
    signature = normalize_signature(f"{component} {symptom}")
    if (
        "apply_patch" in signature
        or "apply-patch" in signature
        or ("patch" in signature and "sandbox" in signature)
    ):
        return "补丁工具无法准备当前 Windows 工作区"
    if "powershell" in signature and any(
        keyword in signature for keyword in ("pipeline", "pipe", "input")
    ):
        return "PowerShell 管道输入处理失败"
    if any(
        keyword in signature
        for keyword in ("browser", "bing", "navigation")
    ):
        return "浏览器无法打开 Bing 搜索页面"
    if any(
        keyword in signature
        for keyword in ("path", "directory", "file not found", "not found")
    ):
        return "文件或目录路径不正确"
    if any(
        keyword in signature
        for keyword in ("permission", "access denied", "sandbox")
    ):
        return "当前操作受到权限或沙箱限制"
    if any(
        keyword in signature
        for keyword in ("test", "validation", "assertion")
    ):
        return "测试或结果验证未通过"
    if any(
        keyword in signature
        for keyword in ("network", "timeout", "dns")
    ):
        return "网络连接或外部服务访问失败"
    if any(
        keyword in signature
        for keyword in (
            "python",
            "yaml",
            "pyyaml",
            "matplotlib",
            "fitz",
            "pymupdf",
            "user-site",
            "dependency",
            "site-package",
        )
    ):
        return "Python 依赖缺失或沙箱不可见"
    if "zotero" in signature:
        return "Zotero 操作失败"
    if any(
        keyword in signature
        for keyword in ("thread", "list_threads", "read_thread")
    ):
        return "Codex 线程接口调用失败"
    if any(
        keyword in signature
        for keyword in ("ocr", "vision", "image", "figure", "截图", "图像")
    ):
        return "图像或截图读取失败"
    if any(
        keyword in signature
        for keyword in ("ripgrep", "rg regex", "rg-")
    ):
        return "ripgrep 检索表达式失败"
    if any(
        keyword in signature
        for keyword in ("git ", "repo", "worktree")
    ):
        return "Git 仓库或工作区状态异常"
    return NOTICE_GENERIC_SUMMARY


def _normalize_notice_summary(
    value: str | None,
    *,
    component: str,
    symptom: str,
) -> str:
    max_summary_chars = (
        NOTICE_TOTAL_MAX_CHARS - len(NOTICE_PREFIX) - len(NOTICE_SUFFIX)
    )
    if value is not None:
        summary = re.sub(r"\s+", " ", str(value)).strip()
        if _contains_cjk(summary) and len(summary) <= max_summary_chars:
            return summary

    summary = _classify_notice_summary(component, symptom)
    if not _contains_cjk(summary) or len(summary) > max_summary_chars:
        raise AssertionError("fixed Chinese notice summary exceeds its contract")
    return summary


def _normalize_reuse_notice_summary(
    value: str | None,
    *,
    component: str,
    symptom: str,
    success: bool,
) -> str:
    """生成复用结果回执摘要，格式为「xx 方法解决 xx 问题」；可显式提供中文摘要。"""
    prefix = REUSE_NOTICE_SUCCESS_PREFIX if success else REUSE_NOTICE_FAILURE_PREFIX
    max_summary_chars = NOTICE_TOTAL_MAX_CHARS - len(prefix) - len(REUSE_NOTICE_SUFFIX)
    if value is not None:
        summary = re.sub(r"\s+", " ", str(value)).strip()
        if _contains_cjk(summary) and len(summary) <= max_summary_chars:
            return summary
    problem = _classify_notice_summary(component, symptom)
    summary = (
        f"已验证方案解决{problem}" if success else f"已验证方案未能解决{problem}"
    )
    if not _contains_cjk(summary) or len(summary) > max_summary_chars:
        raise AssertionError("fixed Chinese reuse notice summary exceeds its contract")
    return summary


def incident_id(
    component: str,
    symptom_signature: str,
    environment_scope: str | dict[str, Any] = "",
) -> str:
    if isinstance(environment_scope, dict):
        scope = json.dumps(
            environment_scope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        scope = str(environment_scope)
    payload = "\n".join(
        (
            component.strip().lower(),
            normalize_signature(symptom_signature),
            scope.strip().lower(),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def empty_registry(now: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now or _now_iso(),
        "incidents": [],
    }


def normalize_capture_input(incident: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(incident)
    component = canonical_component(result.get("component", ""))
    symptom = str(result.get("symptom_signature", "")).strip()
    if not component:
        raise ValueError("capture requires a non-empty component")
    if not symptom:
        raise ValueError("capture requires a non-empty symptom_signature")
    environment = result.get("environment", {})
    if not isinstance(environment, dict):
        raise ValueError("capture environment must be an object")
    result["component"] = component
    result["symptom_signature"] = symptom
    result["environment"] = copy.deepcopy(environment)
    for key, value in CAPTURE_DEFAULTS.items():
        result.setdefault(key, copy.deepcopy(value))
    return result


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _contains_sensitive_key(value: Any) -> str | None:
    for key in _walk_keys(value):
        normalized = re.sub(r"[^a-z]", "", key.lower())
        for fragment in SENSITIVE_KEY_FRAGMENTS:
            if fragment in normalized:
                return key
    return None


def _validate_incident(incident: dict[str, Any]) -> None:
    missing = REQUIRED_INCIDENT_FIELDS - set(incident)
    if missing:
        raise ValueError(f"incident missing fields: {sorted(missing)}")
    sensitive_key = _contains_sensitive_key(incident)
    if sensitive_key:
        raise ValueError(f"sensitive field is forbidden: {sensitive_key}")
    if not isinstance(incident["environment"], dict):
        raise ValueError("incident environment must be an object")
    expected_id = incident_id(
        incident["component"],
        incident["symptom_signature"],
        incident["environment"],
    )
    if incident["id"] != expected_id:
        raise ValueError(
            f"noncanonical incident id: expected {expected_id}, got {incident['id']}"
        )
    if incident["status"] not in ALLOWED_STATUSES:
        raise ValueError(f"invalid incident status: {incident['status']}")
    if incident["status"] in {"verified", "promoted"} and not str(
        incident["verification"]
    ).strip():
        raise ValueError("verified incident requires verification evidence")
    if incident["promotion"] not in {"none", "eligible", "applied", "rolled_back"}:
        raise ValueError(f"invalid promotion state: {incident['promotion']}")
    for field in ("reuse_success_count", "reuse_failure_count"):
        if not isinstance(incident[field], int) or incident[field] < 0:
            raise ValueError(f"{field} must be a non-negative integer")
    if incident["effect_contract"] is not None and not isinstance(
        incident["effect_contract"], dict
    ):
        raise ValueError("effect_contract must be null or an object")
    if incident.get("quality_guard") is not None:
        guard = incident["quality_guard"]
        if not isinstance(guard, dict):
            raise ValueError("quality_guard must be null or an object")
        if not isinstance(guard.get("preserve_output_fidelity"), str) or not guard[
            "preserve_output_fidelity"
        ].strip():
            raise ValueError(
                "quality_guard.preserve_output_fidelity must be a non-empty string"
            )
        if not isinstance(guard.get("forbidden_downgrade_routes"), list) or not all(
            isinstance(item, str) for item in guard.get("forbidden_downgrade_routes", [])
        ):
            raise ValueError(
                "quality_guard.forbidden_downgrade_routes must be a list of strings"
            )
    if not isinstance(incident["forbidden_retries"], list):
        raise ValueError("forbidden_retries must be a list")
    if not isinstance(incident["occurrences"], int) or incident["occurrences"] < 1:
        raise ValueError("occurrences must be a positive integer")
    if incident["source_scope"] not in {
        "current-task",
        "same-project-history",
        "runtime-discovery",
    }:
        raise ValueError(f"invalid source_scope: {incident['source_scope']}")


def validate_registry(registry: dict[str, Any]) -> None:
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version: {registry.get('schema_version')}"
        )
    if not isinstance(registry.get("updated_at"), str):
        raise ValueError("updated_at must be a string")
    incidents = registry.get("incidents")
    if not isinstance(incidents, list):
        raise ValueError("incidents must be a list")
    seen: set[str] = set()
    for incident in incidents:
        if not isinstance(incident, dict):
            raise ValueError("every incident must be an object")
        _validate_incident(incident)
        if incident["id"] in seen:
            raise ValueError(f"duplicate incident id: {incident['id']}")
        seen.add(incident["id"])


def migrate_registry(registry: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(registry)
    version = result.get("schema_version")
    if version not in {1, SCHEMA_VERSION}:
        raise ValueError(f"unsupported schema_version: {version}")
    incidents = result.get("incidents")
    if not isinstance(incidents, list):
        raise ValueError("incidents must be a list")
    for incident in incidents:
        if not isinstance(incident, dict):
            raise ValueError("every incident must be an object")
        for key, value in V2_DEFAULTS.items():
            incident.setdefault(key, copy.deepcopy(value))
    result["schema_version"] = SCHEMA_VERSION
    validate_registry(result)
    return result


def upsert_incident(
    registry: dict[str, Any],
    incident: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or _now_iso()
    candidate = copy.deepcopy(incident)
    environment = candidate.get("environment", {})
    candidate["symptom_signature"] = normalize_signature(
        candidate.get("symptom_signature", "")
    )
    canonical_id = incident_id(
        candidate.get("component", ""),
        candidate["symptom_signature"],
        environment,
    )
    supplied_id = candidate.get("id")
    if supplied_id is not None and supplied_id != canonical_id:
        raise ValueError(
            f"noncanonical incident id: expected {canonical_id}, got {supplied_id}"
        )
    candidate["id"] = canonical_id
    candidate.setdefault("first_seen", timestamp)
    candidate["last_seen"] = timestamp
    candidate.setdefault("occurrences", 1)
    for key, value in V2_DEFAULTS.items():
        candidate.setdefault(key, copy.deepcopy(value))
    _validate_incident(candidate)

    result = migrate_registry(registry)
    existing = next(
        (
            item
            for item in result["incidents"]
            if item.get("id") == candidate["id"]
        ),
        None,
    )
    if existing is None:
        result["incidents"].append(candidate)
    else:
        if existing["status"] == "verified" and candidate["status"] == "observed":
            raise ValueError(
                "verified incident cannot return to observed; mark it regressed explicitly"
            )
        first_seen = existing["first_seen"]
        occurrences = existing["occurrences"] + 1
        existing.clear()
        existing.update(candidate)
        existing["first_seen"] = first_seen
        existing["occurrences"] = occurrences
    result["updated_at"] = timestamp
    validate_registry(result)
    return result


def _environment_score(
    incident_environment: dict[str, Any],
    requested_environment: dict[str, Any],
) -> int:
    return sum(
        1
        for key, value in requested_environment.items()
        if incident_environment.get(key) == value
    )


def match_incidents(
    registry: dict[str, Any],
    *,
    component: str,
    symptom: str,
    environment: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    registry = migrate_registry(registry)
    requested_environment = environment or {}
    normalized_component = component.strip().lower()
    normalized_symptom = normalize_signature(symptom)
    matches: list[dict[str, Any]] = []
    for incident in registry["incidents"]:
        recorded = normalize_signature(incident["symptom_signature"])
        symptom_matches = recorded in normalized_symptom or normalized_symptom in recorded
        if canonical_component(incident["component"]).lower() != canonical_component(
            normalized_component
        ).lower():
            continue
        if not symptom_matches:
            continue
        matches.append(copy.deepcopy(incident))
    matches.sort(
        key=lambda item: (
            item["status"] == "verified",
            _environment_score(item["environment"], requested_environment),
            item["last_seen"],
        ),
        reverse=True,
    )
    return matches


def _advice_from_incident(incident: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "use-verified-solution",
        "incident_id": incident["id"],
        "preferred_route": incident["preferred_route"],
        "forbidden_retries": copy.deepcopy(incident["forbidden_retries"]),
        "requires_equivalence_revalidation": incident["effect_contract"] is None,
        "quality_guard": copy.deepcopy(incident.get("quality_guard")),
        "reuse_required": True,
        "directive": (
            "命中已验证方案：必须按 preferred_route 执行，不得把可复用故障当新故障从头诊断。"
            "成功后立即调用 reuse-result --outcome success（effect_verified + verification + cleanup_complete）"
            "登记复用；失败则调用 reuse-result --outcome failure 标记回归。"
        ),
    }


def preflight(
    registry: dict[str, Any],
    *,
    component: str,
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = migrate_registry(registry)
    requested_environment = environment or {}
    candidates = [
        item
        for item in current["incidents"]
        if canonical_component(item["component"]).lower()
        == canonical_component(component).lower()
    ]
    candidates.sort(
        key=lambda item: (
            item["status"] in {"verified", "promoted"},
            _environment_score(item["environment"], requested_environment),
            item["last_seen"],
        ),
        reverse=True,
    )
    if not candidates:
        return {
            "action": "continue-without-runtime-write",
            "matches": [],
        }
    best = candidates[0]
    if best["status"] in {"verified", "promoted"}:
        advice = _advice_from_incident(best)
        advice["matches"] = copy.deepcopy(candidates)
        return advice
    return {
        "action": "minimal-read-only-probe",
        "matches": copy.deepcopy(candidates),
    }


def preflight_with_fallback(
    local_registry: dict[str, Any],
    public_registry: dict[str, Any] | None,
    *,
    component: str,
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    local_advice = preflight(
        local_registry,
        component=component,
        environment=environment,
    )
    if local_advice["action"] == "use-verified-solution":
        result = copy.deepcopy(local_advice)
        result["registry_source"] = "local"
        return result
    public_advice = None
    if public_registry is not None:
        public_advice = preflight(
            public_registry,
            component=component,
            environment=environment,
        )
        if public_advice["action"] == "use-verified-solution":
            result = copy.deepcopy(public_advice)
            result["registry_source"] = "public"
            return result
    if local_advice.get("matches"):
        result = copy.deepcopy(local_advice)
        result["registry_source"] = "local"
        return result
    if public_advice is not None and public_advice.get("matches"):
        result = copy.deepcopy(public_advice)
        result["registry_source"] = "public"
        return result
    result = copy.deepcopy(local_advice)
    result["registry_source"] = "none"
    return result


def capture_incident(
    registry: dict[str, Any],
    incident: dict[str, Any],
    *,
    now: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    timestamp = now or _now_iso()
    current = migrate_registry(registry)
    component = str(incident.get("component", "")).strip()
    symptom = str(incident.get("symptom_signature", "")).strip()
    if not component:
        raise ValueError("capture requires a non-empty component")
    if not symptom:
        raise ValueError("capture requires a non-empty symptom_signature")
    environment = incident.get("environment", {})
    if not isinstance(environment, dict):
        raise ValueError("capture environment must be an object")
    matches = match_incidents(
        current,
        component=component,
        symptom=symptom,
        environment=environment,
    )
    verified = next(
        (item for item in matches if item["status"] in {"verified", "promoted"}),
        None,
    )
    if verified is not None:
        updated = copy.deepcopy(current)
        stored = next(
            item for item in updated["incidents"] if item["id"] == verified["id"]
        )
        stored["occurrences"] += 1
        stored["last_seen"] = timestamp
        updated["updated_at"] = timestamp
        validate_registry(updated)
        return updated, _advice_from_incident(stored)
    normalized = normalize_capture_input(incident)
    updated = upsert_incident(current, normalized, now=timestamp)
    recorded_id = incident_id(
        normalized["component"],
        normalized["symptom_signature"],
        normalized["environment"],
    )
    stored = next(item for item in updated["incidents"] if item["id"] == recorded_id)
    return updated, {
        "action": "recorded-observation",
        "incident_id": stored["id"],
        "preferred_route": stored["preferred_route"],
        "forbidden_retries": copy.deepcopy(stored["forbidden_retries"]),
        "resolve_required": True,
        "directive": (
            "新故障已记录，库中无已验证方案。首次遇到即应一步到位：当场诊断→修复→"
            "实际执行并验证成功→调用 resolve 固化方案，供后续直接复用；不得只记录不解决。"
        ),
    }


def record_reuse_result(
    registry: dict[str, Any],
    *,
    incident_id: str,
    success: bool,
    effect_verified: bool,
    verification: str,
    side_effects: list[str],
    cleanup_complete: bool,
    now: str | None = None,
) -> dict[str, Any]:
    result = migrate_registry(registry)
    incident = next(
        (item for item in result["incidents"] if item["id"] == incident_id),
        None,
    )
    if incident is None:
        raise KeyError(f"incident not found: {incident_id}")
    evidence = str(verification).strip()
    if not evidence:
        raise ValueError("reuse result requires verification evidence")
    if not isinstance(side_effects, list) or not all(
        isinstance(item, str) for item in side_effects
    ):
        raise ValueError("side_effects must be a list of strings")
    if success:
        contract = incident["effect_contract"]
        if not isinstance(contract, dict):
            raise ValueError("reuse success requires an effect contract")
        if not effect_verified:
            raise ValueError("exit success does not prove equivalent effect")
        if not cleanup_complete:
            raise ValueError("reuse success requires cleanup completion")
        forbidden = set(contract.get("forbidden_side_effects", []))
        guard = incident.get("quality_guard")
        if isinstance(guard, dict):
            forbidden |= set(guard.get("forbidden_downgrade_routes", []))
        violations = sorted(forbidden.intersection(side_effects))
        if violations:
            raise ValueError(f"forbidden side effects observed: {violations}")
        incident["reuse_success_count"] += 1
        if incident["status"] == "regressed":
            incident["status"] = "verified"
    else:
        incident["reuse_failure_count"] += 1
        incident["status"] = "regressed"
    timestamp = now or _now_iso()
    incident["verification"] = evidence
    incident["last_seen"] = timestamp
    result["updated_at"] = timestamp
    validate_registry(result)
    return result


def record_promotion_result(
    registry: dict[str, Any],
    *,
    incident_id: str,
    outcome: str,
    verification: str,
    regression_test: str,
    cleanup_complete: bool,
    lightweight: bool = False,
    now: str | None = None,
) -> dict[str, Any]:
    if outcome not in {"applied", "rolled-back"}:
        raise ValueError("promotion outcome must be applied or rolled-back")
    evidence = str(verification).strip()
    test_path = str(regression_test).strip()
    if not evidence:
        raise ValueError("promotion result requires verification evidence")
    if not test_path:
        raise ValueError("promotion result requires a regression test")
    if not cleanup_complete:
        raise ValueError("promotion result requires cleanup completion")

    result = migrate_registry(registry)
    incident = next(
        (item for item in result["incidents"] if item["id"] == incident_id),
        None,
    )
    if incident is None:
        raise KeyError(f"incident not found: {incident_id}")
    if incident["status"] not in {"verified", "promoted"}:
        raise ValueError("promotion result requires a verified incident")
    if outcome == "applied" and not lightweight:
        effect_contract = incident.get("effect_contract")
        if (
            not isinstance(effect_contract, dict)
            or not str(effect_contract.get("expected_effect", "")).strip()
        ):
            raise ValueError("applied promotion requires an effect contract")

    incident["verification"] = evidence
    incident["regression_test"] = test_path
    incident["promotion"] = "applied" if outcome == "applied" else "rolled_back"
    incident["status"] = "promoted" if outcome == "applied" else "verified"
    timestamp = now or _now_iso()
    incident["last_seen"] = timestamp
    result["updated_at"] = timestamp
    validate_registry(result)
    return result


def promotion_candidates(registry: dict[str, Any]) -> list[dict[str, Any]]:
    current = migrate_registry(registry)
    return [
        copy.deepcopy(item)
        for item in current["incidents"]
        if item["status"] == "verified"
        and item["promotion"] == "none"
        and str(item["known_good_solution"]).strip()
        and str(item["known_good_solution"]).strip() != "unconfirmed"
        and str(item["verification"]).strip()
        and str(item["verification"]).strip() != "not-yet-verified"
    ]


def _canonical_parameters(parameters: dict[str, Any]) -> str:
    return json.dumps(
        parameters,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def assert_retry_allowed(
    registry: dict[str, Any],
    *,
    incident_id: str,
    route: str,
    parameters: dict[str, Any],
) -> None:
    registry = migrate_registry(registry)
    incident = next(
        (item for item in registry["incidents"] if item["id"] == incident_id),
        None,
    )
    if incident is None:
        return
    requested = _canonical_parameters(parameters)
    for forbidden in incident["forbidden_retries"]:
        if forbidden.get("route") != route:
            continue
        if _canonical_parameters(forbidden.get("parameters", {})) == requested:
            raise RetryBlockedError(
                f"unchanged retry blocked for {incident_id}: route={route}"
            )


def select_route(
    available_routes: Iterable[str],
    *,
    foreground_allowed: bool = False,
) -> str:
    available = set(available_routes)
    for route in BACKGROUND_ROUTE_ORDER:
        if route not in available:
            continue
        if route == "foreground-computer-use" and not foreground_allowed:
            raise PermissionError(
                "foreground Computer Use requires explicit permission"
            )
        return route
    raise LookupError("no supported execution route is available")


def load_registry(path: str | Path) -> dict[str, Any]:
    registry = json.loads(Path(path).read_text(encoding="utf-8"))
    return migrate_registry(registry)


def save_registry_atomic(path: str | Path, registry: dict[str, Any]) -> None:
    validate_registry(registry)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(registry, ensure_ascii=False, indent=2) + "\n"
    temporary = target.with_name(
        f".r.{os.getpid()}.{uuid.uuid4().hex[:12]}.tmp"
    )
    try:
        with temporary.open(
            mode="x",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _load_or_empty(path: Path) -> dict[str, Any]:
    return load_registry(path) if path.is_file() else empty_registry()


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@contextmanager
def registry_lock(
    path: str | Path,
    *,
    timeout_s: float = 5.0,
    stale_after_s: float = 60.0,
) -> Iterator[None]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix(target.suffix + ".lock")
    deadline = time.monotonic() + timeout_s
    acquired = False
    while not acquired:
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except (FileExistsError, PermissionError) as error:
            if isinstance(error, PermissionError) and not lock_path.exists():
                raise
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > stale_after_s:
                    payload = json.loads(lock_path.read_text(encoding="utf-8"))
                    pid = int(payload.get("pid", -1))
                    if not _pid_exists(pid):
                        lock_path.unlink()
                        continue
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for registry lock: {lock_path}")
            time.sleep(0.01)
            continue
        try:
            payload = json.dumps(
                {"pid": os.getpid(), "created_at": time.time()},
                ensure_ascii=True,
            ).encode("utf-8")
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)
        acquired = True
    try:
        yield
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def mutate_registry_atomic(
    path: str | Path,
    mutator: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    target = Path(path)
    with registry_lock(target):
        registry = _load_or_empty(target)
        updated = migrate_registry(mutator(registry))
        save_registry_atomic(target, updated)
        return updated


def _parse_environment(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"environment must be key=value: {value}")
        key, item = value.split("=", 1)
        result[key] = item
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query and update the project Codex incident registry."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("--registry", type=Path, required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--registry", type=Path, required=True)

    match = subparsers.add_parser("match")
    match.add_argument("--registry", type=Path, required=True)
    match.add_argument("--component", required=True)
    match.add_argument("--symptom", required=True)
    match.add_argument("--environment", action="append", default=[])

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--registry", type=Path, required=True)
    preflight_parser.add_argument("--fallback-registry", type=Path)
    preflight_parser.add_argument("--component", required=True)
    preflight_parser.add_argument("--environment", action="append", default=[])

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--registry", type=Path, required=True)
    capture_parser.add_argument("--incident-file", type=Path, required=True)

    capture_event_parser = subparsers.add_parser("capture-event")
    capture_event_parser.add_argument("--registry", type=Path, required=True)
    capture_event_parser.add_argument("--component", required=True)
    capture_event_parser.add_argument("--symptom", required=True)
    capture_event_parser.add_argument("--environment", action="append", default=[])
    capture_event_parser.add_argument("--route")
    capture_event_parser.add_argument("--notice-summary")

    reuse_parser = subparsers.add_parser("reuse-result")
    reuse_parser.add_argument("--registry", type=Path, required=True)
    reuse_parser.add_argument("--incident-id", required=True)
    reuse_parser.add_argument("--outcome", choices=("success", "failure"), required=True)
    reuse_parser.add_argument("--effect-verified", action="store_true")
    reuse_parser.add_argument("--verification", required=True)
    reuse_parser.add_argument("--side-effect", action="append", default=[])
    reuse_parser.add_argument("--cleanup-complete", action="store_true")
    reuse_parser.add_argument(
        "--notice-summary",
        default=None,
        help="可选中文复用回执摘要，如「本地依赖方案解决 yaml 缺失」；缺省自动生成",
    )

    candidates_parser = subparsers.add_parser("promotion-candidates")
    candidates_parser.add_argument("--registry", type=Path, required=True)

    promotion_result_parser = subparsers.add_parser("promotion-result")
    promotion_result_parser.add_argument("--registry", type=Path, required=True)
    promotion_result_parser.add_argument("--incident-id", required=True)
    promotion_result_parser.add_argument(
        "--outcome", choices=("applied", "rolled-back"), required=True
    )
    promotion_result_parser.add_argument("--verification", required=True)
    promotion_result_parser.add_argument("--regression-test", required=True)
    promotion_result_parser.add_argument("--cleanup-complete", action="store_true")
    promotion_result_parser.add_argument("--lightweight", action="store_true")

    record = subparsers.add_parser("record")
    record.add_argument("--registry", type=Path, required=True)
    record.add_argument("--incident-file", type=Path, required=True)

    retry = subparsers.add_parser("retry-check")
    retry.add_argument("--registry", type=Path, required=True)
    retry.add_argument("--incident-id", required=True)
    retry.add_argument("--route", required=True)
    retry.add_argument("--parameters-json", default="{}")

    resolve = subparsers.add_parser("resolve")
    resolve.add_argument("--registry", type=Path, required=True)
    resolve.add_argument("--incident-id", required=True)
    resolve.add_argument("--solution", required=True)
    resolve.add_argument("--verification", required=True)
    resolve.add_argument("--preferred-route", required=True)
    resolve.add_argument(
        "--quality-guard",
        default=None,
        help=(
            "quality guard JSON: {'preserve_output_fidelity': str, "
            "'forbidden_downgrade_routes': [str,...]}. 声明该方案保持的输出质量下限"
            "与禁止退回的低档路线，防止把降档路线当 verified 方案。"
        ),
    )
    resolve.add_argument(
        "--effect-contract",
        default=None,
        help=(
            "effect contract JSON: {'expected_effect': str, "
            "'forbidden_side_effects': [str,...], 'domain_semantics': bool}. "
            "reuse-result 成功需要它，缺失时复用只能走失败/回归路径。"
        ),
    )
    scan = subparsers.add_parser("scan-fragments")
    scan.add_argument("--registry", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "migrate":
        registry = mutate_registry_atomic(args.registry, lambda current: current)
        print(
            json.dumps(
                {
                    "migrated": True,
                    "incidents": len(registry["incidents"]),
                    "schema_version": registry["schema_version"],
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "validate":
        registry = load_registry(args.registry)
        print(
            json.dumps(
                {
                    "valid": True,
                    "incidents": len(registry["incidents"]),
                    "schema_version": registry["schema_version"],
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "match":
        registry = load_registry(args.registry)
        matches = match_incidents(
            registry,
            component=args.component,
            symptom=args.symptom,
            environment=_parse_environment(args.environment),
        )
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return 0

    if args.command == "preflight":
        local_registry = load_registry(args.registry)
        public_registry = (
            load_registry(args.fallback_registry)
            if args.fallback_registry is not None
            else None
        )
        advice = preflight_with_fallback(
            local_registry,
            public_registry,
            component=args.component,
            environment=_parse_environment(args.environment),
        )
        print(json.dumps(advice, ensure_ascii=False, indent=2))
        return 0

    if args.command == "scan-fragments":
        # 去碎片健康检查：库内应无"存储组件 ≠ 规范组件"的记录（新捕获已自动归一）
        registry = load_registry(args.registry)
        noncanonical = {}
        for incident in registry["incidents"]:
            c = canonical_component(incident["component"])
            if c != incident["component"]:
                noncanonical.setdefault(incident["component"], []).append(c)
        report = {
            "incidents": len(registry["incidents"]),
            "distinct_components": len({i["component"] for i in registry["incidents"]}),
            "distinct_canonical": len({canonical_component(i["component"]) for i in registry["incidents"]}),
            "noncanonical_records": sum(len(v) for v in noncanonical.values()),
            "noncanonical_components": {k: sorted(set(v)) for k, v in noncanonical.items()},
            "status": "ok" if not noncanonical else "consolidate-needed",
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.command == "promotion-candidates":
        registry = load_registry(args.registry)
        print(
            json.dumps(
                promotion_candidates(registry),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command in {"capture", "capture-event"}:
        if args.command == "capture":
            raw_incident = (
                sys.stdin.read()
                if str(args.incident_file) == "-"
                else args.incident_file.read_text(encoding="utf-8")
            )
            incident = json.loads(raw_incident)
            notice_summary = _normalize_notice_summary(
                None,
                component=str(incident.get("component", "")),
                symptom=str(incident.get("symptom_signature", "")),
            )
        else:
            notice_summary = _normalize_notice_summary(
                args.notice_summary,
                component=args.component,
                symptom=args.symptom,
            )
            incident = {
                "component": args.component,
                "symptom_signature": args.symptom,
                "environment": _parse_environment(args.environment),
            }
            if args.route and args.route.strip():
                incident["preferred_route"] = args.route.strip()
        result_holder: dict[str, Any] = {}

        def capture_mutator(registry: dict[str, Any]) -> dict[str, Any]:
            updated, advice = capture_incident(registry, incident)
            result_holder["advice"] = advice
            return updated

        updated = mutate_registry_atomic(args.registry, capture_mutator)
        recorded_id = result_holder["advice"]["incident_id"]
        stored = next(
            item for item in updated["incidents"] if item["id"] == recorded_id
        )
        conversation_notice = f"{NOTICE_PREFIX}{notice_summary}{NOTICE_SUFFIX}"
        print(
            json.dumps(
                {
                    "advice": result_holder["advice"],
                    "incident": stored,
                    "conversation_notice": conversation_notice,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if result_holder["advice"].get("action") == "use-verified-solution":
            print(
                "REUSE_REQUIRED: 此故障已有已验证方案，禁止当新故障从头解决；"
                "必须按 preferred_route 执行，成功后调用 reuse-result --outcome success 登记。",
                file=sys.stderr,
            )
            return REUSE_REQUIRED_EXIT
        return 0

    if args.command == "reuse-result":
        updated = mutate_registry_atomic(
            args.registry,
            lambda registry: record_reuse_result(
                registry,
                incident_id=args.incident_id,
                success=args.outcome == "success",
                effect_verified=args.effect_verified,
                verification=args.verification,
                side_effects=args.side_effect,
                cleanup_complete=args.cleanup_complete,
            ),
        )
        incident = next(
            item for item in updated["incidents"] if item["id"] == args.incident_id
        )
        success = args.outcome == "success"
        prefix = (
            REUSE_NOTICE_SUCCESS_PREFIX if success else REUSE_NOTICE_FAILURE_PREFIX
        )
        reuse_summary = _normalize_reuse_notice_summary(
            args.notice_summary,
            component=incident["component"],
            symptom=incident["symptom_signature"],
            success=success,
        )
        conversation_notice = f"{prefix}{reuse_summary}{REUSE_NOTICE_SUFFIX}"
        output = copy.deepcopy(incident)
        output["conversation_notice"] = conversation_notice
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    if args.command == "promotion-result":
        updated = mutate_registry_atomic(
            args.registry,
            lambda registry: record_promotion_result(
                registry,
                incident_id=args.incident_id,
                outcome=args.outcome,
                verification=args.verification,
                regression_test=args.regression_test,
                cleanup_complete=args.cleanup_complete,
                lightweight=args.lightweight,
            ),
        )
        incident = next(
            item for item in updated["incidents"] if item["id"] == args.incident_id
        )
        print(json.dumps(incident, ensure_ascii=False, indent=2))
        return 0

    if args.command == "record":
        incident = json.loads(args.incident_file.read_text(encoding="utf-8"))
        updated = mutate_registry_atomic(
            args.registry,
            lambda registry: upsert_incident(registry, incident),
        )
        recorded_id = incident_id(
            incident.get("component", ""),
            incident.get("symptom_signature", ""),
            incident.get("environment", {}),
        )
        recorded = next(
            item for item in updated["incidents"] if item["id"] == recorded_id
        )
        print(json.dumps(recorded, ensure_ascii=False, indent=2))
        return 0

    if args.command == "retry-check":
        registry = load_registry(args.registry)
        assert_retry_allowed(
            registry,
            incident_id=args.incident_id,
            route=args.route,
            parameters=json.loads(args.parameters_json),
        )
        print(json.dumps({"allowed": True}, ensure_ascii=False))
        return 0

    def resolve_incident(registry: dict[str, Any]) -> dict[str, Any]:
        incident = next(
            (
                item
                for item in registry["incidents"]
                if item["id"] == args.incident_id
            ),
            None,
        )
        if incident is None:
            raise KeyError(f"incident not found: {args.incident_id}")
        incident["known_good_solution"] = args.solution
        incident["verification"] = args.verification
        incident["preferred_route"] = args.preferred_route
        if args.quality_guard:
            try:
                incident["quality_guard"] = json.loads(args.quality_guard)
            except json.JSONDecodeError as exc:
                raise ValueError(f"quality_guard must be valid JSON: {exc}")
        if args.effect_contract:
            try:
                incident["effect_contract"] = json.loads(args.effect_contract)
            except json.JSONDecodeError as exc:
                raise ValueError(f"effect_contract must be valid JSON: {exc}")
        incident["status"] = "verified"
        incident["last_seen"] = _now_iso()
        registry["updated_at"] = incident["last_seen"]
        return registry

    updated = mutate_registry_atomic(args.registry, resolve_incident)
    incident = next(
        item for item in updated["incidents"] if item["id"] == args.incident_id
    )
    print(json.dumps(incident, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
