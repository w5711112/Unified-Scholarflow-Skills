from __future__ import annotations

import argparse
import heapq
from dataclasses import dataclass
from itertools import count
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, Patch, Rectangle


Cell = tuple[int, int]
WIDTH = 19
HEIGHT = 12
START: Cell = (1, 6)
GOAL: Cell = (17, 6)
OBSTACLES = frozenset(
    {(9, y) for y in range(1, 11) if y != 3}
    | {(x, 8) for x in range(4, 9)}
    | {(x, 3) for x in range(10, 15)}
)
PALETTE = {
    "expanded_fill": "#DCEAF8",
    "expanded_line": "#4776A8",
    "frontier_fill": "#E8DFF3",
    "frontier_line": "#765A9B",
    "obstacle_fill": "#F6DDDD",
    "obstacle_line": "#B25C5C",
    "path_fill": "#DDEED8",
    "path_line": "#4F8A58",
    "cue_fill": "#FBE6CC",
    "cue_line": "#C47A2C",
    "context_fill": "#EEF1F4",
    "context_line": "#626B75",
}
FORMULA = r"$f(n)=g(n)+h(n)$"
HEURISTIC_FORMULA = r"$h(n)=\left|x_n-x_G\right|+\left|y_n-y_G\right|$"
RELAXATION_FORMULA = r"$g'(m)=g(n)+c(n,m)$"
UPDATE_CONDITION = r"$g'(m)<g_{\mathrm{old}}(m)$"
EXAMPLE_CURRENT: Cell = (3, 6)
EXAMPLE_RIGHT: Cell = (4, 6)
EXAMPLE_DOWN: Cell = (3, 7)
TEXT_COLOR = "#263238"
MUTED_TEXT = "#59636E"


@dataclass(frozen=True)
class SearchResult:
    expanded: tuple[Cell, ...]
    frontier: frozenset[Cell]
    path: tuple[Cell, ...]
    cost: int


def _neighbors(cell: Cell) -> tuple[Cell, ...]:
    x, y = cell
    candidates = ((x + 1, y), (x, y - 1), (x, y + 1), (x - 1, y))
    return tuple(
        candidate
        for candidate in candidates
        if 0 <= candidate[0] < WIDTH
        and 0 <= candidate[1] < HEIGHT
        and candidate not in OBSTACLES
    )


def _heuristic(cell: Cell, mode: str) -> int:
    if mode == "zero":
        return 0
    if mode == "manhattan":
        return abs(cell[0] - GOAL[0]) + abs(cell[1] - GOAL[1])
    raise ValueError(f"unknown heuristic mode: {mode}")


def worked_example() -> dict[str, object]:
    current_g = 2

    def candidate(cell: Cell) -> dict[str, object]:
        edge = 1
        tentative_g = current_g + edge
        h_value = _heuristic(cell, "manhattan")
        return {
            "cell": cell,
            "edge": edge,
            "tentative_g": tentative_g,
            "h": h_value,
            "f": tentative_g + h_value,
        }

    return {
        "current": {"cell": EXAMPLE_CURRENT, "g": current_g},
        "right": candidate(EXAMPLE_RIGHT),
        "down": candidate(EXAMPLE_DOWN),
    }


def solve_search(heuristic_mode: str) -> SearchResult:
    serial = count()
    queue: list[tuple[int, int, int, Cell]] = []
    start_h = _heuristic(START, heuristic_mode)
    heapq.heappush(queue, (start_h, start_h, next(serial), START))
    g_score = {START: 0}
    parent: dict[Cell, Cell] = {}
    expanded: list[Cell] = []
    closed: set[Cell] = set()

    while queue:
        _, _, _, current = heapq.heappop(queue)
        if current in closed:
            continue
        closed.add(current)
        expanded.append(current)
        if current == GOAL:
            break
        for neighbor in _neighbors(current):
            tentative = g_score[current] + 1
            if tentative >= g_score.get(neighbor, 10**9):
                continue
            g_score[neighbor] = tentative
            parent[neighbor] = current
            h_value = _heuristic(neighbor, heuristic_mode)
            heapq.heappush(
                queue,
                (tentative + h_value, h_value, next(serial), neighbor),
            )

    if GOAL not in g_score:
        raise RuntimeError("fixture has no path")

    path = [GOAL]
    while path[-1] != START:
        path.append(parent[path[-1]])
    path.reverse()
    frontier = frozenset(
        cell for _, _, _, cell in queue if cell not in closed
    )
    return SearchResult(
        expanded=tuple(expanded),
        frontier=frontier,
        path=tuple(path),
        cost=g_score[GOAL],
    )


