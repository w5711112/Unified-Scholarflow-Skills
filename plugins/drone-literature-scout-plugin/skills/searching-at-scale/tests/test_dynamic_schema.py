from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.aggregate_evidence import EvidenceAtom, aggregate_fields, progress_payload


class MutablePayload:
    def __init__(self) -> None:
        self.values = []


class HostileDeepcopy:
    def __init__(self) -> None:
        self.deepcopy_called = False

    def __deepcopy__(self, memo):
        self.deepcopy_called = True
        return self


class MutableMappingKey:
    __hash__ = object.__hash__

    def __init__(self) -> None:
        self.label = "mutable"

class DynamicSchemaTests(unittest.TestCase):
    def test_raw_normalized_provenance_and_missing_reason_survive(self):
        observed = datetime(2026, 7, 30, tzinfo=timezone.utc)
        atoms = [
            EvidenceAtom(
                "seller:42",
                "seller",
                "信用等级",
                "极好",
                "excellent",
                None,
                None,
                observed,
                "https://example.com/u/42",
                "B",
                False,
                None,
                0.9,
                None,
            ),
            EvidenceAtom(
                "seller:42",
                "seller",
                "交易数量",
                None,
                None,
                "count",
                None,
                observed,
                "https://example.com/u/42",
                "B",
                False,
                None,
                0.0,
                "未公开展示",
            ),
        ]
        fields = aggregate_fields(atoms)
        self.assertEqual(
            fields["seller:42"]["信用等级"][0].normalized_value, "excellent"
        )
        self.assertEqual(
            fields["seller:42"]["交易数量"][0].missing_reason, "未公开展示"
        )

    def test_conflicting_values_are_aggregated_without_loss(self):
        observed = datetime(2026, 7, 30, tzinfo=timezone.utc)
        atoms = [
            EvidenceAtom(
                "hotel:7",
                "hotel",
                "price",
                "¥500",
                500,
                "CNY",
                None,
                observed,
                "https://official.example/hotel/7",
                "A",
                False,
                None,
                0.95,
                None,
            ),
            EvidenceAtom(
                "hotel:7",
                "hotel",
                "price",
                "¥480",
                480,
                "CNY",
                None,
                observed,
                "https://booking.example/hotel/7",
                "B",
                False,
                None,
                0.85,
                None,
            ),
        ]
        fields = aggregate_fields(atoms)
        self.assertEqual(
            [atom.normalized_value for atom in fields["hotel:7"]["price"]],
            [500, 480],
        )

    def test_progress_payload_is_complete_deterministic_and_serializable(self):
        kwargs = {
            "pure_search_seconds": 61.25,
            "requests": 12,
            "batches": 3,
            "raw_results": 1_200,
            "valid_urls": 900,
            "normalized_unique_urls": 700,
            "content_unique_pages": 650,
            "unique_objects": 400,
            "independent_domains": 55,
            "per_source_counts": {"media": 500, "official": 400},
            "highest_concurrency": 24,
            "marginal_yield": 0.125,
            "current_gaps": {"languages": ["ja", "de"], "sources": ["forum"]},
        }
        test_directory = Path(__file__).resolve().parent
        before = tuple(sorted(path.name for path in test_directory.iterdir()))
        first = progress_payload(**kwargs)
        second = progress_payload(**kwargs)
        after = tuple(sorted(path.name for path in test_directory.iterdir()))

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(first),
            (
                "pure_search_seconds",
                "requests",
                "batches",
                "raw_results",
                "valid_urls",
                "normalized_unique_urls",
                "content_unique_pages",
                "unique_objects",
                "independent_domains",
                "per_source_counts",
                "highest_concurrency",
                "marginal_yield",
                "current_gaps",
            ),
        )
        self.assertEqual(
            tuple(first["per_source_counts"]),
            ("media", "official"),
        )
        self.assertEqual(
            first["current_gaps"],
            {"languages": ["ja", "de"], "sources": ["forum"]},
        )
        self.assertEqual(before, after)
        self.assertIsInstance(json.dumps(first, ensure_ascii=False), str)

    def test_progress_payload_copies_inputs_and_rejects_invalid_counts(self):
        counts = {"official": 2}
        gaps = ["forum"]
        payload = progress_payload(
            pure_search_seconds=1,
            requests=1,
            batches=1,
            raw_results=2,
            valid_urls=2,
            normalized_unique_urls=2,
            content_unique_pages=2,
            unique_objects=1,
            independent_domains=1,
            per_source_counts=counts,
            highest_concurrency=1,
            marginal_yield=0.5,
            current_gaps=gaps,
        )
        counts["official"] = 99
        gaps.append("media")
        self.assertEqual(payload["per_source_counts"]["official"], 2)
        self.assertEqual(payload["current_gaps"], ["forum"])

        with self.assertRaises(ValueError):
            progress_payload(
                pure_search_seconds=1,
                requests=-1,
                batches=1,
                raw_results=2,
                valid_urls=2,
                normalized_unique_urls=2,
                content_unique_pages=2,
                unique_objects=1,
                independent_domains=1,
                per_source_counts={"official": 2},
                highest_concurrency=1,
                marginal_yield=0.5,
                current_gaps=[],
            )

    def test_progress_payload_rejects_impossible_count_lattices(self):
        base = {
            "pure_search_seconds": 1,
            "requests": 1,
            "batches": 1,
            "raw_results": 100,
            "valid_urls": 80,
            "normalized_unique_urls": 70,
            "content_unique_pages": 60,
            "unique_objects": 40,
            "independent_domains": 20,
            "per_source_counts": {"official": 50, "media": 30},
            "highest_concurrency": 4,
            "marginal_yield": 0.25,
            "current_gaps": [],
        }
        impossible = (
            {"raw_results": 79},
            {"normalized_unique_urls": 81},
            {"content_unique_pages": 71},
            {"independent_domains": 71},
        )
        for override in impossible:
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    progress_payload(**(base | override))

    def test_per_source_counts_must_partition_valid_urls(self):
        with self.assertRaises(ValueError):
            progress_payload(
                pure_search_seconds=1,
                requests=1,
                batches=1,
                raw_results=100,
                valid_urls=80,
                normalized_unique_urls=70,
                content_unique_pages=60,
                unique_objects=40,
                independent_domains=20,
                per_source_counts={"official": 50, "media": 29},
                highest_concurrency=4,
                marginal_yield=0.25,
                current_gaps=[],
            )

    def test_aggregation_detaches_nested_source_values(self):
        observed = datetime(2026, 7, 30, tzinfo=timezone.utc)
        raw = {"offers": [{"price": 500}], "tags": ["refundable"]}
        normalized = {"offers": [{"price": 500, "currency": "CNY"}]}
        atom = EvidenceAtom(
            "hotel:7",
            "hotel",
            "offers",
            raw,
            normalized,
            None,
            None,
            observed,
            "https://example.com/hotel/7",
            "B",
            False,
            None,
            0.9,
            None,
        )
        fields = aggregate_fields([atom])
        raw["offers"][0]["price"] = 1
        normalized["offers"][0]["price"] = 2
        snapshot = fields["hotel:7"]["offers"][0]
        self.assertEqual(snapshot.raw_value["offers"][0]["price"], 500)
        self.assertEqual(snapshot.normalized_value["offers"][0]["price"], 500)

    def test_aggregate_nested_values_and_containers_are_immutable(self):
        observed = datetime(2026, 7, 30, tzinfo=timezone.utc)
        atom = EvidenceAtom(
            "hotel:7",
            "hotel",
            "offers",
            {"offer": {"price": 500}},
            {"offer": {"price": 500, "currency": "CNY"}},
            None,
            None,
            observed,
            "https://example.com/hotel/7",
            "B",
            False,
            None,
            0.9,
            None,
        )
        fields = aggregate_fields([atom])
        snapshot = fields["hotel:7"]["offers"][0]
        with self.assertRaises(TypeError):
            snapshot.raw_value["offer"]["price"] = 1
        with self.assertRaises(TypeError):
            fields["hotel:7"]["offers"] = ()
    def test_custom_mutable_evidence_value_is_rejected(self):
        observed = datetime(2026, 7, 30, tzinfo=timezone.utc)
        atom = EvidenceAtom(
            "entity:1",
            "entity",
            "custom",
            MutablePayload(),
            None,
            None,
            None,
            observed,
            "https://example.com/entity/1",
            "B",
            False,
            None,
            0.8,
            None,
        )
        with self.assertRaises(ValueError):
            aggregate_fields([atom])

    def test_hostile_deepcopy_is_rejected_without_invocation(self):
        observed = datetime(2026, 7, 30, tzinfo=timezone.utc)
        hostile = HostileDeepcopy()
        atom = EvidenceAtom(
            "entity:1",
            "entity",
            "hostile",
            hostile,
            None,
            None,
            None,
            observed,
            "https://example.com/entity/1",
            "B",
            False,
            None,
            0.8,
            None,
        )
        with self.assertRaises(ValueError):
            aggregate_fields([atom])
        self.assertFalse(hostile.deepcopy_called)

    def test_nested_mapping_list_and_set_snapshot_is_immutable(self):
        observed = datetime(2026, 7, 30, tzinfo=timezone.utc)
        raw = {
            "offer": {"prices": [500, 520]},
            "tags": {"refundable", "breakfast"},
        }
        atom = EvidenceAtom(
            "hotel:7",
            "hotel",
            "offer",
            raw,
            None,
            None,
            None,
            observed,
            "https://example.com/hotel/7",
            "B",
            False,
            None,
            0.9,
            None,
        )
        snapshot = aggregate_fields([atom])["hotel:7"]["offer"][0].raw_value
        raw["offer"]["prices"].append(1)
        raw["tags"].add("changed")
        self.assertEqual(snapshot["offer"]["prices"], (500, 520))
        self.assertEqual(snapshot["tags"], frozenset({"refundable", "breakfast"}))
        with self.assertRaises(TypeError):
            snapshot["offer"]["prices"] = ()
        with self.assertRaises(AttributeError):
            snapshot["tags"].add("changed")

    def test_mapping_keys_are_recursively_frozen_and_validated(self):
        observed = datetime(2026, 7, 30, tzinfo=timezone.utc)
        supported_key = ("region", frozenset({"south", "cn"}))
        valid_atom = EvidenceAtom(
            "entity:1",
            "entity",
            "structured-key",
            {supported_key: ["value"]},
            None,
            None,
            None,
            observed,
            "https://example.com/entity/1",
            "B",
            False,
            None,
            0.8,
            None,
        )
        snapshot = aggregate_fields([valid_atom])["entity:1"]["structured-key"][0]
        self.assertEqual(snapshot.raw_value[supported_key], ("value",))

        unsupported_key = ("region", MutableMappingKey())
        invalid_atom = EvidenceAtom(
            "entity:2",
            "entity",
            "structured-key",
            {unsupported_key: "value"},
            None,
            None,
            None,
            observed,
            "https://example.com/entity/2",
            "B",
            False,
            None,
            0.8,
            None,
        )
        with self.assertRaises(ValueError):
            aggregate_fields([invalid_atom])
    def test_invalid_evidence_is_rejected(self):
        observed = datetime(2026, 7, 30, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            EvidenceAtom(
                "seller:42",
                "seller",
                "credit",
                "good",
                "good",
                None,
                None,
                observed,
                "https://example.com/u/42",
                "Z",
                False,
                None,
                0.9,
                None,
            )
        with self.assertRaises(ValueError):
            EvidenceAtom(
                "seller:42",
                "seller",
                "credit",
                "good",
                "good",
                None,
                None,
                observed,
                "javascript:alert(1)",
                "B",
                False,
                None,
                0.9,
                None,
            )


if __name__ == "__main__":
    unittest.main()
