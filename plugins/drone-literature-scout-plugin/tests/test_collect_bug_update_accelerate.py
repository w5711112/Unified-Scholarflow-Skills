from __future__ import annotations

import copy
import io
import json
import sys
import shutil
import threading
import uuid
import traceback
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
GOVERNANCE_ROOT = Path.home() / ".agents" / "plugins" / "sources" / "skill-governance-plugin"
ECOSYSTEM_REGISTRY = GOVERNANCE_ROOT / "ecosystem-registry.json"
SKILL_ROOT = GOVERNANCE_ROOT / "skills" / "collect-bug-update-accelerate"
SCRIPT_ROOT = SKILL_ROOT / "scripts"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "incident-registry-seed.json"
ROUTING_PATH = SKILL_ROOT / "references" / "improvement-routing.json"
PLAYBOOK_PATH = SKILL_ROOT / "references" / "known-solution-playbook.md"
RUNTIME_REGISTRY = (
    WORKSPACE_ROOT
    / "skill-with-plugin"
    / "运行数据"
    / "collect-bug-update-accelerate"
    / "incident-registry.json"
)

sys.path.insert(0, str(SCRIPT_ROOT))

from ensure_dependencies import (  # noqa: E402
    _default_runner,
    ensure_dependencies,
    plan_dependencies,
)
from promotion_audit import audit_candidate, load_routing, main as promotion_main  # noqa: E402
import incident_registry as registry_module  # noqa: E402
from incident_registry import (  # noqa: E402
    BACKGROUND_ROUTE_ORDER,
    RetryBlockedError,
    assert_retry_allowed,
    empty_registry,
    incident_id,
    load_registry,
    main as registry_main,
    match_incidents,
    normalize_signature,
    save_registry_atomic,
    select_route,
    upsert_incident,
    validate_registry,
)


@contextmanager
def writable_test_directory():
    """Use an ACL-inheriting directory; tempfile mode 0700 breaks this Windows sandbox."""
    base = Path(__file__).resolve().parent / ".tmp-collect-bug-update"
    base.mkdir(exist_ok=True)
    target = base / uuid.uuid4().hex
    target.mkdir()
    try:
        yield str(target)
    finally:
        shutil.rmtree(target)
        if not any(base.iterdir()):
            base.rmdir()


def fixture_registry() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def verified_incident() -> dict:
    return {
        "component": "powershell",
        "symptom_signature": "An empty pipe element is not allowed at line 12",
        "root_cause": "A foreach statement block was used directly as a pipeline source.",
        "known_good_solution": "Assign foreach output to an array before piping it.",
        "verification": "The corrected command exited 0 and returned all rows.",
        "forbidden_retries": [
            {
                "route": "foreach-direct-pipe",
                "parameters": {"shell": "powershell"},
            }
        ],
        "preferred_route": "array-then-pipe",
        "environment": {"os": "windows", "shell": "powershell"},
        "status": "verified",
        "source_scope": "current-task",
    }


def other_verified_incident() -> dict:
    incident = copy.deepcopy(verified_incident())
    incident["component"] = "other-component"
    incident["symptom_signature"] = "independent verified failure"
    return incident


def fixture_registry_v2() -> dict:
    return registry_module.migrate_registry(fixture_registry())


def fixture_registry_v2_with_effect_contract() -> dict:
    registry = fixture_registry_v2()
    registry["incidents"][0]["effect_contract"] = {
        "expected_effect": "execute the verified background route",
        "forbidden_side_effects": ["foreground-mouse-input"],
    }
    return registry


def observed_matching_incident() -> dict:
    incident = copy.deepcopy(fixture_registry_v2()["incidents"][0])
    incident.pop("id")
    incident["status"] = "observed"
    incident["root_cause"] = "unconfirmed"
    incident["known_good_solution"] = ""
    incident["verification"] = ""
    return incident


def promotable_incident(component: str) -> dict:
    source = verified_incident()
    source["component"] = component
    source["symptom_signature"] = f"verified {component} failure"
    incident = registry_module.migrate_registry(
        upsert_incident(empty_registry(), source)
    )["incidents"][0]
    incident["reuse_success_count"] = 2
    incident["effect_contract"] = {
        "expected_effect": "preserve the original verified outcome",
        "forbidden_side_effects": ["domain-semantic-change"],
        "domain_semantics": False,
    }
    incident["regression_test"] = "tests/test_global_acceleration_contract.py"
    return incident


