from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "skill-with-plugin" / "drone-literature-scout-plugin"
MANIFEST = PLUGIN_ROOT / "architecture-manifest.json"


class SyncConflictError(RuntimeError):
    """Raised when both sides changed since the last recorded synchronization."""


def discover_skill_names(repo_root: Path = REPO_ROOT) -> set[str]:
    root = repo_root / "skill-with-plugin" / "drone-literature-scout-plugin" / "skills"
    return {p.name for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()}


def expected_mirrors(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    return {name: f"{name}-完整指南.md" for name in discover_skill_names(repo_root)}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def validate_manifest_pair(pair: dict, mirrors: dict[str, str]) -> None:
    pair_id = pair.get("id")
    if pair_id not in mirrors:
        raise ValueError(f"未登记的 skill 镜像: {pair_id}")
    if pair.get("mode") != "byte-identical":
        raise ValueError(f"{pair_id} 只允许 byte-identical 模式")
    expected_mirror = mirrors[pair_id]
    if pair.get("mirror") != expected_mirror:
        raise ValueError(
            f"{pair_id} 使用非规范镜像文件名: "
            f"expected={expected_mirror} actual={pair.get('mirror')}"
        )
    expected_canonical = f"skills/{pair_id}/SKILL.md"
    if pair.get("canonical") != expected_canonical:
        raise ValueError(
            f"{pair_id} 使用非规范 canonical: "
            f"expected={expected_canonical} actual={pair.get('canonical')}"
        )


def load_pairs(manifest: Path = MANIFEST, repo_root: Path = REPO_ROOT) -> list[dict]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    pairs = data.get("mirrors")
    if not isinstance(pairs, list) or not pairs:
        raise ValueError(f"同步清单没有有效 pairs: {manifest}")
    mirrors = expected_mirrors(repo_root)
    pair_ids = [pair.get("id") for pair in pairs]
    if len(pair_ids) != len(set(pair_ids)) or set(pair_ids) != set(mirrors):
        raise ValueError("同步清单必须与动态 Skill 拓扑一一对应")
    for pair in pairs:
        validate_manifest_pair(pair, mirrors)
    return pairs


def select_pairs(pairs: list[dict], skill: str | None) -> list[dict]:
    if skill is None:
        return pairs
    selected = [pair for pair in pairs if pair.get("id") == skill]
    if not selected:
        raise ValueError(f"同步清单中不存在 Skill: {skill}")
    return selected


def save_pairs(pairs: list[dict], manifest: Path = MANIFEST) -> None:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["mirrors"] = pairs
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _pair_paths(repo_root: Path, pair: dict) -> tuple[Path, Path]:
    plugin_root = repo_root / "skill-with-plugin" / "drone-literature-scout-plugin"
    return plugin_root / pair["canonical"], repo_root / pair["mirror"]


def check_pair(repo_root: Path, pair: dict) -> tuple[bool, str]:
    validate_manifest_pair(pair, expected_mirrors(repo_root))
    canonical, mirror = _pair_paths(repo_root, pair)
    if not canonical.is_file():
        return False, f"CANONICAL_MISSING {canonical}"
    if not mirror.is_file():
        return False, f"MIRROR_MISSING {mirror}"
    canonical_hash = sha256(canonical)
    mirror_hash = sha256(mirror)
    if canonical_hash != mirror_hash:
        return False, f"MIRROR_MISMATCH canonical={canonical_hash} mirror={mirror_hash}"
    return True, f"OK {pair['id']} sha256={canonical_hash}"


def _set_synced_hash(pair: dict, digest: str) -> None:
    pair["last_synced_sha256"] = digest


def sync_pair(repo_root: Path, pair: dict) -> str:
    validate_manifest_pair(pair, expected_mirrors(repo_root))
    canonical, mirror = _pair_paths(repo_root, pair)
    if not canonical.is_file():
        raise FileNotFoundError(f"主文件不存在: {canonical}")
    mirror.write_bytes(canonical.read_bytes())
    digest = sha256(canonical)
    _set_synced_hash(pair, digest)
    return f"SYNCED {pair['id']} canonical->mirror sha256={digest}"


def sync_changed_pair(repo_root: Path, pair: dict) -> str:
    validate_manifest_pair(pair, expected_mirrors(repo_root))
    canonical, mirror = _pair_paths(repo_root, pair)
    if not canonical.is_file() or not mirror.is_file():
        raise FileNotFoundError(f"同步两侧必须存在: {canonical}, {mirror}")
    canonical_hash = sha256(canonical)
    mirror_hash = sha256(mirror)
    baseline = pair.get("last_synced_sha256")
    if not baseline:
        raise SyncConflictError(f"{pair['id']} 没有基线哈希，禁止猜测变更来源")
    if canonical_hash == mirror_hash and canonical_hash != baseline:
        _set_synced_hash(pair, canonical_hash)
        return f"RECONCILED {pair['id']} sha256={canonical_hash}"
    if canonical_hash == baseline and mirror_hash == baseline:
        return f"UNCHANGED {pair['id']} sha256={baseline}"
    if canonical_hash != baseline and mirror_hash == baseline:
        mirror.write_bytes(canonical.read_bytes())
        _set_synced_hash(pair, canonical_hash)
        return f"SYNCED {pair['id']} canonical->mirror sha256={canonical_hash}"
    if canonical_hash == baseline and mirror_hash != baseline:
        raise SyncConflictError(
            f"{pair['id']} mirror changed; canonical is the only sync source"
        )
    raise SyncConflictError(
        f"{pair['id']} both sides changed canonical={canonical_hash} mirror={mirror_hash}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="检查或同步动态发现的 Skill 与完整指南镜像")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="只检查，不修改")
    group.add_argument("--sync", action="store_true", help="以 canonical 为准同步全部镜像")
    group.add_argument("--sync-auto", action="store_true", help="按上次基线同步单边变更")
    parser.add_argument(
        "--skill",
        help="只检查或同步一个已登记 Skill；完整 manifest 仍会先被校验",
    )
    args = parser.parse_args()

    pairs = load_pairs()
    selected = select_pairs(pairs, args.skill)
    if args.sync:
        messages = [sync_pair(REPO_ROOT, pair) for pair in selected]
        save_pairs(pairs)
        print("\n".join(messages))
        return 0

    if args.sync_auto or not args.check:
        messages = [sync_changed_pair(REPO_ROOT, pair) for pair in selected]
        save_pairs(pairs)
        print("\n".join(messages))
        return 0

    failures = 0
    for pair in selected:
        ok, message = check_pair(REPO_ROOT, pair)
        print(message)
        failures += not ok
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
