import struct
import unittest
from pathlib import Path

VAULT = Path(r"C:\Users\w5711112\Documents\Obsidian Vault")
TARGET = VAULT / "路径规划与环境表示.md"
HUMAN = VAULT / "人机协同.md"
MEDIA = VAULT / "AI绘图存放位置"


def slice_section(text: str, start: str, end: str | None = None) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index) if end else len(text)
    return text[start_index:end_index]


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


class VectorFieldKnowledgeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target = TARGET.read_text(encoding="utf-8")
        cls.human = HUMAN.read_text(encoding="utf-8")

    def test_unique_section_is_between_bspline_and_global_local_division(self):
        self.assertEqual(self.target.count("## 向量场与路径引导"), 1)
        self.assertEqual(self.target.count("### 向量场"), 1)
        self.assertEqual(self.target.count("### 引导向量场 GVF"), 1)
        self.assertLess(
            self.target.index("### B-spline 轨迹"),
            self.target.index("## 向量场与路径引导"),
        )
        self.assertLess(
            self.target.index("## 向量场与路径引导"),
            self.target.index("## 全局引导与局部反应的分工"),
        )

    def assert_visual_formula_order(
        self,
        section: str,
        image_name: str,
        formula_callout: str,
    ):
        markers = [
            "#### 第一层｜直觉理解 |",
            f"![[AI绘图存放位置/{image_name}|950]]",
            "> [!info]- **读图与图例**",
            "#### 第二层｜公式与原理",
            formula_callout,
        ]
        positions = [section.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(section.count("![[AI绘图存放位置/"), 1)

    def test_vector_field_block_is_plain_language_and_formula_complete(self):
        section = slice_section(self.target, "### 向量场", "### 引导向量场 GVF")
        self.assert_visual_formula_order(
            section,
            "向量场-局部箭头与积分曲线.png",
            "> [!info]- **向量场：从局部箭头到积分曲线**",
        )
        for token in (
            "空间的每个位置放一支箭头",
            "向量场不是一条预先画好的轨迹",
            r"F:\Omega\subseteq\mathbb R^n\rightarrow\mathbb R^n",
            r"\dot x(t)=F(x(t))",
            r"x_{k+1}\approx x_k+\Delta tF(x_k)",
            r"F(x,y)=(-y,x)",
            "重新合回计算链",
            "适用与边界",
        ):
            self.assertIn(token, section)

    def test_gvf_block_is_plain_language_and_formula_complete(self):
        section = slice_section(
            self.target,
            "### 引导向量场 GVF",
            "## 全局引导与局部反应的分工",
        )
        self.assert_visual_formula_order(
            section,
            "引导向量场-切向前进与法向收敛.png",
            "> [!info]- **引导向量场：切向前进与法向收敛怎样合成**",
        )
        for token in (
            "一支把偏离路径的状态拉回路径",
            "另一支让到达路径的状态继续沿路径前进",
            r"\chi(x)=k_tE\nabla\phi(x)-k_n\phi(x)\nabla\phi(x)",
            r"\phi(x,y)=x^2+y^2-R^2",
            "路径外",
            "路径内",
            "路径上",
            "误解纠正",
            "重新合回完整公式",
            "符号速查",
        ):
            self.assertIn(token, section)

    def test_human_note_links_to_canonical_explanations_without_old_definition(self):
        self.assertIn("[[路径规划与环境表示#向量场|向量场]]", self.human)
        self.assertIn(
            "[[路径规划与环境表示#引导向量场 GVF|引导向量场]]",
            self.human,
        )
        self.assertNotIn("将期望路径数学化为具有引力的向量矩阵", self.human)

    def test_final_png_assets_exist_and_have_native_resolution(self):
        for name in (
            "向量场-局部箭头与积分曲线.png",
            "引导向量场-切向前进与法向收敛.png",
        ):
            path = MEDIA / name
            self.assertTrue(path.is_file(), name)
            width, height = png_dimensions(path)
            self.assertGreaterEqual(width, 1500)
            self.assertGreaterEqual(height, 800)


if __name__ == "__main__":
    unittest.main()
