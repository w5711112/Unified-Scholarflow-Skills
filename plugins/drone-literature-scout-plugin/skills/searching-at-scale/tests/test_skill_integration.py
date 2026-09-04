from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SEARCH_DIR = PLUGIN_ROOT / "skills" / "searching-at-scale"
SEARCH = SEARCH_DIR / "SKILL.md"
DRONE = PLUGIN_ROOT / "skills" / "drone-literature-scout" / "SKILL.md"
README = PLUGIN_ROOT / "README.md"

EXPECTED_HEADINGS = (
    "# 大规模通用网页调研",
    "## 插件级轻量故障协作",
    "## 触发与退出",
    "## 单层直接参考",
    "## 单一证据脊柱",
    "## 标准执行流",
    "## 脚本接口与状态所有权",
    "## 兄弟 Skill 交接",
)
SUBSTANTIVE_REFERENCES = {
    "source-routing.md",
    "domestic-marketplace-edge-contract.md",
    "global-scheduler.md",
    "adaptive-schema.md",
    "verification-contract.md",
    "report-contract.md",
    "runtime-lifecycle-and-cleanup.md",
}
SCRIPT_ROUTES = {
    "build_query_matrix.py",
    "normalize_and_dedupe.py",
    "aggregate_evidence.py",
    "compute_timeseries.py",
    "validate_report.py",
    "render_search_timeline.py",
    "discover_sitemaps.py",
    "market_scheduler.py",
    "backend_runner.py",
    "runtime_manager.py",
    "searxng_query.py",
    "common_crawl_query.py",
    "common_crawl_url_index.py",
    "duckdb_runtime.py",
}
DRONE_BOUNDARY = """### 通用大规模搜索前置

需要扩展跨网站、跨语言或跨来源候选时，可调用 `searching-at-scale` 完成前期候选发现、URL 去重和通用证据采集。返回结果只作为候选证据包；本 Skill 继续独占 venue、单无人机、感知—控制闭环、算力/部署门槛、论文库写入、方向评分和最终接纳，`searching-at-scale` 不得接管论文接纳。"""


def authority_text() -> str:
    return "\n".join(
        [SEARCH.read_text(encoding="utf-8")]
        + [
            (SEARCH_DIR / "references" / name).read_text(encoding="utf-8")
            for name in sorted(SUBSTANTIVE_REFERENCES)
        ]
    )


