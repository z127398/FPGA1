"""Select a diverse TuSimple subset and render a manual-labelling contact sheet.

TuSimple's official labels contain lane geometry but no SOLID/DASHED class.
This tool only proposes frames with one visible boundary on each side of the
image centre.  The final left/right material labels remain a manual review
step and are stored in a separate manifest.
"""

import argparse
import csv
import json
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "datasets" / "tusimple" / "TuSimple-Road"
DEFAULT_OUTPUT = ROOT / "datasets" / "tusimple_subset"
DEFAULT_INDEX = ROOT / "docs" / "report" / "metrics" / "tusimple_candidates.csv"


def _load_records(dataset):
    labels = dataset / "train_set" / "updated_labels.json"
    image_root = dataset / "train_set" / "tusimple_clips"
    index = {path.name: path for path in image_root.rglob("*.jpg")}
    records = []
    with labels.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            name = Path(record["raw_file"]).name
            image_path = index.get(name)
            if image_path is None:
                continue
            record["image_path"] = image_path
            records.append(record)
    return records


def _lane_at_height(xs, hs, target_h):
    valid = [(int(h), int(x)) for h, x in zip(hs, xs) if int(x) >= 0]
    if not valid:
        return None, 0
    h, x = min(valid, key=lambda item: abs(item[0] - target_h))
    if abs(h - target_h) > 20:
        return None, len(valid)
    return x, len(valid)


def _boundaries(record, width, center_tolerance=35):
    hs = record["h_samples"]
    target_h = max(hs)
    lanes = []
    for lane_id, xs in enumerate(record.get("lanes") or []):
        x, support = _lane_at_height(xs, hs, target_h)
        if x is not None and support >= 12 and 40 <= x <= width - 40:
            lanes.append((x, lane_id))
    lanes.sort()
    centre = width * 0.5
    left = max((item for item in lanes if item[0] < centre - center_tolerance),
               default=None)
    right = min((item for item in lanes if item[0] > centre + center_tolerance),
                default=None)
    return left, right, lanes


def _select(records, count):
    groups = OrderedDict()
    for record in records:
        image_path = record["image_path"]
        image = cv2.imread(str(image_path))
        if image is None:
            continue
        h, w = image.shape[:2]
        left, right, lanes = _boundaries(record, w)
        if left is None or right is None:
            continue
        centre = w * 0.5
        penalty = abs(left[0] - centre * 0.55) + abs(right[0] - centre * 1.45)
        clip = Path(record["raw_file"]).name.split("_", 1)[0]
        candidate = {
            "record": record,
            "image_path": image_path,
            "width": w,
            "height": h,
            "left_x": left[0],
            "right_x": right[0],
            "left_lane_id": left[1],
            "right_lane_id": right[1],
            "lanes": lanes,
            "penalty": penalty,
        }
        groups.setdefault(clip, []).append(candidate)

    for clip in groups:
        groups[clip].sort(
            key=lambda item: (item["penalty"], item["record"]["raw_file"])
        )
    selected = []
    depth = 0
    clip_order = sorted(groups)
    while len(selected) < count:
        added = False
        for clip in clip_order:
            if depth < len(groups[clip]):
                selected.append(groups[clip][depth])
                added = True
                if len(selected) == count:
                    break
        if not added:
            break
        depth += 1
    if len(selected) < count:
        raise RuntimeError(
            "only %d usable frames found, requested %d" % (len(selected), count)
        )
    return selected


def _draw_candidate(candidate, index):
    image = cv2.imread(str(candidate["image_path"]))
    hs = candidate["record"]["h_samples"]
    highlights = {
        candidate["left_lane_id"]: (255, 255, 0),
        candidate["right_lane_id"]: (255, 0, 255),
    }
    for lane_id, xs in enumerate(candidate["record"].get("lanes") or []):
        points = [
            (int(x), int(h))
            for h, x in zip(hs, xs)
            if int(x) >= 0
        ]
        if len(points) < 2:
            continue
        color = highlights.get(lane_id, (0, 255, 0))
        thickness = 4 if lane_id in highlights else 2
        cv2.polylines(image, [np.asarray(points)], False, color, thickness)
    crop = image[240:720]
    crop = cv2.resize(crop, (400, 150), interpolation=cv2.INTER_AREA)
    cv2.rectangle(crop, (0, 0), (399, 20), (0, 0, 0), -1)
    cv2.putText(
        crop,
        "%02d L=%d R=%d" % (
            index,
            candidate["left_x"],
            candidate["right_x"],
        ),
        (5, 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return crop


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument(
        "--indices",
        help="optional comma-separated candidate IDs from a larger selection",
    )
    args = parser.parse_args()

    records = _load_records(args.dataset)
    indices = None
    if args.indices:
        indices = [int(value) for value in args.indices.split(",") if value.strip()]
        selection_count = max(indices) + 1
    else:
        selection_count = args.count
    candidates = _select(records, selection_count)
    if indices is None:
        entries = list(enumerate(candidates))
    else:
        entries = [(index, candidates[index]) for index in indices]

    args.output.mkdir(parents=True, exist_ok=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    crops = []
    for index, candidate in entries:
        target = args.output / ("frame_%02d.jpg" % index)
        image = cv2.imread(str(candidate["image_path"]))
        if not cv2.imwrite(str(target), image):
            raise RuntimeError("cannot write %s" % target)
        rows.append(
            {
                "path": target.relative_to(ROOT / "datasets").as_posix(),
                "source_name": candidate["image_path"].name,
                "left_boundary_x": candidate["left_x"],
                "right_boundary_x": candidate["right_x"],
            }
        )
        crops.append(_draw_candidate(candidate, index))

    with args.index.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    columns = 5
    blank = np.zeros_like(crops[0])
    while len(crops) % columns:
        crops.append(blank)
    rows_img = [
        np.hstack(crops[i:i + columns])
        for i in range(0, len(crops), columns)
    ]
    sheet = np.vstack(rows_img)
    sheet_path = args.output / "contact_sheet.png"
    cv2.imwrite(str(sheet_path), sheet)
    print("selected", len(entries))
    print("index", args.index)
    print("contact sheet", sheet_path)


if __name__ == "__main__":
    main()
