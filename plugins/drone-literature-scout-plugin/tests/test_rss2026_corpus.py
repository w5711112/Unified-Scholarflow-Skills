from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from test_support import writable_test_directory


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "skills" / "draw-style" / "scripts" / "rss2026_corpus.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rss2026_corpus", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RSS2026CorpusTests(unittest.TestCase):
    def test_build_starts_inclusively_and_assigns_five_image_batches(self):
        module = load_module()
        with writable_test_directory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            names = [
                "屏幕截图 2026-08-01 224900.png",
                "屏幕截图 2026-08-01 224935.png",
                "屏幕截图 2026-08-01 225000.png",
                "屏幕截图 2026-08-01 225100.png",
                "屏幕截图 2026-08-01 225200.png",
                "屏幕截图 2026-08-01 225300.png",
                "屏幕截图 2026-08-01 225400.png",
            ]
            for position, name in enumerate(names):
                (source / name).write_bytes(f"image-{position}".encode())

            index = module.build_index(source, names[1], expected_count=6)

            self.assertEqual(index["corpus"]["image_count"], 6)
            self.assertEqual(index["corpus"]["batch_count"], 2)
            self.assertEqual(index["images"][0]["logical_id"], "RSS2026_001")
            self.assertEqual(index["images"][0]["original_filename"], names[1])
            self.assertEqual(index["images"][4]["batch_id"], 1)
            self.assertEqual(index["images"][5]["batch_id"], 2)
            self.assertEqual(index["images"][5]["batch_position"], 1)
            self.assertEqual(index["images"][0]["analysis_status"], "pending")

    def test_validate_detects_source_byte_changes_without_writing_source(self):
        module = load_module()
        with writable_test_directory() as temp:
            source = Path(temp) / "source"
            refs = Path(temp) / "references"
            source.mkdir()
            refs.mkdir()
            start = "屏幕截图 2026-08-01 224935.png"
            image = source / start
            image.write_bytes(b"original")
            index = module.build_index(source, start, expected_count=1)
            index_path = refs / "rss2026-corpus-index.json"
            module.write_index(index_path, index)

            self.assertEqual(module.validate_index(index, source, refs), [])
            before_name = image.name
            image.write_bytes(b"changed")
            errors = module.validate_index(module.read_index(index_path), source, refs)
            self.assertTrue(any("sha256" in error for error in errors))
            self.assertEqual(image.name, before_name)

    def test_freeze_requires_complete_metadata_and_updates_batch_atomically(self):
        module = load_module()
        with writable_test_directory() as temp:
            source = Path(temp) / "source"
            refs = Path(temp) / "references"
            source.mkdir()
            refs.mkdir()
            start = "屏幕截图 2026-08-01 224935.png"
            (source / start).write_bytes(b"one")
            index = module.build_index(source, start, expected_count=1)
            index_path = refs / "rss2026-corpus-index.json"
            module.write_index(index_path, index)
            card = refs / "rss2026-batches" / "batch-001.md"
            card.parent.mkdir()
            card.write_text("# Batch 001\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                module.freeze_batch(index_path, 1, card, "2026-08-04")
            self.assertEqual(
                module.read_index(index_path)["images"][0]["analysis_status"],
                "pending",
            )

            metadata = {
                "visible_figure_label": "Fig. 5",
                "domain_tags": ["Manipulation", "RL"],
                "figure_track": "data/table",
            }
            card.write_text(
                "# Batch 001\n\n"
                "## RSS2026_001\n"
                f"<!-- rss2026-meta {json.dumps(metadata, ensure_ascii=False)} -->\n",
                encoding="utf-8",
            )
            module.freeze_batch(index_path, 1, card, "2026-08-04")
            frozen = module.read_index(index_path)["images"][0]
            self.assertEqual(frozen["analysis_status"], "frozen")
            self.assertEqual(frozen["visible_figure_label"], "Fig. 5")
            self.assertEqual(frozen["domain_tags"], ["Manipulation", "RL"])
            self.assertEqual(frozen["figure_track"], "data/table")
            self.assertEqual(frozen["last_verified"], "2026-08-04")


if __name__ == "__main__":
    unittest.main()
