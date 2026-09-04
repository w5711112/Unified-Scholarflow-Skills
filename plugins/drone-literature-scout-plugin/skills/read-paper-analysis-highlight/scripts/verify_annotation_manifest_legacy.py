from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import fitz


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(manifest_path: str | Path) -> bool:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    required = {
        "source_pdf", "annotated_pdf", "backup_pdf", "original_sha256",
        "annotated_sha256", "page_count", "annotation_count", "storage_mode",
        "annotations",
    }
    missing = required.difference(manifest)
    if missing:
        raise ValueError(f"manifest missing fields: {sorted(missing)}")
    annotated = Path(manifest["annotated_pdf"])
    backup = Path(manifest["backup_pdf"])
    if not annotated.is_file() or not backup.is_file():
        raise ValueError("annotated PDF or backup PDF is missing")
    if sha256(backup) != manifest["original_sha256"]:
        raise ValueError("backup hash does not match original_sha256")
    if sha256(annotated) != manifest["annotated_sha256"]:
        raise ValueError("annotated hash does not match manifest")
    with fitz.open(annotated) as doc:
        if doc.page_count != int(manifest["page_count"]):
            raise ValueError("page count changed")
        for item in manifest["annotations"]:
            page_number = int(item["page"])
            if not 1 <= page_number <= doc.page_count:
                raise ValueError(f"annotation page out of bounds: {page_number}")
            page = doc[page_number - 1]
            if item.get("annotation_type") == "highlight":
                quads = item.get("quads")
                if not quads:
                    raise ValueError("highlight annotation has no quads")
                for values in quads:
                    if len(values) != 8:
                        raise ValueError(f"invalid quad: {values}")
                    points = [
                        fitz.Point(values[index], values[index + 1])
                        for index in range(0, 8, 2)
                    ]
                    if not all(point in page.rect for point in points):
                        raise ValueError(f"annotation quad out of bounds: {values}")
                if not item.get("actual_text"):
                    raise ValueError("highlight annotation has no actual_text")
            elif item.get("annotation_type") == "area":
                rect = fitz.Rect(item["rect"])
                if not page.rect.contains(rect):
                    raise ValueError(f"annotation rect out of bounds: {item['rect']}")
                if not item.get("visual_object"):
                    raise ValueError("area annotation has no visual_object")
            else:
                raise ValueError(f"unknown annotation_type: {item.get('annotation_type')}")
        actual_count = sum(1 for page in doc for _ in (page.annots() or []))
        if actual_count != int(manifest["annotation_count"]):
            raise ValueError("PDF annotation count does not match manifest")
    if len(manifest["annotations"]) != int(manifest["annotation_count"]):
        raise ValueError("annotation count mismatch")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    args = parser.parse_args()
    print("valid" if verify_manifest(args.manifest) else "invalid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())