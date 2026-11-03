"""Build a reproducible traffic-light crop benchmark from the local BSTLD copy.

The downloaded archive is a partial BSTLD mirror.  Its labelled split has 105
files, and only one source image contains an active yellow box.  Red and green
use distinct real source images.  Yellow is deterministically augmented and
the manifest records ``origin=augmented`` so these variants are never reported
as independent real photographs.
"""

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "datasets" / "bstld"
DEFAULT_CROPS = ROOT / "datasets" / "bstld_crops"
DEFAULT_METRICS = ROOT / "docs" / "report" / "metrics"

LABEL_MAP = {
    "Red": "RED",
    "RedLeft": "RED",
    "RedRight": "RED",
    "RedStraight": "RED",
    "RedStraightLeft": "RED",
    "RedStraightRight": "RED",
    "Green": "GREEN",
    "GreenLeft": "GREEN",
    "GreenRight": "GREEN",
    "GreenStraight": "GREEN",
    "GreenStraightLeft": "GREEN",
    "GreenStraightRight": "GREEN",
    "Yellow": "YELLOW",
}


def _image_index(split_root):
    index = defaultdict(list)
    for path in split_root.rglob("*.png"):
        index[path.name].append(path)
    return index


def _load_rows(dataset):
    import yaml

    rows = []
    for split in ("train", "test"):
        yaml_path = dataset / (split + ".yaml")
        if not yaml_path.exists():
            continue
        index = _image_index(dataset / "rgb" / split)
        for row in yaml.safe_load(yaml_path.read_text(encoding="utf-8")):
            matches = index.get(Path(row["path"]).name, [])
            if not matches:
                continue
            row = dict(row)
            row["split"] = split
            row["image_path"] = sorted(matches)[0]
            rows.append(row)
    return rows


def _spread(items, count):
    if len(items) <= count:
        return list(items)
    if count == 1:
        return [items[len(items) // 2]]
    indices = [
        int(round(i * (len(items) - 1) / float(count - 1)))
        for i in range(count)
    ]
    return [items[i] for i in indices]


def _collect_candidates(rows):
    by_key = {}
    for row in rows:
        if row["split"] != "train":
            continue
        boxes = row.get("boxes") or []
        for box in boxes:
            label = LABEL_MAP.get(box.get("label"))
            if label is None or box.get("occluded"):
                continue
            x0 = float(box["x_min"])
            y0 = float(box["y_min"])
            x1 = float(box["x_max"])
            y1 = float(box["y_max"])
            if x1 <= x0 or y1 <= y0:
                continue
            key = (row["image_path"], label)
            candidate = {
                "label": label,
                "row": row,
                "box": (x0, y0, x1, y1),
                "area": (x1 - x0) * (y1 - y0),
            }
            old = by_key.get(key)
            if old is None or candidate["area"] > old["area"]:
                by_key[key] = candidate
    grouped = defaultdict(list)
    for candidate in by_key.values():
        grouped[candidate["label"]].append(candidate)
    for label in grouped:
        grouped[label].sort(
            key=lambda item: (
                str(item["row"]["image_path"]),
                item["box"][1],
                item["box"][0],
            )
        )
    return grouped


def _mask_other_lights(image, row, target_box, offset_x, offset_y):
    import cv2

    h, w = image.shape[:2]
    x0, y0, x1, y1 = target_box
    for box in row.get("boxes") or []:
        if LABEL_MAP.get(box.get("label")) is None:
            continue
        bx0 = float(box["x_min"])
        by0 = float(box["y_min"])
        bx1 = float(box["x_max"])
        by1 = float(box["y_max"])
        if abs(bx0 - x0) < 1.0 and abs(by0 - y0) < 1.0:
            continue
        if bx1 < 0 or by1 < 0 or bx0 >= w or by0 >= h:
            continue
        cv2.rectangle(
            image,
            (max(0, int(bx0) - offset_x - 2),
             max(0, int(by0) - offset_y - 2)),
            (min(w - 1, int(bx1) - offset_x + 2),
             min(h - 1, int(by1) - offset_y + 2)),
            (0, 0, 0),
            thickness=-1,
        )
    return image


def _make_crop(candidate, pad_fraction=0.35, min_side=96):
    import cv2

    row = candidate["row"]
    image = cv2.imread(str(row["image_path"]))
    if image is None:
        raise RuntimeError("cannot read %s" % row["image_path"])
    h, w = image.shape[:2]
    x0, y0, x1, y1 = candidate["box"]
    bw, bh = x1 - x0, y1 - y0
    cx0 = max(0, int(round(x0 - pad_fraction * bw)))
    cy0 = max(0, int(round(y0 - pad_fraction * bh)))
    cx1 = min(w, int(round(x1 + pad_fraction * bw)))
    cy1 = min(h, int(round(y1 + pad_fraction * bh)))
    crop = image[cy0:cy1, cx0:cx1].copy()
    crop = _mask_other_lights(crop, row, candidate["box"], cx0, cy0)
    ch, cw = crop.shape[:2]
    if min(ch, cw) < min_side:
        scale = min_side / float(min(ch, cw))
        crop = cv2.resize(
            crop,
            (max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))),
            interpolation=cv2.INTER_CUBIC,
        )
    return crop


