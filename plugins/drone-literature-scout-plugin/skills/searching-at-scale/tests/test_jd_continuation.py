"""Contract tests for the pure JD continuation state machine."""

from __future__ import annotations

import copy
import unittest

from tests._test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.jd_continuation import (  # noqa: E402
    advance_to_next_topic,
    current_request,
    deterministic_query_families,
    new_continuation,
    page_verified,
    recovery_failed,
    soft_failure,
)


class JdContinuationTests(unittest.TestCase):
    def test_query_families_are_deterministic_and_deduplicated(self) -> None:
        """A whitespace-only normalization regression changes emitted queries."""
        self.assertEqual(
            deterministic_query_families(" 机械键盘 "),
            (
                "机械键盘",
                "机械键盘 自营",
                "机械键盘 品牌",
                "机械键盘 型号",
                "机械键盘 新品",
            ),
        )

    def test_verified_page_lazily_advances_beyond_twenty(self) -> None:
        """A capped or eagerly materialized cursor cannot continue page 21."""
        plan = new_continuation(("机械键盘",))
        for expected in range(1, 22):
            request = current_request(plan)
            self.assertIsNotNone(request)
            assert request is not None
            self.assertEqual(request.page_number, expected)
            self.assertEqual(request.session_action, "start" if expected == 1 else "next")
            page_verified(plan)

    def test_soft_recovery_then_family_rotation(self) -> None:
        """A failed recovery must abandon its family and start the next family."""
        plan = new_continuation(("机械键盘",))
        soft_failure(plan, "pagination_page_transient_empty")
        request = current_request(plan)
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.session_action, "recover")
        soft_failure(plan, "pagination_page_transient_empty")
        request = current_request(plan)
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.session_action, "recover")
        recovery_failed(plan, "browser_page_structure_changed")
        request = current_request(plan)
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.query, "机械键盘 自营")
        self.assertEqual(request.page_number, 1)
        self.assertEqual(request.session_action, "start")

    def test_advance_to_next_topic_moves_to_next_topic_first_family(self) -> None:
        """A page cap on one topic must skip its remaining families."""
        plan = new_continuation(("机械键盘", "青轴"))
        plan["page_number"] = 3

        advance_to_next_topic(plan)

        request = current_request(plan)
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.topic, "青轴")
        self.assertEqual(request.query, "青轴")
        self.assertEqual(request.family_index, 0)
        self.assertEqual(request.page_number, 1)
        self.assertEqual(request.session_action, "start")

    def test_advance_to_next_topic_marks_complete_after_last_topic(self) -> None:
        """The final topic's page cap terminates the plan deterministically."""
        plan = new_continuation(("机械键盘",))

        advance_to_next_topic(plan)

        self.assertTrue(plan["complete"])
        self.assertIsNone(current_request(plan))

    def test_hard_failures_are_rejected_without_mutating_plan(self) -> None:
        """A hard JD warning must never enter recovery or rotate a query family."""
        hard_categories = (
            "authentication_required",
            "browser_authentication_required",
            "captcha_required",
            "browser_captcha_required",
            "rate_limited",
            "browser_rate_limited",
        )
        for transition in (soft_failure, recovery_failed):
            for category in hard_categories:
                with self.subTest(transition=transition.__name__, category=category):
                    plan = new_continuation(("机械键盘",))
                    before = copy.deepcopy(plan)
                    with self.assertRaises(ValueError):
                        transition(plan, category)
                    self.assertEqual(plan, before)

    def test_recovery_stage_uses_only_explicit_protocol_values(self) -> None:
        """Empty recovery stages violate the persisted state protocol."""
        plan = new_continuation(("机械键盘",))
        self.assertEqual(plan["recovery_stage"], "initial")
        soft_failure(plan, "pagination_page_transient_empty")
        self.assertEqual(plan["recovery_stage"], "reproject")
        soft_failure(plan, "pagination_page_transient_empty")
        self.assertEqual(plan["recovery_stage"], "reload")
        page_verified(plan)
        self.assertEqual(plan["recovery_stage"], "initial")
        recovery_failed(plan, "browser_page_structure_changed")
        self.assertEqual(plan["recovery_stage"], "initial")

    def test_invalid_persisted_recovery_stage_is_rejected(self) -> None:
        """An unrecognized persisted stage must not be treated as a new request."""
        plan = new_continuation(("机械键盘",))
        plan["recovery_stage"] = "unknown"
        with self.assertRaises(ValueError):
            current_request(plan)

    def test_page_512_is_valid_and_513_is_not_materialized(self) -> None:
        """An off-by-one protocol cap would issue an invalid page 513 request."""
        plan = new_continuation(("机械键盘",))
        plan["page_number"] = 512
        request = current_request(plan)
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.page_number, 512)
        page_verified(plan)
        self.assertIsNone(current_request(plan))
        self.assertEqual(plan["page_number"], 512)
        self.assertTrue(plan["complete"])

    def test_all_families_exhausted_is_explicit(self) -> None:
        """A missing terminal state would keep scheduling an exhausted topic."""
        plan = new_continuation(("机械键盘",))
        for _ in range(5):
            recovery_failed(plan, "browser_page_structure_changed")
        self.assertIsNone(current_request(plan))
        self.assertTrue(plan["complete"])


if __name__ == "__main__":
    unittest.main()
