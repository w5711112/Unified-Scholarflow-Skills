import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.validate_report import unexpected_artifacts, validate_report


VALID = """# 枕头价格调研
## 核心结论
结论。[来源](https://example.com/source)
## 搜索统计
- 纯搜索时间：600 秒
- 全局运行 ID：run-1
- 运行类型：open_web_research
- 范围指纹：cn-pillow-market-v1
- 上一轮已验证对象数：222
- 本轮新增已验证对象数：31
- 本轮重叠对象数：18
- 明确失效对象数：2
- 累计已验证对象数：251
- 停止证据：pure_search_seconds=600; scheduler_status=ten_minute_limit
- 原始结果数：12000
- 未去重 URL 数：12000
- 有效 URL 数：9000
- 规范化去重有效 URL 数：6500
- 未去重 URL/s：10.0
- 规范化去重 URL/s：5.4
- 成功正文页/s：未执行
- 有效结构化记录/s：300.0
- 搜索模式：bulk
- 50 URL/s目标：未达到（批量后端不可用）
- 独立域名数：800
- 来源类别：官网、电商、媒体、论坛
- 最高并发：120
- 停止原因：达到10分钟
## 搜索轨迹
轨迹运行 ID：run-1
字符折线：▁▃▅█ 0s/0 URL → 600s/12000 URL
## 冲突与缺失
失效项：brand:model-old-1｜官方页面明确下架并由替代型号取代｜https://example.com/replacement-1
失效项：brand:model-old-2｜品牌页确认与另一型号完全相同｜https://example.com/replacement-2
## 来源
- [来源](https://example.com/source)
"""


CATALOG_VALID = VALID.replace(
    "运行类型：open_web_research", "运行类型：catalog_enumeration"
).replace(
    "- 停止原因：达到10分钟",
    """- 唯一商品候选数：2400
- 唯一有效记录数：1800
- 商品候选平均速度：4.0 候选/s
- 最近 30 秒商品候选速度：4.5 候选/s
- 最长零新增间隔：12.0 秒
- 各来源商品聚合：edge:jd(raw=18000,unique=1600,duplicate=16400); searxng(raw=12000,unique=800,duplicate=11200)
- 阻塞次数：0
- 10 商品候选/s目标：未达到
- 确定性范围证据：不适用（宽类固定600秒）
- 停止原因：达到10分钟""",
)


