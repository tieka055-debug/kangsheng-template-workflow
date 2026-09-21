#!/usr/bin/env python3
"""Deterministic pre-review checks for a schema-v2 candidate layout.

This catches clipping, collision, detached assembly transforms, unplaced
inventory regions and obviously unbalanced use of the sheet. It intentionally
does not mark engineering or visual review as passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def intersection(a, b):
    box = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
    return box if area(box) > 0 else None


def gap(a, b) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0)
    dy = max(a[1] - b[3], b[1] - a[3], 0)
    return math.hypot(dx, dy)


def union_covered_area(region, boxes) -> float:
    """Exact rectangle-union area inside region using an x sweep."""
    clips = [intersection(region, box) for box in boxes]
    clips = [box for box in clips if box]
    xs = sorted({region[0], region[2], *[v for box in clips for v in (box[0], box[2])]})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        intervals = sorted((box[1], box[3]) for box in clips if box[0] < right and box[2] > left)
        if not intervals:
            continue
        merged = 0.0
        lo, hi = intervals[0]
        for y0, y1 in intervals[1:]:
            if y0 <= hi:
                hi = max(hi, y1)
            else:
                merged += hi - lo; lo, hi = y0, y1
        merged += hi - lo
        total += (right - left) * merged
    return total


def validate(layout: dict, inventory: dict) -> list[str]:
    errors = []
    groups = layout.get("groups") or []
    frame = layout.get("frame_box", [22, 29, 820, 564])
    quality = layout.get("quality") or {}
    minimum_scale = float(quality.get("minimum_scale", .75))
    minimum_gap = float(quality.get("minimum_group_gap", 0))
    reserved_clearance = float(quality.get("reserved_clearance", 0))

    ids = [g.get("id") for g in groups]
    if len(ids) != len(set(ids)):
        errors.append("duplicate placement id")

    for group in groups:
        target = group["target_box"]
        if target[0] < frame[0] or target[1] < frame[1] or target[2] > frame[2] or target[3] > frame[3]:
            errors.append(f"target outside drawing frame: {group['id']}")
        if float(group.get("scale", 0)) < minimum_scale:
            errors.append(f"scale below minimum: {group['id']}")
        for reserved in layout.get("reserved_regions", []):
            box = reserved["box"]
            expanded = [box[0] - reserved_clearance, box[1] - reserved_clearance,
                        box[2] + reserved_clearance, box[3] + reserved_clearance]
            if intersection(target, expanded):
                errors.append(f"reserved-region collision: {group['id']} / {reserved['id']}")

    for i, left in enumerate(groups):
        for right in groups[i + 1:]:
            if left.get("assembly") == right.get("assembly"):
                continue
            if intersection(left["target_box"], right["target_box"]):
                errors.append(f"target overlap: {left['id']} / {right['id']}")
            elif minimum_gap and gap(left["target_box"], right["target_box"]) < minimum_gap:
                errors.append(f"target gap below {minimum_gap:g}: {left['id']} / {right['id']}")

    assemblies = {}
    for group in groups:
        assemblies.setdefault(group.get("assembly", group["id"]), []).append(group)
    for name, members in assemblies.items():
        if len(members) < 2:
            continue
        transforms = []
        for member in members:
            scale = float(member["scale"])
            src, target = member["source_box"], member["target_box"]
            transforms.append((scale, target[0] - src[0] * scale, target[1] - src[1] * scale))
        if any(max(abs(a - b) for a, b in zip(transforms[0], value)) > .05 for value in transforms[1:]):
            errors.append(f"detached assembly transform: {name}")

    source_boxes = [g["source_box"] for g in groups]
    for item in inventory.get("groups", []):
        regions = item.get("regions") or ([item["region"]] if "region" in item else [])
        if not regions:
            errors.append(f"inventory region missing: {item.get('id')}")
        for region in regions:
            expected = area(region)
            covered = union_covered_area(region, source_boxes)
            if expected <= 0 or covered + .01 < expected:
                errors.append(f"inventory region not fully placed: {item.get('id')}")

    for table in inventory.get("tables", []):
        rows = table.get("cells")
        total_rows, columns = table.get("total_rows"), table.get("columns")
        if not isinstance(rows, list) or len(rows) != total_rows or any(not isinstance(r, list) or len(r) != columns for r in rows):
            errors.append(f"invalid table inventory: {table.get('id')}")
        if table.get("data_rows") != total_rows - 1:
            errors.append(f"table data/total row mismatch: {table.get('id')}")

    if groups:
        targets = [g["target_box"] for g in groups]
        span_x = (max(b[2] for b in targets) - min(b[0] for b in targets)) / (frame[2] - frame[0])
        span_y = (max(b[3] for b in targets) - min(b[1] for b in targets)) / (frame[3] - frame[1])
        if span_x < float(quality.get("minimum_horizontal_span", 0)):
            errors.append(f"horizontal content span too small: {span_x:.3f}")
        if span_y < float(quality.get("minimum_vertical_span", 0)):
            errors.append(f"vertical content span too small: {span_y:.3f}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("layout", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    layout_path = args.layout.resolve()
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    inventory_path = Path(layout["inventory_path"])
    result_errors = []
    if sha256(inventory_path) != layout.get("inventory_sha256"):
        result_errors.append("inventory hash mismatch")
    if sha256(Path(layout["output_path"])) != layout.get("output_sha256"):
        result_errors.append("output hash mismatch")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if inventory.get("source_sha256") != layout.get("source_sha256"):
        result_errors.append("inventory/source hash mismatch")
    result_errors.extend(validate(layout, inventory))
    result = {"ok": not result_errors, "errors": result_errors,
              "notice": "Deterministic layout/inventory coverage only; independent visual and numeric review still required."}
    target = args.output or layout_path.with_name("layout_check.json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
