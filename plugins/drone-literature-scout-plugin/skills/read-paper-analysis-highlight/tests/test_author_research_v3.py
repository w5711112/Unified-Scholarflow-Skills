from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from validate_author_research import validate_document  # noqa: E402


OFFICIAL_URL = "https://person.zju.edu.cn/fgaoaa"


def verified(value: str, url: str = OFFICIAL_URL) -> dict:
    return {
        "status": "verified",
        "value": value,
        "sources": [url],
    }


def not_verified(url: str = OFFICIAL_URL) -> dict:
    return {
        "status": "not_publicly_verified",
        "searched_sources": [url],
    }


def valid_v3_document() -> dict:
    return {
        "author_research_schema_version": 3,
        "paper_id": "paper-001",
        "verified_at": "2026-07-26",
        "designated_authors": [{
            "name": "Fei Gao",
            "roles": ["corresponding_author"],
        }],
        "authors": [{
            "name": "Fei Gao",
            "roles": ["corresponding_author"],
            "education": not_verified(),
            "current_position": verified(
                "浙江大学控制科学与工程学院长聘副教授、博士生导师"
            ),
            "qs_ranking": {
                **verified("浙江大学的 QS 排名需按指定版本记录"),
                "edition": "QS World University Rankings 2027",
            },
            "scholar": not_verified(),
            "memberships": not_verified(),
            "standing_assessment": {
                "status": "inference",
                "basis": (
                    "官方履历、代表作、项目和获奖记录显示其在空中机器人方向"
                    "具有较高影响力；该表述不是官方头衔。"
                ),
            },
            "research_areas": verified(
                "空中机器人、具身智能、群体智能、集群机器人"
            ),
            "lab": verified("浙江大学 FAST Lab"),
            "projects": verified("承担国家级和省部级机器人科研项目"),
            "honors": verified("包含机器人领域论文奖项和人才项目"),
            "representative_outputs": verified(
                "在 Science Robotics、IEEE TRO 等发表代表性成果"
            ),
            "bibliometrics": not_verified(),
            "metric_source": "not_verified",
            "url_checks": [{
                "requested_url": OFFICIAL_URL,
                "final_url": OFFICIAL_URL,
                "status_code": 200,
                "checked_at": "2026-07-26",
                "accessible": True,
            }],
        }],
    }


class AuthorResearchV3Tests(unittest.TestCase):
    def test_accepts_complete_v3_author_record(self):
        self.assertEqual(validate_document(valid_v3_document()), [])

    def test_rejects_missing_extended_author_fields(self):
        document = valid_v3_document()
        del document["authors"][0]["research_areas"]
        errors = validate_document(document)
        self.assertTrue(
            any("research_areas" in error for error in errors),
            errors,
        )

    def test_rejects_verified_fact_whose_url_check_is_not_accessible(self):
        document = valid_v3_document()
        document["authors"][0]["url_checks"][0]["accessible"] = False
        document["authors"][0]["url_checks"][0]["status_code"] = 403
        errors = validate_document(document)
        self.assertTrue(
            any("accessible" in error for error in errors),
            errors,
        )

    def test_rejects_ambiguous_metric_source_name(self):
        document = valid_v3_document()
        document["authors"][0]["metric_source"] = "Google"
        errors = validate_document(document)
        self.assertTrue(
            any("metric_source" in error for error in errors),
            errors,
        )

    def test_accepts_accessible_ad_scientific_index_fallback(self):
        document = valid_v3_document()
        author = document["authors"][0]
        metric_url = (
            "https://adscientificindex.com/scientist/fei-gao/738407/"
        )
        author["bibliometrics"] = verified(
            "Citations 10,190；H-index 48；i10-index 113",
            metric_url,
        )
        author["metric_source"] = "AD Scientific Index"
        author["url_checks"].append({
            "requested_url": metric_url,
            "final_url": metric_url,
            "status_code": 200,
            "checked_at": "2026-07-26",
            "accessible": True,
        })
        self.assertEqual(validate_document(document), [])


if __name__ == "__main__":
    unittest.main()
