"""以统一 CSV 为唯一事实源，生成中文研究分析视图。"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import date
from pathlib import Path

from corpus_tools import (
    can_support_quantitative_claim,
    has_complete_original_abstract,
    validate_csv_file,
)
from research_metrics import rank_directions


DIRECTIONS = [
    {
        "name": "<YOUR_RESEARCH_PROJECT>",
        "summary": "研究单架无人机在动态障碍、感知误差和控制延迟同时存在时，如何用低维风险/走廊表示与安全过滤器完成轻量化轨迹规划；重点不是重复普通避障，而是给出资源—风险—泛化之间可复现实验边界。",
        "keywords": ["dynamic obstacle", "safe reinforcement learning", "uncertainty", "trajectory planning", "corridor", "risk-aware", "monocular", "LiDAR", "risk-tendency", "VO-Safe", "visual odometry", "semantic scenes"],
        "feasibility": "采用两层同接口环境，并把传感器与地图做成可消融变量：第一层是无渲染的 GPU 向量化高层规划环境，用栅格/走廊/动态风险表示训练 B-spline 或低维策略；第二层把同一策略接入 Isaac Lab 无渲染 PhysX 六自由度四旋翼模型，校验质量、惯量、推力、执行器延迟、风扰和传感器延迟。先建立三条可比较链路：LiDAR + 局部建图 + SFC/安全过滤器，激光测距 + 无地图风险策略，以及相机 + VO/语义场景的定位安全策略。安全保障建议分层：几何碰撞约束或 CBF/备用控制器负责硬约束，风险分布或不确定性估计负责策略趋保守，悬停/返航/急停负责超出观测分布时的失效回退；这些是本项目设计假设，不是现有论文已经共同证明的结论。",
        "risk": "NavRL 已经把 PPO、动态障碍、速度障碍安全层、Isaac Sim 和 Jetson Orin NX 组合起来，CORB-Planner 已经在 IEEE/ASME Transactions on Mechatronics 2025 展示低维安全飞行走廊、建图依赖和约十分钟训练；ART-IQN 说明不显式建图的四向激光风险策略可以轻量运行，但其策略在 laptop 上执行，Jetson 适配未报告；VO-Safe 说明相机/VO/语义输入可以避免定位失效，但实验使用 collision-free 环境，不能把定位安全写成障碍碰撞安全。若只替换算法或传感器，论文新颖性不足。必须补上感知不确定性、动作延迟、遮挡/漏检、未见障碍速度和完整资源—风险曲线，并在真实无人机上验证。",
        "venues": "RAL / ICRA / RSS / IROS",
        "dimensions": {"recommendation": 10, "prospect": 10, "feasibility": 8, "venue_fit": 10, "uniqueness": 9, "evidence": 8, "learning_fit": 10},
    },
    {
        "name": "Isaac Lab 并行强化学习与跨动力学四旋翼适应",
        "summary": "用 Isaac Lab 的向量化环境并行训练低维策略，使策略覆盖载荷、风扰、尺度和执行器变化，再在单架四旋翼上验证跨动力学迁移。",
        "keywords": ["dynamics-invariant", "scale-aware", "Omnidrones", "reinforcement learning", "domain randomization", "residual dynamics"],
        "feasibility": "训练放在 Isaac Lab 的向量化强化学习环境中，机载只保留低维策略和安全回退层；目前文献没有给出 RTX 4090 或 RTX 5070 Ti 的项目级训练时长，因此必须用本地基准补齐。",
        "risk": "跨尺度泛化可能依赖系统辨识和真实平台覆盖；如果缺少 Jetson 延迟、峰值显存和真实飞行对比，贡献容易退化为训练工程。",
        "venues": "RAL / IROS / ICRA / CoRL",
        "dimensions": {"recommendation": 10, "prospect": 9, "feasibility": 7, "venue_fit": 9, "uniqueness": 9, "evidence": 8, "learning_fit": 10},
    },
    {
        "name": "感知约束的安全规划与控制屏障过滤",
        "summary": "把视场、可见性、碰撞和降落安全约束写进规划器或控制屏障层，形成可验证的感知—控制闭环。",
        "keywords": ["control barrier", "cbf", "safe navigation", "safety filter", "visibility-aware"],
        "feasibility": "优先使用几何约束、QP、低阶 NMPC 和小型安全策略；Jetson Orin NX 可承担在线过滤，训练可在单卡环境完成。",
        "risk": "约束过于保守会牺牲可行域；必须用真实延迟、感知失效和模型误差实验说明安全收益。",
        "venues": "RAL / T-RO / ICRA / IROS",
        "dimensions": {"recommendation": 9, "prospect": 9, "feasibility": 8, "venue_fit": 9, "uniqueness": 8, "evidence": 9, "learning_fit": 9},
    },
    {
        "name": "可微仿真与残差动力学的在线 Sim-to-Real 适应",
        "summary": "结合可微动力学、残差模型和少量真实飞行数据持续校正策略，实现低数据量的闭环适应。",
        "keywords": ["differentiable simulation", "sim-to-real", "residual dynamics", "policy adaptation", "online learning"],
        "feasibility": "把大规模并行训练与机载推理解耦，机载只保留低阶模型、残差更新和小策略，避免依赖大模型。",
        "risk": "在线学习可能破坏稳定性；必须加入安全回退、更新频率上限和真实飞行预算。",
        "venues": "RAL / ICRA / RSS / CoRL",
        "dimensions": {"recommendation": 9, "prospect": 10, "feasibility": 7, "venue_fit": 9, "uniqueness": 9, "evidence": 8, "learning_fit": 8},
    },
    {
        "name": "轻量视觉闭环导航与实时重规划",
        "summary": "围绕单目、RGB-D 或轻量视觉输入，在有限算力下完成障碍规避、局部规划和控制输出。",
        "keywords": ["vision-based", "visual navigation", "obstacle avoidance", "replanning", "quadrotor navigation"],
        "feasibility": "采用小型编码器、稀疏几何表示和低频感知—高频控制分层，适配 Jetson Orin NX 和 12GB 级训练条件。",
        "risk": "常规视觉避障容易同质化；必须把延迟、失明区和控制稳定性作为统一指标。",
        "venues": "RAL / ICRA / IROS / TRO",
        "dimensions": {"recommendation": 9, "prospect": 9, "feasibility": 9, "venue_fit": 9, "uniqueness": 8, "evidence": 9, "learning_fit": 10},
    },
    {
        "name": "移动目标跟踪与视觉伺服降落",
        "summary": "将目标检测、跟踪、运动估计和单机控制整合为可部署的视觉伺服与移动平台降落闭环。",
        "keywords": ["visual servo", "target tracking", "moving platform", "moving target", "landing"],
        "feasibility": "从相对位姿、速度估计和低阶预测器开始，控制端使用 MPC、CBF 或经典低层回路。",
        "risk": "目标遮挡和相机延迟会放大误差；需要区分真实闭环实验与只做检测的工作。",
        "venues": "RAL / IROS / TMech / TASE",
        "dimensions": {"recommendation": 8, "prospect": 9, "feasibility": 8, "venue_fit": 8, "uniqueness": 8, "evidence": 8, "learning_fit": 9},
    },
    {
        "name": "主动感知、目标搜索与遮挡后重捕获",
        "summary": "让无人机主动选择视角和轨迹以提高信息增益、保持可见性，并在目标丢失后完成搜索与重捕获。",
        "keywords": ["active perception", "active search", "reacquisition", "search and tracking", "information gain"],
        "feasibility": "以局部候选视点、可见性代价和轻量规划为核心，避免依赖大型世界模型或多机协同。",
        "risk": "主动行为与控制耦合容易停留在仿真；需要单机真实遮挡和能耗基准。",
        "venues": "CVPR / ICRA / IROS / RAL",
        "dimensions": {"recommendation": 8, "prospect": 9, "feasibility": 8, "venue_fit": 8, "uniqueness": 8, "evidence": 8, "learning_fit": 8},
    },
    {
        "name": "时间与能耗约束下的轨迹优化与 MPPI/MPC",
        "summary": "在动力学、视场、碰撞和电量约束下进行高效在线轨迹优化，并评估真实闭环收益。",
        "keywords": ["time-optimal", "trajectory", "mpc", "mppi", "contouring", "energy"],
        "feasibility": "控制器可用 C++、CUDA 或低阶采样器部署，学习模块只预测代价、扰动或 warm-start。",
        "risk": "单纯替换代价函数的新颖性不足；必须突出感知约束、算力和真实飞行验证。",
        "venues": "TRO / RAL / ICRA / RSS",
        "dimensions": {"recommendation": 8, "prospect": 8, "feasibility": 9, "venue_fit": 8, "uniqueness": 8, "evidence": 8, "learning_fit": 9},
    },
    {
        "name": "不确定性下的在线自适应控制与动力学辨识",
        "summary": "针对载荷、风、磨损和未建模动力学，学习或估计不确定性并在线调整控制律。",
        "keywords": ["uncertainty", "adaptive control", "neural ode", "dynamics-invariant", "system identification"],
        "feasibility": "使用小型残差模型和安全控制器，训练侧用并行仿真覆盖动力学变化，部署侧保持可解释的低维更新。",
        "risk": "仅做工程压缩不够新；需要把不确定性、感知质量、闭环稳定和任务成功率统一建模。",
        "venues": "RAL / ICRA / IROS / TNNLS",
        "dimensions": {"recommendation": 7, "prospect": 8, "feasibility": 9, "venue_fit": 8, "uniqueness": 7, "evidence": 7, "learning_fit": 9},
    },
    {
        "name": "风扰与外部扰动下的鲁棒飞行控制",
        "summary": "把风场、气动扰动和传感延迟纳入感知—控制闭环，研究可解释的鲁棒性与快速恢复。",
        "keywords": ["wind", "disturbance rejection", "robust control", "quadrotor control", "sim-to-real"],
        "feasibility": "用低维扰动估计器、残差策略和经典控制器组成回退结构，训练可以在 Isaac Lab 中并行完成。",
        "risk": "只做风场 benchmark 的工作新颖性有限；应验证未知扰动、跨平台迁移和机载资源。",
        "venues": "TRO / RAL / ICRA / IROS",
        "dimensions": {"recommendation": 7, "prospect": 8, "feasibility": 8, "venue_fit": 8, "uniqueness": 7, "evidence": 7, "learning_fit": 9},
    },
    {
        "name": "自监督表征学习驱动的视觉控制",
        "summary": "利用自监督、对比表征或几何先验减少标注，提升视觉伺服和导航策略在新环境中的迁移。",
        "keywords": ["self-supervised", "representation learning", "visual control", "geometric prior", "transfer"],
        "feasibility": "采用小型表征和冻结特征，训练与控制解耦，部署侧只保留低延迟编码器和控制策略。",
        "risk": "容易退化为通用视觉表征；必须证明表征确实改变了单机闭环控制而非只提升分类指标。",
        "venues": "RAL / ICRA / IROS / CVPR",
        "dimensions": {"recommendation": 7, "prospect": 8, "feasibility": 8, "venue_fit": 8, "uniqueness": 7, "evidence": 7, "learning_fit": 8},
    },
    {
        "name": "视觉/激光状态估计与控制协同设计",
        "summary": "研究视觉、激光或视觉惯性估计的不确定性如何进入轨迹规划和控制，而不是把估计当成黑盒前置模块。",
        "keywords": ["state estimation", "lidar", "visual inertial", "uncertainty", "control"],
        "feasibility": "采用轻量滤波、局部几何和不确定性传播，避免大型场景模型，适合 Jetson 级在线闭环。",
        "risk": "估计与控制的接口若没有可量化收益，容易成为系统集成；要有延迟、失效和安全事件对比。",
        "venues": "TRO / RAL / ICRA / IROS",
        "dimensions": {"recommendation": 7, "prospect": 8, "feasibility": 9, "venue_fit": 8, "uniqueness": 8, "evidence": 8, "learning_fit": 7},
    },
    {
        "name": "单机信息驱动探索、覆盖与巡检",
        "summary": "面向未知环境探索、结构扫描和巡检任务，以信息增益、可见性和飞行代价共同驱动单无人机规划。",
        "keywords": ["active exploration", "coverage", "inspection", "information gain", "single UAV"],
        "feasibility": "用局部地图、候选视点和低维代价规划，训练可并行扩展，机载只执行轻量局部决策。",
        "risk": "探索任务容易依赖大场景仿真；必须控制场景规模并报告单机资源、闭环延迟和真实巡检收益。",
        "venues": "RAL / ICRA / IROS / RSS",
        "dimensions": {"recommendation": 7, "prospect": 8, "feasibility": 8, "venue_fit": 8, "uniqueness": 8, "evidence": 7, "learning_fit": 8},
    },
    {
        "name": "边缘部署与算力/能耗感知的策略压缩",
        "summary": "把模型大小、延迟、功耗和控制频率作为研究变量，形成可复现的机载部署—闭环性能权衡。",
        "keywords": ["edge deployment", "latency", "power", "policy compression", "Jetson"],
        "feasibility": "采用蒸馏、剪枝、低秩适配和小型策略，直接以 Jetson 级硬件和 12GB 级训练条件为约束。",
        "risk": "单纯压缩模型缺乏方法新意；必须证明资源约束改变了感知—控制设计和任务结果。",
        "venues": "RAL / ICRA / IROS / TMC",
        "dimensions": {"recommendation": 7, "prospect": 8, "feasibility": 10, "venue_fit": 8, "uniqueness": 8, "evidence": 7, "learning_fit": 8},
    },
]


STATUS_LABELS = {
    "abstract_only": "摘要已核验，全文待核验",
    "reviewed_open_access": "开放全文已核验",
    "reviewed_official": "官方全文已核验",
}


def load_rows(path: Path) -> list[dict[str, str]]:
    errors = validate_csv_file(path)
    if errors:
        raise ValueError("CSV 完整性检查失败：\n" + "\n".join(errors))
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(handle)]


def direction_evidence(direction: dict, rows: list[dict[str, str]], limit: int = 5) -> list[dict[str, str]]:
    keywords = [keyword.casefold() for keyword in direction["keywords"]]
    matched = []
    for row in rows:
        text = f"{row.get('title', '')} {row.get('abstract', '')}".casefold()
        hits = sum(keyword in text for keyword in keywords)
        if hits:
            matched.append((hits, row))
    matched.sort(key=lambda item: (-item[0], item[1].get("venue_time", ""), item[1].get("title", "")))
    return [row for _, row in matched[:limit]]


def evidence_level(row: dict[str, str]) -> str:
    if can_support_quantitative_claim(row):
        return "全文已核验，可引用定量证据"
    if has_complete_original_abstract(row):
        return "完整原始摘要已核验；定量字段仍待全文核验"
    return "不得用于方向结论"


def paper_link(row: dict[str, str]) -> str:
    title = row.get("title", "").strip()
    url = row.get("url", "").strip()
    return f"[{title}]({url})" if url else title


def source_table(rows: list[dict[str, str]]) -> str:
    counts = Counter(row.get("source", "") for row in rows)
    lines = ["| 来源 | 篇数 |", "|---|---:|"]
    lines.extend(f"| {source or '未标注'} | {count} |" for source, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    return "\n".join(lines)


def year_table(rows: list[dict[str, str]]) -> str:
    counts = Counter((row.get("venue_time", "").split("-")[0] or "未知") for row in rows)
    lines = ["| 年份 | 篇数 |", "|---|---:|"]
    lines.extend(f"| {year} | {count} |" for year, count in sorted(counts.items(), reverse=True))
    return "\n".join(lines)


def _status(row: dict[str, str]) -> str:
    return STATUS_LABELS.get((row.get("fulltext_status") or "").strip(), "未标注")


def _direction_candidates(rows: list[dict[str, str]]) -> list[dict]:
    candidates = []
    for direction in DIRECTIONS:
        matched = direction_evidence(direction, rows, limit=8)
        if not matched:
            continue
        candidate = dict(
            direction,
            hard_gate=True,
            training_budget_status=direction.get("training_budget_status", "unknown"),
            deployment_status=direction.get("deployment_status", "unknown"),
            generic_topic=False,
        )
        candidate["evidence_count"] = len(matched)
        candidates.append(candidate)
    return candidates


def _rank_table(rows: list[dict[str, str]], limit: int = 3) -> str:
    ranked = rank_directions(_direction_candidates(rows), limit=limit)
    if not ranked:
        return "| — | 当前没有通过硬门槛的方向 | — | 待核验 |"
    return "\n".join(
        f"| {index} | {item['name']} | {item['score']:.2f} | {'待核验' if item.get('preference_status') == '待核验' else '通过'} |"
        for index, item in enumerate(ranked, 1)
    )


def generate_summary(rows: list[dict[str, str]], generated: str) -> str:
    abstract_count = sum(1 for row in rows if has_complete_original_abstract(row))
    fulltext_counts = Counter((row.get("fulltext_status") or "未标注").strip() for row in rows)
    fulltext_text = "；".join(f"{STATUS_LABELS.get(status, status)} {count} 条" for status, count in sorted(fulltext_counts.items()))
    quantitative_count = sum(1 for row in rows if can_support_quantitative_claim(row))
    focus_dois = {
        "10.1109/LRA.2025.3575011",
        "10.1109/IROS60139.2025.11247554",
        "10.1109/IROS60139.2025.11246821",
    }
    focus_titles = {
        "RAPTOR: A Foundation Policy for Quadrotor Control",
        "D-Nav: End-to-End Dynamic UAV Navigation with Dual-Resolution Motion Awareness",
        "RAPID: Robust and Agile Planner Using Inverse Reinforcement Learning for Vision-Based Drone Navigation",
        "Seeing is Believing: Certified Perception-Based Control from Learned Visual Representations via System Level Synthesis",
    }
    focus_rows = [
        row for row in rows
        if row.get("doi", "").strip() in focus_dois or row.get("title", "").strip() in focus_titles
    ]
    evidence_lines = [
        f"| {paper_link(row)} | {row.get('source', '')} / {row.get('venue_time', '')} | {_status(row)} | {(row.get('experiment_evidence') or '暂无经过全文核验的实验数字')[:180]} |"
        for row in focus_rows
    ]
    evidence_table = "\n".join(evidence_lines) or "| 本轮没有新增 DOI 核验记录 | — | — | 暂无 |"
    return f"""# 论文总结

