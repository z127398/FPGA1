"""Collect SOLID and DASHED feature distributions from the live camera."""

import json
import time
from pathlib import Path

import cv2
import numpy as np

import config
from decision import DecisionEngine
from osd import compose, to_lcd
from overlay import AdasOverlay
from perception import PerceptionPipeline


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "lane_type_tuning"


def _step(adas, pipe, engine, index):
    frame = adas.video_in.readframe()
    bgr = cv2.resize(
        frame, adas.proc_size, interpolation=cv2.INTER_NEAREST
    )
    result = pipe.process(bgr, index)
    decision = engine.step(result, adas.read_btns())
    adas.write_dec(
        decision.tl_state, decision.lane_left, decision.lane_right,
        decision.obstacle, decision.force, decision.turn,
        feed_heartbeat=True,
    )
    status = adas.read_status()
    out = compose(
        bgr, result, decision, status, adas.fps, mode="lane",
        heartbeat_source="FRAME",
    )
    adas.video_out.writeframe(to_lcd(out))
    return bgr, result, decision, status, out


def _prompt(adas, pipe, engine, index, text, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        _, _, _, _, out = _step(adas, pipe, engine, index)
        index += 1
        cv2.rectangle(out, (0, 86), (out.shape[1], 142), (0, 0, 0), -1)
        cv2.putText(
            out, text, (20, 122), cv2.FONT_HERSHEY_SIMPLEX,
            0.66, (0, 255, 255), 2, cv2.LINE_AA,
        )
        adas.video_out.writeframe(to_lcd(out))
        time.sleep(0.04)
    return index


def _collect(adas, pipe, engine, index, label, target, max_samples=12):
    folder = OUT / label.lower()
    folder.mkdir(parents=True, exist_ok=True)
    index = _prompt(
        adas, pipe, engine, index,
        "TUNING: SHOW %s CARD CENTERED" % label, 12.0,
    )
    rows = []
    last = None
    started = time.time()
    while time.time() - started < 25.0 and len(rows) < max_samples:
        frame_index = index
        sample = _step(adas, pipe, engine, index)
        index += 1
        last = sample
        lanes = sample[1].lanes
        if frame_index % config.LANE_EVERY_N != 0:
            continue
        if lanes.left_state == "NONE" and lanes.right_state == "NONE":
            continue
        rows.append({
            "left": lanes.left_state,
            "right": lanes.right_state,
            "coverage_left": lanes.coverage_left,
            "coverage_right": lanes.coverage_right,
            "max_gap_left": lanes.max_gap_left,
            "max_gap_right": lanes.max_gap_right,
            "gap_runs_left": lanes.gap_runs_left,
            "gap_runs_right": lanes.gap_runs_right,
        })
    if last is None:
        raise RuntimeError("no frame captured for %s" % label)
    bgr, result, decision, status, osd = last
    fps = len(rows) / max(time.time() - started, 1e-6)
    osd = compose(
        bgr, result, decision, status, fps, mode="lane",
        heartbeat_source="FRAME",
    )
    cv2.imwrite(str(folder / "raw.png"), bgr)
    cv2.imwrite(str(folder / "osd.png"), osd)
    payload = {
        "target": target,
        "fps": fps,
        "samples": rows,
        "classified": {
            "%s/%s" % (row["left"], row["right"]): sum(
                1 for candidate in rows
                if candidate["left"] == row["left"] and
                candidate["right"] == row["right"]
            )
            for row in rows
        },
    }
    (folder / "features.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return index, payload


def main():
    adas = AdasOverlay()
    pipe = PerceptionPipeline(mode="lane")
    engine = DecisionEngine(mode="lane")
    summary = {"ok": False}
    index = 0
    try:
        adas.start()
        adas._set_heartbeat_mode("frame")
        index, summary["solid"] = _collect(
            adas, pipe, engine, index, "SOLID", "SOLID"
        )
        pipe.reset()
        index, summary["dashed"] = _collect(
            adas, pipe, engine, index, "DASHED", "DASHED"
        )
        summary["ok"] = True
        return 0
    finally:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
