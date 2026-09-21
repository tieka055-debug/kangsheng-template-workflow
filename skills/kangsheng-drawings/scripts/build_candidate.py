#!/usr/bin/env python3
"""Build one Kangsheng drawing candidate from a schema-v2 JSON config.

The source page is converted to one reusable vector form per colour mode. Each
placement then clips that shared form, instead of converting the whole SVG for
every crop. This keeps related dimensions together and avoids duplicate PDF
resources.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pymupdf as fitz

BLUE_HEX = "#0642a8"
BLUE = (6 / 255, 66 / 255, 168 / 255)
PAGE = (841.89, 595.276)
FRAME = [22, 29, 820, 564]
TITLE_RESERVED = [
    {"id": "brand_titleblock", "box": [488, 450, 820, 564]},
    {"id": "tolerance_block", "box": [400, 493, 488, 564]},
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def recolor(svg: str, mode: str) -> str:
    if mode == "blue_all":
        svg = re.sub(r"#[0-9a-fA-F]{6}\b", BLUE_HEX, svg)
        svg = re.sub(r"#[0-9a-fA-F]{3}\b", BLUE_HEX, svg)
        svg = svg.replace("<svg ", f'<svg fill="{BLUE_HEX}" ', 1)
        return svg
    if mode in {"black_to_blue", "keep_non_black"}:
        svg = re.sub(r"#000000\b|#000\b", BLUE_HEX, svg, flags=re.I)
        svg = svg.replace("<svg ", f'<svg fill="{BLUE_HEX}" ', 1)
        return svg
    if mode == "preserve":
        return svg
    raise ValueError(f"unknown color_mode: {mode}")


def target_rect(group: dict) -> tuple[fitz.Rect, float]:
    src = fitz.Rect(group["src"])
    if "fit_box" in group:
        box = fitz.Rect(group["fit_box"])
        scale = min(box.width / src.width, box.height / src.height)
        if group.get("allow_upscale") is not True:
            scale = min(scale, 1.0)
        width, height = src.width * scale, src.height * scale
        align = group.get("align", "top-left")
        x = box.x0 if "left" in align else box.x1 - width if "right" in align else box.x0 + (box.width - width) / 2
        y = box.y0 if "top" in align else box.y1 - height if "bottom" in align else box.y0 + (box.height - height) / 2
        return fitz.Rect(x, y, x + width, y + height), scale
    x, y = group["dst"]
    scale = float(group.get("scale", 1.0))
    return fitz.Rect(x, y, x + src.width * scale, y + src.height * scale), scale


def draw_frame_and_title(page: fitz.Page, fields: dict, assets: dict) -> None:
    def line(a, b, width=.65):
        page.draw_line(fitz.Point(*a), fitz.Point(*b), color=BLUE, width=width)
    def rect(box, width=.65):
        page.draw_rect(fitz.Rect(box), color=BLUE, width=width)
    def text(x, y, value, size=7, font="helv"):
        page.insert_text((x, y), value, fontname=font, fontsize=size, color=BLUE)
    def center(box, value, size=7, font="helv"):
        if font == "china-s":
            bounds = fitz.Rect(box)
            font_obj = fitz.Font(fontname=font)
            width = font_obj.text_length(value, fontsize=size)
            x = bounds.x0 + (bounds.width - width) / 2
            y = bounds.y0 + (bounds.height + size * .72) / 2
            page.insert_text((x, y), value, fontname=font, fontsize=size, color=BLUE)
            return
        result = page.insert_textbox(fitz.Rect(box), value, fontname=font, fontsize=size, color=BLUE, align=1)
        if result < 0:
            raise ValueError(f"title text overflow: {value!r}")
    def center_mixed(box, value, size=9):
        bounds = fitz.Rect(box)
        runs = []
        for char in value:
            font = "helv" if char.isascii() else "china-s"
            if runs and runs[-1][0] == font:
                runs[-1] = (font, runs[-1][1] + char)
            else:
                runs.append((font, char))
        def widths(font_size):
            return [fitz.Font(fontname=font).text_length(text, fontsize=font_size) for font, text in runs]
        run_widths = widths(size)
        total = sum(run_widths)
        if total > bounds.width - 4:
            size *= (bounds.width - 4) / total
            run_widths = widths(size); total = sum(run_widths)
        x = bounds.x0 + (bounds.width - total) / 2
        y = bounds.y0 + (bounds.height + size * .72) / 2
        for (font, text_value), width in zip(runs, run_widths):
            page.insert_text((x, y), text_value, fontname=font, fontsize=size, color=BLUE)
            x += width

    rect(FRAME, 1.2)
    for i, x in enumerate([75, 181, 280, 396, 503, 610, 716], 1):
        text(x - 2, 21, str(i), 9); text(x - 2, 580, str(i), 9)
    for x in [113.5, 224.4, 331.8, 447.8, 554.5, 661.8, 770.8]:
        line((x, 14), (x, 29), .8); line((x, 564), (x, 580), .8)
    for x in [67.8, 155.9, 267.7, 384, 491.3, 598, 705.4]:
        line((x, 22), (x, 29), .7); line((x, 564), (x, 573), .7)
    for i, y in enumerate([80, 184, 290, 397, 503]):
        text(11, y, chr(65 + i), 9); text(824, y, chr(65 + i), 9)
    for y in [132.5, 236.9, 342.9, 450.6]:
        line((10, y), (22, y), .8); line((820, y), (832, y), .8)
    for y in [78.4, 181, 286.5, 390.8, 498.6]:
        line((15, y), (22, y), .7); line((820, y), (827, y), .7)

    brand = fitz.open(resolve(Path.cwd(), assets["brand_strip"]))
    brand_pdf = fitz.open("pdf", brand.convert_to_pdf())
    br = brand_pdf[0].rect
    page.show_pdf_page(fitz.Rect(489, 452, 819, 491), brand_pdf, 0,
                       clip=fitz.Rect(br.width * .012, br.height * .12, br.width * .988, br.height * .91))
    brand_pdf.close(); brand.close()

    rect([488, 450, 820, 564], 1)
    line((488, 492), (820, 492)); line((488, 527), (820, 527))
    line((541, 492), (541, 527)); line((600, 492), (600, 527)); line((625, 492), (625, 527))
    line((688, 492), (688, 527)); line((488, 509.5), (688, 509.5))
    for x, y, value in [(492, 502, "DESIGN"), (492, 519, "APPROVED"), (603, 502, "DATE"),
                        (603, 519, "DATE"), (692, 501, "TITLE:"), (492, 537, "MODEL:")]:
        text(x, y, value, 6.5)
    center([696, 505, 813, 524], fields["title"], 11, "china-s")
    line((638, 527), (638, 564)); line((638, 545.5), (820, 545.5))
    for x in [679, 759]: line((x, 527), (x, 545.5))
    for x in [701, 775]: line((x, 545.5), (x, 564))
    text(643, 538, "REV: " + fields.get("revision", "—"), 6.5)
    text(683, 538, "SCALE: " + fields.get("scale_text", "—"), 6.5)
    text(764, 538, "UNIT: " + fields.get("unit", "mm"), 6.5)
    text(643, 557, "SIZE: " + fields.get("size", "A4"), 6.5)
    text(706, 557, "SHEET: " + fields.get("sheet", "1/1"), 6.5)
    center_mixed([491, 541, 635, 563], fields["model"], 9)

    rect([400, 493, 488, 564], .8)
    text(404, 503, "UNLESS OTHERWISE", 6)
    text(404, 511, "SPECIFIED, TOLERANCE:", 5.6)
    y = 523
    for value in fields.get("tolerances", []):
        text(408, y, value, 7); y += 10


def draw_structured_table(page: fitz.Page, table: dict) -> None:
    """Draw verified cells instead of copying placeholder or polluted source furniture."""
    box = fitz.Rect(table["target_box"])
    cells = table["cells"]
    if not cells or any(len(row) != len(cells[0]) for row in cells):
        raise ValueError(f"invalid structured table cells: {table['id']}")
    rows, columns = len(cells), len(cells[0])
    widths = table.get("column_weights") or [1] * columns
    if len(widths) != columns or any(float(value) <= 0 for value in widths):
        raise ValueError(f"invalid structured table column_weights: {table['id']}")
    total = sum(float(value) for value in widths)
    xs = [box.x0]
    for value in widths:
        xs.append(xs[-1] + box.width * float(value) / total)
    ys = [box.y0 + box.height * row / rows for row in range(rows + 1)]
    page.draw_rect(box, color=BLUE, width=.8)
    for x in xs[1:-1]:
        page.draw_line((x, box.y0), (x, box.y1), color=BLUE, width=.65)
    for y in ys[1:-1]:
        page.draw_line((box.x0, y), (box.x1, y), color=BLUE, width=.65)
    for row, values in enumerate(cells):
        for column, value in enumerate(values):
            rect = fitz.Rect(xs[column] + 2, ys[row] + 2, xs[column + 1] - 2, ys[row + 1] - 2)
            size = float(table.get("font_size", 7.2))
            value = str(value)
            runs = []
            for char in value:
                font = "helv" if char.isascii() else "china-s"
                if runs and runs[-1][0] == font:
                    runs[-1] = (font, runs[-1][1] + char)
                else:
                    runs.append((font, char))
            widths = [fitz.Font(fontname=font).text_length(text, fontsize=size) for font, text in runs]
            total_width = sum(widths)
            if total_width > rect.width:
                size *= rect.width / total_width
                widths = [fitz.Font(fontname=font).text_length(text, fontsize=size) for font, text in runs]
                total_width = sum(widths)
            x = rect.x0 + (rect.width - total_width) / 2
            y = rect.y0 + (rect.height + size * .72) / 2
            for (font, text), width in zip(runs, widths):
                page.insert_text((x, y), text, fontname=font, fontsize=size, color=BLUE)
                x += width


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config_path = args.config.resolve()
    base = config_path.parent
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    if cfg.get("schema_version") != 2:
        raise ValueError("schema_version must be 2")

    source_path = resolve(base, cfg["source"]["path"])
    output_path = resolve(base, cfg["output"]["path"])
    preview_path = resolve(base, cfg["output"].get("preview", "preview.png"))
    layout_path = resolve(base, cfg["output"].get("layout", "layout.json"))
    report_path = resolve(base, cfg["output"].get("report", "build_report.json"))
    assets = {k: str(resolve(base, v)) for k, v in cfg["assets"].items()}
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = fitz.open(source_path)
    page_index = int(cfg["source"].get("page", 1)) - 1
    source_page = source[page_index]
    rotation = int(cfg["source"].get("rotation", 0))
    if rotation:
        source_page.set_rotation(rotation)
    svg = source_page.get_svg_image(text_as_path=True)
    source_rect = source_page.rect

    used_modes = {group.get("color_mode", cfg.get("color_mode", "blue_all")) for group in cfg["groups"]}
    variants: dict[str, fitz.Document] = {}
    svg_docs: list[fitz.Document] = []
    for mode in sorted(used_modes):
        svg_doc = fitz.open(stream=recolor(svg, mode).encode("utf-8"), filetype="svg")
        svg_docs.append(svg_doc)
        variants[mode] = fitz.open("pdf", svg_doc.convert_to_pdf())

    out = fitz.open()
    page = out.new_page(width=PAGE[0], height=PAGE[1])
    page.insert_image(page.rect, filename=assets["background"])

    placements = []
    for group in cfg["groups"]:
        src_rect = fitz.Rect(group["src"])
        if not source_rect.contains(src_rect):
            raise ValueError(f"source box outside page: {group['id']}")
        dest, scale = target_rect(group)
        mode = group.get("color_mode", cfg.get("color_mode", "blue_all"))
        page.show_pdf_page(dest, variants[mode], 0, clip=src_rect)
        placements.append({
            "id": group["id"], "assembly": group.get("assembly", group["id"]),
            "kind": group.get("kind", "view"), "source_box": list(src_rect),
            "target_box": list(dest), "scale": scale, "color_mode": mode,
            "inventory_ids": group.get("inventory_ids", []),
        })

    for table in cfg.get("structured_tables", []):
        draw_structured_table(page, table)
        src = fitz.Rect(table["src"])
        target = fitz.Rect(table["target_box"])
        placements.append({
            "id": table["id"], "assembly": table.get("assembly", table["id"]),
            "kind": "table", "source_box": list(src), "target_box": list(target),
            "scale": 1.0, "color_mode": "structured",
            "inventory_ids": table.get("inventory_ids", [table["id"]]),
            "rows": len(table["cells"]), "columns": len(table["cells"][0]),
        })

    draw_frame_and_title(page, cfg["fields"], assets)

    out.set_metadata({"title": cfg["fields"]["model"] + " | 候选修复",
                      "subject": "Source-preserving vector layout; pending independent review."})
    if output_path.exists():
        output_path.unlink()
    out.save(output_path, garbage=4, deflate=True, deflate_fonts=True,
             deflate_images=True, use_objstms=1, compression_effort=100)
    page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(preview_path)

    inventory_path = resolve(base, cfg["inventory"])
    layout = {
        "schema_version": 2, "source_path": str(source_path), "source_sha256": sha256(source_path),
        "source_page": page_index + 1, "source_rotation": rotation,
        "output_path": str(output_path), "output_sha256": sha256(output_path),
        "inventory_path": str(inventory_path), "inventory_sha256": sha256(inventory_path),
        "page_box": [0, 0, PAGE[0], PAGE[1]], "frame_box": FRAME,
        "reserved_regions": TITLE_RESERVED,
        "quality": cfg.get("quality", {}), "groups": placements,
        "technical_fields": cfg["fields"],
    }
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(json.dumps({
        "ok": True, "output": str(output_path), "bytes": output_path.stat().st_size,
        "source_sha256": layout["source_sha256"], "output_sha256": layout["output_sha256"],
        "font": "PyMuPDF built-in china-s (Droid Sans Fallback)", "font_bytes": 0,
        "variant_count": len(variants), "placement_count": len(placements),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    for doc in variants.values(): doc.close()
    for doc in svg_docs: doc.close()
    source.close(); out.close()
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
