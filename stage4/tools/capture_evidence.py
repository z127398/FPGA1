"""Capture the Stage 4 evidence set from one live camera frame.

Run this on the board with the target photo in front of the OV5640:

    PYTHONPATH=. python3 tools/capture_evidence.py

It writes OSD, traffic-light box, lane overlay, HSV S-channel and status JSON
under stage4/evidence/.  The board is restored to the quiet Stage 2 image at
the end.
"""

import json
import time
from pathlib import Path

import cv2
import numpy as np

from decision import DecisionEngine
from osd import compose, draw_lanes, draw_traffic_light, to_lcd
from overlay import AdasOverlay
from perception import PerceptionPipeline


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    adas = AdasOverlay()
    try:
        adas.start()
        # Break the zero-copy tie so the captured frame can also be written
        # back as an OSD image.
        adas.video_out.writeframe(to_lcd(np.zeros((480, 800, 3), dtype=np.uint8)))
        time.sleep(0.5)
        frame = adas.video_in.readframe()
        bgr = cv2.resize(frame, adas.proc_size, interpolation=cv2.INTER_NEAREST)
        mode = "traffic_light"
        pipe = PerceptionPipeline(mode=mode)
        result = pipe.process(bgr, 0)
        decision = DecisionEngine(mode=mode).step(result, adas.read_btns())
        adas.write_dec(decision.tl_state, decision.lane_left,
                       decision.lane_right, decision.obstacle,
                       decision.force, decision.turn)
        time.sleep(0.1)
        status = adas.read_status()
        osd_bgr = compose(
            bgr, result, decision, status, adas.fps, mode=mode
        )

        cv2.imwrite(str(OUT / "osd.png"), osd_bgr)
        tl_img = bgr.copy()
        draw_traffic_light(tl_img, result.traffic_light, 1.0, 1.0)
        cv2.imwrite(str(OUT / "tl_bbox.png"), tl_img)
        lane_img = bgr.copy()
        draw_lanes(lane_img, result.lanes, 1.0, 1.0)
        cv2.imwrite(str(OUT / "lane_bbox.png"), lane_img)

        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        s_channel = hsv[:, :, 1]
        cv2.imwrite(str(OUT / "s_channel.png"), s_channel)
        cv2.imwrite(str(OUT / "s_channel_color.png"),
                    cv2.applyColorMap(s_channel, cv2.COLORMAP_JET))

        meta = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "proc_size": list(adas.proc_size),
            "fps": adas.fps,
            "traffic_light": {
                "state": result.traffic_light.state,
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
            "obstacle": {
                "present": result.obstacle.present,
                "boxes": result.obstacle.boxes,
            },
            "decision": decision.as_dict(),
            "status": status,
            "buttons": adas.read_btns(),
        }
        with (OUT / "status.json").open("w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        adas.display(osd_bgr)
        print("evidence written to", OUT)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    finally:
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored")


if __name__ == "__main__":
    main()
