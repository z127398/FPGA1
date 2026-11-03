"""Show a live mode and continuously publish atomic evidence snapshots."""

import asyncio
import json
import os
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


def _atomic_write_json(path, payload):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_write_image(path, image):
    temporary = path.with_name(path.stem + "_tmp" + path.suffix)
    if not cv2.imwrite(str(temporary), image):
        raise RuntimeError("cannot write %s" % temporary)
    os.replace(temporary, path)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "traffic_light"
    input_mode = sys.argv[2] if len(sys.argv) > 2 else (
        "gray" if mode == "lane" else "color"
    )
    out = ROOT / "evidence" / "live_capture"
    snapshot = out / "snapshot"
    trigger = out / "capture.request"
    done = out / "capture.done.json"
    out.mkdir(parents=True, exist_ok=True)
    adas = AdasOverlay()
    try:
        adas.start()
        adas.set_pipeline(input_mode)
        pipe = PerceptionPipeline(
            mode=mode, input_gray=input_mode == "gray"
        )
        engine = DecisionEngine(mode=mode)
        loop = asyncio.get_event_loop()
        idx = 0
        while True:
            try:
                frame = loop.run_until_complete(
                    asyncio.wait_for(adas.video_in.readframe_async(), 1.0)
                )
            except asyncio.TimeoutError:
                continue
            bgr = cv2.resize(
                frame, adas.proc_size, interpolation=cv2.INTER_NEAREST
            )
            result = pipe.process(bgr, idx)
            decision = engine.step(result, adas.read_btns())
            adas.write_dec(
                decision.tl_state, decision.lane_left,
                decision.lane_right, decision.obstacle,
                decision.force, decision.turn, feed_heartbeat=True,
            )
            status = adas.read_status()
            output = compose(
                bgr, result, decision, status, adas.fps, mode=mode,
                heartbeat_source="FRAME",
            )
            payload = {
                "mode": mode,
                "input_mode": input_mode,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "traffic_light": {
                    "state": result.traffic_light.state,
                    "track_id": result.traffic_light.track_id,
                    "boxes": result.traffic_light.boxes,
                },
                "lanes": {
                    "left": result.lanes.left_state,
                    "right": result.lanes.right_state,
                    "coverage_left": result.lanes.coverage_left,
                    "coverage_right": result.lanes.coverage_right,
                    "center_offset": result.lanes.center_offset,
                    "curvature": result.lanes.curvature,
                    "departure": result.lanes.departure,
                },
                "obstacle": {
                    "present": result.obstacle.present,
                    "learning": result.obstacle.learning,
                    "background_age": result.obstacle.background_age,
                    "boxes": result.obstacle.boxes,
                    "track_ids": result.obstacle.track_ids,
                },
                "decision": decision.as_dict(),
                "status": status,
                "buttons": adas.read_btns(),
            }
            loop.run_until_complete(
                asyncio.wait_for(
                    adas.video_out.writeframe_async(to_lcd(output)), 1.0
                )
            )
            if idx % 6 == 0:
                _atomic_write_image(out / "latest_raw.png", bgr)
                _atomic_write_image(out / "latest_osd.png", output)
                if mode == "lane" and result.lanes.bev is not None:
                    _atomic_write_image(out / "latest_bev.png", result.lanes.bev)
                _atomic_write_json(out / "latest_status.json", payload)
            if trigger.exists():
                snapshot.mkdir(parents=True, exist_ok=True)
                _atomic_write_image(snapshot / "raw.png", bgr)
                _atomic_write_image(snapshot / "osd.png", output)
                if mode == "lane" and result.lanes.bev is not None:
                    _atomic_write_image(snapshot / "bev.png", result.lanes.bev)
                else:
                    stale_bev = snapshot / "bev.png"
                    if stale_bev.exists():
                        stale_bev.unlink()
                _atomic_write_json(snapshot / "status.json", payload)
                _atomic_write_json(done, {
                    "ok": True,
                    "mode": mode,
                    "time": payload["time"],
                    "directory": str(snapshot),
                })
                trigger.unlink()
            idx += 1
    except KeyboardInterrupt:
        return 0
    finally:
        adas.stop()
        adas.restore_quiet_bitstream()
        print("%s capture stopped; stage2 restored" % mode, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
