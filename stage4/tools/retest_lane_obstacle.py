"""Guided board retest for lane and obstacle modes only."""

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
EVIDENCE = ROOT / "evidence"


def _prepare(adas, pipeline, engine, mode, index):
    frame = adas.video_in.readframe()
    bgr = cv2.resize(
        frame, adas.proc_size, interpolation=cv2.INTER_NEAREST
    )
    result = pipeline.process(bgr, index)
    decision = engine.step(result, adas.read_btns())
    adas.write_dec(
        decision.tl_state, decision.lane_left, decision.lane_right,
        decision.obstacle, decision.force, decision.turn,
        feed_heartbeat=True,
    )
    status = adas.read_status()
    out = compose(
        bgr, result, decision, status, adas.fps, mode=mode,
        heartbeat_source="FRAME",
    )
    adas.video_out.writeframe(to_lcd(out))
    return bgr, result, decision, status


def _banner(adas, pipeline, engine, mode, index, text, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        bgr, result, decision, status = _prepare(
            adas, pipeline, engine, mode, index
        )
        out = compose(
            bgr, result, decision, status, adas.fps, mode=mode,
            heartbeat_source="FRAME",
        )
        cv2.rectangle(out, (0, 86), (out.shape[1], 144), (0, 0, 0), -1)
        cv2.putText(
            out, text, (24, 124), cv2.FONT_HERSHEY_SIMPLEX,
            0.72, (0, 255, 255), 2, cv2.LINE_AA,
        )
        adas.video_out.writeframe(to_lcd(out))
        index += 1
        time.sleep(0.05)
    return index


def _run_lane(adas, target, prompt):
    mode = "lane"
    pipeline = PerceptionPipeline(mode=mode)
    engine = DecisionEngine(mode=mode)
    index = _banner(
        adas, pipeline, engine, mode, 0, prompt, 15.0
    )
    started = time.time()
    count = 0
    stable = 0
    last = None
    while time.time() - started < 30.0:
        bgr, result, decision, status = _prepare(
            adas, pipeline, engine, mode, index
        )
        index += 1
        count += 1
        if (result.lanes.left_state == target and
                result.lanes.right_state == target):
            stable += 1
        else:
            stable = 0
        last = (bgr, result, decision, status)
        if stable >= 3:
            break
    if last is None or stable < 3:
        raise RuntimeError("lane target not stable: %s" % target)
    elapsed = time.time() - started
    out_dir = EVIDENCE / "lane_mode" / target.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    bgr, result, decision, status = last
    osd = compose(
        bgr, result, decision, status, count / elapsed, mode=mode,
        heartbeat_source="FRAME",
    )
    cv2.imwrite(str(out_dir / "osd.png"), osd)
    payload = {
        "mode": mode,
        "target": target,
        "fps": count / elapsed,
        "left": result.lanes.left_state,
        "right": result.lanes.right_state,
        "coverage_left": result.lanes.coverage_left,
        "coverage_right": result.lanes.coverage_right,
        "traffic_light": result.traffic_light.state,
        "obstacle": result.obstacle.present,
        "decision": decision.as_dict(),
        "status": status,
    }
    (out_dir / "status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _banner(
        adas, pipeline, engine, mode, index,
        "%s PASSED - HOLD CARD FOR EVIDENCE" % target, 4.0,
    )
    return payload


def _run_obstacle(adas):
    mode = "obstacle"
    pipeline = PerceptionPipeline(mode=mode)
    engine = DecisionEngine(mode=mode)
    index = _banner(
        adas, pipeline, engine, mode, 0,
        "OBSTACLE TEST: REMOVE ALL OBJECTS AND HANDS", 12.0,
    )
    # Learn 24 obstacle updates, which occur every two frames.
    for _ in range(48):
        _prepare(adas, pipeline, engine, mode, index)
        index += 1
    index = _banner(
        adas, pipeline, engine, mode, index,
        "PLACE OBJECT IN LOWER CENTRE: 10 s", 10.0,
    )
    started = time.time()
    count = 0
    first_detection = False
    found = None
    while time.time() - started < 30.0:
        sample = _prepare(adas, pipeline, engine, mode, index)
        index += 1
        count += 1
        if sample[1].obstacle.present and sample[1].obstacle.near:
            first_detection = True
            break
    if not first_detection:
        raise RuntimeError("obstacle was not detected in near zone")

    index = _banner(
        adas, pipeline, engine, mode, index,
        "REMOVE HANDS - KEEP OBJECT IN VIEW", 5.0,
    )
    stable = 0
    verification_started = time.time()
    while time.time() - verification_started < 10.0:
        sample = _prepare(adas, pipeline, engine, mode, index)
        index += 1
        if sample[1].obstacle.present and sample[1].obstacle.near:
            stable += 1
            if stable >= 3:
                found = sample
                break
        else:
            stable = 0
    if found is None:
        raise RuntimeError("obstacle was not detected in near zone")
    elapsed = time.time() - started
    out_dir = EVIDENCE / "obstacle_mode"
    out_dir.mkdir(parents=True, exist_ok=True)
    bgr, result, decision, status = found
    osd = compose(
        bgr, result, decision, status, count / elapsed, mode=mode,
        heartbeat_source="FRAME",
    )
    cv2.imwrite(str(out_dir / "osd.png"), osd)
    payload = {
        "mode": mode,
        "fps": count / elapsed,
        "boxes": result.obstacle.boxes,
        "near": result.obstacle.near,
        "background_age": result.obstacle.background_age,
        "traffic_light": result.traffic_light.state,
        "lanes": [result.lanes.left_state, result.lanes.right_state],
        "decision": decision.as_dict(),
        "status": status,
    }
    (out_dir / "status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    index = _banner(
        adas, pipeline, engine, mode, index,
        "REMOVE OBJECT TO CHECK CLEARING", 8.0,
    )
    cleared = None
    clear_count = 0
    deadline = time.time() + 10.0
    while time.time() < deadline:
        sample = _prepare(adas, pipeline, engine, mode, index)
        index += 1
        if not sample[1].obstacle.present and not sample[1].obstacle.boxes:
            clear_count += 1
            if clear_count >= 3:
                cleared = sample
                break
        else:
            clear_count = 0
    if cleared is None:
        raise RuntimeError("obstacle boxes did not clear after removal")
    payload["cleared"] = True
    (out_dir / "status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def main():
    adas = AdasOverlay()
    obstacle_only = "--obstacle-only" in sys.argv[1:]
    summary_path = EVIDENCE / "modes_retest.json"
    if obstacle_only and summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["ok"] = False
    else:
        summary = {"ok": False}
    try:
        adas.start()
        adas._set_heartbeat_mode("frame")
        if not obstacle_only:
            summary["lane_solid"] = _run_lane(
                adas, "SOLID", "LANE TEST: SHOW SOLID CARD"
            )
            summary["lane_dashed"] = _run_lane(
                adas, "DASHED", "LANE TEST: SHOW DASHED CARD"
            )
        summary["obstacle"] = _run_obstacle(adas)
        summary["ok"] = True
    finally:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored", flush=True)


if __name__ == "__main__":
    main()