class SkillIntegrationTests(unittest.TestCase):
    def test_jd_resilient_pagination_contract_is_consistent_across_surfaces(self) -> None:
        """Catches stale protocol/docs or permission growth before extension reload."""
        skill = authority_text()
        readme = README.read_text(encoding="utf-8")
        manifest = json.loads(
            (SEARCH_DIR / "edge-extension" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual("2.3.1", manifest["version"])
        self.assertEqual(
            ["nativeMessaging", "storage", "alarms"], manifest["permissions"]
        )
        self.assertEqual(
            [
                "https://search.jd.com/*",
                "https://s.taobao.com/*",
                "https://cfe.m.jd.com/privatedomain/risk_handler/*",
                "https://passport.jd.com/new/login.aspx*",
            ],
            manifest["host_permissions"],
        )
        self.assertEqual(
            [
                "https://item.jd.com/*",
                "https://item.taobao.com/*",
                "https://detail.tmall.com/*",
                "https://detail.tmall.hk/*",
            ],
            manifest["optional_host_permissions"],
        )

        for token in (
            "`start | next | recover`",
            "`<topic>`、`<topic> 自营`、`<topic> 品牌`、`<topic> 型号`、`<topic> 新品`",
            "`--max-pages-per-topic auto`",
            "每话题页数上限",
            "懒生成",
            "`1..512`",
            "`reproject` 后同标签 `reload`",
            "验证码、明确限流、风险处理重定向、登录失效和未知失败",
            "失败关闭且不进入恢复",
            "跨查询族全局 SKU 去重",
            "扩展版本 `2.3.1`",
            "`protocol_version: 3`",
            "`projection_schema_version: 4`",
            "`resilient_pagination_v1`",
            "2.2.2 相邻公开 URL 安全例外",
            "每个真实检查点绘制绿色 marker",
            "重叠漏斗终点绘制绿色空心环",
        ):
            self.assertIn(token, skill)

        for token in (
            "扩展 `2.3.1`",
            "`start` / `next` / `recover`",
            "`--max-pages-per-topic auto`",
            "topic → topic 自营 → topic 品牌 → topic 型号 → topic 新品",
            "`edge://extensions`",
            "重新加载",
        ):
            self.assertIn(token, readme)
        self.assertLess(len(readme), len(skill) // 3)

    def test_jd_sustained_driver_failure_and_timing_contract_is_explicit(self) -> None:
        text = authority_text()
        for token in (
            "预检等待不计入 `T_discovery`",
            "默认墙钟安全上限 **900 秒**",
            "`edge_extension_reload_required`",
            "`card_fields_json`",
            "退出码非零",
            "页面未展示时为 JSON `null`",
        ):
            self.assertIn(token, text)

    def test_edge_native_messaging_contract_is_explicit(self) -> None:
        text = authority_text()
        for token in (
            "日常 Edge",
            "active:false",
            "Manifest V3",
            "Native Messaging",
            "不启用远程调试",
            "命名管道",
            "当前 Windows SID",
            "当前用户 HKCU",
            "不读取 Cookie",
            "不读取凭证",
            "一次性 Node",
            "一个 C# Native Host",
            "operation: detail",
            "optional_host_permissions",
            "不跟踪价格",
            "scripts/edge_marketplace_query.py",
            "scripts/edge_extension_client.mjs",
            "scripts/install_edge_native_host.ps1",
            "edge-extension/manifest.json",
        ):
            self.assertIn(token, text)

    def test_native_host_installer_can_register_an_existing_locked_host(self) -> None:
        """Re-registration must not delete a host executable Edge is using."""
        text = (SEARCH_DIR / "scripts" / "install_edge_native_host.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[switch]$RegisterExisting", text)
        self.assertIn("if ($RegisterExisting)", text)
        self.assertIn("edge_native_host_existing_binary_missing", text)
        self.assertIn("UTF8Encoding -ArgumentList $false", text)
        self.assertNotIn("-Encoding utf8NoBOM", text)

    def test_workflow_headings_have_the_approved_order(self) -> None:
        """Catches omitted, renamed, duplicated, or reordered workflow stages."""
        headings = tuple(
            line.strip()
            for line in SEARCH.read_text(encoding="utf-8").splitlines()
            if re.fullmatch(r"#{1,2} .+", line.strip())
        )
        self.assertEqual(EXPECTED_HEADINGS, headings)

    def test_trigger_tiers_and_conflict_upgrade_are_explicit(self) -> None:
        """Catches loss of fast/direct, automatic, explicit, or upgrade routing."""
        text = SEARCH.read_text(encoding="utf-8")
        for token in ("快速直达", "自动大规模触发", "显式调用", "自动升级"):
            self.assertIn(token, text)

    def test_broad_discovery_precedes_strict_verification(self) -> None:
        """Catches moving strict gates ahead of high-recall discovery."""
        text = SEARCH.read_text(encoding="utf-8")
        self.assertIn("### 2. 先召回，再收敛", text)
        self.assertIn("### 5. 核验、报告与最终验收", text)
        self.assertLess(
            text.index("### 2. 先召回，再收敛"),
            text.index("### 5. 核验、报告与最终验收"),
        )
        self.assertIn("L0", text)
        self.assertIn("L3", text)

    def test_clock_concurrency_progress_and_continuation_contracts_exist(self) -> None:
        """Catches early timing, global backoff, count caps, or report-and-pause."""
        text = authority_text()
        for token in (
            "方向准备完成后才启动",
            "不设置固定 URL 数量上限",
            "SearXNG",
            "2 → 4",
            "Common Crawl",
            "1 → 2",
            "4 → 8 → 16",
            "40 降至 32",
            "32 稳定窗口",
            "再回升 40",
            "32 仍不健康",
            "再降至 24",
            "少量、孤立的 429",
            "失败查询进入补偿队列",
            "规范化去重有效 URL/秒",
            "不得从错误统计中删除",
            "不是全局并发上限",
            "最高安全并发",
            "按后端独立退避",
            "约每分钟",
            "报告后不得暂停",
            "自动进入去重、筛选和严格核验",
        ):
            self.assertIn(token, text)
        self.assertNotIn("达到 10,000 后停止", text)
        self.assertNotIn("max_urls", text)

    def test_source_routing_uses_the_approved_concurrency_state_machine(self) -> None:
        """Catches drift from the 24/32/40 ladder or retry compensation."""
        text = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "24 → 32 → 40",
            "少量、孤立的 429",
            "补偿队列",
            "40 降至 32",
            "32 稳定窗口",
            "再回升 40",
            "32 仍不健康",
            "再降至 24",
        ):
            self.assertIn(token, text)

    def test_free_bulk_routing_prefers_open_indexes_and_upgrades_lazily(self) -> None:
        """Catches treating metasearch wrappers or a full cluster as the free default."""
        text = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "开放索引/开放数据",
            "Common Crawl",
            "元搜索只补漏",
            "Fess",
            "Spider",
            "Crawlab",
            "不为 URL 规模里程碑预装",
        ):
            self.assertIn(token, text)
        self.assertLess(text.index("Common Crawl"), text.index("Fess"))
        self.assertLess(text.index("Fess"), text.index("Spider"))
        self.assertLess(text.index("Spider"), text.index("Crawlab"))

    def test_github_bulk_routing_uses_open_datasets_then_local_code_search(self) -> None:
        """Catches driving large GitHub discovery through the live Search API."""
        text = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "GitHub Search API 不作为大规模主干",
            "GH Archive",
            "Software Heritage",
            "World of Code",
            "Zoekt",
            "发现 → 按需获取 → 本地索引 → 本地查询",
        ):
            self.assertIn(token, text)

    def test_concurrency_tiers_are_targets_and_actual_peak_is_reported(self) -> None:
        """Catches claiming 24/32/40 when the active tool exposes a lower cap."""
        route_text = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("调度目标档位", route_text)
        self.assertIn("实际达到的最高并发", route_text)
        self.assertIn("不得把目标档位写成实际并发", route_text)

    def test_marketplace_parallelism_is_cross_source_and_jd_stays_single_lane(self) -> None:
        """Catches replacing source fan-out with same-session JD tab fan-out."""
        route_text = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "跨来源并行",
            "京东 Edge 固定为 1",
            "SQLite 批次提交保持单写入",
            "京东冷却不得压低其他来源",
        ):
            self.assertIn(token, route_text)

    def test_relay_pipeline_fans_out_without_requiring_a_new_controller(self) -> None:
        """Catches serial one-provider search and redundant fetches between stages."""
        text = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "种子发现 → 批量扩张 → 去重抓取 → 证据回流",
            "Codex 内置网页搜索",
            "读取当前会话工具 schema",
            "单次查询数组上限",
            "站点地图/RSS",
            "Firecrawl",
            "同一规范化 URL 只抓取一次",
            "无需新增常驻总控服务",
        ):
            self.assertIn(token, text)

    def test_high_friction_commerce_prefers_batches_and_samples_pages(self) -> None:
        """Catches using protected HTML pages as the high-throughput backbone."""
        text = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("## 高摩擦平台与电商", text)
        section = text.split("## 高摩擦平台与电商", 1)[1].split("\n## ", 1)[0]
        stages = (
            "零凭证批量发现",
            "开放索引/开放数据",
            "搜索摘要",
            "直接 HTTP/已授权浏览器",
            "官方或获授权的批量 API/数据导出",
        )
        for token in (
            *stages,
            "代表样本、异常记录和最终候选",
            "全站",
            "联盟推广池",
            "精选/策展池",
            "商家自有",
            "历史索引",
            "覆盖范围",
            "权限",
            "成本",
            "数据时效",
        ):
            self.assertIn(token, section)
        positions = [section.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))

    def test_throughput_contract_never_relabels_records_as_pages(self) -> None:
        """Catches claiming page throughput from URL discovery or batch records."""
        route = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        report = (SEARCH_DIR / "references" / "report-contract.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "url_discovery_per_second",
            "successful_page_bodies_per_second",
            "unique_valid_structured_records_per_second",
        ):
            self.assertIn(token, route)
            self.assertIn(token, report)
        self.assertIn("不得把商品记录数、URL 发现数或“等价页面”写成成功页面数", route)
        self.assertIn("30 条/秒", route)

    def test_aggregate_concurrency_is_composed_from_real_backend_caps(self) -> None:
        """Catches sending the aggregate target to one constrained backend."""
        text = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "聚合在途任务数",
            "各后端真实并发上限之和",
            "按新增有效 URL/秒分配下一批",
            "不得向单一后端强塞聚合档位",
        ):
            self.assertIn(token, text)

    def test_every_run_emits_raw_url_timeline_and_separate_rates(self) -> None:
        """Catches optional charts or conflated discovery/page/record throughput."""
        skill = SEARCH.read_text(encoding="utf-8")
        report = (SEARCH_DIR / "references" / "report-contract.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "每次使用本 Skill",
            "纯发现时间的墙钟并集",
            "raw_url_observations_per_second",
            "url_discovery_per_second",
            "successful_page_bodies_per_second",
            "unique_valid_structured_records_per_second",
            "累计未去重 URL",
            "Mermaid",
            "字符折线",
            "scripts/render_search_timeline.py",
        ):
            self.assertIn(token, skill + report)

    def test_marketplace_two_point_chat_contract_prefers_html_or_svg(self) -> None:
        """Catalog charts stay visible without requiring Mermaid for two points."""
        contract = (SEARCH_DIR / "references" / "report-contract.md").read_text(
            encoding="utf-8"
        )
        html = contract.index("优先输出轻量 HTML fragment")
        svg = contract.index("无 HTML 时回退 SVG")
        mermaid = contract.index("非商品发现再回退 Mermaid")
        marketplace_ascii = contract.index("商品型任务最终回退为发现字符折线加完整漏斗数字")
        self.assertLess(html, svg)
        self.assertLess(svg, mermaid)
        self.assertLess(mermaid, marketplace_ascii)

    def test_zero_credential_acceleration_route_is_explicit(self) -> None:
        """Catches silent fallback to credentialed affiliate APIs."""
        text = SEARCH.read_text(encoding="utf-8") + (
            SEARCH_DIR / "references" / "source-routing.md"
        ).read_text(encoding="utf-8")
        for token in (
            "默认零凭证数据面顺序",
            "Sitemap/RSS + 宿主已有搜索种子 → 临时 SearXNG → Common Crawl URL Index",
            "联盟或其他授权接口仅在用户明确选择且权限探测通过后使用",
        ):
            self.assertIn(token, text)

    def test_common_crawl_exact_and_bulk_routes_are_unambiguous(self) -> None:
        """Catches returning broad URL discovery to fragile CDX pagination."""
        text = authority_text()
        for token in (
            "exact URL → 单次 CDX",
            "domain/subdomain/prefix → DuckDB URL Index",
            "scripts/common_crawl_query.py",
            "scripts/common_crawl_url_index.py",
            "scripts/duckdb_runtime.py",
            "分钟级历史扩张",
            "10 分钟",
            "显式 `partial`",
            "历史索引不得证明实时价格、库存或当前全量",
            "空闲零常驻",
        ):
            self.assertIn(token, text)
        common_crawl_contract = next(
            line
            for line in text.splitlines()
            if "exact URL → 单次 CDX" in line
        )
        self.assertNotIn("showNumPages", common_crawl_contract)

    def test_product_search_uses_product_first_routes_and_full_funnel(self) -> None:
        """Catches treating a low-yield root Sitemap census as product coverage."""
        skill = SEARCH.read_text(encoding="utf-8")
        route = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        report = (SEARCH_DIR / "references" / "report-contract.md").read_text(
            encoding="utf-8"
        )
        combined = skill + route + report
        for token in (
            "商品专用 Sitemap",
            "商品分类页",
            "JSON-LD Product",
            "根 Sitemap 仅作覆盖审计和补漏",
            "product_candidate_yield",
            "5%",
            "raw_url_observations",
            "literal_unique_urls",
            "normalized_unique_urls",
            "content_unique_pages",
            "topic_relevant_pages",
            "product_page_candidates",
            "unique_valid_structured_records",
            "first_discovery_channel",
            "all_discovery_channels",
            "#2e7d32",
            "#c62828",
            "左/下轴",
            "上/右轴",
        ):
            self.assertIn(token, combined)

    def test_product_relevance_uses_isolated_primary_fields(self) -> None:
        """Catches broad hostname/image leakage while retaining exact platform routes."""
        route = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "只使用规范化 URL 的 path",
            "不得使用 query 或 fragment",
            "product_hostnames",
            "受控精确名单",
            "不是品牌关键词启发式",
            "主商品标题",
            "不得把图片 alt、图片 caption、描述",
            "完整词或受控词边界",
            "pillowcase",
            "pillow-top",
            "机器候选数",
            "不得晋升为 `unique_valid_structured_records`",
        ):
            self.assertIn(token, route)

    def test_product_sources_zoom_and_time_allocation_are_explicit(self) -> None:
        """Catches opaque sellers, browser-only charts, and raw-URL-only routing."""
        skill = SEARCH.read_text(encoding="utf-8")
        route = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        report = (SEARCH_DIR / "references" / "report-contract.md").read_text(
            encoding="utf-8"
        )
        combined = skill + route + report
        for token in (
            "source_role",
            "brand_official",
            "vertical_retailer",
            "marketplace_store",
            "historical_index",
            "seller",
            "market_region",
            "purchase_access",
            "Pillows.com",
            "product_candidates_per_second",
            "unique_valid_records_per_second",
            "纯发现时间 × URL 发现速度 × 商品/记录命中率",
            "单位发现时间新增有效型号最多",
            "Codex 对话内",
            "1×–4×",
            "滚轮",
            "拖动",
            "重置",
            "不打开外部浏览器",
        ):
            self.assertIn(token, combined)

    def test_slow_discovery_switches_to_bulk_and_discloses_degraded_mode(self) -> None:
        """Catches serial search loops or silent operation below 50 raw URL/s."""
        route = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "search",
            "sitemap",
            "open_index",
            "dataset",
            "bulk_api",
            "page",
            "50 个未去重 URL/秒",
            "至少两个批次",
            "5 秒",
            "15 秒",
            "页面通道",
            "API/离线索引通道",
            "独立退避",
        ):
            self.assertIn(token, route)

    def test_chart_type_scale_is_explicit_and_consistent(self) -> None:
        """Catches unreadably small charts or drift between the two contracts."""
        skill = SEARCH.read_text(encoding="utf-8")
        report = (SEARCH_DIR / "references" / "report-contract.md").read_text(
            encoding="utf-8"
        )
        for token in ("24px", "18px", "16px"):
            self.assertIn(token, skill)
            self.assertIn(token, report)

    def test_raw_url_curve_is_not_saturation_evidence_by_itself(self) -> None:
        """Catches claiming saturation from a merely flattening raw URL chart."""
        skill = SEARCH.read_text(encoding="utf-8")
        report = (SEARCH_DIR / "references" / "report-contract.md").read_text(
            encoding="utf-8"
        )
        token = "未去重 URL 增长不能单独证明搜索饱和"
        self.assertIn(token, skill)
        self.assertIn(token, report)

    def test_large_ledgers_spill_only_to_scoped_temporary_storage(self) -> None:
        """Catches placing the URL pool in context or retaining intermediates."""
        text = authority_text()
        for token in (
            "任务专属 SQLite",
            "有界流式 NDJSON",
            "不把 URL 池塞入上下文或状态 JSON",
            "解析并验证绝对路径",
            "验证不存在",
        ):
            self.assertIn(token, text)
        self.assertNotIn("只存在内存或工具返回中，不得落盘", text)

    def test_substantive_references_are_one_level_and_linked(self) -> None:
        """Catches missing heavy contracts or deep-reference drift."""
        text = SEARCH.read_text(encoding="utf-8")
        reference_dir = SEARCH_DIR / "references"
        self.assertEqual(
            SUBSTANTIVE_REFERENCES,
            {path.name for path in reference_dir.glob("*.md")},
        )
        for name in SUBSTANTIVE_REFERENCES:
            route = f"references/{name}"
            self.assertIn(route, text)
            path = reference_dir / name
            self.assertTrue(path.is_file(), path)
            self.assertGreater(len(path.read_text(encoding="utf-8").strip()), 200)
        linked = re.findall(r"`(references/[^`]+\.md)`", text)
        self.assertTrue(linked)
        for route in linked:
            self.assertEqual(1, route.count("/"), route)
            self.assertTrue((SEARCH_DIR / route).is_file(), route)

    def test_collaboration_direct_link_resolves_to_plugin_contract(self) -> None:
        """Catches a fifth local reference or a broken canonical-contract link."""
        text = SEARCH.read_text(encoding="utf-8")
        match = re.search(
            r"\[[^]]+\]\((\.\./\.\./references/skill-collaboration-contract\.md)\)",
            text,
        )
        self.assertIsNotNone(match, text)
        target = (SEARCH_DIR / match.group(1)).resolve()
        self.assertEqual(
            (PLUGIN_ROOT / "references" / "skill-collaboration-contract.md").resolve(),
            target,
        )
        self.assertTrue(target.is_file(), target)

    def test_script_routes_exist_and_only_scheduler_owns_scoped_state(self) -> None:
        """Catches stale links or stateful helpers outside the global scheduler."""
        text = SEARCH.read_text(encoding="utf-8")
        for name in SCRIPT_ROUTES:
            route = f"scripts/{name}"
            self.assertIn(route, text)
            self.assertTrue((SEARCH_DIR / route).is_file(), route)
        self.assertIn("除 `scripts/market_scheduler.py` 外", text)
        self.assertIn("其他确定性脚本", text)
        self.assertIn("标准输入/输出", text)
        self.assertIn("不得读写任务状态文件", text)
        self.assertIn("任务专属状态路径", text)

    def test_market_discovery_requires_global_scheduler(self) -> None:
        """Catches batch completion being mislabeled as complete market coverage."""
        text = authority_text()
        for token in (
            "scripts/market_scheduler.py",
            "`preflight_probe`",
            "`backend_batch`",
            "`market_discovery`",
            "`queue_exhausted` 只结束当前批次",
            "600 秒",
            "`incomplete_blocked`",
            "跨轮累计并集",
        ):
            self.assertIn(token, text)

    def test_lightweight_data_plane_and_run_types_are_explicit(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                SEARCH,
                SEARCH_DIR / "references" / "source-routing.md",
                SEARCH_DIR / "references" / "global-scheduler.md",
                SEARCH_DIR / "references" / "report-contract.md",
            )
        )
        for token in (
            "quick_direct",
            "open_web_research",
            "catalog_enumeration",
            "bounded_dataset_extract",
            "deterministic_scope_complete",
            "临时 SearXNG",
            "Common Crawl URL Index",
            "任务专属 SQLite",
            "惰性分批",
            "不自动启动 Docker Desktop",
            "不创建持久 volume",
            "空闲零常驻",
            "2 → 4",
            "1 → 2",
            "4 → 8 → 16",
            "1 → 2",
            "10 分钟（600 秒）硬上限",
            "历史索引不得证明实时价格、库存或当前全量",
            "成功、失败和中断",
            "精确清理",
            "run-backends",
        ):
            self.assertIn(token, combined)
        for forbidden in (
            "20 分钟",
            "20分钟",
            "1,200 秒",
            "默认 60 秒",
            "默认 300 秒",
        ):
            self.assertNotIn(forbidden, combined)

    def test_global_scheduler_reference_is_routed(self) -> None:
        """Catches hiding the operational loop outside the skill routing table."""
        self.assertIn(
            "references/global-scheduler.md",
            SEARCH.read_text(encoding="utf-8"),
        )

    def test_legacy_twenty_minute_contract_is_absent(self) -> None:
        """Catches drift back to the superseded 20-minute discovery ceiling."""
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                SEARCH,
                SEARCH_DIR / "references" / "source-routing.md",
                SEARCH_DIR / "references" / "report-contract.md",
                SEARCH_DIR / "references" / "global-scheduler.md",
            )
            if path.exists()
        )
        for token in ("20 分钟", "20分钟", "1,200 秒", "达到20分钟"):
            self.assertNotIn(token, combined)

    def test_bulk_sitemap_gate_contract_is_explicit(self) -> None:
        """Catches treating ranked search as an unverified bulk-discovery route."""
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                SEARCH,
                SEARCH_DIR / "references" / "source-routing.md",
                SEARCH_DIR / "references" / "report-contract.md",
            )
        )
        for token in (
            "scripts/discover_sitemaps.py",
            "Python `urllib`",
            "bulk_unchecked",
            "bulk_ready",
            "bulk_degraded",
            "bulk_unavailable",
            "只有 `bulk_ready`",
            "硬停止",
            "普通搜索不能满足批量闸门",
            "primary_urls_per_second",
            "media_url_observations",
            "error_category",
            "SEC_E_NO_CREDENTIALS",
        ):
            self.assertIn(token, combined)

    def test_schannel_error_is_assigned_to_the_powershell_curl_route(self) -> None:
        """Catches assigning Schannel credential failures to urllib/OpenSSL."""
        for text in (
            SEARCH.read_text(encoding="utf-8"),
            (SEARCH_DIR / "references" / "source-routing.md").read_text(
                encoding="utf-8"
            ),
        ):
            self.assertIn("Python `urllib`/OpenSSL", text)
            self.assertIn("PowerShell/curl 的 Schannel 路线", text)
            self.assertNotIn(
                "Python `urllib` 出现 Schannel `SEC_E_NO_CREDENTIALS`", text
            )
            self.assertNotIn(
                "Python `urllib` 返回 Schannel `SEC_E_NO_CREDENTIALS`", text
            )

    def test_sitemap_runtime_evidence_and_positive_coverage_are_documented(self) -> None:
        """Catches empty-Sitemap readiness or loss of streamed provenance fields."""
        route = (SEARCH_DIR / "references" / "source-routing.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "`exhaustive_seed_count >= 2`",
            "`primary_urls > 0`",
            "空 Sitemap 不能进入 `bulk_ready`",
            '`discovery_channel="sitemap"`',
            "`product_candidate_evidence`",
            "`sitemap_product_shard`",
            "`url_path_hint`",
            "精确 path token",
            "`nonproduct`",
        ):
            self.assertIn(token, route)
        readiness = next(
            line
            for line in route.splitlines()
            if line.startswith("- `bulk_ready`")
        )
        self.assertIn("`exhaustive_seed_count >= 2`", readiness)
        self.assertIn("`primary_urls > 0`", readiness)
        self.assertIn("空 Sitemap 不能进入 `bulk_ready`", readiness)
        self.assertIn(
            "归入 `first_discovery_channel` 和 `all_discovery_channels`", route
        )

    def test_drone_handoff_keeps_acceptance_owner(self) -> None:
        """Catches generic discovery taking UAV acceptance ownership."""
        text = DRONE.read_text(encoding="utf-8")
        self.assertEqual(1, text.count(DRONE_BOUNDARY))

    def test_search_and_readme_skill_names_stay_aligned(self) -> None:
        """Catches unformatted or missing sibling identifiers."""
        self.assertTrue(SEARCH.is_file())
        readme = README.read_text(encoding="utf-8")
        for name in ("searching-at-scale",):
            self.assertRegex(readme, rf"(?m)^\| `{re.escape(name)}`\s*\|")
        self.assertIn("六个领域 skill", readme)
        self.assertIn("global.collect-bug-update-accelerate", readme)
        self.assertIn("global.migration-skill", readme)
        self.assertIn("global.renhua", readme)


if __name__ == "__main__":
    unittest.main()
