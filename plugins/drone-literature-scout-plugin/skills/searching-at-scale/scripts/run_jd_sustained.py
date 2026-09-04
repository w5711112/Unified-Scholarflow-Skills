"""Unattended JD slow-lane discovery driver.

Runs the whole search window without an LLM in the loop: creates a fresh
run/SQLite, pre-seeds bounded Edge marketplace cursors, and loops the global
scheduler until the run reaches a success status or the wall-clock budget
elapses. Edge request pacing lives inside ``edge_marketplace_session_adapter``
(see ``scripts/jd_pace.py``); the driver only waits when repeated scheduler
rounds prove there is currently no runnable work.

Exit code 0 only when a success status was reached; otherwise 1 with the real
status and the ledger path so a later pass can resume.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

if __package__ in {None, ""}:
    skill_root = str(Path(__file__).resolve().parents[1])
    if skill_root not in sys.path:
        sys.path.insert(0, skill_root)

from scripts.domestic_marketplace_query import (
    MarketplaceQueryDimensions,
    edge_pipe_path,
    edge_task_batch,
)
from scripts.edge_marketplace_query import (
    EdgeWorkerFailure,
    probe_edge_background_bridge,
)
from scripts.backend_runner import edge_marketplace_session_adapter
from scripts.jd_continuation import (
    HARD_JD_FAILURE_CATEGORIES,
    current_request,
    new_continuation,
)
from scripts.market_scheduler import (
    SUCCESS_STATUSES,
    _edge_task_for_request,
    create_run_state,
    evaluate_global_status,
    finalize_run,
    pure_search_seconds,
    run_backend_tasks,
)


FULL_WINDOW_IDLE_WAIT_SECONDS = 2.0


@dataclass(frozen=True)
class DriverDependencies:
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    preflight: Callable[[float], Mapping[str, object]]
    create_state: Callable[..., MutableMapping[str, object]]
    evaluate: Callable[[dict[str, object]], str]
    run_tasks: Callable[..., object]
    finalize: Callable[[dict[str, object]], object]
    discovery_seconds: Callable[[Mapping[str, object]], float]
    emit: Callable[[str], object]
    open_edge_session: Callable[..., object] | None = None


@dataclass(frozen=True)
class DriverResult:
    exit_code: int
    summary: Mapping[str, object]


DEFAULT_DEPENDENCIES = DriverDependencies(
    monotonic=time.perf_counter,
    sleep=time.sleep,
    preflight=probe_edge_background_bridge,
    create_state=create_run_state,
    evaluate=evaluate_global_status,
    run_tasks=run_backend_tasks,
    finalize=finalize_run,
    discovery_seconds=pure_search_seconds,
    emit=lambda message: print(message, flush=True),
    open_edge_session=edge_marketplace_session_adapter,
)


_TOPIC_SEPARATOR = re.compile(r"[,，;；\n\r]+")


def normalize_topics(values: Sequence[str] | str) -> tuple[str, ...]:
    """Normalize repeated CLI values and common Chinese list separators."""
    raw_values = (values,) if isinstance(values, str) else tuple(values)
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        if not isinstance(raw, str):
            raise ValueError("topic values must be strings")
        for part in _TOPIC_SEPARATOR.split(raw):
            topic = " ".join(part.split())
            if topic and topic not in seen:
                seen.add(topic)
                normalized.append(topic)
    if not normalized:
        raise ValueError("topic must contain at least one non-empty value")
    return tuple(normalized)


def _seed_edge_tasks(
    topics: Sequence[str],
    *,
    platforms: tuple[str, ...],
    query_budget: int,
    max_pages_per_topic: int = 1,
    pagination_enabled: bool = False,
    user_data_dir: str | None = None,
) -> tuple[dict[str, object], ...]:
    """Build fail-closed page tasks in topic-major sequential page order."""
    if not 1 <= max_pages_per_topic <= 20:
        raise ValueError("max_pages_per_topic must be from 1 to 20")
    effective_pages = max_pages_per_topic if pagination_enabled else 1
    page_numbers = tuple(range(1, effective_pages + 1))
    seeded: list[dict[str, object]] = []
    for topic in topics:
        dimensions = MarketplaceQueryDimensions(topic=topic)
        batch = edge_task_batch(
            dimensions,
            offset=0,
            limit=min(max(1, query_budget), 64),
            platforms=platforms,
            page_numbers=page_numbers,
            pagination_enabled=pagination_enabled,
            user_data_dir=user_data_dir,
        )
        for task in batch:
            seeded.append(deepcopy(task))
    topic_order = {topic: index for index, topic in enumerate(topics)}
    seeded.sort(
        key=lambda task: (
            topic_order[str(task["payload"]["query"])],
            int(task["payload"]["cursor"]["page_number"]),
            int(task["payload"]["cursor"]["ordinal"]),
        )
    )
    for sequence_index, task in enumerate(seeded):
        task["sequence_index"] = sequence_index
    return tuple(seeded)


def _seed_resilient_edge_state(
    topics: Sequence[str],
    *,
    platforms: tuple[str, ...],
    pagination_enabled: bool,
    jd_debug_page_limit: int | None = None,
    user_data_dir: str | None = None,
) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    """Seed only the continuation head; all later JD pages stay lazy."""
    if platforms != ("jd",):
        raise ValueError("resilient JD continuation requires platforms=('jd',)")
    if not pagination_enabled:
        raise ValueError("resilient JD continuation requires pagination")
    if jd_debug_page_limit is not None and not 1 <= jd_debug_page_limit <= 512:
        raise ValueError("jd_debug_page_limit must be from 1 to 512")
    continuation = new_continuation(topics)
    request = current_request(continuation)
    if request is None:  # pragma: no cover - new_continuation always has page one
        raise ValueError("new JD continuation has no current request")
    return (
        deepcopy(_edge_task_for_request(request, user_data_dir=user_data_dir)),
    ), continuation


def _parse_page_limit(value: str) -> str | int:
    normalized = value.strip().casefold()
    if normalized == "auto":
        return "auto"
    try:
        page_limit = int(normalized)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "must be 'auto' or an integer from 1 to 512"
        ) from error
    if not 1 <= page_limit <= 512:
        raise argparse.ArgumentTypeError(
            "must be 'auto' or an integer from 1 to 512"
        )
    return page_limit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unattended JD slow-lane discovery"
    )
    parser.add_argument(
        "--topic",
        required=True,
        action="append",
        help="搜索话题；可重复，并支持中英文逗号、分号或换行分隔",
    )
    parser.add_argument("--platforms", default="jd")
    parser.add_argument("--search-limit-seconds", type=float, default=600.0)
    parser.add_argument("--jd-slow-lane", action="store_true", default=True)
    parser.add_argument("--ledger", required=True, help="path to the run.sqlite")
    parser.add_argument(
        "--query-budget", type=int, default=256,
        help="bounded in-memory Edge cursor/page tasks (1-512)",
    )
    parser.add_argument("--max-tasks", type=int, default=8)
    parser.add_argument("--enable-jd-pagination", action="store_true")
    parser.add_argument(
        "--max-pages-per-topic",
        type=_parse_page_limit,
        default=2,
        help=(
            "per-topic page cap from 1 to 512 (default 2: breadth-first, the "
            "risk-safe shape; deep pagination past page 2 is a strong JD "
            "behavioral signal). 'auto' removes the cap for depth experiments"
        ),
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--bridge-preflight-seconds", type=float, default=60.0)
    parser.add_argument(
        "--jd-pagination-route",
        default="experimental_url",
        choices=[
            "existing",
            "public_control",
            "numbered_link",
            "page_jump",
            "infinite_scroll",
            "experimental_url",
            "human_flow",
        ],
        help=(
            "JD pagination route for this run (default: experimental_url, the "
            "promoted foreground direct-URL route). Overrides extension "
            "storage for legacy/research routes. human_flow starts on the "
            "www.jd.com homepage then searches with a from=home URL and flips "
            "pages by clicking the real .pn-next control."
        ),
    )
    parser.add_argument("--wall-limit-seconds", type=float, default=None)
    parser.add_argument(
        "--min-run-gap-seconds",
        type=float,
        default=1800.0,
        help=(
            "campaign gate: minimum wall-clock seconds between consecutive runs "
            "sharing one ledger (default 1800). Refuses to start early so runs do "
            "not stack inside JD's risk window."
        ),
    )
    parser.add_argument(
        "--hard-block-cooldown-seconds",
        type=float,
        default=3600.0,
        help=(
            "campaign gate: seconds to refuse a new run after JD hard risk-control "
            "(default 3600 = 1h, mirrors the extension's breaker)."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="bypass the campaign spacing gate for this run",
    )
    parser.add_argument(
        "--append-ledger",
        action="store_true",
        help=(
            "reuse an existing run.sqlite so URL dedup accumulates across a "
            "campaign (default: fresh ledger per run)"
        ),
    )
    parser.add_argument(
        "--user-data-dir",
        default=None,
        help=(
            "owned Edge profile directory (must end in 'edge-profile'). Bring it up "
            "with launch_edge_profile.py (loads the bundled extension + gives it its "
            "own broker pipe); the driver probes and runs on that profile. Alternating "
            "profiles across spaced runs spreads JD's behavioral risk budget."
        ),
    )
    parser.add_argument(
        "--watchdog-child", action="store_true", help=argparse.SUPPRESS
    )
    return parser


def _terminate_owned_tree(process: object) -> None:
    pid = getattr(process, "pid", None)
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("watchdog child must expose a positive pid")
    if os.name == "nt":
        taskkill = (
            Path(os.environ.get("SystemRoot", r"C:\Windows"))
            / "System32"
            / "taskkill.exe"
        )
        subprocess.run(
            [str(taskkill), "/PID", str(pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10.0,
        )
    else:  # pragma: no cover - Edge route is Windows-only
        terminate = getattr(process, "terminate", None)
        if callable(terminate):
            terminate()
    wait = getattr(process, "wait", None)
    if callable(wait):
        try:
            wait(timeout=5.0)
        except (subprocess.TimeoutExpired, TypeError):
            kill = getattr(process, "kill", None)
            if callable(kill):
                kill()


def _run_watchdog(
    argv: list[str],
    args: argparse.Namespace,
    *,
    spawn: Callable[[list[str]], object] | None = None,
    terminate_tree: Callable[[object], None] = _terminate_owned_tree,
) -> int:
    command = [sys.executable, str(Path(__file__).resolve()), *argv]
    if "--watchdog-child" not in command:
        command.append("--watchdog-child")
    process = (
        spawn(command)
        if spawn is not None
        else subprocess.Popen(
            command,
            cwd=str(Path(__file__).resolve().parents[1]),
            stdin=subprocess.DEVNULL,
        )
    )
    wait = getattr(process, "wait", None)
    if not callable(wait):
        raise TypeError("watchdog child must provide wait(timeout=...)")
    wall_limit = (
        float(args.wall_limit_seconds)
        if args.wall_limit_seconds is not None
        else float(args.search_limit_seconds) + 300.0
    )
    timeout = float(args.bridge_preflight_seconds) + wall_limit + 5.0
    try:
        return int(wait(timeout=timeout))
    except subprocess.TimeoutExpired:
        terminate_tree(process)
        print(
            json.dumps(
                {
                    "status": "watchdog_wall_timeout",
                    "wall_limit_seconds": wall_limit,
                    "preflight_limit_seconds": float(
                        args.bridge_preflight_seconds
                    ),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 1


def _future_cooldown_delay(state: Mapping[str, object], now: float) -> float | None:
    plan = state.get("marketplace_plan")
    if not isinstance(plan, Mapping):
        return None
    cool_until = plan.get("platform_cool_until")
    if not isinstance(cool_until, Mapping):
        return None
    future = [
        float(value)
        for value in cool_until.values()
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) > now
    ]
    return min(future) - now if future else None


def _campaign_path(ledger: Path) -> Path:
    """The campaign sidecar lives next to the shared ledger."""
    return ledger.with_suffix(".campaign.json")


def _load_campaign(ledger: Path) -> dict[str, object]:
    path = _campaign_path(ledger)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_campaign(ledger: Path, campaign: Mapping[str, object]) -> None:
    path = _campaign_path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(campaign, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _campaign_gate(
    ledger: Path,
    *,
    min_run_gap_seconds: float,
    hard_block_cooldown_seconds: float,
    force: bool,
) -> dict[str, object] | None:
    """Enforce spacing between runs that share one ledger.

    Returns a gated summary when the run must not start yet, or ``None`` when it
    may proceed (updating the sidecar's ``last_run_started_at``). The gate is the
    durable, cross-process counterpart to the extension's 60-minute breaker: it
    refuses before preflight, so a throttled session is never woken and a fresh
    window is never wasted.
    """
    campaign = _load_campaign(ledger)
    now = time.time()
    retry_after = 0.0
    reason: str | None = None
    last_hard_block = campaign.get("last_hard_block_at")
    if (
        not force
        and isinstance(last_hard_block, (int, float))
        and not isinstance(last_hard_block, bool)
    ):
        remaining = float(last_hard_block) + hard_block_cooldown_seconds - now
        if remaining > 0:
            reason = "hard_block_cooldown"
            retry_after = remaining
    if reason is None and not force:
        last_run_started = campaign.get("last_run_started_at")
        if (
            isinstance(last_run_started, (int, float))
            and not isinstance(last_run_started, bool)
        ):
            remaining = float(last_run_started) + min_run_gap_seconds - now
            if remaining > 0:
                reason = "run_gap"
                retry_after = remaining
    if reason is not None:
        return {
            "status": "campaign_gated",
            "reason": reason,
            "retry_after_seconds": round(max(0.0, retry_after), 1),
            "ledger_path": str(ledger),
            "campaign_file": str(_campaign_path(ledger)),
            "min_run_gap_seconds": min_run_gap_seconds,
            "hard_block_cooldown_seconds": hard_block_cooldown_seconds,
        }
    _save_campaign(
        ledger,
        {
            **campaign,
            "schema_version": 1,
            "last_run_started_at": now,
            "run_count": int(campaign.get("run_count", 0)) + 1,
        },
    )
    return None


def _record_campaign_hard_block(ledger: Path) -> None:
    """Note a hard risk-control hit so later runs gate behind the cooldown."""
    campaign = _load_campaign(ledger)
    _save_campaign(
        ledger,
        {
            **campaign,
            "schema_version": 1,
            "last_hard_block_at": time.time(),
        },
    )


# 一旦出现这些不可重试的桥/扩展类别，driver 立即以真实原因终止，而不是在
# 恢复探针永不 armed 的 blocked 来源上空转三轮回合并误报 unrecoverable_no_progress。
FATAL_EDGE_CATEGORIES = frozenset(
    {
        "edge_extension_reload_required",
        "edge_extension_message_invalid",
        "edge_extension_projection_invalid",
        "edge_native_message_invalid",
        "edge_operation_unsupported",
        "edge_worker_start_failed",
        "edge_background_bridge_unavailable",
        "edge_remote_debugging_disabled",
        "edge_active_port_invalid",
    }
)


def _distinct_failure_categories(
    state: Mapping[str, object],
) -> dict[str, int]:
    """Return error_category -> count from scheduler failures (compact, safe).

    ``run_backend_tasks`` records every failed attempt in ``state["failures"]``
    with an ``error_category`` (e.g. ``edge_extension_reload_required`` or
    ``edge_background_bridge_unavailable``).  The driver must surface these so an
    instant "all attempts failed" run is diagnosed as the real bridge/extension
    fault instead of a misleading ``unrecoverable_no_progress``.
    """
    failures = state.get("failures")
    if not isinstance(failures, list):
        return {}
    counts: dict[str, int] = {}
    for item in failures:
        if not isinstance(item, Mapping):
            continue
        category = item.get("error_category")
        if isinstance(category, str) and category:
            counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))


def _marketplace_acceptance(
    state: Mapping[str, object],
) -> tuple[int, bool]:
    discovery = state.get("marketplace_discovery")
    if not isinstance(discovery, Mapping):
        return 0, False
    raw_count = discovery.get("total_unique_candidates", 0)
    count = (
        raw_count
        if isinstance(raw_count, int) and not isinstance(raw_count, bool)
        else 0
    )
    decision = discovery.get("decision")
    accepted = (
        isinstance(decision, Mapping)
        and decision.get("acceptance_passed") is True
    )
    return count, accepted


def _jd_platform_blocked(state: Mapping[str, object]) -> bool:
    plan = state.get("marketplace_plan")
    health = plan.get("platform_health") if isinstance(plan, Mapping) else None
    return isinstance(health, Mapping) and health.get("jd") == "blocked"


def _all_jd_first_pages_failed(state: Mapping[str, object]) -> bool:
    plan = state.get("jd_continuation")
    if not isinstance(plan, Mapping) or plan.get("complete") is not True:
        return False
    families = plan.get("families")
    abandoned = plan.get("abandoned_families")
    counters = state.get("counters")
    successful_pages = (
        int(counters.get("successful_pages", 0))
        if isinstance(counters, Mapping)
        else 0
    )
    return (
        isinstance(families, list)
        and isinstance(abandoned, list)
        and len(families) > 0
        and len(abandoned) >= len(families)
        and int(plan.get("page_number", 0)) == 1
        and successful_pages == 0
    )


def run_sustained(
    args: argparse.Namespace,
    *,
    dependencies: DriverDependencies = DEFAULT_DEPENDENCIES,
) -> DriverResult:
    with ExitStack() as edge_session_stack:
        return _run_sustained(
            args,
            dependencies=dependencies,
            edge_session_stack=edge_session_stack,
        )


def _run_sustained(
    args: argparse.Namespace,
    *,
    dependencies: DriverDependencies,
    edge_session_stack: ExitStack,
) -> DriverResult:
    ledger = Path(args.ledger).resolve()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    min_run_gap_seconds = float(getattr(args, "min_run_gap_seconds", 1800.0))
    hard_block_cooldown_seconds = float(
        getattr(args, "hard_block_cooldown_seconds", 3600.0)
    )
    force = bool(getattr(args, "force", False))
    append_ledger = bool(getattr(args, "append_ledger", False))
    user_data_dir = getattr(args, "user_data_dir", None)
    gated = _campaign_gate(
        ledger,
        min_run_gap_seconds=min_run_gap_seconds,
        hard_block_cooldown_seconds=hard_block_cooldown_seconds,
        force=force,
    )
    if gated is not None:
        dependencies.emit(json.dumps(gated, ensure_ascii=False, indent=2))
        return DriverResult(3, gated)
    if user_data_dir:
        # An explicit profile always runs on its own broker pipe so a fresh
        # campaign never contends with the real Edge extension for one pipe.
        pipe_override = edge_pipe_path(user_data_dir)
        if pipe_override:
            os.environ["SAT_EDGE_PIPE_PATH"] = pipe_override
    dependencies.preflight(float(args.bridge_preflight_seconds))
    if getattr(args, "jd_pagination_route", None) is not None:
        # Propagates to the one-shot Node worker (edge_extension_client.mjs),
        # which injects it into the broker task message. No payload change.
        os.environ["SAT_JD_PAGINATION_ROUTE"] = str(args.jd_pagination_route)
    if ledger.exists() and not append_ledger:
        ledger.unlink()
    run_id = args.run_id or f"jd-slow-{uuid.uuid4().hex[:8]}"
    platforms = tuple(item.strip() for item in args.platforms.split(",") if item.strip())
    topics = normalize_topics(args.topic)
    debug_page_limit = (
        args.max_pages_per_topic
        if isinstance(args.max_pages_per_topic, int)
        else None
    )
    continuation: dict[str, object] | None = None
    if args.enable_jd_pagination:
        edge_tasks, continuation = _seed_resilient_edge_state(
            topics,
            platforms=platforms,
            pagination_enabled=True,
            jd_debug_page_limit=debug_page_limit,
            user_data_dir=user_data_dir,
        )
    else:
        edge_tasks = _seed_edge_tasks(
            topics,
            platforms=platforms,
            query_budget=args.query_budget,
            max_pages_per_topic=1,
            pagination_enabled=False,
            user_data_dir=user_data_dir,
        )
    started = dependencies.monotonic()
    wall_limit = (
        float(args.wall_limit_seconds)
        if args.wall_limit_seconds is not None
        else float(args.search_limit_seconds) + 300.0
    )
    deadline = started + wall_limit
    config = {
        "run_kind": "market_discovery",
        "run_type": "catalog_enumeration",
        "search_limit_seconds": args.search_limit_seconds,
        "topic": ",".join(topics),
        "scope_fingerprint": f"{','.join(topics)}:{','.join(platforms)}",
        "ledger_path": str(ledger),
        "applicable_sources": ["marketplace_list", "search_engine"],
        "marketplace_plan": {
            "topic_dimensions": [{"topic": topic} for topic in topics],
            "platforms": list(platforms),
            "batch_size": 8,
            "jd_slow_lane": args.jd_slow_lane,
        },
        "source_pool": list(edge_tasks),
        "jd_full_window": True,
        "wall_deadline": deadline,
    }
    if continuation is not None:
        config["jd_continuation"] = continuation
    if debug_page_limit is not None:
        config["jd_debug_page_limit"] = debug_page_limit
    state = dependencies.create_state(config, run_id=run_id)
    state.setdefault("jd_full_window", True)
    if continuation is not None:
        state.setdefault("jd_continuation", deepcopy(continuation))
    if debug_page_limit is not None:
        state.setdefault("jd_debug_page_limit", debug_page_limit)
    state["wall_deadline"] = deadline
    # 慢速车道验收按墙钟窗口计（pacing 是刻意的，不算空闲）；driver 记录单调
    # 起点，调度器用 _wall_elapsed_seconds 换算已消耗窗口。
    state["wall_started_at"] = started
    rounds = 0
    terminal_reason = "wall_limit_reached"
    last_status: str | None = None
    next_heartbeat = started + 60.0
    consecutive_no_progress = 0
    failed_rounds = 0
    shared_edge_adapter: object | None = None
    edge_session_started = False

    def run_scheduler_tasks() -> object:
        nonlocal edge_session_started, shared_edge_adapter
        if dependencies.open_edge_session is None:
            return dependencies.run_tasks(state, max_tasks=args.max_tasks)
        if not edge_session_started:
            session_context = dependencies.open_edge_session(
                wall_deadline=deadline
            )
            shared_edge_adapter = edge_session_stack.enter_context(
                session_context
            )
            edge_session_started = True
        return dependencies.run_tasks(
            state,
            max_tasks=args.max_tasks,
            edge_session_adapter=shared_edge_adapter,
        )

    while True:
        now = dependencies.monotonic()
        if now >= deadline:
            status = dependencies.evaluate(state)
            break
        status = dependencies.evaluate(state)
        if status != last_status or now >= next_heartbeat:
            dependencies.emit(f"[jd-slow] round={rounds} status={status}")
            last_status = status
            next_heartbeat = now + 60.0
        if status in SUCCESS_STATUSES and not (
            state.get("jd_full_window") is True
            and status in {"search_saturated", "deterministic_scope_complete"}
        ):
            terminal_reason = status
            break
        if _jd_platform_blocked(state):
            terminal_reason = "jd_hard_blocked"
            break
        if _all_jd_first_pages_failed(state):
            terminal_reason = "all_jd_query_families_failed_on_first_page"
            break
        cooldown_delay = _future_cooldown_delay(state, now)
        if cooldown_delay is not None:
            dependencies.sleep(min(cooldown_delay, deadline - now))
            continue
        if status == "incomplete_blocked":
            continuation_plan = state.get("jd_continuation")
            if isinstance(continuation_plan, Mapping) and not bool(
                continuation_plan.get("complete")
            ):
                pass
            else:
            # 慢道验收按墙钟窗口计：若已收集候选但任务暂时耗尽，继续等到 wall
            # deadline 让窗口跑满（到期 evaluate 按墙钟判 ten_minute_limit + acceptance）；
            # 若零候选且无路可走，立即以 unrecoverable_blocked 退出，不空转。
                candidate_count, _ = _marketplace_acceptance(state)
                if candidate_count > 0:
                    dependencies.sleep(min(2.0, deadline - dependencies.monotonic()))
                    continue
                terminal_reason = "unrecoverable_blocked"
                break
        before_failures = len(state.get("failures", [])) if isinstance(
            state.get("failures"), list
        ) else 0
        try:
            task_results = run_scheduler_tasks()
            after_failures = len(state.get("failures", [])) if isinstance(
                state.get("failures"), list
            ) else 0
            new_failures = max(0, after_failures - before_failures)
            if task_results != ():
                consecutive_no_progress = 0
                failed_rounds = 0
            elif new_failures > 0:
                # 本轮确实尝试了任务但全部失败：这是桥/扩展被拦截，不是"无任务可做"。
                # 不把"全部失败"误算成"连续零任务"；用失败类别直接给出诊断。
                consecutive_no_progress = 0
                failed_rounds += 1
            else:
                consecutive_no_progress += 1
        except Exception as error:
            status = dependencies.evaluate(state)
            terminal_reason = (
                f"scheduler_exception:{type(error).__name__.casefold()}"
            )
            dependencies.emit(
                "[jd-slow] stopped: run_backend_tasks raised "
                f"{type(error).__name__}: {error}"
            )
            break
        rounds += 1
        if state.get("wall_budget_exhausted") is True:
            remaining = max(0.0, deadline - dependencies.monotonic())
            if remaining > 0:
                dependencies.sleep(remaining)
            status = dependencies.evaluate(state)
            terminal_reason = "wall_limit_reached"
            break
        if _jd_platform_blocked(state):
            status = dependencies.evaluate(state)
            terminal_reason = "jd_hard_blocked"
            break
        if _all_jd_first_pages_failed(state):
            status = dependencies.evaluate(state)
            terminal_reason = "all_jd_query_families_failed_on_first_page"
            break
        failure_categories = _distinct_failure_categories(state)
        if failure_categories and any(
            category in FATAL_EDGE_CATEGORIES for category in failure_categories
        ):
            status = dependencies.evaluate(state)
            top = next(
                category
                for category in failure_categories
                if category in FATAL_EDGE_CATEGORIES
            )
            terminal_reason = f"edge_fault:{top}"
            dependencies.emit(
                "[jd-slow] stopped: fatal Edge bridge/extension fault "
                f"categories={failure_categories}"
            )
            break
        if (
            state.get("jd_full_window") is not True
            and failed_rounds >= 3
            and failure_categories
        ):
            status = dependencies.evaluate(state)
            top = max(failure_categories, key=failure_categories.get)
            terminal_reason = f"edge_attempts_failed:{top}"
            dependencies.emit(
                "[jd-slow] stopped: all edge attempts failed "
                f"categories={failure_categories}"
            )
            break
        if (
            state.get("jd_full_window") is not True
            and consecutive_no_progress >= 3
        ):
            status = dependencies.evaluate(state)
            terminal_reason = "unrecoverable_no_progress"
            dependencies.emit(
                "[jd-slow] stopped after 3 consecutive zero-task rounds"
            )
            break
        if consecutive_no_progress >= 3:
            dependencies.sleep(
                min(
                    FULL_WINDOW_IDLE_WAIT_SECONDS,
                    max(0.0, deadline - dependencies.monotonic()),
                )
            )
    elapsed = dependencies.monotonic() - started
    unique_candidates, acceptance_passed = _marketplace_acceptance(state)
    reached_success = status in SUCCESS_STATUSES and (
        status != "ten_minute_limit" or acceptance_passed
    )
    if status == "ten_minute_limit" and not acceptance_passed:
        terminal_reason = "acceptance_failed"
    if reached_success:
        dependencies.finalize(state)
    failure_categories = _distinct_failure_categories(state)
    if (
        terminal_reason == "jd_hard_blocked"
        or any(
            category in HARD_JD_FAILURE_CATEGORIES
            for category in failure_categories
        )
    ):
        _record_campaign_hard_block(ledger)
    summary = {
        "run_id": run_id,
        "status": status,
        "rounds": rounds,
        "wall_seconds": round(elapsed, 1),
        "wall_limit_seconds": wall_limit,
        "search_limit_seconds": float(args.search_limit_seconds),
        "discovery_seconds": dependencies.discovery_seconds(state),
        "ledger_path": str(ledger),
        "reached_success": reached_success,
        "unique_candidates": unique_candidates,
        "acceptance_passed": acceptance_passed,
        "terminal_reason": terminal_reason,
        "failure_categories": failure_categories,
        "campaign": {
            "ledger_appended": append_ledger,
            "user_data_dir": user_data_dir or "default",
            "min_run_gap_seconds": min_run_gap_seconds,
            "hard_block_cooldown_seconds": hard_block_cooldown_seconds,
        },
    }
    dependencies.emit(json.dumps(summary, ensure_ascii=False, indent=2))
    return DriverResult(0 if reached_success else 1, summary)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw_argv)
    wall_limit = (
        float(args.wall_limit_seconds)
        if args.wall_limit_seconds is not None
        else float(args.search_limit_seconds) + 300.0
    )
    if args.search_limit_seconds <= 0:
        parser.error("--search-limit-seconds must be positive")
    if args.bridge_preflight_seconds <= 0:
        parser.error("--bridge-preflight-seconds must be positive")
    if not 1 <= args.query_budget <= 512:
        parser.error("--query-budget must be from 1 to 512")
    if args.max_pages_per_topic != "auto" and not (
        isinstance(args.max_pages_per_topic, int)
        and 1 <= args.max_pages_per_topic <= 512
    ):
        parser.error("--max-pages-per-topic must be auto or from 1 to 512")
    if wall_limit < args.search_limit_seconds:
        parser.error("--wall-limit-seconds must be at least --search-limit-seconds")
    if args.min_run_gap_seconds < 0:
        parser.error("--min-run-gap-seconds must be non-negative")
    if args.hard_block_cooldown_seconds < 0:
        parser.error("--hard-block-cooldown-seconds must be non-negative")
    if not args.watchdog_child:
        return _run_watchdog(raw_argv, args)
    try:
        return run_sustained(args).exit_code
    except EdgeWorkerFailure as error:
        print(
            json.dumps(
                {
                    "status": "preflight_failed",
                    "error_category": error.category,
                    "retryable": error.retryable,
                },
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
