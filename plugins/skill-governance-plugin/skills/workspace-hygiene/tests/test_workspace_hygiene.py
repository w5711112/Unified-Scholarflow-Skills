from pathlib import Path
import sys
import hashlib
import json
import os
import shutil

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from workspace_hygiene import (  # noqa: E402
    Candidate,
    HygieneProposal,
    apply_proposal,
    build_proposal,
    purge_quarantine,
    scan_workspace,
)


def test_scan_auto_classifies_only_mechanical_cache(tmp_path: Path) -> None:
    cache = tmp_path / "pkg" / "__pycache__" / "x.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"cache")
    source = tmp_path / "tests" / "test_feature.py"
    source.parent.mkdir()
    source.write_text("def test_feature(): pass\n", encoding="utf-8")
    report = scan_workspace(tmp_path, {"protected_names": ["tests", "python-packages"]})
    assert [item.relative_path for item in report.auto_candidates] == ["pkg/__pycache__/x.pyc"]
    assert "tests/test_feature.py" in report.protected_paths


def test_test_sources_stay_protected_while_nested_cache_is_automatic(tmp_path: Path) -> None:
    cache = tmp_path / "tests" / "__pycache__" / "test_feature.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"cache")
    source = tmp_path / "tests" / "test_feature.py"
    source.write_text("def test_feature(): pass\n", encoding="utf-8")
    report = scan_workspace(tmp_path, {"tests_completed": True})
    assert [item.relative_path for item in report.auto_candidates] == [
        "tests/__pycache__/test_feature.pyc"
    ]
    assert report.protected_paths == ["tests/test_feature.py"]


def test_exact_semantic_candidate_policy_never_overrides_protected_paths(tmp_path: Path) -> None:
    requested = tmp_path / "staging" / "candidate.txt"
    requested.parent.mkdir()
    requested.write_text("candidate", encoding="utf-8")
    protected_test = tmp_path / "tests" / "historical.txt"
    protected_test.parent.mkdir()
    protected_test.write_text("test", encoding="utf-8")
    protected_runtime = tmp_path / "python-packages" / "dependency.txt"
    protected_runtime.parent.mkdir()
    protected_runtime.write_text("dependency", encoding="utf-8")

    report = scan_workspace(
        tmp_path,
        {
            "semantic_candidate_paths": [
                "staging/candidate.txt",
                "tests/historical.txt",
                "python-packages/dependency.txt",
            ]
        },
    )

    assert [item.relative_path for item in report.proposal_candidates] == ["staging/candidate.txt"]
    assert report.protected_paths == ["python-packages/dependency.txt", "tests/historical.txt"]


def test_scan_never_descends_into_reparse_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    linked = tmp_path / "linked"
    linked.mkdir()
    nested = linked / "legacy" / "outside.txt"
    nested.parent.mkdir()
    nested.write_text("outside", encoding="utf-8")
    hygiene = __import__("workspace_hygiene")
    original_reparse = hygiene._reparse
    monkeypatch.setattr(hygiene, "_reparse", lambda path: path == linked or original_reparse(path))

    report = scan_workspace(tmp_path, {})

    assert report.proposal_candidates == []
    assert report.auto_candidates == []
    assert report.protected_paths == ["linked"]
    assert report.total_bytes == 0


def test_scan_marks_directory_protected_when_enumeration_becomes_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    (unreadable / "legacy.txt").write_text("legacy", encoding="utf-8")
    hygiene = __import__("workspace_hygiene")
    original_scandir = hygiene.os.scandir

    def guarded_scandir(path):
        if Path(path) == unreadable:
            raise FileNotFoundError(unreadable)
        return original_scandir(path)

    monkeypatch.setattr(hygiene.os, "scandir", guarded_scandir)

    report = scan_workspace(tmp_path, {})

    assert report.proposal_candidates == []
    assert report.auto_candidates == []
    assert report.protected_paths == ["unreadable"]
    assert report.total_bytes == 0


def test_python_packages_is_always_protected(tmp_path: Path) -> None:
    dependency = tmp_path / ".codex-runtime" / "python-packages" / "pkg.py"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("VERSION = 1\n", encoding="utf-8")
    report = scan_workspace(tmp_path, {"protected_names": ["python-packages"]})
    assert report.auto_candidates == []
    assert ".codex-runtime/python-packages/pkg.py" in report.protected_paths