def _yellow_variant(image, index):
    import cv2
    import numpy as np

    brightness_values = (0.78, 0.90, 1.0, 1.10, 1.22)
    blur_values = (0.0, 0.6, 1.0, 1.4, 1.8)
    brightness = brightness_values[index % len(brightness_values)]
    sigma = blur_values[(index // len(brightness_values)) % len(blur_values)]
    out = np.clip(image.astype(np.float32) * brightness, 0, 255).astype(np.uint8)
    if sigma > 0:
        out = cv2.GaussianBlur(out, (0, 0), sigmaX=sigma, sigmaY=sigma)
    return out, "brightness=%.2f;blur_sigma=%.1f" % (brightness, sigma)


def _write_image(path, image):
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise RuntimeError("cannot write %s" % path)


def _record(crop_root, path, label, split, origin, source_id,
            condition, augmentation="", box=None):
    return {
        "path": path.relative_to(crop_root).as_posix(),
        "label": label,
        "split": split,
        "origin": origin,
        "source_id": source_id,
        "condition": condition,
        "augmentation": augmentation,
        "box_x_min": "" if box is None else "%.3f" % box[0],
        "box_y_min": "" if box is None else "%.3f" % box[1],
        "box_x_max": "" if box is None else "%.3f" % box[2],
        "box_y_max": "" if box is None else "%.3f" % box[3],
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def build(dataset, crop_root, metrics_dir):
    rows = _load_rows(dataset)
    grouped = _collect_candidates(rows)
    crop_root.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)

    records = []
    selected_counts = {}
    for label in ("RED", "GREEN"):
        selected = _spread(grouped.get(label, []), 25)
        if len(selected) < 25:
            raise RuntimeError(
                "%s has %d usable sources, need 25" % (label, len(selected))
            )
        selected_counts[label] = len(selected)
        for index, candidate in enumerate(selected):
            split = "tune" if index < 15 else "test"
            image = _make_crop(candidate)
            source_id = "%s/%s" % (
                candidate["row"]["split"], candidate["row"]["image_path"].name
            )
            path = crop_root / "crops" / label.lower() / (
                "%s_%s_%03d.png" % (label.lower(), split, index)
            )
            _write_image(path, image)
            records.append(
                _record(
                    crop_root,
                    path,
                    label,
                    split,
                    "real",
                    source_id,
                    "close_crop",
                    box=candidate["box"],
                )
            )

    yellow_sources = grouped.get("YELLOW", [])
    if not yellow_sources:
        raise RuntimeError("no active yellow source box found")
    selected_counts["YELLOW"] = len(yellow_sources)
    yellow = _make_crop(yellow_sources[0])
    source_id = "train/%s" % yellow_sources[0]["row"]["image_path"].name
    for index in range(25):
        if index == 0:
            image = yellow
            origin = "real"
            augmentation = ""
        else:
            image, augmentation = _yellow_variant(yellow, index - 1)
            origin = "augmented"
        split = "test" if index == 0 or index >= 16 else "tune"
        path = crop_root / "crops" / "yellow" / (
            "yellow_%s_%03d_%s.png" % (split, index, origin)
        )
        _write_image(path, image)
        records.append(
            _record(
                crop_root,
                path,
                "YELLOW",
                split,
                origin,
                source_id,
                "close_crop",
                augmentation,
                yellow_sources[0]["box"],
            )
        )

    none_rows = [row for row in rows if row["split"] == "test" and not row.get("boxes")]
    none_rows.sort(key=lambda row: str(row["image_path"]))
    selected_none = _spread(none_rows, 25)
    if len(selected_none) < 25:
        raise RuntimeError("NONE has %d frames, need 25" % len(selected_none))
    selected_counts["NONE"] = len(selected_none)
    for index, row in enumerate(selected_none):
        import cv2

        image = cv2.imread(str(row["image_path"]))
        if image is None:
            raise RuntimeError("cannot read %s" % row["image_path"])
        image = cv2.resize(image, (320, 240), interpolation=cv2.INTER_AREA)
        split = "tune" if index < 15 else "test"
        path = crop_root / "crops" / "none" / (
            "none_%s_%03d.png" % (split, index)
        )
        _write_image(path, image)
        records.append(
            _record(
                crop_root,
                path,
                "NONE",
                split,
                "real",
                "test/%s" % row["image_path"].name,
                "full_frame_no_active_light",
            )
        )

    fieldnames = [
        "path",
        "label",
        "split",
        "origin",
        "source_id",
        "condition",
        "augmentation",
        "box_x_min",
        "box_y_min",
        "box_x_max",
        "box_y_max",
        "sha256",
    ]
    for split in ("tune", "test"):
        manifest = metrics_dir / ("manifest_bstld_%s.csv" % split)
        subset = sorted(
            (record for record in records if record["split"] == split),
            key=lambda record: (record["label"], record["path"]),
        )
        with manifest.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(subset)

    summary = {
        "dataset_rows_mapped": len(rows),
        "candidate_source_images": {
            label: len(items) for label, items in sorted(grouped.items())
        },
        "selected_real_yellow_sources": selected_counts.get("YELLOW", 0),
        "samples": len(records),
        "samples_by_split": dict(Counter(row["split"] for row in records)),
        "samples_by_label": dict(Counter(row["label"] for row in records)),
        "samples_by_origin": dict(Counter(row["origin"] for row in records)),
        "limitations": [
            "The local BSTLD mirror contains 105 labelled training frames and "
            "114 unlabelled/no-active-light test frames, not the full dataset.",
            "Only one active yellow source box is present; 24 of 25 yellow "
            "samples are deterministic variants of that same source.",
            "Yellow held-out samples share their source with tuning variants, "
            "so yellow accuracy must not be described as independent.",
        ],
        "crop_policy": (
            "Tight target crop with 35% padding on each side; other labelled "
            "traffic lights are masked; minimum side is upscaled to 96 px."
        ),
    }
    summary_path = metrics_dir / "bstld_subset_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda row: row["path"]):
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("ascii"))
        digest.update(b"\0")
    summary["manifest_digest"] = digest.hexdigest()
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--crops", type=Path, default=DEFAULT_CROPS)
    parser.add_argument("--metrics-dir", type=Path, default=DEFAULT_METRICS)
    args = parser.parse_args()
    build(args.dataset, args.crops, args.metrics_dir)


if __name__ == "__main__":
    main()
