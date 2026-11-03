"""Guided board test for BEV lane geometry and departure alert."""

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from decision import DecisionEngine
from osd import compose, to_lcd
from overlay import AdasOverlay
from perception import PerceptionPipeline


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "lane_geometry"


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
        bgr, result, decision, status, out = _step(
            adas, pipe, engine, index
        )
        cv2.rectangle(out, (0, 86), (out.shape[1], 142), (0, 0, 0), -1)
        cv2.putText(
            out, text, (20, 122), cv2.FONT_HERSHEY_SIMPLEX,
            0.68, (0, 255, 255), 2, cv2.LINE_AA,
        )
        adas.video_out.writeframe(to_lcd(out))
        index += 1
        time.sleep(0.05)
    return index


def _save(name, sample, fps=None):
    bgr, result, decision, status, out = sample
    if fps is not None:
        out = compose(
            bgr, result, decision, status, fps, mode="lane",
            heartbeat_source="FRAME",
        )
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(folder / "osd.png"), out)
    if result.lanes.bev is not None:
        cv2.imwrite(str(folder / "bev.png"), result.lanes.bev)
    payload = {
        "fps": fps,
        "left": result.lanes.left_state,
        "right": result.lanes.right_state,
        "coverage_left": result.lanes.coverage_left,
        "coverage_right": result.lanes.coverage_right,
        "max_gap_left": result.lanes.max_gap_left,
        "max_gap_right": result.lanes.max_gap_right,
        "gap_runs_left": result.lanes.gap_runs_left,
        "gap_runs_right": result.lanes.gap_runs_right,
        "center_offset": result.lanes.center_offset,
        "curvature": result.lanes.curvature,
        "departure": result.lanes.departure,
        "left_curve": result.lanes.left_curve,
        "right_curve": result.lanes.right_curve,
        "decision": decision.as_dict(),
        "status": status,
    }
    (folder / "status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def _same_lane_state(sample, state):
    lanes = sample[1].lanes
    return (
        lanes.left_state == state and
        lanes.right_state == state and
        lanes.left_curve is not None and
        lanes.right_curve is not None
    )


def main():
    target = sys.argv[1].upper() if len(sys.argv) > 1 else "AUTO"
    if target not in ("AUTO", "SOLID", "DASHED"):
        raise SystemExit("target must be AUTO, SOLID or DASHED")
    adas = AdasOverlay()
    pipe = PerceptionPipeline(mode="lane")
    engine = DecisionEngine(mode="lane")
    result = {"ok": False}
    index = 0
    try:
        adas.start()
        adas._set_heartbeat_mode("frame")
        index = _prompt(
            adas, pipe, engine, index,
            "LANE GEOMETRY: CENTER %s CARD" % (
                "LANE" if target == "AUTO" else target
            ), 15.0,
        )
        centered = None
        last_centered = None
        stable = 0
        centered_started = time.time()
        centered_count = 0
        deadline = time.time() + 15.0
        while time.time() < deadline:
            sample = _step(adas, pipe, engine, index)
            index += 1
            centered_count += 1
            last_centered = sample
            lanes = sample[1].lanes
            accepted = (
                lanes.left_state in ("SOLID", "DASHED")
                if target == "AUTO" else lanes.left_state == target
            )
            if (accepted and
                    lanes.right_state == lanes.left_state and
                    lanes.left_curve is not None and
                    lanes.right_curve is not None and
                    not lanes.departure):
                stable += 1
                if stable >= 3:
                    centered = sample
                    break
            else:
                stable = 0
        if centered is None:
            if last_centered is not None:
                result["failed_centered"] = _save(
                    "failed_centered", last_centered,
                    centered_count / max(time.time() - centered_started, 1e-6),
                )
            raise RuntimeError("centered lane geometry did not become stable")
        centered_state = centered[1].lanes.left_state
        result["centered"] = _save(
            "centered", centered,
            centered_count / max(time.time() - centered_started, 1e-6),
        )

        index = _prompt(
            adas, pipe, engine, index,
            "MOVE CARD RIGHT UNTIL DEPARTURE ALERT", 8.0,
        )
        departed = None
        last_departed = None
        stable = 0
        departure_started = time.time()
        departure_count = 0
        deadline = time.time() + 12.0
        while time.time() < deadline:
            sample = _step(adas, pipe, engine, index)
            index += 1
            departure_count += 1
            last_departed = sample
            if (sample[1].lanes.departure and
                    _same_lane_state(sample, centered_state)):
                stable += 1
                if stable >= 3:
                    departed = sample
                    break
            else:
                stable = 0
        if departed is None:
            if last_departed is not None:
                result["failed_departure"] = _save(
                    "failed_departure", last_departed,
                    departure_count / max(time.time() - departure_started, 1e-6),
                )
            raise RuntimeError("lane departure alert did not trigger")
        departure_fps = (
            departure_count / max(time.time() - departure_started, 1e-6)
        )
        result["departure"] = _save(
            "departure", departed, departure_fps
        )
        if (departed[2].obstacle != 1 or
                departed[3].get("alarm_reason") != 3):
            raise RuntimeError("departure did not reach the alarm output")

        index = _prompt(
            adas, pipe, engine, index,
            "CENTER CARD AGAIN TO CLEAR ALERT", 8.0,
        )
        cleared = False
        cleared_sample = None
        clear_started = time.time()
        clear_count = 0
        deadline = time.time() + 12.0
        while time.time() < deadline:
            sample = _step(adas, pipe, engine, index)
            index += 1
            clear_count += 1
            if (_same_lane_state(sample, centered_state) and
                    not sample[1].lanes.departure and
                    sample[2].obstacle == 0 and
                    sample[3].get("alarm_reason") == 0):
                cleared = True
                cleared_sample = sample
                break
        if cleared_sample is not None:
            result["cleared_evidence"] = _save(
                "cleared", cleared_sample,
                clear_count / max(time.time() - clear_started, 1e-6),
            )
        result["cleared"] = cleared
        result["ok"] = cleared
        return 0 if cleared else 1
    finally:
        OUT.mkdir(parents=True, exist_ok=True)
        (ROOT / "evidence" / "lane_geometry.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