def _font() -> font_manager.FontProperties:
    candidates = (
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return font_manager.FontProperties(fname=str(candidate))
    return font_manager.FontProperties(family="DejaVu Sans")


def _draw_cell(axis, cell: Cell, fill: str, line: str, *, zorder: int) -> None:
    x, y = cell
    axis.add_patch(
        Rectangle(
            (x, y),
            1,
            1,
            facecolor=fill,
            edgecolor=line,
            linewidth=0.75,
            zorder=zorder,
        )
    )


def _unit_axis(axis) -> None:
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")


def _add_card(
    axis,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: str,
    line: str,
    linewidth: float = 1.15,
    radius: float = 0.025,
) -> None:
    axis.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle=f"round,pad=0.008,rounding_size={radius}",
            transform=axis.transAxes,
            facecolor=fill,
            edgecolor=line,
            linewidth=linewidth,
            clip_on=False,
        )
    )


def _draw_definition_layer(axis) -> None:
    _unit_axis(axis)
    font = _font()
    axis.text(
        0.5,
        0.95,
        "Dijkstra 与 A*：同一松弛更新，不同排序键如何改变搜索",
        transform=axis.transAxes,
        ha="center",
        va="top",
        fontproperties=font,
        fontsize=17,
        fontweight="bold",
        color=TEXT_COLOR,
    )

    _add_card(
        axis,
        0.025,
        0.64,
        0.95,
        0.19,
        fill=PALETTE["context_fill"],
        line="#B8C0C8",
        radius=0.018,
    )
    axis.text(
        0.045,
        0.765,
        "共同图模型：四邻域栅格，单步边代价 c(n,m)=1；OPEN=已发现待扩张，CLOSED=已扩张",
        transform=axis.transAxes,
        ha="left",
        va="center",
        fontproperties=font,
        fontsize=11.8,
        color=TEXT_COLOR,
    )
    axis.text(
        0.045,
        0.685,
        "共同循环：弹出排序键最小的节点 → 松弛邻居 → 更新 OPEN；目标 G 从 OPEN 弹出时停止",
        transform=axis.transAxes,
        ha="left",
        va="center",
        fontproperties=font,
        fontsize=11.8,
        color=TEXT_COLOR,
    )

    _add_card(
        axis,
        0.025,
        0.03,
        0.46,
        0.52,
        fill="#F4F8FC",
        line=PALETTE["expanded_line"],
    )
    axis.text(
        0.05,
        0.48,
        "Dijkstra",
        transform=axis.transAxes,
        ha="left",
        va="center",
        fontproperties=font,
        fontsize=14,
        fontweight="bold",
        color=PALETTE["expanded_line"],
    )
    axis.text(
        0.05,
        0.36,
        r"排序键：$q(n)=g(n)$",
        transform=axis.transAxes,
        ha="left",
        va="center",
        fontproperties=font,
        fontsize=13,
        color=TEXT_COLOR,
    )
    axis.text(
        0.05,
        0.245,
        "g(n)：从起点 S 到 n 的当前最低累计代价",
        transform=axis.transAxes,
        ha="left",
        va="center",
        fontproperties=font,
        fontsize=11.6,
        color=TEXT_COLOR,
    )
    axis.text(
        0.05,
        0.135,
        "选择：从 OPEN 弹出 g 最小的节点",
        transform=axis.transAxes,
        ha="left",
        va="center",
        fontproperties=font,
        fontsize=11.6,
        color=TEXT_COLOR,
    )

    _add_card(
        axis,
        0.515,
        0.03,
        0.46,
        0.52,
        fill="#FCF7F0",
        line=PALETTE["cue_line"],
    )
    axis.text(
        0.54,
        0.48,
        "A*",
        transform=axis.transAxes,
        ha="left",
        va="center",
        fontproperties=font,
        fontsize=14,
        fontweight="bold",
        color=PALETTE["cue_line"],
    )
    axis.text(
        0.54,
        0.375,
        r"排序键：$q(n)=f(n)=g(n)+h(n)$",
        transform=axis.transAxes,
        ha="left",
        va="center",
        fontproperties=font,
        fontsize=13,
        color=TEXT_COLOR,
    )
    axis.text(
        0.54,
        0.27,
        HEURISTIC_FORMULA,
        transform=axis.transAxes,
        ha="left",
        va="center",
        fontsize=13,
        color=PALETTE["cue_line"],
    )
    axis.text(
        0.54,
        0.175,
        "选择：从 OPEN 弹出 f 最小的节点",
        transform=axis.transAxes,
        ha="left",
        va="center",
        fontproperties=font,
        fontsize=11.6,
        color=TEXT_COLOR,
    )
    axis.text(
        0.54,
        0.085,
        "h 只估计剩余栅格步数、忽略障碍；h=0 时退化为 Dijkstra",
        transform=axis.transAxes,
        ha="left",
        va="center",
        fontproperties=font,
        fontsize=10.5,
        color=MUTED_TEXT,
    )