> 本文件是清洁后论文库的总体复盘视图；论文事实以 论文库统一.csv 为唯一来源。生成时间：{generated}。

## 本轮严格检索记录

- 本轮先完成既有 33 条记录的官方摘要与证据列复核；5 条 `abstract_only` 记录逐条回到 DOI/出版社记录寻找官方或机构开放全文，仍未取得可接受的正文或补充材料，因此继续保留摘要级状态，未把摘要数字升级为全文定量证据。严格审计通过后，新增 1 条 RSS 2026 记录 `Seeing is Believing...`：官方 proceedings 全文核验了方法、四旋翼仿真和约束实验，但其真实硬件是 TurtleBot 地面车，Jetson/12GB/真实无人机部署仍是缺口。主库现为 34/34 条完整原始摘要且均有官方摘要 URL。
- 证据规则：训练时长、显存、功耗、参数量、端到端延迟和实验数字，只有在已核验的官方全文、开放全文或补充材料中出现时才能写入；摘要没有报告的内容统一写“未报告”。
- 方案 A 项目目标不是论文事实：使用 Isaac Lab 向量化强化学习，RTX 4090 训练控制在个位数小时，RTX 5070 Ti 控制在一天内，部署不超过 Jetson 级硬件。未知测量值继续标为待核验。
- 本轮官方候选筛选：接收 1 条 RSS 2026 `Seeing is Believing...`；RSS 2026 `Learning Agile Quadrotor Flight in the Real World` 因高机动/激进飞行是核心任务而拒收，`TinySDP` 因官方摘要与全文呈现为几何规划/控制而非感知—控制闭环而拒收。此前已记录的事件相机、Nature Communications、PMLR 和 Scientific Reports 候选仍按原门槛排除；Bee-Nav、RAPID 等已入库记录本轮不重复计入新论文。

