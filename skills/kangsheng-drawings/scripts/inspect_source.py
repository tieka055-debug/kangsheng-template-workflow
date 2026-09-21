#!/usr/bin/env python3
"""Extract page geometry and text blocks without rendering or model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf as fitz


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rotation", type=int, default=0)
    args = parser.parse_args()
    source = args.source.resolve()
    doc = fitz.open(source)
    pages = []
    for index, page in enumerate(doc):
        if args.rotation:
            page.set_rotation(args.rotation)
        blocks = []
        for block in page.get_text("dict").get("blocks", []):
            item = {"bbox": list(block.get("bbox", [])), "type": block.get("type")}
            if block.get("type") == 0:
                item["text"] = "\n".join(
                    "".join(span.get("text", "") for span in line.get("spans", []))
                    for line in block.get("lines", []))
            blocks.append(item)
        drawings = [{"rect": list(item["rect"]), "type": item.get("type")}
                    for item in page.get_drawings()]
        pages.append({"page": index + 1, "box": list(page.rect), "rotation": page.rotation,
                      "text_blocks": blocks, "drawing_paths": drawings,
                      "image_count": len(page.get_images(full=True))})
    result = {"schema_version": 1, "source": str(source),
              "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "pages": pages}
    target = (args.output or source.with_suffix(".structure.json")).resolve()
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
