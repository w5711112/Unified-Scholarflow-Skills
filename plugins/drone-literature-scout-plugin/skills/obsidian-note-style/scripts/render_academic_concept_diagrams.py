from __future__ import annotations

import argparse
import heapq
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from matplotlib import font_manager, rcParams  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import (  # noqa: E402
    Circle,
    FancyArrowPatch,
    PathPatch,
    Polygon,
    Rectangle,
)
from matplotlib.path import Path as MplPath  # noqa: E402


BACKGROUND_COLOR = "#ffffff"
INK = "#202830"
MUTED = "#66717d"
GRID = "#cfd6dc"
LIGHT_GRID = "#eef1f3"
BLUE = "#4f7396"
LIGHT_BLUE = "#e7eef4"
RED = "#a55c5c"
LIGHT_RED = "#f3e5e3"
SEMANTIC_ACCENTS = (BLUE, RED)
ARROW_MUTATION_SCALE = 6.5
MAX_LINE_WIDTH = 2.25
BASE_LINE_WIDTH = 1.35
FIGURE_SIZE = (13.2, 7.4)
FONT_SCALE = 1.15
MIN_TEXT_SIZE = 9.2
PANEL_HEADING_SIZE = 12.2
MIN_MATH_SIZE = 12.5
OUTER_MARGIN = 0.04
PANEL_GAP = 0.03
SAVE_PAD_INCHES = 0.04
EXPECTED_FILENAMES = (
    "Dijkstra与代价场原理.svg",
    "SDF与ESDF原理.svg",
    "CBF到HOCBF安全过滤.svg",
)