## 本轮证据表

| 论文 | 来源 | 全文状态 | 已核验的实验证据 |
|---|---|---|---|
{evidence_table}

## 方案 A 前三方向快照

| 排名 | 方向 | 得分 | 偏好状态 |
|---:|---|---:|---|
{_rank_table(rows, limit=3)}

## 清库状态

- 最终收录：**{len(rows)} 篇**；完整原始摘要覆盖 **{abstract_count}/{len(rows)}**。
- 全文状态：{fulltext_text or '暂无标注'}；已有全文证据、可支持定量算力或实验结论的记录为 **{quantitative_count} 条**，其余记录不得从摘要推断显存、延迟、功耗或成功率。
- 只保留白名单顶刊/顶会、DOI/出版社记录或官方会议页面；搜索结果、项目主页和未识别 venue 只能作为线索。
- CSV 采用固定 15 列和 UTF-8 结构化写入；标题中的问号可以保留，但 method_evidence、compute_evidence、experiment_evidence 不允许出现问号占位符或替换字符。
- 已排除多无人机/群体、事件相机、VLA/VLM/LLM、大型 Gaussian Splatting 和纯 survey/taxonomy 等硬门槛内容。

## 来源分布

{source_table(rows)}

## 年份分布

{year_table(rows)}

## 全局复盘