class IncidentRegistryTests(unittest.TestCase):
    def test_v1_registry_migrates_idempotently_without_losing_incidents(self):
        migrate = getattr(registry_module, "migrate_registry", None)
        self.assertIsNotNone(migrate, "migrate_registry must exist")
        source = fixture_registry()
        migrated = migrate(source)
        again = migrate(migrated)
        self.assertEqual(migrated, again)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(
            {item["id"] for item in migrated["incidents"]},
            {item["id"] for item in source["incidents"]},
        )
        incident = migrated["incidents"][0]
        self.assertIn("owner_skill", incident)
        self.assertIn("effect_contract", incident)
        self.assertEqual(incident["promotion"], "none")

    def test_concurrent_mutations_preserve_both_incidents_and_remove_lock(self):
        mutate = getattr(registry_module, "mutate_registry_atomic", None)
        self.assertIsNotNone(mutate, "mutate_registry_atomic must exist")
        with writable_test_directory() as tmp:
            path = Path(tmp) / "registry.json"
            save_registry_atomic(path, empty_registry())
            barrier = threading.Barrier(2)
            errors = []

            def worker(incident):
                try:
                    barrier.wait()
                    mutate(
                        path,
                        lambda registry: upsert_incident(registry, incident),
                    )
                except Exception as exc:
                    errors.append((exc, traceback.format_exc()))

            threads = [
                threading.Thread(target=worker, args=(verified_incident(),)),
                threading.Thread(target=worker, args=(other_verified_incident(),)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(load_registry(path)["incidents"]), 2)
            self.assertFalse(path.with_suffix(path.suffix + ".lock").exists())
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_windows_permission_error_on_existing_lock_is_contention(self):
        with writable_test_directory() as tmp:
            target = Path(tmp) / "registry.json"
            lock_path = target.with_suffix(target.suffix + ".lock")
            lock_path.write_text('{"pid": 1}', encoding="utf-8")
            real_open = registry_module.os.open
            attempts = 0

            def permission_then_open(path, flags):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise PermissionError(13, "Permission denied", str(path))
                return real_open(path, flags)

            def release_existing_lock(_delay):
                lock_path.unlink()

            with patch.object(
                registry_module.os, "open", side_effect=permission_then_open
            ), patch.object(
                registry_module.time, "sleep", side_effect=release_existing_lock
            ):
                with registry_module.registry_lock(target, timeout_s=0.1):
                    self.assertTrue(lock_path.exists())
            self.assertFalse(lock_path.exists())

    def test_migrate_cli_writes_v2_and_preserves_incident_count(self):
        with writable_test_directory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(
                json.dumps(fixture_registry(), ensure_ascii=False),
                encoding="utf-8",
            )
            output = io.StringIO()
            try:
                with redirect_stdout(output):
                    result = registry_main(["migrate", "--registry", str(path)])
            except SystemExit as exc:
                self.fail(f"migrate command must exist: {exc}")
            self.assertEqual(result, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["schema_version"], 2)
            self.assertEqual(report["incidents"], 1)
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["schema_version"], 2)
            self.assertEqual(len(stored["incidents"]), 1)
            self.assertFalse(path.with_suffix(path.suffix + ".lock").exists())

    def test_preflight_is_read_only_for_unknown_component(self):
        preflight = getattr(registry_module, "preflight", None)
        self.assertIsNotNone(preflight, "preflight must exist")
        registry = fixture_registry_v2()
        before = json.dumps(registry, sort_keys=True)
        advice = preflight(
            registry,
            component="new-component",
            environment={"os": "windows"},
        )
        self.assertEqual(advice["action"], "continue-without-runtime-write")
        self.assertEqual(json.dumps(registry, sort_keys=True), before)

    def test_preflight_fallback_prefers_local_verified_solution(self):
        lookup = getattr(registry_module, "preflight_with_fallback", None)
        self.assertIsNotNone(lookup, "preflight_with_fallback must exist")
        local_incident = verified_incident()
        local_incident["preferred_route"] = "local-route"
        public_incident = verified_incident()
        public_incident["preferred_route"] = "public-route"
        local = upsert_incident(empty_registry(), local_incident)
        public = upsert_incident(empty_registry(), public_incident)
        advice = lookup(
            local,
            public,
            component="powershell",
            environment={"os": "windows"},
        )
        self.assertEqual(advice["registry_source"], "local")
        self.assertEqual(advice["preferred_route"], "local-route")

    def test_preflight_fallback_uses_public_when_local_has_no_component(self):
        lookup = getattr(registry_module, "preflight_with_fallback", None)
        self.assertIsNotNone(lookup, "preflight_with_fallback must exist")
        public = upsert_incident(empty_registry(), verified_incident())
        advice = lookup(
            empty_registry(),
            public,
            component="powershell",
            environment={"os": "windows"},
        )
        self.assertEqual(advice["registry_source"], "public")
        self.assertEqual(advice["preferred_route"], "array-then-pipe")

    def test_preflight_fallback_returns_zero_write_advice_when_none_match(self):
        lookup = getattr(registry_module, "preflight_with_fallback", None)
        self.assertIsNotNone(lookup, "preflight_with_fallback must exist")
        advice = lookup(
            empty_registry(),
            empty_registry(),
            component="unknown-component",
        )
        self.assertEqual(advice["registry_source"], "none")
        self.assertEqual(advice["action"], "continue-without-runtime-write")
        self.assertEqual(advice["matches"], [])

    def test_capture_preserves_verified_solution_and_returns_its_route(self):
        capture = getattr(registry_module, "capture_incident", None)
        self.assertIsNotNone(capture, "capture_incident must exist")
        registry = fixture_registry_v2()
        original = copy.deepcopy(registry["incidents"][0])
        updated, advice = capture(registry, observed_matching_incident())
        stored = updated["incidents"][0]
        self.assertEqual(stored["status"], "verified")
        self.assertEqual(stored["known_good_solution"], original["known_good_solution"])
        self.assertEqual(stored["occurrences"], original["occurrences"] + 1)
        self.assertEqual(advice["preferred_route"], original["preferred_route"])
        self.assertEqual(advice["forbidden_retries"], original["forbidden_retries"])

    def test_capture_accepts_minimal_new_incident_and_defaults_unknown_fields(self):
        capture = getattr(registry_module, "capture_incident", None)
        self.assertIsNotNone(capture, "capture_incident must exist")
        minimal = {
            "component": "git-context",
            "symptom_signature": "git status fails outside a repository",
            "environment": {"os": "windows"},
        }
        updated, advice = capture(
            empty_registry("2026-07-30T00:00:00+08:00"),
            minimal,
            now="2026-07-30T00:01:00+08:00",
        )
        stored = updated["incidents"][0]
        self.assertEqual(stored["status"], "observed")
        self.assertEqual(stored["root_cause"], "unconfirmed")
        self.assertEqual(stored["known_good_solution"], "unconfirmed")
        self.assertEqual(stored["verification"], "not-yet-verified")
        self.assertEqual(stored["preferred_route"], "diagnose-before-retry")
        self.assertEqual(stored["source_scope"], "current-task")
        self.assertEqual(advice["incident_id"], stored["id"])

    def test_capture_rejects_empty_component_or_symptom(self):
        capture = getattr(registry_module, "capture_incident", None)
        for incident in (
            {"component": "", "symptom_signature": "failed", "environment": {}},
            {"component": "tool", "symptom_signature": "", "environment": {}},
        ):
            with self.subTest(incident=incident), self.assertRaises(ValueError):
                capture(empty_registry(), incident)

    def test_reuse_success_requires_effect_evidence_and_cleanup(self):
        record_result = getattr(registry_module, "record_reuse_result", None)
        self.assertIsNotNone(record_result, "record_reuse_result must exist")
        registry = fixture_registry_v2_with_effect_contract()
        incident_id_value = registry["incidents"][0]["id"]
        with self.assertRaises(ValueError):
            record_result(
                registry,
                incident_id=incident_id_value,
                success=True,
                effect_verified=False,
                verification="command exited 0",
                side_effects=[],
                cleanup_complete=True,
            )

    def test_forbidden_side_effect_prevents_reuse_success(self):
        record_result = getattr(registry_module, "record_reuse_result", None)
        self.assertIsNotNone(record_result, "record_reuse_result must exist")
        registry = fixture_registry_v2_with_effect_contract()
        with self.assertRaises(ValueError):
            record_result(
                registry,
                incident_id=registry["incidents"][0]["id"],
                success=True,
                effect_verified=True,
                verification="artifact read back",
                side_effects=["foreground-mouse-input"],
                cleanup_complete=True,
            )

    def test_reuse_count_does_not_gate_promotion_candidate(self):
        record_result = getattr(registry_module, "record_reuse_result", None)
        candidates = getattr(registry_module, "promotion_candidates", None)
        self.assertIsNotNone(record_result, "record_reuse_result must exist")
        self.assertIsNotNone(candidates, "promotion_candidates must exist")
        registry = fixture_registry_v2_with_effect_contract()
        incident_id_value = registry["incidents"][0]["id"]
        self.assertEqual(len(candidates(registry)), 1)
        after_reuse = record_result(
            registry,
            incident_id=incident_id_value,
            success=True,
            effect_verified=True,
            verification="target artifact and state read back successfully",
            side_effects=[],
            cleanup_complete=True,
        )
        result = candidates(after_reuse)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], incident_id_value)
    def test_failed_reuse_marks_verified_solution_regressed(self):
        record_result = getattr(registry_module, "record_reuse_result", None)
        self.assertIsNotNone(record_result, "record_reuse_result must exist")
        registry = fixture_registry_v2_with_effect_contract()
        updated = record_result(
            registry,
            incident_id=registry["incidents"][0]["id"],
            success=False,
            effect_verified=False,
            verification="verified route failed in the current environment",
            side_effects=[],
            cleanup_complete=True,
        )
        incident = updated["incidents"][0]
        self.assertEqual(incident["status"], "regressed")
        self.assertEqual(incident["reuse_failure_count"], 1)

    def test_preflight_cli_is_read_only(self):
        with writable_test_directory() as tmp:
            path = Path(tmp) / "registry.json"
            save_registry_atomic(path, fixture_registry_v2())
            before = path.read_bytes()
            output = io.StringIO()
            try:
                with redirect_stdout(output):
                    code = registry_main(
                        [
                            "preflight",
                            "--registry",
                            str(path),
                            "--component",
                            "new-component",
                            "--environment",
                            "os=windows",
                        ]
                    )
            except SystemExit as exc:
                self.fail(f"preflight command must exist: {exc}")
            self.assertEqual(code, 0)
            self.assertEqual(
                json.loads(output.getvalue())["action"],
                "continue-without-runtime-write",
            )
            self.assertEqual(path.read_bytes(), before)

    def test_preflight_cli_reads_public_fallback_without_writing_it(self):
        with writable_test_directory() as tmp:
            local_path = Path(tmp) / "local.json"
            public_path = Path(tmp) / "public.json"
            save_registry_atomic(local_path, empty_registry())
            save_registry_atomic(
                public_path,
                upsert_incident(empty_registry(), verified_incident()),
            )
            public_before = public_path.read_bytes()
            output = io.StringIO()
            try:
                with redirect_stdout(output):
                    code = registry_main(
                        [
                            "preflight",
                            "--registry",
                            str(local_path),
                            "--fallback-registry",
                            str(public_path),
                            "--component",
                            "powershell",
                            "--environment",
                            "os=windows",
                        ]
                    )
            except SystemExit as exc:
                self.fail(f"fallback preflight must exist: {exc}")
            self.assertEqual(code, 0)
            advice = json.loads(output.getvalue())
            self.assertEqual(advice["registry_source"], "public")
            self.assertEqual(advice["preferred_route"], "array-then-pipe")
            self.assertEqual(public_path.read_bytes(), public_before)

    def test_capture_cli_preserves_verified_solution(self):
        with writable_test_directory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            incident_path = Path(tmp) / "incident.json"
            registry = fixture_registry_v2()
            original_occurrences = registry["incidents"][0]["occurrences"]
            save_registry_atomic(registry_path, registry)
            incident_path.write_text(
                json.dumps(observed_matching_incident(), ensure_ascii=False),
                encoding="utf-8",
            )
            output = io.StringIO()
            try:
                with redirect_stdout(output):
                    code = registry_main(
                        [
                            "capture",
                            "--registry",
                            str(registry_path),
                            "--incident-file",
                            str(incident_path),
                        ]
                    )
            except SystemExit as exc:
                self.fail(f"capture command must exist: {exc}")
            # 命中 verified 方案时 capture 以 REUSE_REQUIRED(42) 退出，禁止当新故障从头解决
            self.assertEqual(code, registry_module.REUSE_REQUIRED_EXIT)
            report = json.loads(output.getvalue())
            self.assertEqual(report["advice"]["action"], "use-verified-solution")
            self.assertTrue(report["advice"]["reuse_required"])
            stored = load_registry(registry_path)["incidents"][0]
            self.assertEqual(stored["status"], "verified")
            self.assertEqual(stored["occurrences"], original_occurrences + 1)

    def test_capture_event_cli_records_without_scoped_input_file(self):
        with writable_test_directory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            long_chinese_summary = (
                "实施计划已写入并通过自审，现在按用户已选的内联方式执行："
                "先让新增契约测试失败，再最小修改 Skill 与镜像；随后"
            )
            arguments = [
                "capture-event",
                "--registry",
                str(registry_path),
                "--component",
                "powershell-parser",
                "--symptom",
                "An empty pipe element is not allowed",
                "--environment",
                "shell=pwsh",
                "--route",
                "array-then-pipe",
                "--notice-summary",
                long_chinese_summary,
            ]
            output = io.StringIO()
            try:
                with redirect_stdout(output):
                    code = registry_main(arguments)
            except SystemExit as exc:
                self.fail(f"capture-event command must exist: {exc}")
            self.assertEqual(code, 0)
            report = json.loads(output.getvalue())
            stored = report["incident"]
            self.assertEqual(stored["status"], "observed")
            self.assertEqual(stored["preferred_route"], "array-then-pipe")
            self.assertEqual(stored["environment"], {"shell": "pwsh"})
            expected_notice = f"【发现故障：{long_chinese_summary}，已记录】"
            self.assertEqual(report["conversation_notice"], expected_notice)
            self.assertLessEqual(len(expected_notice), 96)
            self.assertNotIn("…", expected_notice)
            self.assertNotIn("notice_summary", stored)

            repeated_output = io.StringIO()
            with redirect_stdout(repeated_output):
                repeated_code = registry_main(arguments)
            self.assertEqual(repeated_code, 0)
            repeated = json.loads(repeated_output.getvalue())
            self.assertEqual(repeated["incident"]["id"], stored["id"])
            self.assertEqual(repeated["incident"]["occurrences"], 2)
            self.assertEqual(repeated["conversation_notice"], expected_notice)
            self.assertEqual(
                {path.name for path in Path(tmp).iterdir()},
                {"registry.json"},
            )

    def test_capture_event_legacy_or_english_notice_uses_complete_chinese_fallback(self):
        cases = (
            (
                "powershell-pipeline",
                "PowerShell pipeline input was rejected",
                None,
                "PowerShell 管道输入处理失败",
            ),
            (
                "apply-patch-windows-sandbox",
                "apply_patch could not prepare Windows sandbox",
                "apply_patch could not prepare Windows sandbox",
                "补丁工具无法准备当前 Windows 工作区",
            ),
            (
                "browser-client/bing-navigation",
                "Bing navigation failed",
                None,
                "浏览器无法打开 Bing 搜索页面",
            ),
            (
                "unknown-tool",
                "unexpected opaque error",
                None,
                "工具执行失败，详细原因已写入故障库",
            ),
        )
        for component, symptom, explicit_summary, expected_summary in cases:
            with self.subTest(component=component):
                with writable_test_directory() as tmp:
                    registry_path = Path(tmp) / "registry.json"
                    arguments = [
                        "capture-event",
                        "--registry",
                        str(registry_path),
                        "--component",
                        component,
                        "--symptom",
                        symptom,
                        "--environment",
                        "os=windows",
                        "--route",
                        "changed-route",
                    ]
                    if explicit_summary is not None:
                        arguments.extend(["--notice-summary", explicit_summary])
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = registry_main(arguments)
                    self.assertEqual(code, 0)
                    report = json.loads(output.getvalue())
                    expected_notice = f"【发现故障：{expected_summary}，已记录】"
                    self.assertEqual(report["conversation_notice"], expected_notice)
                    self.assertLessEqual(len(expected_notice), 96)
                    self.assertRegex(expected_notice, r"[\u3400-\u9fff]")
                    self.assertNotIn("…", expected_notice)
                    self.assertNotIn(component, expected_notice)
                    self.assertNotIn("notice_summary", report["incident"])

    def test_capture_event_normalizes_or_falls_back_without_blocking_write(self):
        cases = (
            ("第一行\n第二行", "第一行 第二行"),
            (
                "这是一段必须保持完整但已经超过回执总长度限制的中文问题摘要" * 4,
                "工具执行失败，详细原因已写入故障库",
            ),
        )
        for index, (notice_summary, expected_summary) in enumerate(cases):
            with self.subTest(notice_summary=notice_summary):
                with writable_test_directory() as tmp:
                    registry_path = Path(tmp) / f"registry-{index}.json"
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = registry_main(
                            [
                                "capture-event",
                                "--registry",
                                str(registry_path),
                                "--component",
                                "unknown-tool",
                                "--symptom",
                                "unexpected opaque error",
                                "--environment",
                                "os=windows",
                                "--route",
                                "changed-route",
                                "--notice-summary",
                                notice_summary,
                            ]
                        )
                    self.assertEqual(code, 0)
                    report = json.loads(output.getvalue())
                    expected_notice = f"【发现故障：{expected_summary}，已记录】"
                    self.assertEqual(report["conversation_notice"], expected_notice)
                    self.assertLessEqual(len(expected_notice), 96)
                    self.assertNotIn("\n", expected_notice)
                    self.assertNotIn("…", expected_notice)
                    self.assertTrue(registry_path.exists())

    def test_capture_cli_reads_utf8_json_from_stdin(self):
        with writable_test_directory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            payload = {
                "component": "zotero-ui",
                "symptom_signature": "未找到目标窗口",
                "environment": {"os": "windows"},
            }
            output = io.StringIO()
            try:
                with patch.object(
                    sys,
                    "stdin",
                    io.StringIO(json.dumps(payload, ensure_ascii=False)),
                ), redirect_stdout(output):
                    code = registry_main(
                        [
                            "capture",
                            "--registry",
                            str(registry_path),
                            "--incident-file",
                            "-",
                        ]
                    )
            except SystemExit as exc:
                self.fail(f"capture stdin must exist: {exc}")
            self.assertEqual(code, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["advice"]["action"], "recorded-observation")
            stored = load_registry(registry_path)["incidents"][0]
            self.assertEqual(stored["symptom_signature"], "未找到目标窗口")
            self.assertEqual(stored["status"], "observed")

    def test_reuse_result_cli_updates_verified_counter(self):
        with writable_test_directory() as tmp:
            path = Path(tmp) / "registry.json"
            registry = fixture_registry_v2_with_effect_contract()
            incident_id_value = registry["incidents"][0]["id"]
            save_registry_atomic(path, registry)
            output = io.StringIO()
            try:
                with redirect_stdout(output):
                    code = registry_main(
                        [
                            "reuse-result",
                            "--registry",
                            str(path),
                            "--incident-id",
                            incident_id_value,
                            "--outcome",
                            "success",
                            "--effect-verified",
                            "--verification",
                            "artifact and state read back",
                            "--cleanup-complete",
                        ]
                    )
            except SystemExit as exc:
                self.fail(f"reuse-result command must exist: {exc}")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["reuse_success_count"], 1)
            self.assertEqual(
                load_registry(path)["incidents"][0]["reuse_success_count"],
                1,
            )

    def test_first_verified_solution_is_immediate_temporary_candidate(self):
        registry = upsert_incident(empty_registry(), verified_incident())
        stored = registry["incidents"][0]
        self.assertEqual(stored["reuse_success_count"], 0)
        candidates = registry_module.promotion_candidates(registry)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], stored["id"])

    def test_candidate_rejects_placeholder_solution_or_verification(self):
        registry = upsert_incident(empty_registry(), verified_incident())
        stored = registry["incidents"][0]
        stored["known_good_solution"] = "unconfirmed"
        self.assertEqual(registry_module.promotion_candidates(registry), [])
        stored["known_good_solution"] = "verified background route"
        stored["verification"] = "not-yet-verified"
        self.assertEqual(registry_module.promotion_candidates(registry), [])

    def test_observed_incident_is_not_a_candidate(self):
        registry = upsert_incident(empty_registry(), observed_matching_incident())
        self.assertEqual(registry_module.promotion_candidates(registry), [])
    def test_promotion_candidates_cli_is_read_only(self):
        with writable_test_directory() as tmp:
            path = Path(tmp) / "registry.json"
            registry = fixture_registry_v2()
            self.assertEqual(registry["incidents"][0]["reuse_success_count"], 0)
            save_registry_atomic(path, registry)
            before = path.read_bytes()
            output = io.StringIO()
            try:
                with redirect_stdout(output):
                    code = registry_main(
                        ["promotion-candidates", "--registry", str(path)]
                    )
            except SystemExit as exc:
                self.fail(f"promotion-candidates command must exist: {exc}")
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(output.getvalue())), 1)
            self.assertEqual(path.read_bytes(), before)

    def test_applied_promotion_requires_regression_test_and_cleanup(self):
        registry = upsert_incident(empty_registry(), verified_incident())
        incident_id_value = registry["incidents"][0]["id"]
        with self.assertRaises(ValueError):
            registry_module.record_promotion_result(
                registry,
                incident_id=incident_id_value,
                outcome="applied",
                verification="permanent fix passed",
                regression_test="",
                cleanup_complete=True,
            )
        with self.assertRaises(ValueError):
            registry_module.record_promotion_result(
                registry,
                incident_id=incident_id_value,
                outcome="applied",
                verification="permanent fix passed",
                regression_test="tests/test_collect_bug_update_accelerate.py",
                cleanup_complete=False,
            )
        with self.assertRaises(ValueError):
            registry_module.record_promotion_result(
                registry,
                incident_id=incident_id_value,
                outcome="applied",
                verification="permanent fix passed",
                regression_test="tests/test_collect_bug_update_accelerate.py",
                cleanup_complete=True,
            )

    def test_applied_promotion_marks_incident_promoted(self):
        registry = upsert_incident(empty_registry(), verified_incident())
        registry["incidents"][0]["effect_contract"] = {
            "expected_effect": "prevent the original failure without side effects",
            "forbidden_side_effects": [],
            "domain_semantics": False,
        }
        incident_id_value = registry["incidents"][0]["id"]
        updated = registry_module.record_promotion_result(
            registry,
            incident_id=incident_id_value,
            outcome="applied",
            verification="test failed before fix and passed after fix",
            regression_test="tests/test_collect_bug_update_accelerate.py",
            cleanup_complete=True,
            now="2026-07-30T23:00:00+08:00",
        )
        stored = updated["incidents"][0]
        self.assertEqual(stored["status"], "promoted")
        self.assertEqual(stored["promotion"], "applied")
        self.assertEqual(
            stored["regression_test"],
            "tests/test_collect_bug_update_accelerate.py",
        )

    def test_lightweight_promotion_allows_missing_effect_contract(self):
        registry = upsert_incident(empty_registry(), verified_incident())
        incident_id_value = registry["incidents"][0]["id"]
        updated = registry_module.record_promotion_result(
            registry,
            incident_id=incident_id_value,
            outcome="applied",
            verification="official guidance and local effect recheck passed",
            regression_test="pwsh route smoke check",
            cleanup_complete=True,
            lightweight=True,
        )
        stored = updated["incidents"][0]
        self.assertEqual(stored["status"], "promoted")
        self.assertEqual(stored["promotion"], "applied")
        self.assertEqual(stored["regression_test"], "pwsh route smoke check")


    def test_rolled_back_promotion_never_keeps_promoted_status(self):
        registry = upsert_incident(empty_registry(), verified_incident())
        incident_id_value = registry["incidents"][0]["id"]
        updated = registry_module.record_promotion_result(
            registry,
            incident_id=incident_id_value,
            outcome="rolled-back",
            verification="original files restored and checked",
            regression_test="tests/test_collect_bug_update_accelerate.py",
            cleanup_complete=True,
            now="2026-07-30T23:00:00+08:00",
        )
        stored = updated["incidents"][0]
        self.assertEqual(stored["status"], "verified")
        self.assertEqual(stored["promotion"], "rolled_back")

    def test_promotion_result_cli_writes_exact_updated_incident(self):
        with writable_test_directory() as tmp:
            path = Path(tmp) / "registry.json"
            registry = upsert_incident(empty_registry(), verified_incident())
            registry["incidents"][0]["effect_contract"] = {
                "expected_effect": "prevent the original failure without side effects",
                "forbidden_side_effects": [],
                "domain_semantics": False,
            }
            incident_id_value = registry["incidents"][0]["id"]
            save_registry_atomic(path, registry)
            output = io.StringIO()
            try:
                with redirect_stdout(output):
                    code = registry_main(
                        [
                            "promotion-result",
                            "--registry",
                            str(path),
                            "--incident-id",
                            incident_id_value,
                            "--outcome",
                            "applied",
                            "--verification",
                            "regression test passed after permanent fix",
                            "--regression-test",
                            "tests/test_collect_bug_update_accelerate.py",
                            "--cleanup-complete",
                        ]
                    )
            except SystemExit as exc:
                self.fail(f"promotion-result command must exist: {exc}")
            self.assertEqual(code, 0)
            reported = json.loads(output.getvalue())
            stored = load_registry(path)["incidents"][0]
            self.assertEqual(reported, stored)
            self.assertEqual(stored["status"], "promoted")
            self.assertEqual(stored["promotion"], "applied")
    def test_lightweight_promotion_result_cli_passes_mode_through(self):
        with writable_test_directory() as tmp:
            path = Path(tmp) / "registry.json"
            registry = upsert_incident(empty_registry(), verified_incident())
            incident_id_value = registry["incidents"][0]["id"]
            save_registry_atomic(path, registry)
            output = io.StringIO()
            try:
                with redirect_stdout(output):
                    code = registry_main(
                        [
                            "promotion-result",
                            "--registry",
                            str(path),
                            "--incident-id",
                            incident_id_value,
                            "--outcome",
                            "applied",
                            "--verification",
                            "official guidance and local effect recheck passed",
                            "--regression-test",
                            "pwsh route smoke check",
                            "--cleanup-complete",
                            "--lightweight",
                        ]
                    )
            except SystemExit as exc:
                self.fail(f"lightweight promotion-result must exist: {exc}")
            self.assertEqual(code, 0)
            stored = load_registry(path)["incidents"][0]
            self.assertEqual(json.loads(output.getvalue()), stored)
            self.assertEqual(stored["status"], "promoted")
            self.assertEqual(stored["promotion"], "applied")


    def test_signature_normalization_removes_volatile_values(self):
        first = normalize_signature(
            "Error at C:\\tmp\\run-123\\x.py line 42, UUID "
            "019fac1c-10e7-7f73-89e9-150119e0c2cb at 2026-07-29T10:20:30"
        )
        second = normalize_signature(
            "Error at C:\\tmp\\run-999\\x.py line 87, UUID "
            "019fabcd-0000-7000-8000-000000000000 at 2026-07-30T11:22:33"
        )
        self.assertEqual(first, second)

    def test_incident_id_is_stable_for_equivalent_signatures(self):
        one = incident_id("powershell", "failure at line 12", "windows")
        two = incident_id("PowerShell", "failure at line 99", "Windows")
        self.assertEqual(one, two)

    def test_signature_preserves_semantic_numbers(self):
        self.assertNotEqual(
            normalize_signature("HTTP 401 while fetching metadata"),
            normalize_signature("HTTP 500 while fetching metadata"),
        )

    def test_incident_id_uses_sorted_complete_environment(self):
        one = incident_id(
            "zotero-run-js",
            "return not in function",
            {"os": "windows", "zotero": "9"},
        )
        reordered = incident_id(
            "zotero-run-js",
            "return not in function",
            {"zotero": "9", "os": "windows"},
        )
        different_version = incident_id(
            "zotero-run-js",
            "return not in function",
            {"os": "windows", "zotero": "8"},
        )
        self.assertEqual(one, reordered)
        self.assertNotEqual(one, different_version)

    def test_upsert_deduplicates_and_increments_occurrences(self):
        first = upsert_incident(
            empty_registry(),
            verified_incident(),
            now="2026-07-29T01:00:00+08:00",
        )
        second = upsert_incident(
            first,
            verified_incident(),
            now="2026-07-29T02:00:00+08:00",
        )
        self.assertEqual(len(second["incidents"]), 1)
        self.assertEqual(second["incidents"][0]["occurrences"], 2)
        self.assertEqual(
            second["incidents"][0]["last_seen"],
            "2026-07-29T02:00:00+08:00",
        )

    def test_match_returns_verified_environment_specific_solution_first(self):
        registry = fixture_registry()
        verified_id = registry["incidents"][0]["id"]
        observed = {
            **registry["incidents"][0],
            "status": "observed",
            "environment": {"os": "windows", "zotero": "8"},
        }
        observed["id"] = incident_id(
            observed["component"],
            observed["symptom_signature"],
            observed["environment"],
        )
        registry["incidents"].append(observed)
        matches = match_incidents(
            registry,
            component="zotero-run-js",
            symptom="SyntaxError: return not in function",
            environment={"os": "windows", "zotero": "9"},
        )
        self.assertEqual(matches[0]["id"], verified_id)
        self.assertEqual(matches[0]["status"], "verified")

    def test_retry_guard_rejects_unchanged_failed_route(self):
        with self.assertRaises(RetryBlockedError):
            assert_retry_allowed(
                fixture_registry(),
                incident_id=fixture_registry()["incidents"][0]["id"],
                route="stale-codemirror-setvalue",
                parameters={"async": False},
            )

    def test_retry_guard_allows_changed_route(self):
        assert_retry_allowed(
            fixture_registry(),
            incident_id=fixture_registry()["incidents"][0]["id"],
            route="fresh-window-wm-paste-async-toggle",
            parameters={"async": True},
        )

    def test_background_route_is_selected_before_foreground(self):
        route = select_route(
            {"foreground-computer-use", "app-internal-api", "local-file-script"}
        )
        self.assertEqual(route, "local-file-script")
        self.assertEqual(
            BACKGROUND_ROUTE_ORDER[-1],
            "foreground-computer-use",
        )

    def test_foreground_route_requires_explicit_permission(self):
        with self.assertRaises(PermissionError):
            select_route({"foreground-computer-use"})
        self.assertEqual(
            select_route(
                {"foreground-computer-use"},
                foreground_allowed=True,
            ),
            "foreground-computer-use",
        )

    def test_registry_rejects_sensitive_fields(self):
        bad = verified_incident()
        bad["token"] = "secret"
        with self.assertRaises(ValueError):
            upsert_incident(empty_registry(), bad)

    def test_verified_incident_requires_verification_evidence(self):
        bad = verified_incident()
        bad["verification"] = ""
        with self.assertRaises(ValueError):
            upsert_incident(empty_registry(), bad)

    def test_registry_rejects_noncanonical_incident_id(self):
        incident = upsert_incident(
            empty_registry(),
            verified_incident(),
            now="2026-07-29T01:00:00+08:00",
        )["incidents"][0]
        incident["id"] = "friendly-but-noncanonical-id"
        with self.assertRaises(ValueError):
            validate_registry(
                {
                    "schema_version": registry_module.SCHEMA_VERSION,
                    "updated_at": "2026-07-29T01:00:00+08:00",
                    "incidents": [incident],
                }
            )

    def test_verified_incident_requires_explicit_regression_before_downgrade(self):
        registry = upsert_incident(
            empty_registry(),
            verified_incident(),
            now="2026-07-29T01:00:00+08:00",
        )
        observed = verified_incident()
        observed["status"] = "observed"
        observed["root_cause"] = "unconfirmed"
        observed["known_good_solution"] = ""
        observed["verification"] = ""
        with self.assertRaises(ValueError):
            upsert_incident(
                registry,
                observed,
                now="2026-07-29T02:00:00+08:00",
            )

    def test_verified_incident_can_be_marked_regressed(self):
        registry = upsert_incident(
            empty_registry(),
            verified_incident(),
            now="2026-07-29T01:00:00+08:00",
        )
        regressed = verified_incident()
        regressed["status"] = "regressed"
        regressed["verification"] = "The same route failed after Zotero 9.1."
        updated = upsert_incident(
            registry,
            regressed,
            now="2026-07-29T02:00:00+08:00",
        )
        self.assertEqual(updated["incidents"][0]["status"], "regressed")
        self.assertEqual(updated["incidents"][0]["occurrences"], 2)

    def test_record_cli_prints_the_incident_that_was_updated(self):
        first = upsert_incident(
            empty_registry(),
            verified_incident(),
            now="2026-07-29T01:00:00+08:00",
        )
        other = verified_incident()
        other["component"] = "other-component"
        other["symptom_signature"] = "other failure"
        registry = upsert_incident(
            first,
            other,
            now="2026-07-29T01:30:00+08:00",
        )
        with writable_test_directory() as tmp:
            registry_path = Path(tmp) / "registry.json"
            incident_path = Path(tmp) / "incident.json"
            save_registry_atomic(registry_path, registry)
            incident_path.write_text(
                json.dumps(verified_incident(), ensure_ascii=False),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    registry_main(
                        [
                            "record",
                            "--registry",
                            str(registry_path),
                            "--incident-file",
                            str(incident_path),
                        ]
                    ),
                    0,
                )
            reported = json.loads(output.getvalue())
            self.assertEqual(reported["component"], "powershell")
            self.assertEqual(reported["occurrences"], 2)

    def test_atomic_save_round_trips_without_temp_residue(self):
        registry = upsert_incident(
            empty_registry(),
            verified_incident(),
            now="2026-07-29T01:00:00+08:00",
        )
        with writable_test_directory() as tmp:
            path = Path(tmp) / "registry.json"
            save_registry_atomic(path, registry)
            self.assertEqual(load_registry(path), registry)
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])