def _draw_local_example(axis) -> None:
    font = _font()
    x0, y0 = 0.055, 0.25
    cell_w, cell_h = 0.077, 0.205
    cells = (
        (x0, y0 + cell_h, PALETTE["expanded_fill"], PALETTE["expanded_line"], "n\n(3,6)"),
        (x0 + cell_w, y0 + cell_h, PALETTE["cue_fill"], PALETTE["cue_line"], "$m_R$\n(4,6)"),
        (x0, y0, PALETTE["frontier_fill"], PALETTE["frontier_line"], "$m_D$\n(3,7)"),
        (x0 + cell_w, y0, "#FFFFFF", "#CBD2D9", ""),
    )
    for x, y, fill, line, label in cells:
        axis.add_patch(
            Rectangle(
                (x, y),
                cell_w,
                cell_h,
                transform=axis.transAxes,
                facecolor=fill,
                edgecolor=line,
                linewidth=1.25,
            )
        )
        if label:
            axis.text(
                x + cell_w / 2,
                y + cell_h / 2,
                label,
                transform=axis.transAxes,
                ha="center",
                va="center",
                fontproperties=font,
                fontsize=10.6,
                color=TEXT_COLOR,
            )
    axis.annotate(
        "",
        xy=(x0 + cell_w + 0.002, y0 + 1.5 * cell_h),
        xytext=(x0 + cell_w - 0.023, y0 + 1.5 * cell_h),
        xycoords=axis.transAxes,
        arrowprops={"arrowstyle": "->", "color": PALETTE["cue_line"], "lw": 1.4},
    )
    axis.annotate(
        "",
        xy=(x0 + cell_w / 2, y0 + cell_h + 0.002),
        xytext=(x0 + cell_w / 2, y0 + cell_h + 0.045),
        xycoords=axis.transAxes,
        arrowprops={"arrowstyle": "->", "color": PALETTE["frontier_line"], "lw": 1.4},
    )


def _draw_numeric_table(axis) -> None:
    font = _font()
    x0, y0, width, height = 0.292, 0.285, 0.415, 0.37
    col_fracs = (0.24, 0.12, 0.12, 0.25, 0.27)
    headers = ("候选 m", "g'", "h(m)", "Dijkstra\n键=g'", "A*\n键=f")
    rows = (
        ("$m_R=(4,6)$", "3", "13", "3", "16"),
        ("$m_D=(3,7)$", "3", "15", "3", "18"),
    )
    row_height = height / 3
    x_positions = [x0]
    for fraction in col_fracs:
        x_positions.append(x_positions[-1] + width * fraction)
    for row_index in range(3):
        y = y0 + height - (row_index + 1) * row_height
        fill = PALETTE["context_fill"] if row_index == 0 else "#FFFFFF"
        values = headers if row_index == 0 else rows[row_index - 1]
        for col_index, value in enumerate(values):
            x = x_positions[col_index]
            cell_width = x_positions[col_index + 1] - x
            axis.add_patch(
                Rectangle(
                    (x, y),
                    cell_width,
                    row_height,
                    transform=axis.transAxes,
                    facecolor=fill,
                    edgecolor="#BFC7CF",
                    linewidth=0.9,
                )
            )
            color = TEXT_COLOR
            if row_index > 0 and col_index == 4:
                color = PALETTE["cue_line"]
            axis.text(
                x + cell_width / 2,
                y + row_height / 2,
                value,
                transform=axis.transAxes,
                ha="center",
                va="center",
                fontproperties=font,
                fontsize=10.2 if row_index == 0 else 10.8,
                fontweight="bold" if row_index == 0 else "normal",
                color=color,
            )