def test_empty_cache_directories_inside_hard_protected_paths_are_never_removed(
    tmp_path: Path,
) -> None:
    protected_caches = [
        tmp_path / ".git" / "__pycache__",
        tmp_path / ".skill-contract" / "__pycache__",
        tmp_path / ".codex-runtime" / "python-packages" / "__pycache__",
    ]
    for cache in protected_caches:
        cache.mkdir(parents=True)
    report = scan_workspace(tmp_path, {"tests_completed": True})
    proposal = build_proposal(report, [])

    result = apply_proposal(
        proposal,
        tmp_path.parent / f"unused-quarantine-{tmp_path.name}",
        None,
    )

    assert result.paths == []
    assert all(cache.is_dir() for cache in protected_caches)


def test_empty_cache_directory_inside_policy_protected_path_is_never_removed(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "vendor-runtime" / "__pycache__"
    cache.mkdir(parents=True)
    report = scan_workspace(
        tmp_path,
        {"protected_names": ["vendor-runtime"], "tests_completed": True},
    )
    proposal = build_proposal(report, [])

    result = apply_proposal(
        proposal,
        tmp_path.parent / f"unused-quarantine-{tmp_path.name}",
        None,
    )

    assert result.paths == []
    assert cache.is_dir()


def test_workspace_hygiene_uses_registered_canonical_source_without_mirror() -> None:
    root = Path(__file__).resolve().parents[3]
    registry = json.loads((root / "ecosystem-registry.json").read_text(encoding="utf-8"))
    component = next(
        item for item in registry["components"]
        if item["id"] == "global.workspace-hygiene"
    )
    assert component["relative_path"].endswith("skills/workspace-hygiene")
    assert component["mirrors"] == []
    assert (root / "skills/workspace-hygiene/SKILL.md").is_file()


def test_apply_preflights_all_moves_before_mutating(tmp_path: Path) -> None:
    first = tmp_path / "legacy" / "one.txt"
    first.parent.mkdir(parents=True)
    first.write_text("one", encoding="utf-8")
    other = tmp_path / "legacy" / "two.txt"
    other.write_text("two", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/one.txt", "legacy/two.txt"])
    quarantine = tmp_path.parent / f"quarantine-{tmp_path.name}"
    other.unlink()
    approval = "APPROVE:" + __import__("workspace_hygiene")._proposal_digest(proposal)
    with pytest.raises(FileNotFoundError):
        apply_proposal(proposal, quarantine, approval)
    assert first.exists()


def test_unrelated_protected_path_drift_does_not_invalidate_approved_candidates(tmp_path: Path) -> None:
    candidate = tmp_path / "legacy" / "one.txt"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("one", encoding="utf-8")
    protected = tmp_path / "notes.md"
    protected.write_text("keep", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/one.txt"])
    approval = "APPROVE:" + __import__("workspace_hygiene")._proposal_digest(proposal)

    (tmp_path / "unrelated.md").write_text("also keep", encoding="utf-8")
    result = apply_proposal(
        proposal,
        tmp_path.parent / f"quarantine-{tmp_path.name}",
        approval,
    )

    assert result.action == "mixed"
    assert result.rollback_path is not None
    assert protected.read_text(encoding="utf-8") == "keep"
    assert (tmp_path / "unrelated.md").read_text(encoding="utf-8") == "also keep"


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path behavior")
def test_deep_quarantine_destination_uses_extended_length_paths(tmp_path: Path) -> None:
    relative = Path(*(["nested-segment"] * 8), "one.txt")
    candidate = tmp_path / "legacy" / relative
    candidate.parent.mkdir(parents=True)
    candidate.write_text("one", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), [f"legacy/{relative.as_posix()}"])
    approval = "APPROVE:" + __import__("workspace_hygiene")._proposal_digest(proposal)
    quarantine = tmp_path.parent / ("q" * 120)

    try:
        result = apply_proposal(proposal, quarantine, approval)
        assert result.rollback_path == str(quarantine)
        assert len(str(quarantine / "legacy" / relative)) > 260
    finally:
        extended = "\\\\?\\" + str(quarantine)
        if os.path.exists(extended):
            shutil.rmtree(extended)


def test_quarantine_must_be_outside_scan_root(tmp_path: Path) -> None:
    candidate = tmp_path / "legacy" / "one.txt"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("one", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/one.txt"])
    approval = "APPROVE:" + __import__("workspace_hygiene")._proposal_digest(proposal)
    with pytest.raises(ValueError, match="quarantine"):
        apply_proposal(proposal, tmp_path / ".cleanup-quarantine", approval)
    assert candidate.exists()


def test_semantic_cleanup_and_purge_require_separate_exact_tokens(tmp_path: Path) -> None:
    candidate = tmp_path / "legacy" / "one.txt"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("one", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/one.txt"])
    quarantine = tmp_path.parent / "quarantine"
    approval = "APPROVE:" + __import__("workspace_hygiene")._proposal_digest(proposal)
    with pytest.raises(PermissionError):
        apply_proposal(proposal, quarantine, "APPROVE:wrong")
    result = apply_proposal(proposal, quarantine, approval)
    with pytest.raises(PermissionError):
        purge_quarantine(result, approval)


def test_apply_rejects_forged_proposal_that_targets_protected_or_unknown_paths(tmp_path: Path) -> None:
    protected = tmp_path / "tests" / "keep.py"
    protected.parent.mkdir()
    protected.write_text("keep", encoding="utf-8")
    forged = HygieneProposal(str(tmp_path), [Candidate("tests/keep.py", 4, "forged", "forged", "delete")], [], 4)
    with pytest.raises(PermissionError):
        apply_proposal(forged, tmp_path.parent / "quarantine", None)
    assert protected.exists()


def test_purge_rejects_forged_result_for_arbitrary_directory(tmp_path: Path) -> None:
    arbitrary = tmp_path / "important"
    arbitrary.mkdir()
    (arbitrary / "keep.txt").write_text("keep", encoding="utf-8")
    forged = __import__("workspace_hygiene").HygieneResult([], "mixed", [], 0, 0, str(arbitrary), [])
    token = "PURGE:" + hashlib.sha256(str(arbitrary.resolve()).encode("utf-8")).hexdigest()
    with pytest.raises(PermissionError):
        purge_quarantine(forged, token)
    assert (arbitrary / "keep.txt").exists()


def test_failed_second_move_rolls_back_first_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("one.txt", "two.txt"):
        path = tmp_path / "legacy" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(name, encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/one.txt", "legacy/two.txt"])
    approval = "APPROVE:" + __import__("workspace_hygiene")._proposal_digest(proposal)
    module = __import__("workspace_hygiene")
    original_rename = module._rename_open_handle
    calls = 0

    def fail_second(handle: int, target_dir_handle: int, leaf_name: str) -> None:
        nonlocal calls
        if leaf_name in {"one.txt", "two.txt"}:
            calls += 1
            if calls == 2:
                raise OSError("move failed")
        original_rename(handle, target_dir_handle, leaf_name)

    monkeypatch.setattr(module, "_rename_open_handle", fail_second)
    with pytest.raises(OSError, match="move failed"):
        apply_proposal(proposal, tmp_path.parent / f"quarantine-{tmp_path.name}", approval)
    assert (tmp_path / "legacy/one.txt").exists()
    assert (tmp_path / "legacy/two.txt").exists()


def test_pytest_cache_requires_successful_test_evidence(tmp_path: Path) -> None:
    cache = tmp_path / ".pytest_cache" / "v" / "cache"
    cache.parent.mkdir(parents=True)
    cache.write_text("cache", encoding="utf-8")
    assert scan_workspace(tmp_path, {}).auto_candidates == []
    assert [item.relative_path for item in scan_workspace(tmp_path, {"tests_completed": True}).auto_candidates] == [".pytest_cache/v/cache"]


def test_semantic_only_scan_can_protect_unrelated_automatic_candidates(tmp_path: Path) -> None:
    cache = tmp_path / "pkg" / "__pycache__" / "generated.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"cache")
    pytest_cache = tmp_path / ".pytest_cache" / "v" / "cache" / "nodeids"
    pytest_cache.parent.mkdir(parents=True)
    pytest_cache.write_text("[]", encoding="utf-8")
    legacy = tmp_path / "requirements-runtime.txt"
    legacy.write_text("package==1\n", encoding="utf-8")

    report = scan_workspace(
        tmp_path,
        {
            "automatic_cleanup": False,
            "tests_completed": True,
            "semantic_candidate_paths": [
                "requirements-runtime.txt",
                ".pytest_cache/v/cache/nodeids",
            ],
        },
    )

    assert report.auto_candidates == []
    assert [item.relative_path for item in report.proposal_candidates] == ["requirements-runtime.txt"]
    assert report.protected_paths == [
        ".pytest_cache/v/cache/nodeids",
        "pkg/__pycache__/generated.pyc",
    ]


def test_symlinked_cache_never_deletes_protected_target(tmp_path: Path) -> None:
    protected = tmp_path / "tests" / "keep.py"
    protected.parent.mkdir()
    protected.write_text("keep", encoding="utf-8")
    link = tmp_path / "cache.pyc"
    try:
        link.symlink_to(protected)
    except OSError as error:
        pytest.skip(f"symlink unavailable: {error}")
    report = scan_workspace(tmp_path, {})
    assert "cache.pyc" in report.protected_paths
    proposal = build_proposal(report, [])
    apply_proposal(proposal, tmp_path.parent / f"quarantine-{tmp_path.name}", None)
    assert protected.read_text(encoding="utf-8") == "keep"


def test_manifest_write_failure_rolls_back_semantic_moves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "legacy" / "keep.txt"
    source.parent.mkdir()
    source.write_text("keep", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/keep.txt"])
    module = __import__("workspace_hygiene")
    monkeypatch.setattr(module, "_commit_manifest", lambda *_: (_ for _ in ()).throw(OSError("manifest failed")))
    token = "APPROVE:" + module._proposal_digest(proposal)
    with pytest.raises(OSError, match="manifest failed"):
        apply_proposal(proposal, tmp_path.parent / f"quarantine-{tmp_path.name}", token)
    assert source.exists()


def test_automatic_delete_failure_keeps_committed_recovery_quarantine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    semantic = tmp_path / "legacy" / "keep.txt"
    semantic.parent.mkdir()
    semantic.write_text("keep", encoding="utf-8")
    cache = tmp_path / "pkg" / "__pycache__" / "cache.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_text("cache", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/keep.txt"])
    module = __import__("workspace_hygiene")
    monkeypatch.setattr(
        module, "_delete_open_handle", lambda handle: (_ for _ in ()).throw(OSError("delete failed"))
    )
    token = "APPROVE:" + module._proposal_digest(proposal)
    quarantine = tmp_path.parent / f"quarantine-{tmp_path.name}"
    with pytest.raises(OSError, match="delete failed"):
        apply_proposal(proposal, quarantine, token)
    assert not semantic.exists()
    assert (quarantine / ".workspace-hygiene-manifest.json").is_file()


def test_final_candidate_replaced_with_link_never_touches_protected_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "cache.pyc"
    cache.write_text("cache", encoding="utf-8")
    protected = tmp_path / "tests" / "keep.py"
    protected.parent.mkdir()
    protected.write_text("keep", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), [])
    module = __import__("workspace_hygiene")
    original_replace = module.os.replace

    def replace_candidate(source: str, destination: str) -> None:
        if Path(source) == cache:
            cache.unlink()
            try:
                cache.symlink_to(protected)
            except OSError as error:
                pytest.skip(f"symlink unavailable: {error}")
        original_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", replace_candidate)
    apply_proposal(proposal, tmp_path.parent / f"quarantine-{tmp_path.name}", None)
    assert protected.read_text(encoding="utf-8") == "keep"


def test_manifest_paths_are_preflight_collision_checked(tmp_path: Path) -> None:
    source = tmp_path / "legacy" / "keep.txt"
    source.parent.mkdir()
    source.write_text("keep", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/keep.txt"])
    quarantine = tmp_path.parent / f"quarantine-{tmp_path.name}"
    quarantine.mkdir()
    (quarantine / ".workspace-hygiene-manifest.prepared").write_text("foreign", encoding="utf-8")
    token = "APPROVE:" + __import__("workspace_hygiene")._proposal_digest(proposal)
    with pytest.raises(FileExistsError):
        apply_proposal(proposal, quarantine, token)
    assert source.exists()


def test_automatic_only_success_retains_traceable_transaction_artifacts(tmp_path: Path) -> None:
    cache = tmp_path / "cache.pyc"
    cache.write_text("cache", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), [])
    quarantine = tmp_path.parent / f"quarantine-{tmp_path.name}"
    result = apply_proposal(proposal, quarantine, None)
    assert result.rollback_path == str(quarantine)
    assert not cache.exists()
    assert not (quarantine / ".automatic" / "cache.pyc").exists()
    assert (quarantine / ".workspace-hygiene-manifest.json").is_file()


def test_automatic_cleanup_removes_empty_cache_directories(tmp_path: Path) -> None:
    cache = tmp_path / "tests" / "__pycache__" / "test_feature.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"cache")
    proposal = build_proposal(scan_workspace(tmp_path, {"tests_completed": True}), [])
    quarantine = tmp_path.parent / f"quarantine-{tmp_path.name}"

    apply_proposal(proposal, quarantine, None)

    assert not cache.parent.exists()
    assert (tmp_path / "tests").is_dir()


def test_automatic_cleanup_removes_preexisting_empty_cache_directory(tmp_path: Path) -> None:
    cache_dir = tmp_path / "tests" / "__pycache__"
    cache_dir.mkdir(parents=True)
    proposal = build_proposal(scan_workspace(tmp_path, {"tests_completed": True}), [])

    result = apply_proposal(proposal, tmp_path.parent / f"quarantine-{tmp_path.name}", None)

    assert not cache_dir.exists()
    assert (tmp_path / "tests").is_dir()
    assert str(cache_dir) in result.paths
    assert result.rollback_path is None


def test_ancestor_swap_after_source_open_never_touches_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_parent = tmp_path / "cache-dir"
    source_parent.mkdir()
    source = source_parent / "cache.pyc"
    source.write_text("original-cache", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), [])
    quarantine = tmp_path.parent / f"quarantine-{tmp_path.name}"
    detached_parent = tmp_path / "detached-cache-dir"
    replacement = source_parent / "cache.pyc"
    module = __import__("workspace_hygiene")
    original_rename = module._rename_open_handle
    swapped = False
    attack_rejected = False

    def swap_ancestor_after_source_open(handle: int, target_dir_handle: int, leaf_name: str) -> None:
        nonlocal attack_rejected, swapped
        if not swapped and leaf_name == "cache.pyc":
            try:
                source_parent.rename(detached_parent)
            except PermissionError:
                attack_rejected = True
            else:
                source_parent.mkdir()
                replacement.write_text("protected-replacement", encoding="utf-8")
                swapped = True
        original_rename(handle, target_dir_handle, leaf_name)

    monkeypatch.setattr(module, "_rename_open_handle", swap_ancestor_after_source_open)
    apply_proposal(proposal, quarantine, None)

    assert swapped or attack_rejected
    if swapped:
        assert replacement.read_text(encoding="utf-8") == "protected-replacement"
    else:
        assert not replacement.exists()


def test_competing_quarantine_root_creation_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "legacy" / "keep.txt"
    source.parent.mkdir()
    source.write_text("keep", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/keep.txt"])
    quarantine = tmp_path.parent / f"quarantine-{tmp_path.name}"
    module = __import__("workspace_hygiene")
    original_mkdir = module._mkdir_plain
    injected = False

    def inject_root_collision(path: Path) -> None:
        nonlocal injected
        if path == quarantine and not injected:
            original_mkdir(path)
            (path / "foreign.txt").write_text("foreign", encoding="utf-8")
            injected = True
        original_mkdir(path)

    monkeypatch.setattr(module, "_mkdir_plain", inject_root_collision)
    token = "APPROVE:" + __import__("workspace_hygiene")._proposal_digest(proposal)
    with pytest.raises(FileExistsError):
        apply_proposal(proposal, quarantine, token)
    assert source.read_text(encoding="utf-8") == "keep"
    assert (quarantine / "foreign.txt").read_text(encoding="utf-8") == "foreign"


def test_target_ancestor_swap_is_rejected_while_directory_handle_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "legacy" / "keep.txt"
    source.parent.mkdir()
    source.write_text("keep", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/keep.txt"])
    quarantine = tmp_path.parent / f"quarantine-{tmp_path.name}"
    detached = tmp_path.parent / f"detached-{tmp_path.name}"
    module = __import__("workspace_hygiene")
    original_rename = module._rename_open_handle
    attack_rejected = False

    def attack_target_ancestor(source_handle: int, target_dir_handle: int, leaf_name: str) -> None:
        nonlocal attack_rejected
        try:
            quarantine.rename(detached)
        except PermissionError:
            attack_rejected = True
        original_rename(source_handle, target_dir_handle, leaf_name)

    monkeypatch.setattr(module, "_rename_open_handle", attack_target_ancestor)
    token = "APPROVE:" + module._proposal_digest(proposal)
    apply_proposal(proposal, quarantine, token)
    assert attack_rejected
    assert (quarantine / "legacy" / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_cross_volume_preflight_closes_new_source_handle_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "legacy" / "keep.txt"
    source.parent.mkdir()
    source.write_text("keep", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/keep.txt"])
    module = __import__("workspace_hygiene")
    original_open_source = module._open_rename_handle
    original_information = module._handle_information
    original_close = module._close_windows_handle
    source_handles: list[int] = []
    closed: list[int] = []

    def remember_source_handle(path: Path, expected: tuple[int, int, int, int]) -> int:
        handle = original_open_source(path, expected)
        closed.clear()
        source_handles.append(handle)
        return handle

    def force_target_volume_mismatch(handle: int):
        information = original_information(handle)
        if source_handles and handle != source_handles[-1]:
            information.dwVolumeSerialNumber ^= 1
        return information

    def remember_close(handle: int) -> None:
        closed.append(handle)
        original_close(handle)

    monkeypatch.setattr(module, "_open_rename_handle", remember_source_handle)
    monkeypatch.setattr(module, "_handle_information", force_target_volume_mismatch)
    monkeypatch.setattr(module, "_close_windows_handle", remember_close)
    token = "APPROVE:" + module._proposal_digest(proposal)
    with pytest.raises(OSError, match="cross-volume"):
        apply_proposal(proposal, tmp_path.parent / f"quarantine-{tmp_path.name}", token)

    assert source_handles
    assert closed.count(source_handles[-1]) == 1


def test_automatic_delete_keeps_target_ancestor_locked_until_handle_disposition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache.pyc"
    cache.write_text("cache", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), [])
    quarantine = tmp_path.parent / f"quarantine-{tmp_path.name}"
    detached = tmp_path.parent / f"detached-{tmp_path.name}"
    module = __import__("workspace_hygiene")
    attacked = False
    attack_rejected = False

    def attack_before_disposition(handle: int) -> None:
        nonlocal attacked, attack_rejected
        attacked = True
        try:
            quarantine.rename(detached)
        except PermissionError:
            attack_rejected = True
        module._real_delete_open_handle(handle)

    monkeypatch.setattr(module, "_delete_open_handle", attack_before_disposition, raising=False)
    apply_proposal(proposal, quarantine, None)

    assert attacked
    assert attack_rejected
    assert not cache.exists()
    assert not (quarantine / ".automatic" / "cache.pyc").exists()


def test_purge_keeps_quarantine_ancestor_locked_through_handle_disposition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "legacy" / "keep.txt"
    candidate.parent.mkdir()
    candidate.write_text("keep", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/keep.txt"])
    module = __import__("workspace_hygiene")
    quarantine = tmp_path.parent / f"quarantine-{tmp_path.name}"
    detached = tmp_path.parent / f"detached-{tmp_path.name}"
    apply_token = "APPROVE:" + module._proposal_digest(proposal)
    result = apply_proposal(proposal, quarantine, apply_token)
    original_delete = module._delete_open_handle
    attacked = False
    attack_rejected = False

    def attack_before_disposition(handle: int) -> None:
        nonlocal attacked, attack_rejected
        if not attacked:
            attacked = True
            try:
                quarantine.rename(detached)
            except PermissionError:
                attack_rejected = True
        original_delete(handle)

    monkeypatch.setattr(module, "_delete_open_handle", attack_before_disposition)
    purge_token = "PURGE:" + hashlib.sha256(str(quarantine).encode("utf-8")).hexdigest()
    purged = purge_quarantine(result, purge_token)

    assert attacked
    assert attack_rejected
    assert purged.rollback_path is None
    assert not quarantine.exists()


def test_purge_rejects_unknown_quarantine_entry_before_deleting_known_content(tmp_path: Path) -> None:
    candidate = tmp_path / "legacy" / "keep.txt"
    candidate.parent.mkdir()
    candidate.write_text("keep", encoding="utf-8")
    proposal = build_proposal(scan_workspace(tmp_path, {}), ["legacy/keep.txt"])
    module = __import__("workspace_hygiene")
    quarantine = tmp_path.parent / f"quarantine-{tmp_path.name}"
    apply_token = "APPROVE:" + module._proposal_digest(proposal)
    result = apply_proposal(proposal, quarantine, apply_token)
    foreign = quarantine / "foreign.txt"
    foreign.write_text("foreign", encoding="utf-8")
    purge_token = "PURGE:" + hashlib.sha256(str(quarantine).encode("utf-8")).hexdigest()

    with pytest.raises(PermissionError, match="unknown"):
        purge_quarantine(result, purge_token)

    assert (quarantine / "legacy" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert foreign.read_text(encoding="utf-8") == "foreign"