class ReportContractTests(unittest.TestCase):
    def test_catalog_report_requires_candidate_specific_statistics(self):
        self.assertEqual(validate_report(CATALOG_VALID).errors, ())
        for field in (
            "唯一商品候选数",
            "唯一有效记录数",
            "商品候选平均速度",
            "最近 30 秒商品候选速度",
            "最长零新增间隔",
            "各来源商品聚合",
            "阻塞次数",
            "10 商品候选/s目标",
            "确定性范围证据",
        ):
            with self.subTest(field=field):
                line = next(
                    line for line in CATALOG_VALID.splitlines() if line.startswith(f"- {field}：")
                )
                self.assertIn(
                    f"missing-catalog-stat:{field}",
                    validate_report(CATALOG_VALID.replace(line + "\n", "")).errors,
                )

    def test_raw_url_rate_cannot_be_reported_as_candidate_target(self):
        misreported = CATALOG_VALID.replace(
            "10 商品候选/s目标：未达到", "10 商品候选/s目标：达到"
        )
        self.assertIn(
            "marketplace-throughput-target-misreported",
            validate_report(misreported).errors,
        )

    def test_catalog_deterministic_completion_rejects_auth_or_captcha_blockers(self):
        deterministic = (
            CATALOG_VALID.replace("纯搜索时间：600 秒", "纯搜索时间：90 秒")
            .replace("商品候选平均速度：4.0 候选/s", "商品候选平均速度：26.6667 候选/s")
            .replace("停止原因：达到10分钟", "停止原因：确定范围完成")
            .replace(
                "停止证据：pure_search_seconds=600; scheduler_status=ten_minute_limit",
                "停止证据：scheduler_status=deterministic_scope_complete",
            )
            .replace(
                "确定性范围证据：不适用（宽类固定600秒）",
                "确定性范围证据：query_generation_exhausted=true; "
                "healthy_cursors_open=0; healthy_cursors_blocked=0; "
                "edge_plan_completed=true; recent_candidate_additions=1,0,0; "
                "untried_high_yield_families=0; captcha_required=0; "
                "authentication_required=0",
            )
        )
        self.assertEqual(validate_report(deterministic).errors, ())
        for blocker in ("captcha_required", "authentication_required"):
            with self.subTest(blocker=blocker):
                blocked = deterministic.replace(f"{blocker}=0", f"{blocker}=1")
                self.assertIn(
                    "blocked-deterministic-marketplace-scope",
                    validate_report(blocked).errors,
                )

    def test_valid_report_passes(self):
        self.assertEqual(validate_report(VALID).errors, ())

    def test_missing_statistics_fail(self):
        result = validate_report("# 调研\n## 核心结论\n没有统计")
        self.assertIn("missing-section:搜索统计", result.errors)

    def test_missing_stat_has_direct_error(self):
        result = validate_report(VALID.replace("- 原始结果数：12000\n", ""))
        self.assertIn("missing-stat:原始结果数", result.errors)

    def test_empty_stat_value_has_direct_error(self):
        result = validate_report(VALID.replace("- 有效 URL 数：9000", "- 有效 URL 数：   "))
        self.assertIn("missing-stat:有效 URL 数", result.errors)

    def test_invalid_stop_reason_fails(self):
        result = validate_report(VALID.replace("达到10分钟", "时间耗尽"))
        self.assertIn("invalid-stop-reason", result.errors)

    def test_missing_trajectory_section_or_chart_fails(self):
        no_section = VALID.replace(
            "## 搜索轨迹\n轨迹运行 ID：run-1\n字符折线：▁▃▅█ 0s/0 URL → 600s/12000 URL\n",
            "",
        )
        no_chart = VALID.replace(
            "字符折线：▁▃▅█ 0s/0 URL → 600s/12000 URL", "无图"
        )
        self.assertIn("missing-section:搜索轨迹", validate_report(no_section).errors)
        self.assertIn("missing-search-timeline", validate_report(no_chart).errors)

    def test_mermaid_timeline_passes(self):
        mermaid = VALID.replace(
            "字符折线：▁▃▅█ 0s/0 URL → 600s/12000 URL",
            "```mermaid\nxychart-beta\n    x-axis [0, 600]\n"
            '    y-axis "累计未去重 URL" 0 --> 12000\n'
            "    line [0, 12000]\n```",
        )
        self.assertEqual(validate_report(mermaid).errors, ())

    def test_inline_svg_timeline_passes(self):
        svg = VALID.replace(
            "字符折线：▁▃▅█ 0s/0 URL → 600s/12000 URL",
            '<svg role="img" aria-label="搜索时间—累计未去重 URL" '
            'viewBox="0 0 720 360"><polyline class="trajectory" '
            'points="64,312 700,18" /></svg>',
        )
        self.assertEqual(validate_report(svg).errors, ())

    def test_timeline_must_be_visible_and_inside_its_section(self):
        outside = VALID.replace(
            "字符折线：▁▃▅█ 0s/0 URL → 600s/12000 URL",
            "无图",
        ) + "\n字符折线：▁█ 0s/0 URL → 600s/12000 URL\n"
        fenced = VALID.replace(
            "字符折线：▁▃▅█ 0s/0 URL → 600s/12000 URL",
            "```text\n字符折线：▁█ 0s/0 URL → 600s/12000 URL\n```",
        )
        self.assertIn("missing-search-timeline", validate_report(outside).errors)
        self.assertIn("missing-search-timeline", validate_report(fenced).errors)

    def test_missing_new_throughput_stat_has_direct_error(self):
        result = validate_report(VALID.replace("- 未去重 URL/s：10.0\n", ""))
        self.assertIn("missing-stat:未去重 URL/s", result.errors)

    def test_missing_provenance_fails(self):
        result = validate_report(VALID.replace("https://example.com/source", "ftp://example.com/source"))
        self.assertIn("missing-http-source", result.errors)

    def test_fenced_content_cannot_satisfy_contract(self):
        result = validate_report(f"```markdown\n{VALID}\n```")
        self.assertIn("missing-section:搜索统计", result.errors)
        self.assertIn("missing-http-source", result.errors)

    def test_short_same_character_fence_does_not_close_longer_fence(self):
        text = f"````markdown\nignored\n```\n{VALID}\n````"
        result = validate_report(text)
        self.assertIn("missing-section:搜索统计", result.errors)

    def test_fence_with_non_whitespace_suffix_does_not_close(self):
        text = f"````markdown\nignored\n```` not-a-closing-fence\n{VALID}\n````"
        result = validate_report(text)
        self.assertIn("missing-section:搜索统计", result.errors)

    def test_headings_and_statistics_cannot_span_lines(self):
        split_heading = VALID.replace("## 核心结论", "##\n核心结论")
        split_stat = VALID.replace("- 原始结果数：12000", "-\n原始结果数：12000")
        split_stop = VALID.replace("- 停止原因：达到10分钟", "-\n停止原因：达到10分钟")
        self.assertIn("missing-section:核心结论", validate_report(split_heading).errors)
        self.assertIn("missing-stat:原始结果数", validate_report(split_stat).errors)
        self.assertIn("missing-stat:停止原因", validate_report(split_stop).errors)
        self.assertIn("invalid-stop-reason", validate_report(split_stop).errors)

    def test_bare_statistics_outside_entries_fail(self):
        bare = "\n".join(line.removeprefix("- ") for line in VALID.splitlines())
        result = validate_report(bare)
        self.assertIn("missing-stat:纯搜索时间", result.errors)

    def test_source_must_be_valid_link_in_sources_section(self):
        no_source_link = VALID.replace(
            "## 来源\n- [来源](https://example.com/source)", "## 来源\n无"
        )
        malformed = VALID.replace("https://example.com/source", "https:// ")
        self.assertIn("missing-http-source", validate_report(no_source_link).errors)
        self.assertIn("missing-http-source", validate_report(malformed).errors)

    def test_source_rejects_backslashes_and_invalid_percent_escapes(self):
        backslash = VALID.replace("https://example.com/source", "https://example.com\\path")
        invalid_percent = VALID.replace("https://example.com/source", "https://example.com/%zz")
        self.assertIn("missing-http-source", validate_report(backslash).errors)
        self.assertIn("missing-http-source", validate_report(invalid_percent).errors)

    def test_backend_batch_cannot_be_final_market_report(self):
        result = validate_report(
            VALID.replace("运行类型：open_web_research", "运行类型：backend_batch")
        )
        self.assertIn("not-global-market-run", result.errors)

    def test_stop_reason_must_match_run_type(self):
        result = validate_report(
            VALID.replace(
                "运行类型：open_web_research",
                "运行类型：bounded_dataset_extract",
            )
            .replace("停止原因：达到10分钟", "停止原因：搜索饱和")
            .replace(
                "停止证据：pure_search_seconds=600; scheduler_status=ten_minute_limit",
                "停止证据：source_classes=complete; query_dimensions=complete; "
                "zero_yield_rounds=3; coverage_gaps=closed; domains=diverse; "
                "candidate_set=stable",
            )
        )
        self.assertIn("invalid-stop-for-run-type", result.errors)

    def test_bounded_scope_completion_requires_exact_page_evidence(self):
        valid = (
            VALID.replace(
                "运行类型：open_web_research",
                "运行类型：bounded_dataset_extract",
            )
            .replace("纯搜索时间：600 秒", "纯搜索时间：12.5 秒")
            .replace("停止原因：达到10分钟", "停止原因：确定范围完成")
            .replace(
                "停止证据：pure_search_seconds=600; scheduler_status=ten_minute_limit",
                "停止证据：boundary=pages:0..3; expected_pages=4; "
                "completed_pages=4; failed_pages=0; "
                "scheduler_status=deterministic_scope_complete",
            )
        )
        self.assertEqual(validate_report(valid).errors, ())
        incomplete = valid.replace("completed_pages=4", "completed_pages=3")
        self.assertIn(
            "incomplete-deterministic-scope",
            validate_report(incomplete).errors,
        )

    def test_ten_minute_reason_requires_six_hundred_search_seconds(self):
        result = validate_report(
            VALID.replace("纯搜索时间：600 秒", "纯搜索时间：6.74 秒")
        )
        self.assertIn("ten-minute-stop-before-limit", result.errors)

    def test_trajectory_run_id_must_match_statistics(self):
        result = validate_report(
            VALID.replace("轨迹运行 ID：run-1", "轨迹运行 ID：probe-1")
        )
        self.assertIn("trajectory-run-mismatch", result.errors)

    def test_cumulative_union_arithmetic_is_enforced(self):
        result = validate_report(
            VALID.replace("累计已验证对象数：251", "累计已验证对象数：78")
        )
        self.assertIn("invalid-cumulative-union", result.errors)

    def test_saturation_requires_complete_machine_readable_evidence(self):
        saturated = VALID.replace("停止原因：达到10分钟", "停止原因：搜索饱和").replace(
            "停止证据：pure_search_seconds=600; scheduler_status=ten_minute_limit",
            "停止证据：zero_yield_rounds=3",
        )
        self.assertIn(
            "incomplete-saturation-evidence", validate_report(saturated).errors
        )

    def test_only_final_report_and_incident_registry_are_allowed(self):
        before = {"existing.md"}
        after = {
            "existing.md",
            "调研报告/final.md",
            ".codex-runtime/collect-bug-update-accelerate/incident-registry.json",
            "tmp.json",
        }
        allowed = {
            "调研报告/final.md",
            ".codex-runtime/collect-bug-update-accelerate/incident-registry.json",
        }
        self.assertEqual(unexpected_artifacts(before, after, allowed), {"tmp.json"})

    def test_artifact_paths_normalize_separators_case_and_dot_segments(self):
        before = {"existing.md"}
        after = {"TEMP/cache/../report.md", "logs\\.\\run.txt"}
        allowed = {"temp\\REPORT.md"}
        self.assertEqual(unexpected_artifacts(before, after, allowed), {"logs\\run.txt"})


if __name__ == "__main__":
    unittest.main()


