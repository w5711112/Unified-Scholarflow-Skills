import unittest
from unittest.mock import patch

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.normalize_and_dedupe import UrlLedger, normalize_url


class UrlDedupeTests(unittest.TestCase):
    def test_tracking_fragment_case_and_query_order_normalize(self):
        """Removing tracking fields and fragments must not split one resource."""
        a = "HTTPS://Example.COM:443/item/42?b=2&utm_source=x&a=1#detail"
        b = "https://example.com/item/42?a=1&b=2"
        self.assertEqual(normalize_url(a), normalize_url(b))

    def test_product_identifiers_remain_distinct(self):
        """Dropping every query parameter would incorrectly merge products."""
        self.assertNotEqual(
            normalize_url("https://example.com/item?id=41"),
            normalize_url("https://example.com/item?id=42"),
        )

    def test_repeated_query_values_keep_their_original_order(self):
        """Sorting values within a repeated key would merge ordered operations."""
        forward = "https://example.com/workflow?step=1&step=2&z=last"
        reverse = "https://example.com/workflow?z=last&step=2&step=1"
        self.assertNotEqual(normalize_url(forward), normalize_url(reverse))

    def test_invalid_percent_encoded_query_data_fails_closed(self):
        """Replacement decoding would collapse different invalid octets."""
        for raw_url in (
            "https://example.com/item?q=%",
            "https://example.com/item?q=%ZZ",
            "https://example.com/item?q=%FF",
            "https://example.com/item?q=%FE",
        ):
            self.assertIsNone(normalize_url(raw_url), raw_url)

    def test_userinfo_unicode_and_malformed_hosts_fail_closed(self):
        """Lossy authority transformations must not create false duplicates."""
        for raw_url in (
            "https://alice@example.com/item",
            "https://faß.de/item",
            "https://exa mple.com/item",
            "https://example.com%2F.attacker/item",
            "https://example.com%/item",
        ):
            self.assertIsNone(normalize_url(raw_url), raw_url)

    def test_authority_controls_are_rejected_before_urlsplit(self):
        """urlsplit must not erase controls before authority validation sees them."""
        for control in ("\r", "\n", "\t"):
            raw_url = f"https://exa{control}mple.com/item"
            self.assertIsNone(normalize_url(raw_url), repr(raw_url))
    def test_non_default_ports_remain_distinct(self):
        """Only the default port for a scheme may be removed."""
        self.assertEqual(
            normalize_url("https://example.com:443/item"),
            "https://example.com/item",
        )
        self.assertEqual(
            normalize_url("https://example.com:8443/item"),
            "https://example.com:8443/item",
        )
        self.assertNotEqual(
            normalize_url("https://example.com/item"),
            normalize_url("https://example.com:8443/item"),
        )

    def test_invalid_urls_fail_closed(self):
        """Malformed and non-HTTP inputs must not crash or enter the ledger."""
        ledger = UrlLedger()
        outcome = ledger.add(
            "https://example.com:bad-port/item", title="ignored",
            query_family="invalid", source_class="directory",
        )
        self.assertFalse(outcome.valid)
        self.assertEqual(outcome.reason, "invalid-http-url")
        self.assertEqual(ledger.stats().valid_urls, 0)

    def test_ledger_keeps_distinct_urls_when_fingerprints_collide(self):
        """Digest collisions must be resolved by canonical URL equality."""
        ledger = UrlLedger()
        with patch("scripts.normalize_and_dedupe.url_fingerprint", return_value=b"x" * 16):
            first = ledger.add(
                "https://example.com/item/41", title="one",
                query_family="collision", source_class="directory",
            )
            second = ledger.add(
                "https://example.com/item/42", title="two",
                query_family="collision", source_class="directory",
            )
            repeated = ledger.add(
                "https://example.com/item/41", title="one again",
                query_family="collision", source_class="directory",
            )
        self.assertFalse(first.duplicate)
        self.assertFalse(second.duplicate)
        self.assertTrue(repeated.duplicate)
        self.assertIsInstance(ledger._entries_by_hash[b"x" * 16], dict)
        self.assertEqual(ledger.stats().unique_urls, 2)

    def test_first_url_uses_compact_non_collision_entry(self):
        """Ordinary entries must avoid collision maps and singleton provenance sets."""
        ledger = UrlLedger()
        ledger.add(
            "https://example.com/item/42", title="discarded",
            query_family="broad", source_class="directory",
        )
        stored = next(iter(ledger._entries_by_hash.values()))
        self.assertNotIsInstance(stored, dict)
        self.assertIsNone(stored.additional_query_families)
        self.assertIsNone(stored.additional_source_classes)

    def test_duplicate_routes_accumulate_compact_provenance_and_stats(self):
        """Deduplication must preserve the routes that found one URL."""
        ledger = UrlLedger()
        ledger.add(
            "https://Example.com:443/item/42?b=2&a=1", title="first title",
            query_family="broad", source_class="directory",
        )
        duplicate = ledger.add(
            "https://example.com/item/42?a=1&b=2", title="second title",
            query_family="precise", source_class="review", access_limited=True,
        )

        self.assertTrue(duplicate.duplicate)
        provenance = ledger.provenance_for("https://example.com/item/42?b=2&a=1")
        self.assertIsNotNone(provenance)
        self.assertEqual(provenance.domain, "example.com")
        self.assertEqual(provenance.query_families, ("broad", "precise"))
        self.assertEqual(provenance.source_classes, ("directory", "review"))
        self.assertTrue(provenance.access_limited)
        stats = ledger.stats()
        self.assertEqual(stats.unique_domains, 1)
        self.assertEqual(stats.access_limited_urls, 1)
        self.assertEqual(
            stats.source_class_urls, (("directory", 1), ("review", 1)),
        )
        self.assertEqual(
            stats.query_family_urls, (("broad", 1), ("precise", 1)),
        )

    def test_ledger_crosses_one_hundred_thousand(self):
        """A fixed URL cap would silently discard valid search results."""
        ledger = UrlLedger()
        for index in range(100_001):
            result = ledger.add(
                f"https://example.com/item/{index}", title=f"item {index}",
                query_family="scale", source_class="directory",
            )
            self.assertTrue(result.valid)
        self.assertEqual(ledger.stats().unique_urls, 100_001)