1. **证据质量优先。** 主要质量提升不是单纯增加数量，而是把论文标题收紧为可追溯的官方记录、完整原始摘要和可复核证据。
2. **研究重心。** 当前文献支持视觉导航、闭环规划控制、可微仿真/残差适应、目标跟踪/降落和安全约束；重点是轻量感知如何改变控制决策。
3. **算力约束下的机会。** 小型表征、残差动力学、CBF/MPC/MPPI、局部地图、不确定性估计和在线校正适合把训练放到 Isaac Lab 并行环境，把机载部分压到 Jetson 级。
4. **新颖性门槛。** 传统单无人机避障、多无人机协同和普通路径规划只作为基线或背景，不作为高优先级主方向。

## 下一轮搜索与复盘重点

- 优先补足强化学习训练时长、并行环境吞吐、峰值显存、策略参数量、Jetson 延迟和真实扰动实验。
- 每篇候选都记录官方页面、venue、年份、单机关系、感知输入、闭环输出、算力证据和排除原因。
- 每轮结束后重新计算全库方向得分；方向池动态保留 0–15 个候选，不为旧方向保留名额。
- 连续两个搜索角度没有新增“已官方核验且未重复”的论文，就切换角度或结束，不以堆数量为目标。

## 文件边界

- 论文库统一.csv：唯一论文事实库。
- 论文总结.md：全库统计、来源审计、趋势和轮次复盘。
- 研究方向分析.md：动态方向池、评分、证据映射和可做实验。

