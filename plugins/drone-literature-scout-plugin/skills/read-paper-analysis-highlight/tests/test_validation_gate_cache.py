from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from validation_gate_cache import (  # noqa: E402
    fingerprint_inputs,
    record_gate_result,
    serialize_cache,
    should_run_gate,
)


class ValidationGateCacheTests(unittest.TestCase):
    def test_passed_unchanged_gate_is_skipped_during_intermediate_work(self):
        fingerprint = fingerprint_inputs({"note": "AAA"}, {"zotero": "9"})
        cache = record_gate_result({}, "callout", fingerprint, True, "ok")
        self.assertFalse(should_run_gate(cache, "callout", fingerprint))

    def test_failed_gate_always_reruns(self):
        fingerprint = fingerprint_inputs({"note": "AAA"})
        cache = record_gate_result({}, "callout", fingerprint, False, "bad")
        self.assertTrue(should_run_gate(cache, "callout", fingerprint))

    def test_changed_fingerprint_reruns(self):
        old = fingerprint_inputs({"note": "AAA"})
        new = fingerprint_inputs({"note": "BBB"})
        cache = record_gate_result({}, "callout", old, True)
        self.assertTrue(should_run_gate(cache, "callout", new))

    def test_affected_downstream_gate_reruns(self):
        fingerprint = fingerprint_inputs({"note": "AAA"})
        cache = record_gate_result({}, "links", fingerprint, True)
        self.assertTrue(
            should_run_gate(cache, "links", fingerprint, affected=True)
        )

    def test_final_run_ignores_cached_success(self):
        fingerprint = fingerprint_inputs({"note": "AAA"})
        cache = record_gate_result({}, "callout", fingerprint, True)
        self.assertTrue(
            should_run_gate(cache, "callout", fingerprint, final=True)
        )

    def test_fingerprint_is_stable_across_dictionary_order(self):
        first = fingerprint_inputs(
            {"skill": "A", "pdf": "B"},
            {"zotero": "9", "mode": "native"},
        )
        second = fingerprint_inputs(
            {"pdf": "B", "skill": "A"},
            {"mode": "native", "zotero": "9"},
        )
        self.assertEqual(first, second)

    def test_cache_serialization_is_deterministic_utf8_json(self):
        first = {
            "gates": {
                "作者": {
                    "passed": True,
                    "fingerprint": "abc",
                    "details": "已核验",
                }
            }
        }
        second = {
            "gates": {
                "作者": {
                    "details": "已核验",
                    "fingerprint": "abc",
                    "passed": True,
                }
            }
        }
        first_text = serialize_cache(first)
        second_text = serialize_cache(second)
        self.assertEqual(first_text, second_text)
        self.assertEqual(first_text.encode("utf-8").decode("utf-8"), first_text)
        self.assertIn("作者", first_text)
        self.assertNotIn("\\u4f5c", first_text)


if __name__ == "__main__":
    unittest.main()