def _draw_worked_example_layer(axis) -> None:
    _unit_axis(axis)
    font = _font()
    example = worked_example()
    right = example["right"]
    down = example["down"]

    axis.text(
        0.5,
        0.965,
        "一步数值更新：两者共享松弛与写回，区别只在 OPEN 的排序键",
        transform=axis.transAxes,
        ha="center",
        va="top",
        fontproperties=font,
        fontsize=15,
        fontweight="bold",
        color=TEXT_COLOR,
    )

    _add_card(axis, 0.02, 0.09, 0.235, 0.76, fill="#FAFBFC", line="#AEB7C0")
    axis.text(
        0.1375,
        0.79,
        "当前节点与两个候选",
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=12,
        fontweight="bold",
        color=TEXT_COLOR,
    )
    _draw_local_example(axis)
    axis.text(
        0.1375,
        0.185,
        "g(n)=2，两个边代价均为 1",
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=10.8,
        color=MUTED_TEXT,
    )

    _add_card(axis, 0.27, 0.09, 0.46, 0.76, fill="#FFFDF9", line=PALETTE["cue_line"])
    axis.text(
        0.5,
        0.79,
        r"先算暂定代价：$g'=g(n)+c(n,m)=2+1=3$",
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=12.2,
        color=TEXT_COLOR,
    )
    _draw_numeric_table(axis)
    axis.text(
        0.5,
        0.22,
        rf"向右：$h=\left|4-17\right|+\left|6-6\right|={right['h']}$，$f=3+{right['h']}={right['f']}$",
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=10.8,
        color=TEXT_COLOR,
    )
    axis.text(
        0.5,
        0.135,
        rf"向下：$h=\left|3-17\right|+\left|7-6\right|={down['h']}$，$f=3+{down['h']}={down['f']}$",
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=10.8,
        color=TEXT_COLOR,
    )

    _add_card(axis, 0.745, 0.09, 0.235, 0.76, fill="#F8F5FB", line=PALETTE["frontier_line"])
    axis.text(
        0.8625,
        0.79,
        "选择、写回与循环",
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=12,
        fontweight="bold",
        color=TEXT_COLOR,
    )
    axis.text(
        0.8625,
        0.675,
        "Dijkstra：3 = 3，两个候选并列",
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=10.8,
        color=PALETTE["expanded_line"],
        bbox={"boxstyle": "round,pad=0.28", "fc": "#FFFFFF", "ec": "none"},
    )
    axis.text(
        0.8625,
        0.575,
        "A*：16 < 18，优先向右",
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=10.8,
        color=PALETTE["cue_line"],
        bbox={"boxstyle": "round,pad=0.28", "fc": "#FFFFFF", "ec": "none"},
    )
    axis.text(
        0.8625,
        0.455,
        UPDATE_CONDITION,
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontsize=12,
        color=TEXT_COLOR,
    )
    axis.text(
        0.8625,
        0.31,
        "满足：g(m) ← g'，parent(m) ← n\n加入或更新 OPEN",
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=10.2,
        linespacing=1.25,
        color=TEXT_COLOR,
    )
    axis.text(
        0.8625,
        0.15,
        "否则保留旧值；随后回到“弹出最小键”",
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontproperties=font,
        fontsize=10.2,
        color=MUTED_TEXT,
    )


