from __future__ import annotations

import argparse
from collections import deque
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
import typing
from unittest.mock import patch

import scripts.run_jd_sustained as jd_driver
from scripts.domestic_marketplace_query import (
    MarketplaceQueryDimensions,
    edge_pipe_path,
)
from scripts.run_jd_sustained import (
    DriverDependencies,
    _run_watchdog,
    _seed_edge_tasks,
    main,
    run_sustained,
)
from scripts.edge_marketplace_query import EdgeWorkerFailure
from scripts.market_scheduler import create_run_state, rank_source_tasks


class FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class SustainedDriverTests(unittest.TestCase):
    def test_topic_normalizer_type_hints_resolve_at_runtime(self):
        hints = typing.get_type_hints(jd_driver.normalize_topics)

        self.assertIn("values", hints)

    def test_topic_normalization_accepts_cli_forms_and_deduplicates(self) -> None:
        cases = (
            (["枕头,枕芯"], ("枕头", "枕芯")),
            (["枕头，枕芯"], ("枕头", "枕芯")),
            (["枕头;枕芯\n记忆棉枕"], ("枕头", "枕芯", "记忆棉枕")),
            ([" 枕头 ", "枕芯", "枕头"], ("枕头", "枕芯")),
        )
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(jd_driver.normalize_topics(values), expected)

    def test_topic_normalization_rejects_empty_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "topic"):
            jd_driver.normalize_topics(["， ; \n"])

    def test_parser_preserves_repeated_topic_flags(self) -> None:
        args = jd_driver._parser().parse_args(
            ["--topic", "枕头", "--topic", "枕芯", "--ledger", "probe.sqlite"]
        )
        self.assertEqual(args.topic, ["枕头", "枕芯"])

    def test_watchdog_terminates_owned_child_after_preflight_plus_wall(self) -> None:
        observed: dict[str, object] = {}

        class Process:
            pid = 1234

            def wait(self, *, timeout):
                observed["timeout"] = timeout
                raise subprocess.TimeoutExpired("driver", timeout)

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = _run_watchdog(
                ["--topic", "枕头", "--ledger", "probe.sqlite"],
                self.args(
                    Path("probe.sqlite"),
                    bridge_preflight_seconds=60.0,
                    wall_limit_seconds=900.0,
                ),
                spawn=lambda command: (observed.setdefault("command", command), Process())[1],
                terminate_tree=lambda process: observed.setdefault("terminated", process),
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(observed["timeout"], 965.0)
        self.assertIsInstance(observed["terminated"], Process)
        self.assertIn("--watchdog-child", observed["command"])
        self.assertEqual(
            __import__("json").loads(output.getvalue())["status"],
            "watchdog_wall_timeout",
        )

    def test_multi_topic_materializes_one_first_page_task_each(self) -> None:
        tasks = _seed_edge_tasks(
            ["枕头", "枕芯", "记忆棉枕"],
            platforms=("jd",),
            query_budget=4,
        )

        # 每个话题一个第 1 页任务：3 个话题 → 3 个任务、3 个不同 cursor。
        self.assertEqual(len(tasks), 3)
        self.assertEqual(
            [task["payload"]["cursor"]["page_number"] for task in tasks],
            [1, 1, 1],
        )
        self.assertEqual(
            len({task["task_id"] for task in tasks}),
            3,
        )
        self.assertEqual(
            len({task["payload"]["cursor"]["cursor_id"] for task in tasks}),
            3,
        )

    def test_multi_topic_budget_caps_tasks_per_topic(self) -> None:
        tasks = _seed_edge_tasks(
            ["枕头", "枕芯"],
            platforms=("jd",),
            query_budget=1,
        )

        self.assertEqual(len(tasks), 2)
        self.assertEqual(
            [task["payload"]["cursor"]["page_number"] for task in tasks],
            [1, 1],
        )

    def test_pagination_is_default_off_and_explicitly_bounded(self) -> None:
        disabled = _seed_edge_tasks(
            ["枕头", "枕芯"],
            platforms=("jd",),
            query_budget=8,
            max_pages_per_topic=3,
            pagination_enabled=False,
        )
        enabled = _seed_edge_tasks(
            ["枕头", "枕芯"],
            platforms=("jd",),
            query_budget=8,
            max_pages_per_topic=3,
            pagination_enabled=True,
        )

        self.assertEqual(
            [task["payload"]["cursor"]["page_number"] for task in disabled],
            [1, 1],
        )
        self.assertEqual(
            [
                (
                    task["payload"]["query"],
                    task["payload"]["cursor"]["page_number"],
                )
                for task in enabled
            ],
            [
                ("枕头", 1),
                ("枕头", 2),
                ("枕头", 3),
                ("枕芯", 1),
                ("枕芯", 2),
                ("枕芯", 3),
            ],
        )
        self.assertEqual(
            [task["payload"]["session_action"] for task in enabled],
            ["start", "next", "next", "start", "next", "next"],
        )
        for topic in ("枕头", "枕芯"):
            topic_tasks = [task for task in enabled if task["payload"]["query"] == topic]
            self.assertEqual(len({task["payload"]["cursor"]["cursor_id"] for task in topic_tasks}), 1)
            self.assertEqual(len({task["task_id"] for task in topic_tasks}), 3)

    def test_parser_exposes_fail_closed_pagination_flags(self) -> None:
        parser = jd_driver._parser()
        safe = parser.parse_args(["--topic", "枕头", "--ledger", "probe.sqlite"])
        enabled = parser.parse_args(
            [
                "--topic", "枕头", "--ledger", "probe.sqlite",
                "--enable-jd-pagination", "--max-pages-per-topic", "3",
            ]
        )
        auto = parser.parse_args(
            [
                "--topic", "枕头", "--ledger", "probe.sqlite",
                "--enable-jd-pagination", "--max-pages-per-topic", "auto",
            ]
        )
        self.assertFalse(safe.enable_jd_pagination)
        # 2026-08-11 default is breadth-first (2 pages), not unbounded depth.
        self.assertEqual(safe.max_pages_per_topic, 2)
        self.assertEqual(auto.max_pages_per_topic, "auto")
        self.assertTrue(enabled.enable_jd_pagination)
        self.assertEqual(enabled.max_pages_per_topic, 3)

    def test_parser_accepts_jd_pagination_route_override(self) -> None:
        parser = jd_driver._parser()
        args = parser.parse_args(
            [
                "--topic", "枕头", "--ledger", "probe.sqlite",
                "--jd-pagination-route", "experimental_url",
            ]
        )
        self.assertEqual(args.jd_pagination_route, "experimental_url")
        for valid in ("experimental_url", "human_flow", "page_jump"):
            with self.subTest(route=valid):
                parsed = parser.parse_args(
                    [
                        "--topic", "枕头", "--ledger", "probe.sqlite",
                        "--jd-pagination-route", valid,
                    ]
                )
                self.assertEqual(parsed.jd_pagination_route, valid)
        for invalid in ("bogus", "try_everything"):
            with self.subTest(invalid=invalid), redirect_stderr(
                io.StringIO()
            ), self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "--topic", "枕头", "--ledger", "probe.sqlite",
                        "--jd-pagination-route", invalid,
                    ]
                )

    def test_jd_pagination_route_flag_propagates_to_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            args = self.args(Path(tmp) / "run.sqlite")
            args.jd_pagination_route = "experimental_url"
            saved = os.environ.get("SAT_JD_PAGINATION_ROUTE")
            try:
                run_sustained(
                    args,
                    dependencies=self.dependencies(
                        clock, state, ["incomplete_blocked"], calls
                    ),
                )
                self.assertEqual(
                    os.environ.get("SAT_JD_PAGINATION_ROUTE"),
                    "experimental_url",
                )
            finally:
                if saved is None:
                    os.environ.pop("SAT_JD_PAGINATION_ROUTE", None)
                else:
                    os.environ["SAT_JD_PAGINATION_ROUTE"] = saved

    def test_explicit_user_data_dir_sets_per_profile_pipe_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            args = self.args(Path(tmp) / "run.sqlite")
            profile = "/tmp/profile-b/edge-profile"
            args.user_data_dir = profile
            expected = edge_pipe_path(profile)
            self.assertIsNotNone(expected)
            saved = os.environ.get("SAT_EDGE_PIPE_PATH")
            try:
                run_sustained(
                    args,
                    dependencies=self.dependencies(
                        clock, state, ["incomplete_blocked"], calls
                    ),
                )
                self.assertEqual(os.environ.get("SAT_EDGE_PIPE_PATH"), expected)
            finally:
                if saved is None:
                    os.environ.pop("SAT_EDGE_PIPE_PATH", None)
                else:
                    os.environ["SAT_EDGE_PIPE_PATH"] = saved

    def test_default_user_data_dir_leaves_pipe_override_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            args = self.args(Path(tmp) / "run.sqlite")
            args.user_data_dir = None
            saved = os.environ.get("SAT_EDGE_PIPE_PATH")
            try:
                os.environ.pop("SAT_EDGE_PIPE_PATH", None)
                run_sustained(
                    args,
                    dependencies=self.dependencies(
                        clock, state, ["incomplete_blocked"], calls
                    ),
                )
                self.assertNotIn("SAT_EDGE_PIPE_PATH", os.environ)
            finally:
                if saved is None:
                    os.environ.pop("SAT_EDGE_PIPE_PATH", None)
                else:
                    os.environ["SAT_EDGE_PIPE_PATH"] = saved

    def test_driver_seeds_only_current_page_in_auto_mode(self) -> None:
        """Eager page ranges would violate the single-continuation-task contract."""
        self.assertTrue(hasattr(jd_driver, "_seed_resilient_edge_state"))
        tasks, continuation = jd_driver._seed_resilient_edge_state(
            ("机械键盘",),
            platforms=("jd",),
            pagination_enabled=True,
        )

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["payload"]["cursor"]["page_number"], 1)
        self.assertEqual(continuation["page_number"], 1)
        self.assertNotIn("debug_page_limit", continuation)

    def test_numeric_page_limit_is_outer_debug_configuration(self) -> None:
        """A debug cap must not add a non-whitelisted continuation field."""
        parser = jd_driver._parser()
        args = parser.parse_args(
            [
                "--topic", "机械键盘", "--ledger", "probe.sqlite",
                "--enable-jd-pagination", "--max-pages-per-topic", "512",
            ]
        )
        self.assertTrue(hasattr(jd_driver, "_seed_resilient_edge_state"))
        tasks, continuation = jd_driver._seed_resilient_edge_state(
            ("机械键盘",),
            platforms=("jd",),
            pagination_enabled=True,
            jd_debug_page_limit=args.max_pages_per_topic,
        )

        self.assertEqual(args.max_pages_per_topic, 512)
        self.assertEqual(len(tasks), 1)
        self.assertNotIn("debug_page_limit", continuation)
        for invalid in ("0", "513"):
            with self.subTest(invalid=invalid), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "--topic", "机械键盘", "--ledger", "probe.sqlite",
                        "--max-pages-per-topic", invalid,
                    ]
                )

    def test_scheduler_preserves_topic_major_numeric_page_order(self) -> None:
        tasks = _seed_edge_tasks(
            ["话题A", "话题B"],
            platforms=("jd",),
            query_budget=32,
            max_pages_per_topic=12,
            pagination_enabled=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            state = create_run_state(
                {
                    "run_kind": "market_discovery",
                    "run_type": "catalog_enumeration",
                    "search_limit_seconds": 600,
                    "topic": "话题A,话题B",
                    "scope_fingerprint": "topic-major-order",
                    "ledger_path": str(Path(tmp) / "run.sqlite"),
                    "applicable_sources": ["marketplace_list"],
                    "marketplace_plan": {
                        "topic_dimensions": [{"topic": "话题A"}, {"topic": "话题B"}],
                        "platforms": ["jd"],
                        "batch_size": 8,
                        "jd_slow_lane": True,
                    },
                    "source_pool": list(tasks),
                },
                run_id="topic-major-order",
            )
        ranked = [
            task for task in rank_source_tasks(state)
            if task.get("adapter") == "edge_marketplace"
        ]
        self.assertEqual(
            [
                (task["payload"]["query"], task["payload"]["cursor"]["page_number"])
                for task in ranked
            ],
            [
                (topic, page)
                for topic in ("话题A", "话题B")
                for page in range(1, 13)
            ],
        )

    def test_main_reports_preflight_failure_as_compact_json(self) -> None:
        output = io.StringIO()
        failure = EdgeWorkerFailure(
            "edge_background_bridge_unavailable", True, "not connected"
        )
        with patch(
            "scripts.run_jd_sustained.run_sustained", side_effect=failure
        ), redirect_stdout(output):
            exit_code = main(
                [
                    "--watchdog-child",
                    "--topic", "枕头",
                    "--ledger", "probe.sqlite",
                ]
            )

        self.assertEqual(exit_code, 2)
        value = __import__("json").loads(output.getvalue())
        self.assertEqual(value["status"], "preflight_failed")
        self.assertEqual(
            value["error_category"], "edge_background_bridge_unavailable"
        )
        self.assertNotIn("traceback", output.getvalue().casefold())

    def test_main_accepts_equal_search_and_wall_limits_for_exact_window(self) -> None:
        with patch(
            "scripts.run_jd_sustained._run_watchdog", return_value=17
        ) as watchdog:
            exit_code = main(
                [
                    "--topic", "枕头",
                    "--ledger", "probe.sqlite",
                    "--search-limit-seconds", "600",
                    "--wall-limit-seconds", "600",
                ]
            )

        self.assertEqual(exit_code, 17)
        parsed = watchdog.call_args.args[1]
        self.assertEqual(parsed.search_limit_seconds, 600.0)
        self.assertEqual(parsed.wall_limit_seconds, 600.0)

    def args(self, ledger: Path, **overrides: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "topic": "枕头",
            "platforms": "jd",
            "search_limit_seconds": 600.0,
            "wall_limit_seconds": 900.0,
            "bridge_preflight_seconds": 60.0,
            "jd_slow_lane": True,
            "ledger": str(ledger),
            "query_budget": 1,
            "max_tasks": 1,
            "enable_jd_pagination": False,
            "max_pages_per_topic": 3,
            "run_id": "driver-test",
            "min_run_gap_seconds": 0.0,
            "hard_block_cooldown_seconds": 0.0,
            "force": False,
            "append_ledger": False,
            "user_data_dir": None,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def dependencies(
        self,
        clock: FakeClock,
        state: dict[str, object],
        statuses: list[str],
        calls: dict[str, object],
    ) -> DriverDependencies:
        queued = deque(statuses)

        def evaluate(value: dict[str, object]) -> str:
            del value
            if len(queued) > 1:
                return queued.popleft()
            return queued[0]

        def run_tasks(value: dict[str, object], *, max_tasks: int) -> None:
            del value, max_tasks
            calls["run_tasks"] = int(calls.get("run_tasks", 0)) + 1
            clock.now += 1.0

        def finalize(value: dict[str, object]) -> None:
            del value
            calls["finalize"] = int(calls.get("finalize", 0)) + 1

        return DriverDependencies(
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            preflight=lambda timeout: {"ok": True, "timeout": timeout},
            create_state=lambda config, run_id: state,
            evaluate=evaluate,
            run_tasks=run_tasks,
            finalize=finalize,
            discovery_seconds=lambda value: float(value.get("pure_seconds", 0.0)),
            emit=lambda message: calls.setdefault("logs", []).append(message),
        )

    def test_unrecoverable_blocked_exits_without_busy_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            result = run_sustained(
                self.args(Path(tmp) / "run.sqlite"),
                dependencies=self.dependencies(
                    clock, state, ["incomplete_blocked"], calls
                ),
            )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.summary["terminal_reason"], "unrecoverable_blocked")
        self.assertEqual(calls.get("run_tasks", 0), 0)
        self.assertLessEqual(result.summary["rounds"], 1)

    def test_running_without_executed_tasks_uses_full_wall_window(self) -> None:
        """Three recoverable zero-task rounds must not end the JD window early."""
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            dependencies = self.dependencies(
                clock, state, ["running"], calls
            )

            def no_tasks(value: dict[str, object], *, max_tasks: int) -> tuple[()]:
                del value, max_tasks
                calls["run_tasks"] = int(calls.get("run_tasks", 0)) + 1
                clock.now += 0.01
                return ()

            dependencies = DriverDependencies(
                **{**dependencies.__dict__, "run_tasks": no_tasks}
            )
            result = run_sustained(
                self.args(
                    Path(tmp) / "run.sqlite",
                    search_limit_seconds=0.05,
                    wall_limit_seconds=0.1,
                ),
                dependencies=dependencies,
            )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(
            result.summary["terminal_reason"], "wall_limit_reached"
        )
        self.assertEqual(calls["run_tasks"], 3)
        self.assertEqual(len(clock.sleeps), 1)
        self.assertAlmostEqual(clock.sleeps[0], 0.07)
        self.assertGreaterEqual(result.summary["wall_seconds"], 0.1)

    def test_full_window_recoverable_idle_is_bounded_without_busy_spin(self) -> None:
        """A no-progress 600 s window must wait, while still checking work periodically."""
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(0.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            dependencies = self.dependencies(clock, state, ["running"], calls)

            def no_tasks(value: dict[str, object], *, max_tasks: int) -> tuple[()]:
                del value, max_tasks
                calls["run_tasks"] = int(calls.get("run_tasks", 0)) + 1
                return ()

            dependencies = DriverDependencies(
                **{**dependencies.__dict__, "run_tasks": no_tasks}
            )
            result = run_sustained(
                self.args(
                    Path(tmp) / "run.sqlite",
                    search_limit_seconds=600.0,
                    wall_limit_seconds=600.0,
                ),
                dependencies=dependencies,
            )

        self.assertEqual(result.summary["wall_seconds"], 600.0)
        self.assertLessEqual(calls["run_tasks"], 305)
        self.assertGreater(calls["run_tasks"], 3)
        self.assertTrue(clock.sleeps)
        self.assertGreaterEqual(min(clock.sleeps), 1.0)

    def test_unexpected_scheduler_exception_stops_without_idle_spinning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(0.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_health": {"jd": "healthy"}}}
            dependencies = self.dependencies(clock, state, ["running"], calls)

            def missing_spool(value, *, max_tasks, **kwargs):
                del value, max_tasks, kwargs
                calls["run_tasks"] = int(calls.get("run_tasks", 0)) + 1
                raise FileNotFoundError("owned spool missing")

            dependencies = DriverDependencies(
                **{**dependencies.__dict__, "run_tasks": missing_spool}
            )
            result = run_sustained(
                self.args(
                    Path(tmp) / "run.sqlite",
                    search_limit_seconds=600.0,
                    wall_limit_seconds=600.0,
                ),
                dependencies=dependencies,
            )

        self.assertEqual(calls["run_tasks"], 1)
        self.assertEqual(
            result.summary["terminal_reason"],
            "scheduler_exception:filenotfounderror",
        )
        self.assertEqual(result.summary["wall_seconds"], 0.0)

    def test_new_transient_failure_wakes_recovery_after_prior_idle_rounds(self) -> None:
        """A real failure transition must clear an older no-task idle streak."""
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(0.0)
            calls: dict[str, object] = {}
            state = {
                "marketplace_plan": {"platform_cool_until": {"jd": 0.0}},
                "failures": [],
            }
            dependencies = self.dependencies(clock, state, ["running"], calls)
            outcomes = deque(("empty", "empty", "empty", "failure", "recovery"))
            call_times: list[float] = []

            def run_tasks(value: dict[str, object], *, max_tasks: int) -> object:
                del max_tasks
                call_times.append(clock.now)
                outcome = outcomes.popleft()
                if outcome == "failure":
                    value["failures"].append(
                        {"error_category": "pagination_page_transient_empty"}
                    )
                    return ()
                if outcome == "recovery":
                    clock.now = 10.0
                    return ("recovered",)
                return ()

            dependencies = DriverDependencies(
                **{**dependencies.__dict__, "run_tasks": run_tasks}
            )
            run_sustained(
                self.args(
                    Path(tmp) / "run.sqlite",
                    search_limit_seconds=10.0,
                    wall_limit_seconds=10.0,
                ),
                dependencies=dependencies,
            )

        self.assertEqual(len(call_times), 5)
        self.assertEqual(call_times[:4], [0.0, 0.0, 0.0, 2.0])
        self.assertEqual(call_times[4], call_times[3])

    def test_sustained_run_owns_one_edge_session_across_scheduler_rounds(self) -> None:
        """Creating a session per round would reset both CDP and pace state."""
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(0.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            dependencies = self.dependencies(clock, state, ["running"], calls)
            entries: list[tuple[str, float] | str] = []
            adapter = object()
            seen_adapters: list[object] = []

            @contextmanager
            def open_session(*, wall_deadline: float):
                entries.append(("enter", wall_deadline))
                try:
                    yield adapter
                finally:
                    entries.append("exit")

            def run_tasks(
                value: dict[str, object],
                *,
                max_tasks: int,
                edge_session_adapter: object,
            ) -> tuple[()]:
                del value, max_tasks
                seen_adapters.append(edge_session_adapter)
                clock.now += 1.0
                return ()

            dependencies = DriverDependencies(
                **{
                    **dependencies.__dict__,
                    "run_tasks": run_tasks,
                    "open_edge_session": open_session,
                }
            )
            run_sustained(
                self.args(
                    Path(tmp) / "run.sqlite",
                    search_limit_seconds=2.0,
                    wall_limit_seconds=2.0,
                ),
                dependencies=dependencies,
            )

        self.assertEqual(entries, [("enter", 2.0), "exit"])
        self.assertEqual(seen_adapters, [adapter, adapter])

    def test_sustained_session_receives_later_evaluate_exception_once(self) -> None:
        """A later driver failure must unwind an already-entered ordinary context."""
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(0.0)
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            calls: dict[str, object] = {}
            dependencies = self.dependencies(clock, state, ["running"], calls)
            exits: list[tuple[object, object, object]] = []
            evaluations = 0
            adapter = object()

            class SessionContext:
                def __enter__(self):
                    return adapter

                def __exit__(self, exc_type, exc, traceback):
                    exits.append((exc_type, exc, traceback))
                    return False

            def evaluate(value: dict[str, object]) -> str:
                nonlocal evaluations
                del value
                evaluations += 1
                if evaluations == 2:
                    raise RuntimeError("evaluate failed")
                return "running"

            def run_tasks(
                value: dict[str, object],
                *,
                max_tasks: int,
                edge_session_adapter: object,
            ) -> tuple[str]:
                del value, max_tasks
                self.assertIs(edge_session_adapter, adapter)
                return ("progress",)

            dependencies = DriverDependencies(
                **{
                    **dependencies.__dict__,
                    "evaluate": evaluate,
                    "run_tasks": run_tasks,
                    "open_edge_session": lambda **kwargs: SessionContext(),
                }
            )
            with self.assertRaisesRegex(RuntimeError, "evaluate failed"):
                run_sustained(
                    self.args(Path(tmp) / "run.sqlite"),
                    dependencies=dependencies,
                )

        self.assertEqual(len(exits), 1)
        self.assertIs(exits[0][0], RuntimeError)
        self.assertIsInstance(exits[0][1], RuntimeError)
        self.assertIsNotNone(exits[0][2])

    def test_failed_session_enter_never_dispatches_or_exits_unentered_context(self) -> None:
        """A failed __enter__ must not publish a None adapter or register __exit__."""
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(0.0)
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            calls: dict[str, object] = {}
            dependencies = self.dependencies(clock, state, ["running"], calls)
            enter_calls = 0
            exit_calls = 0
            dispatched: list[object] = []

            class FailingContext:
                def __enter__(self):
                    nonlocal enter_calls
                    enter_calls += 1
                    raise RuntimeError("enter failed")

                def __exit__(self, exc_type, exc, traceback):
                    nonlocal exit_calls
                    del exc_type, exc, traceback
                    exit_calls += 1
                    return False

            def run_tasks(
                value: dict[str, object],
                *,
                max_tasks: int,
                edge_session_adapter: object,
            ) -> tuple[()]:
                del value, max_tasks
                dispatched.append(edge_session_adapter)
                return ()

            dependencies = DriverDependencies(
                **{
                    **dependencies.__dict__,
                    "run_tasks": run_tasks,
                    "open_edge_session": lambda **kwargs: FailingContext(),
                }
            )
            run_sustained(
                self.args(
                    Path(tmp) / "run.sqlite",
                    search_limit_seconds=2.0,
                    wall_limit_seconds=2.0,
                ),
                dependencies=dependencies,
            )

        self.assertGreaterEqual(enter_calls, 1)
        self.assertEqual(dispatched, [])
        self.assertEqual(exit_calls, 0)

    def test_search_saturated_with_sixty_candidates_uses_full_window(self) -> None:
        """Candidate saturation is acceptance evidence, not an early JD stop."""
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {
                "marketplace_plan": {"platform_cool_until": {"jd": 0.0}},
                "marketplace_discovery": {
                    "enabled": True,
                    "total_unique_candidates": 60,
                    "decision": {"acceptance_passed": False},
                },
            }
            result = run_sustained(
                self.args(
                    Path(tmp) / "run.sqlite",
                    search_limit_seconds=2.0,
                    wall_limit_seconds=4.0,
                ),
                dependencies=self.dependencies(
                    clock, state, ["search_saturated"], calls
                ),
            )

        self.assertEqual(result.summary["terminal_reason"], "wall_limit_reached")
        self.assertGreater(calls.get("run_tasks", 0), 0)
        self.assertEqual(result.summary["unique_candidates"], 60)

    def test_first_page_family_failure_stop_requires_zero_verified_pages(self) -> None:
        """Later natural exhaustion must not masquerade as five failed page ones."""
        continuation = {
            "complete": True,
            "families": ["a", "b", "c", "d", "e"],
            "abandoned_families": ["a", "b", "c", "d", "e"],
            "page_number": 1,
        }
        self.assertTrue(
            jd_driver._all_jd_first_pages_failed(
                {
                    "jd_continuation": continuation,
                    "counters": {"successful_pages": 0},
                }
            )
        )
        self.assertFalse(
            jd_driver._all_jd_first_pages_failed(
                {
                    "jd_continuation": continuation,
                    "counters": {"successful_pages": 1},
                }
            )
        )

    def test_time_limit_without_marketplace_acceptance_is_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {
                "marketplace_plan": {"platform_cool_until": {"jd": 0.0}},
                "marketplace_discovery": {
                    "enabled": True,
                    "total_unique_candidates": 0,
                    "decision": {"acceptance_passed": False},
                },
            }
            result = run_sustained(
                self.args(Path(tmp) / "run.sqlite"),
                dependencies=self.dependencies(
                    clock, state, ["ten_minute_limit"], calls
                ),
            )

        self.assertEqual(result.exit_code, 1)
        self.assertFalse(result.summary["reached_success"])
        self.assertFalse(result.summary["acceptance_passed"])
        self.assertEqual(result.summary["unique_candidates"], 0)
        self.assertEqual(result.summary["terminal_reason"], "acceptance_failed")

    def test_wall_budget_exhaustion_waits_for_wall_deadline(self) -> None:
        """A near-deadline materialization guard is not an early-stop reason."""
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            dependencies = self.dependencies(clock, state, ["running"], calls)

            def exhaust_wall(value: dict[str, object], *, max_tasks: int) -> tuple[()]:
                del max_tasks
                calls["run_tasks"] = int(calls.get("run_tasks", 0)) + 1
                value["wall_budget_exhausted"] = True
                clock.now += 1.0
                return ()

            dependencies = DriverDependencies(
                **{**dependencies.__dict__, "run_tasks": exhaust_wall}
            )
            result = run_sustained(
                self.args(
                    Path(tmp) / "run.sqlite",
                    search_limit_seconds=1.0,
                    wall_limit_seconds=2.0,
                ),
                dependencies=dependencies,
            )

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.summary["terminal_reason"], "wall_limit_reached")
        self.assertGreaterEqual(result.summary["wall_seconds"], 2.0)
        self.assertEqual(calls["run_tasks"], 1)

    def test_failed_preflight_does_not_delete_existing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "run.sqlite"
            ledger.write_bytes(b"keep-me")
            clock = FakeClock(50.0)
            calls: dict[str, object] = {}
            dependencies = self.dependencies(
                clock,
                {"marketplace_plan": {}},
                ["incomplete_blocked"],
                calls,
            )

            def unavailable(timeout: float) -> dict[str, object]:
                del timeout
                raise EdgeWorkerFailure(
                    "edge_background_bridge_unavailable", True, "not connected"
                )

            dependencies = DriverDependencies(
                **{
                    **dependencies.__dict__,
                    "preflight": unavailable,
                }
            )
            with self.assertRaises(EdgeWorkerFailure):
                run_sustained(self.args(ledger), dependencies=dependencies)

            self.assertEqual(ledger.read_bytes(), b"keep-me")
            self.assertEqual(calls.get("run_tasks", 0), 0)

    def test_campaign_gate_blocks_when_run_gap_not_elapsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "run.sqlite"
            campaign = ledger.with_suffix(".campaign.json")
            now = 1_000_000.0
            campaign.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "last_run_started_at": now - 100.0,
                        "run_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            ledger.write_bytes(b"keep-me")
            clock = FakeClock(now)
            calls: dict[str, object] = {}
            args = self.args(
                ledger,
                min_run_gap_seconds=1800.0,
                hard_block_cooldown_seconds=3600.0,
            )
            with patch("scripts.run_jd_sustained.time.time", return_value=now):
                result = run_sustained(
                    args,
                    dependencies=self.dependencies(
                        clock, {"marketplace_plan": {}}, ["incomplete_blocked"], calls
                    ),
                )

            self.assertEqual(result.exit_code, 3)
            self.assertEqual(result.summary["status"], "campaign_gated")
            self.assertEqual(result.summary["reason"], "run_gap")
            self.assertAlmostEqual(result.summary["retry_after_seconds"], 1700.0)
            self.assertEqual(calls.get("run_tasks", 0), 0)
            self.assertEqual(ledger.read_bytes(), b"keep-me")
            self.assertEqual(
                json.loads(campaign.read_text(encoding="utf-8"))["run_count"], 1
            )

    def test_campaign_gate_allows_after_gap_and_records_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "run.sqlite"
            campaign = ledger.with_suffix(".campaign.json")
            now = 1_000_000.0
            campaign.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "last_run_started_at": now - 3600.0,
                        "run_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            args = self.args(
                ledger,
                min_run_gap_seconds=1800.0,
                hard_block_cooldown_seconds=3600.0,
            )
            with patch("scripts.run_jd_sustained.time.time", return_value=now):
                result = run_sustained(
                    args,
                    dependencies=self.dependencies(
                        clock, state, ["incomplete_blocked"], calls
                    ),
                )

            self.assertEqual(result.exit_code, 1)
            self.assertNotEqual(result.summary["status"], "campaign_gated")
            recorded = json.loads(campaign.read_text(encoding="utf-8"))
            self.assertEqual(recorded["last_run_started_at"], now)
            self.assertEqual(recorded["run_count"], 2)

    def test_campaign_gate_blocks_on_hard_block_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "run.sqlite"
            campaign = ledger.with_suffix(".campaign.json")
            now = 1_000_000.0
            campaign.write_text(
                json.dumps({"schema_version": 1, "last_hard_block_at": now - 100.0}),
                encoding="utf-8",
            )
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            args = self.args(
                ledger,
                min_run_gap_seconds=1800.0,
                hard_block_cooldown_seconds=3600.0,
            )
            with patch("scripts.run_jd_sustained.time.time", return_value=now):
                result = run_sustained(
                    args,
                    dependencies=self.dependencies(
                        clock, {"marketplace_plan": {}}, ["incomplete_blocked"], calls
                    ),
                )

            self.assertEqual(result.exit_code, 3)
            self.assertEqual(result.summary["reason"], "hard_block_cooldown")
            self.assertAlmostEqual(result.summary["retry_after_seconds"], 3500.0)
            self.assertEqual(calls.get("run_tasks", 0), 0)

    def test_campaign_gate_force_bypasses_spacing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "run.sqlite"
            campaign = ledger.with_suffix(".campaign.json")
            now = 1_000_000.0
            campaign.write_text(
                json.dumps({"schema_version": 1, "last_run_started_at": now - 100.0}),
                encoding="utf-8",
            )
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            args = self.args(
                ledger,
                min_run_gap_seconds=1800.0,
                force=True,
            )
            with patch("scripts.run_jd_sustained.time.time", return_value=now):
                result = run_sustained(
                    args,
                    dependencies=self.dependencies(
                        clock, state, ["running"], calls
                    ),
                )

            self.assertEqual(result.exit_code, 1)
            self.assertNotEqual(result.summary["status"], "campaign_gated")
            self.assertGreater(calls.get("run_tasks", 0), 0)

    def test_campaign_records_hard_block_after_jd_hard_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "run.sqlite"
            campaign = ledger.with_suffix(".campaign.json")
            now = 1_000_000.0
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {
                "marketplace_plan": {"platform_health": {"jd": "blocked"}},
                "counters": {},
            }
            args = self.args(
                ledger,
                min_run_gap_seconds=1800.0,
                hard_block_cooldown_seconds=3600.0,
            )
            with patch("scripts.run_jd_sustained.time.time", return_value=now):
                result = run_sustained(
                    args,
                    dependencies=self.dependencies(
                        clock, state, ["running"], calls
                    ),
                )

            self.assertEqual(result.summary["terminal_reason"], "jd_hard_blocked")
            recorded = json.loads(campaign.read_text(encoding="utf-8"))
            self.assertEqual(recorded["last_hard_block_at"], now)

    def test_append_ledger_preserves_existing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "run.sqlite"
            ledger.write_bytes(b"keep-me")
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            args = self.args(ledger, append_ledger=True)
            with patch("scripts.run_jd_sustained.time.time", return_value=1_000_000.0):
                result = run_sustained(
                    args,
                    dependencies=self.dependencies(
                        clock, state, ["incomplete_blocked"], calls
                    ),
                )

            self.assertEqual(result.exit_code, 1)
            self.assertEqual(ledger.read_bytes(), b"keep-me")

    def test_fresh_run_replaces_existing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "run.sqlite"
            ledger.write_bytes(b"keep-me")
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {"marketplace_plan": {"platform_cool_until": {"jd": 0.0}}}
            with patch("scripts.run_jd_sustained.time.time", return_value=1_000_000.0):
                result = run_sustained(
                    self.args(ledger),
                    dependencies=self.dependencies(
                        clock, state, ["incomplete_blocked"], calls
                    ),
                )

            self.assertEqual(result.exit_code, 1)
            self.assertFalse(ledger.exists())

    def test_user_data_dir_threads_into_seeded_tasks(self) -> None:
        profile = "C:/Profiles/search/edge-profile"
        tasks = _seed_edge_tasks(
            ["枕头"],
            platforms=("jd",),
            query_budget=4,
            user_data_dir=profile,
        )
        self.assertEqual(tasks[0]["payload"]["user_data_dir"], profile)
        resilient, _continuation = jd_driver._seed_resilient_edge_state(
            ("枕头",),
            platforms=("jd",),
            pagination_enabled=True,
            user_data_dir=profile,
        )
        self.assertEqual(resilient[0]["payload"]["user_data_dir"], profile)

    def test_wall_window_consumed_with_candidates_is_success(self) -> None:
        """墙钟窗口跑满且候选达标 -> ten_minute_limit 成功退出，而非 acceptance_failed。

        京东慢速车道的 pacing 让 pure_search_seconds 远小于窗口，driver 必须按
        wall_started_at 换算的墙钟窗口验收；本用例模拟窗口跑满、候选 >= 300 时
        evaluate 返回 ten_minute_limit 且 acceptance_passed=True -> exit 0。
        """
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {
                "marketplace_plan": {
                    "platform_cool_until": {"jd": 0.0},
                    "jd_slow_lane": True,
                },
                "marketplace_discovery": {
                    "enabled": True,
                    "total_unique_candidates": 340,
                    "decision": {"acceptance_passed": True},
                },
                "pure_seconds": 40.0,
            }
            result = run_sustained(
                self.args(Path(tmp) / "run.sqlite"),
                dependencies=self.dependencies(
                    clock,
                    state,
                    ["running", "ten_minute_limit"],
                    calls,
                ),
            )

        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.summary["reached_success"])
        self.assertTrue(result.summary["acceptance_passed"])
        self.assertEqual(result.summary["status"], "ten_minute_limit")
        self.assertEqual(result.summary["terminal_reason"], "ten_minute_limit")
        self.assertEqual(calls.get("finalize"), 1)
        # 纯搜索时间仍小，达标依据是墙钟窗口而非纯请求秒。
        self.assertEqual(result.summary["discovery_seconds"], 40.0)

    def test_future_platform_cooldown_waits_then_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(100.0)
            calls: dict[str, object] = {}
            state = {
                "marketplace_plan": {
                    "platform_cool_until": {"jd": 125.0},
                    "platform_health": {"jd": "cooling"},
                }
            }
            result = run_sustained(
                self.args(Path(tmp) / "run.sqlite"),
                dependencies=self.dependencies(
                    clock,
                    state,
                    ["incomplete_blocked", "running", "search_saturated"],
                    calls,
                ),
            )

        self.assertEqual(clock.sleeps, [25.0])
        self.assertGreater(calls.get("run_tasks", 0), 1)
        self.assertEqual(calls.get("finalize", 0), 1)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.summary["terminal_reason"], "wall_limit_reached")

    def test_wall_timeout_cannot_create_discovery_time_or_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clock = FakeClock(0.0)
            calls: dict[str, object] = {}
            state = {
                "pure_seconds": 0.0,
                "marketplace_plan": {"platform_cool_until": {"jd": 1000.0}},
            }
            result = run_sustained(
                self.args(
                    Path(tmp) / "run.sqlite",
                    search_limit_seconds=10.0,
                    wall_limit_seconds=11.0,
                ),
                dependencies=self.dependencies(
                    clock, state, ["incomplete_blocked"], calls
                ),
            )

        self.assertEqual(clock.sleeps, [11.0])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.summary["terminal_reason"], "wall_limit_reached")
        self.assertEqual(result.summary["discovery_seconds"], 0.0)
        self.assertEqual(calls.get("finalize", 0), 0)


if __name__ == "__main__":
    unittest.main()