def _cjk_font() -> font_manager.FontProperties:
    candidates = (
        Path(r"C:\Windows\Fonts\msyhl.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            font_manager.fontManager.addfont(str(candidate))
            return font_manager.FontProperties(fname=str(candidate))
    return font_manager.FontProperties(family="DejaVu Sans")


CJK_FONT = _cjk_font()
rcParams.update(
    {
        "svg.fonttype": "path",
        "svg.hashsalt": "academic-concept-diagrams-v1",
        "figure.facecolor": BACKGROUND_COLOR,
        "axes.facecolor": BACKGROUND_COLOR,
        "savefig.facecolor": BACKGROUND_COLOR,
        "mathtext.fontset": "dejavusans",
        "axes.unicode_minus": False,
    }
)


def _figure() -> Figure:
    return Figure(figsize=FIGURE_SIZE, dpi=100, facecolor=BACKGROUND_COLOR)


def _axis(
    figure: Figure,
    bounds: tuple[float, float, float, float],
    *,
    xlim: tuple[float, float] = (0.0, 1.0),
    ylim: tuple[float, float] = (0.0, 1.0),
    equal: bool = False,
):
    axis = figure.add_axes(bounds)
    axis.set_xlim(*xlim)
    axis.set_ylim(*ylim)
    if equal:
        axis.set_aspect("equal", adjustable="box")
    axis.axis("off")
    return axis


def _text(
    axis,
    x: float,
    y: float,
    value: str,
    *,
    size: float = 10,
    color: str = INK,
    weight: str = "normal",
    ha: str = "left",
    va: str = "center",
    data: bool = False,
    linespacing: float = 1.25,
):
    transform = axis.transData if data else axis.transAxes
    return axis.text(
        x,
        y,
        value,
        transform=transform,
        fontsize=max(MIN_TEXT_SIZE, size * FONT_SCALE),
        color=color,
        fontproperties=CJK_FONT,
        fontweight=weight,
        horizontalalignment=ha,
        verticalalignment=va,
        linespacing=linespacing,
        clip_on=False,
    )


def _math(
    axis,
    x: float,
    y: float,
    value: str,
    *,
    size: float = 12,
    color: str = INK,
    ha: str = "left",
    va: str = "center",
    data: bool = False,
):
    transform = axis.transData if data else axis.transAxes
    return axis.text(
        x,
        y,
        value,
        transform=transform,
        fontsize=max(MIN_MATH_SIZE, size * FONT_SCALE),
        color=color,
        horizontalalignment=ha,
        verticalalignment=va,
        clip_on=False,
    )


def _line(axis, xs, ys, *, color=INK, width=BASE_LINE_WIDTH, style="-", data=False):
    transform = axis.transData if data else axis.transAxes
    return axis.plot(
        xs,
        ys,
        color=color,
        linewidth=width,
        linestyle=style,
        transform=transform,
        solid_capstyle="round",
        clip_on=False,
    )[0]


def _arrow(
    axis,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color=INK,
    width=BASE_LINE_WIDTH,
    data=False,
    style="-|>",
    mutation_scale: float = ARROW_MUTATION_SCALE,
    linestyle="-",
):
    patch = FancyArrowPatch(
        start,
        end,
        transform=axis.transData if data else axis.transAxes,
        arrowstyle=style,
        mutation_scale=mutation_scale,
        linewidth=width,
        linestyle=linestyle,
        color=color,
        shrinkA=0,
        shrinkB=0,
        clip_on=False,
    )
    axis.add_patch(patch)
    return patch


def _panel_heading(axis, label: str, title: str) -> None:
    _text(
        axis,
        0.0,
        1.01,
        f"({label})",
        size=PANEL_HEADING_SIZE / FONT_SCALE,
        weight="bold",
        va="bottom",
    )
    _text(
        axis,
        0.075,
        1.01,
        title,
        size=PANEL_HEADING_SIZE / FONT_SCALE,
        weight="bold",
        va="bottom",
    )
    _line(axis, (0.0, 1.0), (0.975, 0.975), color=GRID, width=1.0)


def _save(
    figure: Figure,
    path: Path,
    preview_path: Path | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        path,
        format="svg",
        dpi=100,
        metadata={
            "Date": None,
            "Creator": "read-paper-analysis-highlight academic diagram renderer",
        },
        facecolor=BACKGROUND_COLOR,
        edgecolor="none",
        bbox_inches="tight",
        pad_inches=SAVE_PAD_INCHES,
    )
    if preview_path is not None:
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(
            preview_path,
            format="png",
            dpi=160,
            facecolor=BACKGROUND_COLOR,
            edgecolor="none",
            bbox_inches="tight",
            pad_inches=SAVE_PAD_INCHES,
        )
    figure.clear()
    return path


def _dijkstra_costs(
    columns: int,
    rows: int,
    obstacles: set[tuple[int, int]],
    goal: tuple[int, int],
) -> dict[tuple[int, int], float]:
    costs: dict[tuple[int, int], float] = {goal: 0.0}
    queue: list[tuple[float, tuple[int, int]]] = [(0.0, goal)]
    while queue:
        cost, cell = heapq.heappop(queue)
        if cost != costs[cell]:
            continue
        x, y = cell
        for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            nx, ny = neighbor
            if not (0 <= nx < columns and 0 <= ny < rows):
                continue
            if neighbor in obstacles:
                continue
            candidate = cost + 1.0
            if candidate < costs.get(neighbor, math.inf):
                costs[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))
    return costs


def _descending_path(
    start: tuple[int, int],
    goal: tuple[int, int],
    costs: dict[tuple[int, int], float],
) -> list[tuple[int, int]]:
    path = [start]
    current = start
    while current != goal:
        x, y = current
        candidates = [
            neighbor
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            if neighbor in costs and costs[neighbor] < costs[current]
        ]
        if not candidates:
            raise RuntimeError(f"no descending Dijkstra path from {current}")
        current = min(candidates, key=lambda cell: (costs[cell], -cell[1], cell[0]))
        path.append(current)
    return path


def render_dijkstra(path: Path, preview_path: Path | None = None) -> Path:
    figure = _figure()
    grid_axis = _axis(
        figure,
        (OUTER_MARGIN, 0.07, 0.55, 0.86),
        xlim=(-0.35, 9.35),
        ylim=(-1.05, 7.55),
        equal=True,
    )
    reward_axis = _axis(figure, (0.62, 0.07, 0.34, 0.86))
    _panel_heading(grid_axis, "a", "Dijkstra 从目标反向计算 cost-to-go")
    _panel_heading(reward_axis, "b", "论文在代价场上构造进展奖励")

    columns, rows = 9, 7
    obstacles = {
        (3, 0),
        (3, 1),
        (3, 2),
        (3, 3),
        (3, 4),
        (5, 2),
        (5, 3),
        (5, 4),
        (5, 5),
        (7, 1),
        (7, 2),
    }
    start = (0, 1)
    goal = (8, 5)
    costs = _dijkstra_costs(columns, rows, obstacles, goal)
    route = _descending_path(start, goal, costs)
    max_cost = max(costs.values())

    for x in range(columns):
        for y in range(rows):
            cell = (x, y)
            if cell in obstacles:
                face = LIGHT_RED
                edge = RED
            else:
                cost = costs.get(cell, max_cost)
                strength = 0.965 - 0.12 * (max_cost - cost) / max_cost
                face = (strength, strength + 0.01, strength + 0.02)
                edge = GRID
            rectangle = Rectangle(
                (x, y),
                1,
                1,
                facecolor=face,
                edgecolor=edge,
                linewidth=0.8 if cell not in obstacles else 1.2,
                clip_on=False,
            )
            grid_axis.add_patch(rectangle)
            if cell in costs:
                _text(
                    grid_axis,
                    x + 0.5,
                    y + 0.5,
                    str(int(costs[cell])),
                    size=8.4,
                    color=MUTED,
                    ha="center",
                    data=True,
                )
            elif cell in obstacles:
                _text(
                    grid_axis,
                    x + 0.5,
                    y + 0.5,
                    "障碍",
                    size=7.1,
                    color=RED,
                    ha="center",
                    data=True,
                )

    route_x = [x + 0.5 for x, _ in route]
    route_y = [y + 0.5 for _, y in route]
    _line(grid_axis, route_x, route_y, color=BLUE, width=2.0, data=True)
    for index in range(1, len(route) - 1, 3):
        before = (route_x[index - 1], route_y[index - 1])
        after = (route_x[index], route_y[index])
        _arrow(
            grid_axis,
            before,
            after,
            color=BLUE,
            width=1.6,
            data=True,
            mutation_scale=5.5,
        )

    grid_axis.add_patch(
        Circle(
            (start[0] + 0.5, start[1] + 0.5),
            0.16,
            facecolor=BACKGROUND_COLOR,
            edgecolor=INK,
            linewidth=1.5,
            clip_on=False,
        )
    )
    grid_axis.add_patch(
        Circle(
            (goal[0] + 0.5, goal[1] + 0.5),
            0.2,
            facecolor=BLUE,
            edgecolor=BLUE,
            linewidth=1.3,
            clip_on=False,
        )
    )
    _text(grid_axis, 0.5, 1.0, "S", size=8, weight="bold", ha="center", data=True)
    _text(
        grid_axis,
        goal[0] + 0.5,
        goal[1] + 0.5,
        "G",
        size=8,
        color=BACKGROUND_COLOR,
        weight="bold",
        ha="center",
        data=True,
    )
    _text(
        grid_axis,
        0.0,
        -0.55,
        "每个数字是到目标的最小累计代价；路径沿数值下降方向前进。",
        size=9.2,
        color=MUTED,
        data=True,
    )
    _math(
        grid_axis,
        4.5,
        -0.95,
        r"$J(v)\leftarrow\min\!\left[J(v),\,J(u)+w(u,v)\right]$",
        size=12.5,
        ha="center",
        data=True,
    )

    _text(reward_axis, 0.03, 0.89, "相邻时刻只查询同一张代价场", size=9.6, color=MUTED)
    _math(
        reward_axis,
        0.03,
        0.79,
        r"$\Delta\Phi_t=\operatorname{Interp}(\Phi_g,p_{t-1})"
        r"-\operatorname{Interp}(\Phi_g,p_t)$",
        size=12.2,
    )
    _text(
        reward_axis,
        0.03,
        0.68,
        "若当前位置的 cost-to-go 变小，说明沿可绕障路线接近目标。",
        size=9.5,
    )
    _line(reward_axis, (0.03, 0.97), (0.61, 0.61), color=GRID, width=0.9)
    _math(
        reward_axis,
        0.03,
        0.52,
        r"$r_t=\lambda\,\operatorname{clamp}"
        r"\!\left(\Delta\Phi_t,-C,C\right)$",
        size=13.2,
    )
    _text(
        reward_axis,
        0.03,
        0.41,
        "$p_t$：时刻 t 的位置；$C$：单步奖励幅值上限；\n"
        "$\\lambda$：该奖励项的权重。",
        size=9.4,
        linespacing=1.35,
    )

    chart_x = [0.09, 0.25, 0.42, 0.58, 0.75, 0.91]
    chart_cost = [0.28, 0.31, 0.245, 0.205, 0.16, 0.115]
    _line(reward_axis, (0.07, 0.94), (0.09, 0.09), color=INK, width=1.0)
    _line(reward_axis, (0.07, 0.07), (0.09, 0.33), color=INK, width=1.0)
    _line(reward_axis, chart_x, chart_cost, color=BLUE, width=1.8)
    for x, y in zip(chart_x, chart_cost):
        reward_axis.add_patch(
            Circle(
                (x, y),
                0.008,
                transform=reward_axis.transAxes,
                facecolor=BLUE,
                edgecolor=BLUE,
                linewidth=0.8,
                clip_on=False,
            )
        )
    _text(reward_axis, 0.5, 0.035, "时间 / 轨迹推进", size=8.4, color=MUTED, ha="center")
    _text(
        reward_axis,
        0.015,
        0.21,
        "代价",
        size=8.4,
        color=MUTED,
        ha="center",
        va="center",
    )
    _text(
        reward_axis,
        0.03,
        -0.04,
        "关键区分：Dijkstra 的核心是最短路松弛；上式奖励只是使用它的结果。",
        size=9.2,
        color=RED,
        va="top",
    )
    return _save(figure, path, preview_path)


def _brace_path(x: float, y0: float, y1: float, width: float) -> MplPath:
    middle = (y0 + y1) / 2
    vertices = [
        (x + width, y1),
        (x, y1),
        (x + width * 0.3, middle + (y1 - y0) * 0.08),
        (x, middle),
        (x + width * 0.3, middle - (y1 - y0) * 0.08),
        (x, y0),
        (x + width, y0),
    ]
    codes = [
        MplPath.MOVETO,
        MplPath.CURVE3,
        MplPath.CURVE3,
        MplPath.CURVE3,
        MplPath.CURVE3,
        MplPath.CURVE3,
        MplPath.CURVE3,
    ]
    return MplPath(vertices, codes)


def render_sdf_esdf(path: Path, preview_path: Path | None = None) -> Path:
    figure = _figure()
    geometry_axis = _axis(
        figure,
        (OUTER_MARGIN, 0.08, 0.45, 0.84),
        xlim=(0, 10),
        ylim=(0, 7),
        equal=True,
    )
    field_axis = _axis(
        figure,
        (0.54, 0.31, 0.42, 0.61),
        xlim=(0, 10),
        ylim=(0, 7),
        equal=True,
    )
    formula_axis = _axis(figure, (0.50, 0.105, 0.48, 0.185))
    note_axis = _axis(figure, (0.52, 0.015, 0.45, 0.075))
    _panel_heading(geometry_axis, "a", "SDF：点到障碍边界的带符号最短距离")
    _panel_heading(field_axis, "b", "ESDF：把欧氏距离存成可查询的空间场")

    obstacle_vertices = [
        (2.5, 1.2),
        (6.0, 1.2),
        (6.0, 5.3),
        (4.65, 5.3),
        (4.65, 3.55),
        (2.5, 3.55),
    ]
    geometry_axis.add_patch(
        Polygon(
            obstacle_vertices,
            closed=True,
            facecolor=LIGHT_RED,
            edgecolor=RED,
            linewidth=2.0,
            clip_on=False,
        )
    )
    _text(geometry_axis, 3.55, 2.25, "障碍内部", size=10, color=RED, data=True)

    outside = (8.25, 4.25)
    outside_nearest = (6.0, 4.25)
    inside = (3.55, 2.55)
    inside_nearest = (2.5, 2.55)
    for point, edge, color, label in (
        (outside, outside_nearest, BLUE, r"$x^{+}$"),
        (inside, inside_nearest, RED, r"$x^{-}$"),
    ):
        geometry_axis.add_patch(
            Circle(
                point,
                0.105,
                facecolor=BACKGROUND_COLOR,
                edgecolor=color,
                linewidth=1.8,
                clip_on=False,
            )
        )
        geometry_axis.add_patch(
            Circle(
                edge,
                0.075,
                facecolor=color,
                edgecolor=color,
                linewidth=1.0,
                clip_on=False,
            )
        )
        _line(
            geometry_axis,
            (point[0], edge[0]),
            (point[1], edge[1]),
            color=color,
            width=1.35,
            style=(0, (3, 2)),
            data=True,
        )
        _math(
            geometry_axis,
            point[0] + 0.18,
            point[1] + 0.18,
            label,
            size=12,
            color=color,
            data=True,
        )

    _arrow(
        geometry_axis,
        outside_nearest,
        (7.15, 4.25),
        color=BLUE,
        width=1.5,
        data=True,
    )
    _math(
        geometry_axis,
        6.53,
        4.56,
        r"$\nabla\phi(x)$",
        size=11,
        color=BLUE,
        ha="center",
        data=True,
    )
    _math(
        geometry_axis,
        7.05,
        3.86,
        r"$d(x)=\min_{y\in\partial\mathcal{O}}\|x-y\|_2$",
        size=12.2,
        ha="center",
        data=True,
    )
    _text(
        geometry_axis,
        5.0,
        0.45,
        "符号区分内外；距离大小来自最近边界点，梯度指向距离增长最快的方向。",
        size=9.3,
        color=MUTED,
        ha="center",
        data=True,
    )

    center = (5.0, 3.45)
    obstacle_radius = 1.0
    field_axis.add_patch(
        Circle(
            center,
            obstacle_radius,
            facecolor=LIGHT_RED,
            edgecolor=RED,
            linewidth=2.0,
            clip_on=False,
        )
    )
    for distance, width in ((0.7, 1.7), (1.4, 1.45), (2.1, 1.2)):
        field_axis.add_patch(
            Circle(
                center,
                obstacle_radius + distance,
                fill=False,
                edgecolor=BLUE,
                linewidth=width,
                alpha=0.78,
                clip_on=False,
            )
        )
        _math(
            field_axis,
            center[0] + obstacle_radius + distance + 0.08,
            center[1] + 0.12,
            rf"${distance:.1f}$",
            size=8.5,
            color=BLUE,
            data=True,
        )

    for grid_x in range(1, 10):
        _line(
            field_axis,
            (grid_x, grid_x),
            (0.35, 6.55),
            color=LIGHT_GRID,
            width=0.7,
            data=True,
        )
    for grid_y in range(1, 7):
        _line(
            field_axis,
            (0.45, 9.55),
            (grid_y, grid_y),
            color=LIGHT_GRID,
            width=0.7,
            data=True,
        )
    sample_points = (
        (1.0, 1.0),
        (2.0, 5.8),
        (5.0, 6.2),
        (8.5, 5.6),
        (8.7, 1.2),
        (3.0, 3.45),
        (6.8, 3.45),
    )
    for x, y in sample_points:
        signed_distance = math.hypot(x - center[0], y - center[1]) - obstacle_radius
        _text(
            field_axis,
            x,
            y,
            f"{signed_distance:.1f}",
            size=8.1,
            color=BLUE if signed_distance >= 0 else RED,
            ha="center",
            data=True,
        )
    _text(
        field_axis,
        0.5,
        -0.03,
        "同一等值线上的点，到最近障碍边界的欧氏距离相同。",
        size=9.2,
        color=MUTED,
        ha="center",
        va="top",
    )

    _math(formula_axis, 0.02, 0.62, r"$\phi(x)=$", size=14)
    brace = PathPatch(
        _brace_path(0.185, 0.18, 0.88, 0.035),
        transform=formula_axis.transAxes,
        facecolor="none",
        edgecolor=INK,
        linewidth=1.3,
        clip_on=False,
    )
    formula_axis.add_patch(brace)
    _math(
        formula_axis,
        0.245,
        0.80,
        r"$+d(x),\quad x\notin\mathcal{O}$",
        size=11.8,
    )
    _math(
        formula_axis,
        0.245,
        0.53,
        r"$0,\qquad\;\;x\in\partial\mathcal{O}$",
        size=11.8,
    )
    _math(
        formula_axis,
        0.245,
        0.26,
        r"$-d(x),\quad x\in\operatorname{int}(\mathcal{O})$",
        size=11.8,
    )
    _text(
        note_axis,
        0.5,
        0.5,
        "ESDF 是 SDF 在空间中的离散存储与查询形式：给出局部距离和梯度，\n"
        "但不包含绕障所需的全局拓扑。",
        size=9.3,
        color=MUTED,
        ha="center",
        linespacing=1.35,
    )
    return _save(figure, path, preview_path)


def render_cbf_hocbf(path: Path, preview_path: Path | None = None) -> Path:
    figure = _figure()
    state_axis = _axis(
        figure,
        (0.035, 0.08, 0.305, 0.84),
        xlim=(0, 10),
        ylim=(0, 8),
        equal=True,
    )
    chain_axis = _axis(figure, (0.36, 0.08, 0.295, 0.84))
    action_axis = _axis(
        figure,
        (0.67, 0.08, 0.30, 0.84),
        xlim=(-0.5, 8.5),
        ylim=(-0.8, 8.0),
        equal=True,
    )
    _panel_heading(state_axis, "a", "状态空间：安全余量与危险运动趋势")
    _panel_heading(chain_axis, "b", "相对阶：直到控制量进入约束")
    _panel_heading(action_axis, "c", "动作空间：QP 投影到可行半空间")

    obstacle_center = (3.2, 3.7)
    obstacle_radius = 1.0
    safety_radius = 2.0
    state_axis.add_patch(
        Circle(
            obstacle_center,
            safety_radius,
            facecolor="none",
            edgecolor=RED,
            linewidth=1.45,
            linestyle=(0, (4, 3)),
            clip_on=False,
        )
    )
    state_axis.add_patch(
        Circle(
            obstacle_center,
            obstacle_radius,
            facecolor=LIGHT_RED,
            edgecolor=RED,
            linewidth=2.0,
            clip_on=False,
        )
    )
    _text(
        state_axis,
        obstacle_center[0],
        obstacle_center[1],
        "障碍",
        size=9.5,
        color=RED,
        ha="center",
        data=True,
    )
    _text(state_axis, 1.15, 6.15, r"安全集 $\mathcal{C}$", size=10.2, color=BLUE, data=True)
    _math(
        state_axis,
        4.25,
        5.25,
        r"$h(x)=0$",
        size=10.5,
        color=RED,
        data=True,
    )
    vehicle = (7.25, 4.2)
    state_axis.add_patch(
        Circle(
            vehicle,
            0.14,
            facecolor=INK,
            edgecolor=INK,
            linewidth=1.0,
            clip_on=False,
        )
    )
    _math(state_axis, 7.55, 4.35, r"$x_t$", size=11, data=True)
    _arrow(
        state_axis,
        vehicle,
        (5.0, 3.95),
        color=RED,
        width=1.65,
        data=True,
    )
    _text(state_axis, 6.25, 3.65, "名义动作：继续逼近", size=8.5, color=RED, ha="center", data=True)
    _arrow(
        state_axis,
        vehicle,
        (6.25, 6.1),
        color=BLUE,
        width=1.8,
        data=True,
    )
    _text(state_axis, 7.05, 6.25, "修正动作：增加安全余量", size=8.5, color=BLUE, ha="center", data=True)
    _math(
        state_axis,
        5.0,
        0.65,
        r"$\mathcal{C}=\{x\mid h(x)\geq0\}$",
        size=12.2,
        ha="center",
        data=True,
    )

    _text(
        chain_axis,
        0.5,
        0.90,
        "基础 CBF（控制已出现在一阶导数）",
        size=9.4,
        weight="bold",
        ha="center",
    )
    _math(
        chain_axis,
        0.5,
        0.82,
        r"$\dot h(x,u)+\alpha\!\left(h(x)\right)\geq0$",
        size=12.0,
        ha="center",
    )
    _arrow(chain_axis, (0.5, 0.75), (0.5, 0.65), color=MUTED, width=1.2)
    _text(
        chain_axis,
        0.5,
        0.61,
        "若位置约束对加速度是二阶，\n一阶导数里还看不到控制量",
        size=9.1,
        color=MUTED,
        ha="center",
        linespacing=1.35,
    )
    _arrow(chain_axis, (0.5, 0.53), (0.5, 0.43), color=MUTED, width=1.2)
    _text(
        chain_axis,
        0.5,
        0.39,
        "HOCBF：递推到相对阶 r",
        size=9.5,
        weight="bold",
        ha="center",
    )
    _math(
        chain_axis,
        0.5,
        0.31,
        r"$\psi_0=h,\qquad"
        r"\psi_k=\dot\psi_{k-1}+\alpha_k(\psi_{k-1})$",
        size=10.9,
        ha="center",
    )
    _math(
        chain_axis,
        0.5,
        0.18,
        r"$\ddot B+\alpha_1\dot B+\alpha_0B\geq0$",
        size=12.0,
        color=BLUE,
        ha="center",
    )
    _text(
        chain_axis,
        0.5,
        0.06,
        "递推把位置安全要求变成对当前加速度的线性不等式。",
        size=8.9,
        color=MUTED,
        ha="center",
    )

    _line(action_axis, (0.4, 7.7), (0.4, 0.4), color=INK, width=1.0, data=True)
    _line(action_axis, (0.4, 0.4), (0.4, 7.2), color=INK, width=1.0, data=True)
    _arrow(action_axis, (7.2, 0.4), (7.75, 0.4), color=INK, width=1.0, data=True)
    _arrow(action_axis, (0.4, 7.2), (0.4, 7.75), color=INK, width=1.0, data=True)
    _math(action_axis, 7.75, 0.1, r"$u_1$", size=10.5, ha="center", data=True)
    _math(action_axis, 0.0, 7.72, r"$u_2$", size=10.5, ha="center", data=True)

    feasible = Polygon(
        [(0.4, 3.0), (0.4, 7.2), (7.2, 7.2), (7.2, 6.4)],
        closed=True,
        facecolor=LIGHT_BLUE,
        edgecolor="none",
        clip_on=False,
    )
    action_axis.add_patch(feasible)
    _line(action_axis, (0.4, 7.2), (3.0, 6.4), color=BLUE, width=2.0, data=True)
    _math(
        action_axis,
        5.25,
        6.95,
        r"$A_{\rm cbf}u=b_{\rm cbf}$",
        size=10.2,
        color=BLUE,
        ha="center",
        data=True,
    )
    _text(action_axis, 2.0, 6.2, "可行动作", size=9.4, color=BLUE, ha="center", data=True)
    nominal = (5.75, 2.2)
    projected = (4.36, 4.98)
    action_axis.add_patch(
        Circle(
            nominal,
            0.13,
            facecolor=RED,
            edgecolor=RED,
            linewidth=1.0,
            clip_on=False,
        )
    )
    action_axis.add_patch(
        Circle(
            projected,
            0.13,
            facecolor=BLUE,
            edgecolor=BLUE,
            linewidth=1.0,
            clip_on=False,
        )
    )
    _line(
        action_axis,
        (nominal[0], projected[0]),
        (nominal[1], projected[1]),
        color=MUTED,
        width=1.2,
        style=(0, (3, 2)),
        data=True,
    )
    _arrow(
        action_axis,
        (5.18, 3.34),
        projected,
        color=BLUE,
        width=1.45,
        data=True,
    )
    _math(
        action_axis,
        nominal[0] + 0.2,
        nominal[1] - 0.15,
        r"$u_{\rm nom}$",
        size=10.5,
        color=RED,
        data=True,
    )
    _math(
        action_axis,
        projected[0] - 0.15,
        projected[1] + 0.35,
        r"$u^\star$",
        size=10.5,
        color=BLUE,
        data=True,
    )
    _math(
        action_axis,
        4.05,
        1.18,
        r"$u^\star=\arg\min_u\ \frac{1}{2}\|u-u_{\rm nom}\|_2^2$",
        size=10.9,
        ha="center",
        data=True,
    )
    _math(
        action_axis,
        4.05,
        0.65,
        r"$\mathrm{s.t.}\quad A_{\rm cbf}u\geq b_{\rm cbf}$",
        size=10.9,
        ha="center",
        data=True,
    )
    _text(
        action_axis,
        0.5,
        -0.045,
        "模型、感知、可行性和跟踪成立时，QP 才能给出条件性安全修正。",
        size=8.8,
        color=RED,
        ha="center",
        va="top",
    )
    return _save(figure, path, preview_path)


def render_all(output_dir: Path, preview_dir: Path | None = None) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if preview_dir is not None:
        preview_dir = Path(preview_dir)
        preview_dir.mkdir(parents=True, exist_ok=True)
    renderers = (
        render_dijkstra,
        render_sdf_esdf,
        render_cbf_hocbf,
    )
    return [
        renderer(
            output_dir / filename,
            None if preview_dir is None else preview_dir / Path(filename).with_suffix(".png"),
        )
        for renderer, filename in zip(renderers, EXPECTED_FILENAMES)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render restrained academic SVG diagrams for Obsidian knowledge notes."
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--preview-dir", type=Path)
    args = parser.parse_args()
    for rendered in render_all(args.output_dir, preview_dir=args.preview_dir):
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