def _draw_search_panel(axis, result: SearchResult, title: str, key_label: str) -> None:
    for x in range(WIDTH):
        for y in range(HEIGHT):
            _draw_cell(axis, (x, y), "#FFFFFF", "#D9DEE3", zorder=0)
    for cell in result.expanded:
        _draw_cell(
            axis,
            cell,
            PALETTE["expanded_fill"],
            PALETTE["expanded_line"],
            zorder=1,
        )
    for cell in result.frontier:
        _draw_cell(
            axis,
            cell,
            PALETTE["frontier_fill"],
            PALETTE["frontier_line"],
            zorder=2,
        )
    for cell in OBSTACLES:
        _draw_cell(
            axis,
            cell,
            PALETTE["obstacle_fill"],
            PALETTE["obstacle_line"],
            zorder=3,
        )

    shared_path = solve_search("manhattan").path
    for cell in shared_path:
        _draw_cell(
            axis,
            cell,
            PALETTE["path_fill"],
            PALETTE["path_line"],
            zorder=4,
        )
    xs = [x + 0.5 for x, _ in shared_path]
    ys = [y + 0.5 for _, y in shared_path]
    axis.plot(
        xs,
        ys,
        color=PALETTE["path_line"],
        linewidth=3.2,
        solid_capstyle="round",
        zorder=5,
    )

    axis.scatter(
        [START[0] + 0.5, GOAL[0] + 0.5],
        [START[1] + 0.5, GOAL[1] + 0.5],
        s=105,
        c=[PALETTE["path_fill"], PALETTE["cue_fill"]],
        edgecolors=[PALETTE["path_line"], PALETTE["cue_line"]],
        linewidths=1.6,
        zorder=6,
    )
    axis.text(
        START[0] + 0.5,
        START[1] + 0.5,
        "S",
        ha="center",
        va="center",
        fontsize=10.2,
        color="#263238",
        zorder=7,
    )
    axis.text(
        GOAL[0] + 0.5,
        GOAL[1] + 0.5,
        "G",
        ha="center",
        va="center",
        fontsize=10.2,
        color="#263238",
        zorder=7,
    )

    axis.set_title(
        title,
        fontproperties=_font(),
        fontsize=13.5,
        color=TEXT_COLOR,
        pad=5,
    )
    axis.text(
        0.5,
        -0.065,
        f"排序键 {key_label}　|　最优路径代价 {result.cost}　|　已扩张 {len(result.expanded)} 个节点",
        transform=axis.transAxes,
        ha="center",
        va="top",
        fontproperties=_font(),
        fontsize=10.6,
        color=MUTED_TEXT,
    )
    axis.set_xlim(0, WIDTH)
    axis.set_ylim(HEIGHT, 0)
    axis.set_aspect("equal")
    axis.axis("off")


def render_comparison(output_path: Path, *, dpi: int = 220) -> Path:
    dijkstra = solve_search("zero")
    astar = solve_search("manhattan")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    figure = plt.figure(figsize=(14.0, 10.0), dpi=dpi, facecolor="white")
    grid = figure.add_gridspec(
        3,
        2,
        height_ratios=(1.25, 1.65, 2.35),
        left=0.025,
        right=0.985,
        top=0.975,
        bottom=0.075,
        hspace=0.14,
        wspace=0.055,
    )
    definition_axis = figure.add_subplot(grid[0, :])
    example_axis = figure.add_subplot(grid[1, :])
    dijkstra_axis = figure.add_subplot(grid[2, 0])
    astar_axis = figure.add_subplot(grid[2, 1])

    _draw_definition_layer(definition_axis)
    _draw_worked_example_layer(example_axis)
    _draw_search_panel(
        dijkstra_axis,
        dijkstra,
        "(a) Dijkstra：按最小累计代价向外扩张",
        "g(n)",
    )
    _draw_search_panel(
        astar_axis,
        astar,
        "(b) A*：累计代价与启发式共同排序",
        "f(n)=g(n)+h(n)",
    )
    legend = (
        Patch(facecolor=PALETTE["expanded_fill"], edgecolor=PALETTE["expanded_line"], label="已扩张"),
        Patch(facecolor=PALETTE["frontier_fill"], edgecolor=PALETTE["frontier_line"], label="前沿"),
        Patch(facecolor=PALETTE["obstacle_fill"], edgecolor=PALETTE["obstacle_line"], label="障碍"),
        Patch(facecolor=PALETTE["path_fill"], edgecolor=PALETTE["path_line"], label="最短路径"),
    )
    figure.legend(
        handles=legend,
        loc="lower center",
        ncol=4,
        frameon=False,
        prop=_font().copy(),
        bbox_to_anchor=(0.5, 0.006),
    )
    for text in figure.legends[0].get_texts():
        text.set_fontsize(10.6)
    figure.savefig(
        output_path,
        dpi=dpi,
        facecolor="white",
        metadata={"Software": "obsidian-note-style deterministic renderer"},
    )
    plt.close(figure)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--dpi", type=int, default=220)
    args = parser.parse_args()
    print(render_comparison(args.output, dpi=args.dpi))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
