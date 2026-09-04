from __future__ import annotations

import sys
import unittest
from pathlib import Path

import fitz


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from augment_pdf_memory_layer import (  # noqa: E402
    DEFAULT_LINK_LABEL,
    MemoryLayerError,
    add_memory_layer,
    build_obsidian_uri,
    build_zotero_bridge_url,
)

from test_support import writable_test_directory  # noqa: E402

class MemoryLayerTests(unittest.TestCase):
    def test_zotero_bridge_url_wraps_obsidian_uri_in_reader_safe_https_link(self):
        uri = build_obsidian_uri(
            "Obsidian Vault",
            "研究目录/01-核心论文精读.md",
            "paper-high-speed-safety-shielded",
        )
        bridge_url = build_zotero_bridge_url(uri)
        self.assertTrue(
            bridge_url.startswith("https://obsidian-link.invalid/open?uri=")
        )
        self.assertNotIn("obsidian://", bridge_url)
        self.assertEqual(DEFAULT_LINK_LABEL, "返回 Obsidian的对应精读位置")

    def test_obsidian_uri_targets_exact_block_with_reserved_characters_encoded(self):
        uri = build_obsidian_uri(
            "Obsidian Vault",
            "研究目录/01-核心论文精读.md",
            "paper-high-speed-safety-shielded",
        )
        self.assertEqual(
            uri,
            "obsidian://open?vault=Obsidian%20Vault&"
            "file=%E7%A0%94%E7%A9%B6%E7%9B%AE%E5%BD%95%2F"
            "01-%E6%A0%B8%E5%BF%83%E8%AE%BA%E6%96%87%E7%B2%BE%E8%AF%BB"
            "%23%5Epaper-high-speed-safety-shielded",
        )

    def test_memory_layer_adds_text_and_exactly_one_uri_link_without_pdf_markup(self):
        with writable_test_directory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            output = root / "output.pdf"
            document = fitz.open()
            page = document.new_page(width=594, height=792)
            page.insert_textbox(
                fitz.Rect(70, 60, 524, 115),
                "Fixture Paper Title",
                fontsize=20,
                align=fitz.TEXT_ALIGN_CENTER,
            )
            document.save(source)
            document.close()

            sentence = (
                "Global cost shapes direction; a safety QP minimally corrects actions."
            )
            uri = build_obsidian_uri(
                "Obsidian Vault",
                "research/note.md",
                "paper-fixture",
            )
            report = add_memory_layer(
                source=source,
                output=output,
                memory_sentence=sentence,
                obsidian_uri=uri,
                memory_rect=(45, 42, 549, 58),
                link_rect=(37, 14, 165, 29),
                protected_rects=((37, 32, 552, 41), (64, 60, 526, 115)),
                memory_font_size=8.5,
                link_font_size=7.5,
            )

            self.assertEqual(report["page_count"], 1)
            bridge_url = build_zotero_bridge_url(uri)
            self.assertEqual(report["obsidian_uri"], uri)
            self.assertEqual(report["bridge_url"], bridge_url)
            self.assertEqual(report["link_label"], DEFAULT_LINK_LABEL)
            self.assertEqual(report["memory_sentence"], sentence)
            self.assertTrue(output.is_file())

            checked = fitz.open(output)
            self.assertIn(sentence, checked[0].get_text())
            matching_links = [
                link
                for link in checked[0].get_links()
                if link.get("uri") == bridge_url
            ]
            self.assertEqual(len(matching_links), 1)
            self.assertFalse(
                any(link.get("uri") == uri for link in checked[0].get_links())
            )
            markup_types = {
                annot.type[1]
                for annot in (checked[0].annots() or ())
            }
            self.assertEqual(markup_types, set())
            checked.close()


    def test_layout_line_breaks_do_not_break_memory_sentence_verification(self):
        with writable_test_directory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            output = root / "output.pdf"
            document = fitz.open()
            document.new_page(width=300, height=300)
            document.save(source)
            document.close()

            sentence = (
                "Global cost shapes direction while a safety quadratic program "
                "minimally corrects every unsafe action."
            )
            report = add_memory_layer(
                source=source,
                output=output,
                memory_sentence=sentence,
                obsidian_uri="obsidian://open?vault=V&file=N%23%5Eb",
                memory_rect=(40, 30, 260, 72),
                link_rect=(10, 5, 130, 20),
                memory_font_size=9,
            )
            self.assertEqual(report["memory_sentence"], sentence)
    def test_memory_or_link_rect_may_not_overlap_protected_content(self):
        with writable_test_directory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            output = root / "output.pdf"
            document = fitz.open()
            document.new_page(width=300, height=300)
            document.save(source)
            document.close()

            with self.assertRaises(MemoryLayerError):
                add_memory_layer(
                    source=source,
                    output=output,
                    memory_sentence="Meaningful memory sentence.",
                    obsidian_uri="obsidian://open?vault=V&file=N%23%5Eb",
                    memory_rect=(10, 20, 290, 50),
                    link_rect=(10, 5, 100, 18),
                    protected_rects=((0, 40, 300, 80),),
                )


if __name__ == "__main__":
    unittest.main()
