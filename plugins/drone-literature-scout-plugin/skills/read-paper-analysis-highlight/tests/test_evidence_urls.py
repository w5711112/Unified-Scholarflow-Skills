from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from check_evidence_urls import check_url  # noqa: E402


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        final_url: str = "https://example.org/profile",
        body: bytes = b"official profile",
    ):
        self.status = status
        self._final_url = final_url
        self._body = body

    def geturl(self):
        return self._final_url

    def read(self, _limit):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class EvidenceUrlTests(unittest.TestCase):
    def test_accepts_accessible_page_and_records_final_url(self):
        result = check_url(
            "https://example.org/old-profile",
            opener=lambda *_args, **_kwargs: FakeResponse(
                final_url="https://example.org/profile"
            ),
            checked_on=date(2026, 7, 26),
        )
        self.assertTrue(result["accessible"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(
            result["final_url"],
            "https://example.org/profile",
        )
        self.assertEqual(result["checked_at"], "2026-07-26")

    def test_rejects_access_denied_and_rate_limited_pages(self):
        for status in (403, 429):
            def opener(request, timeout, status=status):
                raise HTTPError(
                    request.full_url,
                    status,
                    "blocked",
                    hdrs=None,
                    fp=None,
                )

            with self.subTest(status=status):
                result = check_url(
                    "https://scholar.google.com/citations?user=example",
                    opener=opener,
                    checked_on=date(2026, 7, 26),
                )
                self.assertFalse(result["accessible"])
                self.assertEqual(result["status_code"], status)

    def test_rejects_captcha_or_access_denied_body_even_with_200(self):
        result = check_url(
            "https://example.org/profile",
            opener=lambda *_args, **_kwargs: FakeResponse(
                body=b"Access denied. Complete the CAPTCHA to continue."
            ),
            checked_on=date(2026, 7, 26),
        )
        self.assertFalse(result["accessible"])
        self.assertEqual(result["failure_reason"], "access-barrier")


if __name__ == "__main__":
    unittest.main()
