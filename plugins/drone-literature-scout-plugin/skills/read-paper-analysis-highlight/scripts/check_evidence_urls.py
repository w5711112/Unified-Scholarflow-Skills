from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ACCESS_BARRIER_MARKERS = (
    "access denied",
    "captcha",
    "unusual traffic",
    "verify you are human",
    "too many requests",
    "robot check",
)
DEFAULT_TIMEOUT_SECONDS = 15
BODY_PROBE_BYTES = 65536


def check_url(
    url: str,
    *,
    opener: Callable[..., Any] = urlopen,
    checked_on: date | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    checked = checked_on or date.today()
    result: dict[str, Any] = {
        "requested_url": url,
        "final_url": url,
        "status_code": None,
        "checked_at": checked.isoformat(),
        "accessible": False,
    }
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/137 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            final_url = str(response.geturl())
            body = response.read(BODY_PROBE_BYTES)
    except HTTPError as error:
        result["status_code"] = int(error.code)
        result["final_url"] = str(error.geturl() or url)
        result["failure_reason"] = f"http-{error.code}"
        return result
    except (URLError, TimeoutError, OSError) as error:
        result["failure_reason"] = f"network-error:{type(error).__name__}"
        return result

    result["status_code"] = status
    result["final_url"] = final_url
    text_probe = body.decode("utf-8", errors="ignore").casefold()
    if any(marker in text_probe for marker in ACCESS_BARRIER_MARKERS):
        result["failure_reason"] = "access-barrier"
        return result
    if not 200 <= status < 400:
        result["failure_reason"] = f"http-{status}"
        return result
    result["accessible"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether author and supporting-evidence URLs are readable."
    )
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()
    checks = [
        check_url(url, timeout=args.timeout)
        for url in args.urls
    ]
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return int(any(not check["accessible"] for check in checks))


if __name__ == "__main__":
    raise SystemExit(main())
