#!/usr/bin/env python3
"""Create schema-v2 placements from an inventory using deterministic packing.

The program does not inspect pixels and does not call a model. Ambiguous source
grouping remains an explicit inventory task; placement after that point is
repeatable and token-free.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def area(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def intersects(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def contains(a, b):
    return a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]


def prune(rects):
    good = [r for r in rects if area(r) > 4]
    return [r for i, r in enumerate(good)
            if not any(i != j and contains(other, r) for j, other in enumerate(good))]


def split_free(rects, used):
    result = []
    for free in rects:
        if not intersects(free, used):
            result.append(free); continue
        if used[0] > free[0]: result.append([free[0], free[1], used[0], free[3]])
        if used[2] < free[2]: result.append([used[2], free[1], free[2], free[3]])
        if used[1] > free[1]: result.append([free[0], free[1], free[2], used[1]])
        if used[3] < free[3]: result.append([free[0], used[3], free[2], free[3]])
    return prune(result)


def anchor_score(kind, placed, canvas):
    x0, y0, x1, y1 = placed
    left, top, right, bottom = canvas
    if kind in {"performance", "specification"}:
        return abs(x1 - right) * 5 + abs(y0 - top) * 2
    if kind == "pcb":
        return abs(x1 - right) * 5 + abs(y1 - bottom) * 2
    if kind == "table":
        return abs(x0 - left) * 5 + abs(y1 - bottom) * 2
    if kind == "isometric":
        return abs((x0 + x1) / 2 - (left + right) / 2) + abs(y0 - top)
    return abs(x0 - left) + abs(y0 - top)


def candidates(free, width, height, kind, canvas):
    result = []
    for rect in free:
        if rect[2] - rect[0] + 1e-6 < width or rect[3] - rect[1] + 1e-6 < height:
            continue
        points = [(rect[0], rect[1]), (rect[2] - width, rect[1]),
                  (rect[0], rect[3] - height), (rect[2] - width, rect[3] - height)]
        for x, y in points:
            used = [x, y, x + width, y + height]
            waste = area(rect) - width * height
            result.append((anchor_score(kind, used, canvas) + waste * .0005, used))
    return sorted(result, key=lambda value: value[0])


def pack(items, canvas, gap, scale):
    free = [list(canvas)]
    placed = {}
    # Semantic anchors first; remaining views follow by decreasing area.
    order = sorted(items, key=lambda item: (
        {"table": 0, "pcb": 1, "performance": 2, "specification": 2}.get(item["kind"], 3),
        -item["width"] * item["height"], item["order"]))
    for item in order:
        if item["kind"] == "table":
            item_scale = 1.0
            width, height = item["width"], item["height"]
        else:
            item_scale = min(scale, float(item.get("maximum_scale", scale)))
            width, height = item["width"] * item_scale, item["height"] * item_scale
        options = candidates(free, width + gap, height + gap, item["kind"], canvas)
        if not options:
            return None
        padded = options[0][1]
        used = [padded[0], padded[1], padded[2] - gap, padded[3] - gap]
        placed[item["id"]] = {"box": used, "scale": item_scale}
        free = split_free(free, padded)
    return placed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    job_path = args.job.resolve()
    base = job_path.parent
    job = json.loads(job_path.read_text(encoding="utf-8"))
    inventory_path = (base / job["inventory"]).resolve()
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    settings = job.get("layout", {})
    canvas = settings.get("canvas", [30, 36, 810, 444])
    gap = float(settings.get("gap", 12))
    min_scale = float(settings.get("minimum_scale", .72))
    max_scale = float(settings.get("maximum_scale", 1.3))
    items = []
    for order, group in enumerate(inventory["groups"]):
        regions = group.get("regions") or [group["region"]]
        if len(regions) != 1:
            raise ValueError(f"group {group['id']} needs one enclosing region for auto layout")
        src = regions[0]
        kind = group.get("kind", "view")
        if kind == "table":
            cells = group.get("cells")
            if not cells:
                raise ValueError(f"table cells missing: {group['id']}")
            width = float(group.get("target_width", 420))
            height = float(group.get("row_height", 22)) * len(cells)
        else:
            width, height = src[2] - src[0], src[3] - src[1]
        items.append({"id": group["id"], "kind": kind, "src": src,
                      "width": width, "height": height, "order": order, "raw": group,
                      "maximum_scale": group.get("maximum_scale", max_scale)})
    placements = None
    scale = max_scale
    while scale + 1e-9 >= min_scale:
        placements = pack(items, canvas, gap, scale)
        if placements:
            break
        scale = round(scale - .02, 4)
    if not placements:
        raise SystemExit("layout failed: no placement at or above minimum_scale")
    groups, tables = [], []
    for item in items:
        placement = placements[item["id"]]
        target, item_scale = placement["box"], placement["scale"]
        raw = item["raw"]
        common = {"id": item["id"], "src": item["src"], "kind": item["kind"],
                  "assembly": raw.get("assembly", item["id"]),
                  "inventory_ids": [item["id"]]}
        if item["kind"] == "table":
            common.update({"target_box": target, "cells": raw["cells"],
                           "column_weights": raw.get("column_weights"),
                           "font_size": raw.get("font_size", 7.2)})
            tables.append(common)
        else:
            common.update({"dst": target[:2], "scale": item_scale,
                           "color_mode": raw.get("color_mode", job.get("color_mode", "blue_all"))})
            groups.append(common)
    output = dict(job)
    output.pop("layout", None)
    output["schema_version"] = 2
    output["groups"] = groups
    output["structured_tables"] = tables
    output["quality"] = {**job.get("quality", {}), "minimum_scale": min_scale,
                         "minimum_group_gap": gap - .1, "reserved_clearance": 3,
                         "minimum_horizontal_span": .65, "minimum_vertical_span": .55,
                         "selected_uniform_view_scale": scale}
    target = (args.output or job_path.with_name("candidate_config.json")).resolve()
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "config": str(target), "uniform_view_scale": scale,
                      "placements": placements}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
