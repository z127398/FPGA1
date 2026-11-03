"""Wait for a requested traffic-light/lane card and save evidence.

Usage on the board:
    PYTHONPATH=. python3 tools/wait_target_capture.py GREEN
    PYTHONPATH=. python3 tools/wait_target_capture.py YELLOW
    PYTHONPATH=. python3 tools/wait_target_capture.py SOLID
    PYTHONPATH=. python3 tools/wait_target_capture.py DASHED
"""

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from decision import DecisionEngine
from osd import compose, draw_lanes, draw_traffic_light, to_lcd
from overlay import AdasOverlay
from perception import PerceptionPipeline


ROOT = Path(__file__).resolve().parents[1]


def main():
    target = (sys.argv[1] if len(sys.argv) > 1 else "RED").upper()
    mode = (
        "traffic_light"
        if target in ("RED", "GREEN", "YELLOW", "NONE")
        else "lane"
    )
    out = ROOT / "evidence" / target.lower()
    out.mkdir(parents=True, exist_ok=True)
    adas = AdasOverlay()
    try:
        adas.start()
        input_mode = "gray" if mode == "lane" else "color"
        adas.set_pipeline(input_mode)
        adas.video_out.writeframe(to_lcd(np.zeros((480, 800, 3), dtype=np.uint8)))
        pipe = PerceptionPipeline(
            mode=mode, input_gray=input_mode == "gray"
        )
        engine = DecisionEngine(mode=mode)
        deadline = time.time() + 30.0
        i = 0
        found = None
        stable = 0
        while time.time() < deadline:
            frame = adas.video_in.readframe()
            bgr = cv2.resize(frame, adas.proc_size, interpolation=cv2.INTER_NEAREST)
            result = pipe.process(bgr, i)
            decision = engine.step(result, adas.read_btns())
            adas.write_dec(
                decision.tl_state, decision.lane_left,
                decision.lane_right, decision.obstacle,
                decision.force, decision.turn, feed_heartbeat=True,
            )
            status = adas.read_status()
            osd_bgr = compose(
                bgr, result, decision, status, adas.fps, mode=mode,
                heartbeat_source="FRAME",
            )
            if target in ("RED", "GREEN", "YELLOW", "NONE"):
                hit = result.traffic_light.state == target
            else:
                hit = (result.lanes.left_state == target and
                       result.lanes.right_state == target)
            stable = stable + 1 if hit else 0
            if stable >= 3:
                found = (bgr, result, decision, status, osd_bgr)
                break
            cv2.rectangle(osd_bgr, (0, 86), (799, 142), (0, 0, 0), -1)
            cv2.putText(
                osd_bgr,
                "HOLD %s CARD - WAIT FOR LOCK" % target,
                (20, 121), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, (0, 255, 255), 2, cv2.LINE_AA,
            )
            adas.video_out.writeframe(to_lcd(osd_bgr))
            if hit:
                print("confirming %s %d/3" % (target, stable), flush=True)
            if i % 20 == 0:
                print("waiting %s ... TL=%s L=%s R=%s" % (
                    target, result.traffic_light.state,
                    result.lanes.left_state, result.lanes.right_state), flush=True)
            i += 1
        if found is None:
            print("TIMEOUT", target)
            return
        bgr, result, decision, status, osd_bgr = found
        btns = adas.read_btns()
        cv2.imwrite(str(out / "osd.png"), osd_bgr)
        tl_img = bgr.copy()
        draw_traffic_light(tl_img, result.traffic_light, 1.0, 1.0)
        cv2.imwrite(str(out / "tl_bbox.png"), tl_img)
        lane_img = bgr.copy()
        draw_lanes(lane_img, result.lanes, 1.0, 1.0)
        cv2.imwrite(str(out / "lane_bbox.png"), lane_img)
        if mode == "lane" and result.lanes.bev is not None:
            cv2.imwrite(str(out / "bev.png"), result.lanes.bev)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        cv2.imwrite(str(out / "s_channel.png"), hsv[:, :, 1])
        cv2.imwrite(str(out / "s_channel_color.png"),
                    cv2.applyColorMap(hsv[:, :, 1], cv2.COLORMAP_JET))
        meta = {
            "target": target,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "traffic_light": {
                "state": result.traffic_light.state,
                "relaxed": result.traffic_light.relaxed,
                "boxes": result.traffic_light.boxes,
                "circularity": result.traffic_light.circularity,
                "convexity": result.traffic_light.convexity,
                "inertia_ratio": result.traffic_light.inertia_ratio,
            },
            "lanes": {
                "left": result.lanes.left_state,
                "right": result.lanes.right_state,
                "coverage_left": result.lanes.coverage_left,
                "coverage_right": result.lanes.coverage_right,
            },
            "obstacle": result.obstacle.present,
            "decision": decision.as_dict(),
            "status": status,
            "buttons": btns,
        }
        (out / "status.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        adas.display(osd_bgr)
        hold_deadline = time.time() + 2.5
        while time.time() < hold_deadline:
            adas.write_dec(
                decision.tl_state, decision.lane_left,
                decision.lane_right, decision.obstacle,
                decision.force, decision.turn, feed_heartbeat=True,
            )
            adas.video_out.writeframe(to_lcd(osd_bgr))
            time.sleep(0.05)
        print("FOUND %s -> %s" % (target, out))
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    finally:
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored")


if __name__ == "__main__":
    main()