class PromotionAuditTests(unittest.TestCase):
    def test_pdf_coordinate_incident_routes_only_to_read_paper_skill(self):
        result = audit_candidate(
            promotable_incident("pdf-coordinate"),
            load_routing(ROUTING_PATH),
            ECOSYSTEM_REGISTRY,
        )
        self.assertTrue(result["eligible"])
        self.assertEqual(
            result["owner_component"],
            "research.read-paper-analysis-highlight",
        )
        self.assertTrue(
            result["canonical_path"].endswith(
                "read-paper-analysis-highlight/SKILL.md"
            )
        )

    def test_domain_semantic_change_requires_owner_evidence(self):
        incident = promotable_incident("paper-highlight-semantics")
        incident["effect_contract"]["domain_semantics"] = True
        result = audit_candidate(incident, load_routing(ROUTING_PATH), ECOSYSTEM_REGISTRY)
        self.assertEqual(result["promotion_policy"], "full")
        self.assertFalse(result["allow_auto_apply"])
        self.assertIn("owner evidence contract required", result["reasons"])

    def test_unknown_component_falls_back_to_collect_skill(self):
        result = audit_candidate(
            promotable_incident("unknown-runtime"),
            load_routing(ROUTING_PATH),
            ECOSYSTEM_REGISTRY,
        )
        self.assertEqual(
            result["owner_component"],
            "global.collect-bug-update-accelerate",
        )
        self.assertEqual(result["promotion_policy"], "full")

    def test_single_verified_infrastructure_success_is_ready_for_lightweight_fix(self):
        incident = promotable_incident("workspace-patching")
        incident["reuse_success_count"] = 0
        incident["effect_contract"] = None
        incident["regression_test"] = None
        result = audit_candidate(incident, load_routing(ROUTING_PATH), ECOSYSTEM_REGISTRY)
        self.assertTrue(result["reusable_now"])
        self.assertTrue(result["eligible"])
        self.assertEqual(result["promotion_policy"], "lightweight")
        self.assertEqual(
            result["candidate_stage"],
            "ready-for-lightweight-permanent-fix",
        )
        self.assertNotIn("effect contract required", result["reasons"])
        self.assertNotIn("regression test required", result["reasons"])

    def test_high_risk_candidate_without_full_evidence_stays_temporary(self):
        incident = promotable_incident("zotero-import")
        incident["effect_contract"] = None
        incident["regression_test"] = None
        result = audit_candidate(incident, load_routing(ROUTING_PATH), ECOSYSTEM_REGISTRY)
        self.assertTrue(result["reusable_now"])
        self.assertFalse(result["eligible"])
        self.assertEqual(result["promotion_policy"], "full")
        self.assertEqual(result["candidate_stage"], "temporary")
        self.assertIn("effect contract required", result["reasons"])
        self.assertIn("regression test required", result["reasons"])

    def test_lightweight_candidate_with_reuse_failure_is_not_eligible(self):
        incident = promotable_incident("workspace-patching")
        incident["effect_contract"] = None
        incident["regression_test"] = None
        incident["reuse_failure_count"] = 1
        result = audit_candidate(incident, load_routing(ROUTING_PATH), ECOSYSTEM_REGISTRY)
        self.assertTrue(result["reusable_now"])
        self.assertFalse(result["eligible"])
        self.assertIn("reuse regression must be resolved", result["reasons"])

    def test_local_deterministic_candidate_uses_lightweight_recheck(self):
        result = audit_candidate(
            promotable_incident("incident-registry-write"),
            load_routing(ROUTING_PATH),
            ECOSYSTEM_REGISTRY,
        )
        self.assertEqual(result["evidence_route"], "local-effect-recheck")
        self.assertEqual(result["recommended_surface"], "skill-or-runtime")

    def test_platform_candidate_requests_official_sources_and_local_check(self):
        result = audit_candidate(
            promotable_incident("workspace-patching"),
            load_routing(ROUTING_PATH),
            ECOSYSTEM_REGISTRY,
        )
        self.assertEqual(
            result["evidence_route"],
            "official-upstream-plus-local-check",
        )
        self.assertEqual(
            result["recommended_surface"],
            "runtime-or-environment-preflight",
        )

    def test_external_version_candidate_requests_official_sources(self):
        result = audit_candidate(
            promotable_incident("zotero-run-js"),
            load_routing(ROUTING_PATH),
            ECOSYSTEM_REGISTRY,
        )
        self.assertEqual(
            result["evidence_route"],
            "official-upstream-plus-local-test",
        )
    def test_valid_infrastructure_candidate_allows_auto_apply(self):
        result = audit_candidate(
            promotable_incident("incident-registry-write"),
            load_routing(ROUTING_PATH),
            ECOSYSTEM_REGISTRY,
        )
        self.assertTrue(result["eligible"])
        self.assertTrue(result["allow_auto_apply"])
        self.assertEqual(
            result["owner_component"],
            "global.collect-bug-update-accelerate",
        )

    def test_cli_audits_only_candidates_without_writing_registry(self):
        registry = empty_registry()
        registry["incidents"] = [promotable_incident("pdf-coordinate")]
        with writable_test_directory() as tmp:
            path = Path(tmp) / "registry.json"
            save_registry_atomic(path, registry)
            before = path.read_bytes()
            output = io.StringIO()
            with redirect_stdout(output):
                result = promotion_main(
                    [
                        "--registry",
                        str(path),
                        "--routing",
                        str(ROUTING_PATH),
                        "--ecosystem-registry",
                        str(ECOSYSTEM_REGISTRY),
                    ]
                )
            self.assertEqual(result, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(len(report), 1)
            self.assertEqual(
                report[0]["owner_component"],
                "research.read-paper-analysis-highlight",
            )
            self.assertEqual(path.read_bytes(), before)


class DependencyBootstrapTests(unittest.TestCase):
    def test_subprocess_output_replaces_undecodable_bytes(self):
        completed = unittest.mock.Mock(returncode=0, stdout="ok", stderr="")
        with patch("ensure_dependencies.subprocess.run", return_value=completed) as run:
            result = _default_runner(["python", "-m", "pip"])
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_dependency_plan_uses_explicit_distribution_mapping(self):
        result = plan_dependencies(
            {"yaml": "PyYAML"},
            probe=lambda _interpreter, _import_name: False,
            interpreter="C:\\Python\\python.exe",
        )
        self.assertEqual(result[0]["distribution"], "PyYAML")
        self.assertEqual(result[0]["status"], "missing")

    def test_unknown_distribution_is_not_auto_installed(self):
        with self.assertRaises(ValueError):
            plan_dependencies(
                {"yaml": ""},
                probe=lambda _interpreter, _import_name: False,
                interpreter="python",
            )

    def test_install_and_verify_use_the_same_interpreter(self):
        commands: list[list[str]] = []
        probe_answers = iter([False, True])

        def probe(_interpreter: str, _import_name: str) -> bool:
            return next(probe_answers)

        def runner(command: list[str]) -> dict:
            commands.append(command)
            return {"returncode": 0, "stdout": "ok", "stderr": ""}

        results = ensure_dependencies(
            {"yaml": "PyYAML"},
            interpreter="C:\\Python\\python.exe",
            install=True,
            probe=probe,
            runner=runner,
        )
        self.assertEqual(results[0]["status"], "installed")
        self.assertEqual(commands[0][:4], ["C:\\Python\\python.exe", "-m", "pip", "install"])
        self.assertEqual(commands[1][0], "C:\\Python\\python.exe")
        self.assertEqual(commands[1][1], "-c")

    def test_explicit_install_target_is_used_and_verified(self):
        commands: list[list[str]] = []
        probe_answers = iter([False, True])

        def probe(_interpreter: str, _import_name: str) -> bool:
            return next(probe_answers)

        def runner(command: list[str]) -> dict:
            commands.append(command)
            return {"returncode": 0, "stdout": "6.0.3", "stderr": ""}

        target = "C:\\Python\\Lib\\site-packages"
        results = ensure_dependencies(
            {"yaml": "PyYAML"},
            interpreter="C:\\Python\\python.exe",
            install=True,
            install_target=target,
            probe=probe,
            runner=runner,
        )
        self.assertEqual(
            commands[0],
            [
                "C:\\Python\\python.exe",
                "-m",
                "pip",
                "install",
                "--target",
                target,
                "PyYAML",
            ],
        )
        self.assertIn(repr(target), commands[1][2])
        self.assertEqual(results[0]["install_target"], target)


if __name__ == "__main__":
    unittest.main()