每轮整理完成后只保留以上三个研究核心文件；插件脚本、技能说明和计划文档不属于研究核心文件。
"""


def generate_analysis(rows: list[dict[str, str]], generated: str) -> str:
    candidates = _direction_candidates(rows)
    ranked = rank_directions(candidates, limit=15)
    lines = [
        "# 研究方向分析",
        "",
        f"> 基于清洁后的 {len(rows)} 篇论文生成动态方向复盘；生成时间：{generated}。",
        "> 方向池没有固定基线；每轮重新评分，允许保留 0–15 个方向。排名不是永久名额。",
        "",
        "## 方案 A 偏好硬门槛",
        "",
        "- 算力目标：RTX 4090 单卡训练控制在个位数小时；RTX 5070 Ti 控制在一天内。训练预算未知时只能标为待核验。",
        "- 部署目标：不超过 Jetson 级硬件，优先 Jetson Orin NX 或更低；高于 Jetson 或只能多卡运行的方向不晋级。",
        "- 新颖性目标：传统单无人机避障、传统多无人机协同和普通路径规划只作基线，不作为高优先级主问题。",
        "- 证据纪律：未知训练时长、峰值显存、功耗、参数量、Jetson 延迟或真实飞行数据，不得写成定量可行性结论。",
        "",
        "## 本轮官方候选筛选",
        "",
        "- Efficient robot navigation inspired by honeybee learning flights（Bee-Nav）：Nature 官方开放全文确认单架四旋翼，全链路为全景视觉 home vector 到 PX4 高层控制；Raspberry Pi 4、868/10,820 参数网络、0.5 m 归巢误差和长距离飞行证据均已写入主库。该记录来自上轮，本轮仅复核，不重复计入新增论文（https://www.nature.com/articles/s41586-026-10461-3）。",
        "- Autonomous navigation of intelligent microrobotic swarms in unknown environments：Nature Machine Intelligence 官方页面明确为 swarm navigation，按多机/群体门槛拒收（https://www.nature.com/articles/s42256-026-01252-6）。",
        "- Perching of quadrotor using adaptive second-order continuous control 以及 Fault-tolerant control of quadrotor unmanned aerial vehicle：官方页面虽可访问，但分别缺少项目要求的感知输入到闭环控制链路或不属于 venue 白名单，拒收（https://www.nature.com/articles/s41598-026-36857-9；https://www.nature.com/articles/s41598-026-46576-w）。",
        "- All eyes, no IMU: learning flight attitude from vision alone 与 WACV 2026 的 event-based visuomotor policy：官方页面确认事件相机主题，按排除主题门槛拒收（https://www.nature.com/articles/s44182-026-00081-4；https://openaccess.thecvf.com/content/WACV2026/html/Kamal_Memory-Augmented_Representation_for_Efficient_Event-based_Visuomotor_Policy_Learning_with_Adaptive_WACV_2026_paper.html）。",
        "- Imperative MPC: An End-to-End Self-Supervised Learning with Differentiable MPC for UAV Attitude Control：PMLR 官方页面与全文确认单 UAV、学习 IMU odometry 与 d-MPC 闭环，全文报告 50 Hz 控制/200 Hz IMU、20 m/s 仿真风扰和 0.243° 稳态误差；因 PMLR 不在当前 venue 白名单，暂不写入主库（https://proceedings.mlr.press/v283/he25a.html）。",
        "- An autonomous single-actuator UAV with omnidirectional field of view, high agility, and collision resistance：Nature Communications 官方摘要确认 LiDAR 感知与 MPC，但当前 venue 白名单不含 Nature Communications，且主要贡献属于结构与模型控制，不进入主库（https://www.nature.com/articles/s41467-026-73283-x）。",
        "- RAPID：RSS 官方全文已补全并写入主库，Jetson Orin NX、6.34 M parameters、26 M FLOPs、10.24 ms 推理和 10/20/50/200/250 Hz 控制链路均来自全文，不再保留 abstract_only。",
        "- Seeing is Believing: Certified Perception-Based Control from Learned Visual Representations via System Level Synthesis：RSS 2026 官方页面和 proceedings 全文确认 RGB 感知—输出反馈闭环；10D quadrotor 结果来自仿真，VISION-SLS 的成功率/约束违反率为 100%/0%，而真实硬件为 TurtleBot 地面车，因此只作为方法证据和仿真对照，不宣称真实无人机或 Jetson 已验证（https://roboticsconference.org/program/papers/172/；https://www.roboticsproceedings.org/rss22/p172.pdf）。",
        "- Learning Agile Quadrotor Flight in the Real World 与 TinySDP：RSS 2026 官方页面确认前者以激进高机动飞行为核心，后者以嵌入式 SDP/MPC 几何约束为核心；分别按高速度特技和非感知—控制闭环门槛拒收（https://roboticsconference.org/program/papers/135/；https://roboticsconference.org/program/papers/110/）。",
        "",
        "## Isaac Lab 最小可行路线",
        "",
        "- 第一层先建立无渲染的高层规划环境：用 GPU 张量批量推进 B-spline、栅格/走廊、动态障碍和风险约束；这一步不渲染光影，也不把完整刚体物理放进每个训练步。",
        "- 第二层再用 Isaac Lab 无渲染 PhysX 六自由度模型接入同一观测/动作接口，随机化载荷、风扰、推力曲线、执行器延迟和感知延迟；用 MuJoCo MJX-Warp 做独立动力学交叉检查，AirSim 只保留给后期 PX4 SITL/HITL 联调。",
        "- 每轮必须记录并行环境数、步数/秒、墙钟训练时长、峰值显存、策略参数量、推理延迟、控制频率、成功率、安全违规、跨动力学泛化和真实飞行时长；第一晋级条件是低维策略达到训练预算、通过第二层动力学验证并能部署到 Jetson 级硬件。",
        "",
        "## 评分与硬门槛",
        "",
        "方案 A 的维度为推荐度、前景、可行性、venue 匹配、独特性、证据强度和学习价值；权重由插件 research_metrics.py 统一计算。任何多机、事件相机、VLA/VLM/LLM、大型 3DGS、纯 survey 或非感知—控制闭环候选先淘汰。",
        "",
        "| 排名 | 方向 | 得分 | 证据篇数 | 硬门槛状态 | 目标 venue |",
        "|---:|---|---:|---:|---|---|",
    ]
    evidence_map = {}
    for rank, direction in enumerate(ranked, start=1):
        evidence = direction_evidence(direction, rows)
        evidence_map[direction["name"]] = evidence
        gate_status = "待核验" if direction.get("preference_status") == "待核验" else "通过"
        lines.append(f"| {rank} | {direction['name']} | {direction['score']:.2f} | {len(evidence)} | {gate_status} | {direction['venues']} |")

    lines.extend(["", "## 动态方向详情", ""])
    for rank, direction in enumerate(ranked, start=1):
        evidence = evidence_map[direction["name"]]
        quantitative = [row for row in evidence if can_support_quantitative_claim(row)]
        lines.extend([
            f"### {rank}. {direction['name']}（{direction['score']:.2f}/10）",
            "",
            "#### 研究对象与系统边界",
            "",
            f"**核心问题：** {direction['summary']} 研究对象限定为单架无人机或单机—地面系统；只有感知输入确实影响规划、控制或安全过滤输出时，才属于本方向。",
            "",
            "#### 技术路线",
            "",
            f"**可验证的系统链路：** 将任务观测转换为低维状态或不确定性表示，再由规划/策略模块生成候选动作，最后经控制器或安全层输出飞行指令。{direction['feasibility']} 这是一条待实验证据路线，不把一般工程经验写成论文事实。",
            "",
            "#### 论文证据与信息状态",
            "",
            "| 论文 | venue / 年份 | 证据等级 | 官方记录 |",
            "|---|---|---|---|",
        ])
        if evidence:
            for row in evidence:
                lines.append(f"| {row.get('title', '')} | {row.get('source', '')} / {row.get('venue_time', '')} | {evidence_level(row)} | {paper_link(row)} |")
        else:
            lines.append("| 当前没有直接证据 | — | 待补充 | 下一轮只从官方来源补充 |")
        if direction["name"] == "<YOUR_RESEARCH_PROJECT>":
            lines.extend([
                "",
                "#### 关键对照线索与正式基线",
                "",
                "CORB-Planner（IEEE/ASME Transactions on Mechatronics 2025）给出低维安全飞行走廊、B-spline 轨迹和约十分钟训练；其安全走廊仍不等同于端到端形式化安全证明，而且依赖上游建图、定位和走廊生成。[正式 IEEE 记录](https://ieeexplore.ieee.org/document/11247855)；[开放全文](https://arxiv.org/html/2509.11240)。",
                "传感器与建图不能凭直觉二选一：ART-IQN 使用四个沿 x/y 轴的激光测距器和 optical-flow camera，在二维点质量环境中用下尾条件方差估计内在不确定性并自适应 CVaR；全文未描述显式 SLAM/三维建图，但真实策略在 laptop 上执行，训练约 3.5 小时，27.5 g Crazyflie 的 Jetson/机载延迟未报告。[官方 DOI](https://doi.org/10.1109/ICRA48891.2023.10160324)；[开放全文](https://arxiv.org/pdf/2203.14749)。",
                "VO-Safe 使用 RGB camera、VO 和 semantic images，PPO 只输出高层 1 m waypoint/方向动作，低层由经典控制器执行；全文系统描述未出现 LiDAR 或显式建图，但实验假设 collision-free，因此它解决的是定位/视觉里程计失效，不是障碍碰撞安全。仿真 success rate 为 0.78，真实平台为 RealSense D435 + Intel NUC 11 Pro，Jetson 级闭环仍待核验。[官方 DOI](https://doi.org/10.1109/ICRA57147.2024.10611487)；[开放全文](https://orca.cardiff.ac.uk/id/eprint/166897/1/Ji%20Z%20-%20VO-Safe%20Reinforcement%20Learning%20....pdf)。",
                "本轮基于全文证据的判断：激光雷达不是逻辑上的必选项，ART-IQN 证明四向激光测距即可做轻量风险趋向；但若目标是未知障碍的碰撞安全，至少需要可量化的局部几何/距离观测和硬安全层。显式建图也不是所有路线的必选项：无地图策略可做局部反应，但 CORB 的建图 + 走廊路线更适合表达空间可行域；相机/VO 路线若只验证定位安全，不能替代碰撞安全。最终应以 LiDAR/局部地图、激光无地图和视觉/VO 三路消融，统一测量安全事件、感知失效、端到端延迟和机载资源。" ,
                "近期视觉安全强化学习工作把策略与可证明安全过滤结合，说明安全性仍是活跃问题；但这也意味着简单复现‘视觉强化学习加安全屏蔽’的区分度不足，新工作应转向单目或低维表征、感知不确定性、控制延迟，或完整的资源—风险曲线：[相关预印本](https://arxiv.org/abs/2602.08653)。",
                "RAPID（RSS 2025）和 D-Nav（RSS 2026）说明高速视觉导航与动态避障仍在顶级会议持续出现；NavRL 已经覆盖动态障碍、PPO、速度障碍安全层、Isaac Sim 和 Jetson Orin NX，不能把这些组件简单拼接当作新贡献：[RAPID](https://roboticsconference.org/2025/program/papers/142/)；[D-Nav](https://roboticsconference.org/program/papers/65/)；[NavRL](https://doi.org/10.1109/LRA.2025.3546069)。",
            ])
        lines.extend(["", "#### 量化算力与部署可行性", ""])
        if quantitative:
            for row in quantitative:
                compute = (row.get("compute_evidence") or "").strip() or "未报告可复核的算力数字"
                experiment = (row.get("experiment_evidence") or "").strip() or "未报告可复核的实验数字"
                lines.append(f"- **{row.get('title', '')}：** 算力/延迟证据：{compute}；实验证据：{experiment}（全文：{row.get('fulltext_url', '')}）。")
            lines.append("这些数字只能用于相同任务、硬件、软件版本和测量口径下的比较；12GB 训练显存和 Jetson Orin NX 适配仍需单独复测。")
        else:
            lines.append("**当前结论：** 没有经过全文核验的显存、参数量、训练时长、延迟、控制频率或功耗数字，因此不能声称已经满足 12GB 或 Jetson Orin NX 约束；这里只列出待验证的部署假设。")
        lines.extend([
            "",
            "#### 最小可行实验",
            "",
            "先在单机闭环仿真中固定动力学、感知频率和安全边界，对比经典控制/规划基线与所提模块；随后在受控真实条件下报告任务成功率、碰撞或安全事件、端到端延迟、峰值显存、控制频率和飞行时长。每个数字都要注明硬件、软件版本、测量窗口和对应论文或实验记录。",
            "",
            "#### 证据缺口与主要风险",
            "",
            f"**主要风险：** {direction['risk']} **证据缺口：** 如果当前记录只有摘要级证据，不得推断模型大小、训练预算、机载帧率或真实飞行效果；这些字段必须在官方全文、开放全文或补充材料中逐项补齐。",
            "",
            f"**目标 venue：** {direction['venues']}",
            "",
        ])

    lines.extend([
        "## 方向选择建议",
        "",
        "优先比较排名靠前方向的最小可行实验，统一报告机载延迟、峰值显存、控制频率、任务成功率、安全事件、真实飞行时长和跨环境泛化。优先选择既有新问题又能在单卡和 Jetson 级硬件上闭环验证的方向。",
        "",
        "## 本轮排除的主题",
        "",
        "事件相机、VLA/VLM/LLM、多无人机或蜂群、大型 NeRF/3DGS、纯检测、纯综述以及只有高速特技 benchmark 而缺少可迁移闭环方法的工作，不进入方向池。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    args = parser.parse_args()
    rows = load_rows(args.csv)
    generated = date.today().isoformat()
    args.summary.write_text(generate_summary(rows, generated), encoding="utf-8")
    args.analysis.write_text(generate_analysis(rows, generated), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
