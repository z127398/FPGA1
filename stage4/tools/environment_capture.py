"""Learn an empty small scene, then box a newly placed static object."""

import json
import time
from pathlib import Path

import cv2
import numpy as np

from decision import DecisionEngine
from osd import compose, draw_obstacle, to_lcd
from overlay import AdasOverlay
from perception import PerceptionPipeline


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "environment"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    adas = AdasOverlay()
    try:
        adas.start()
        adas.video_out.writeframe(to_lcd(np.zeros((480, 800, 3), dtype=np.uint8)))
        pipe = PerceptionPipeline(mode="obstacle")
        engine = DecisionEngine(mode="obstacle")

        print("LEARNING: keep the scene empty", flush=True)
        for i in range(48):  # 24 obstacle updates, every 2 frames
            frame = adas.video_in.readframe()
            bgr = cv2.resize(frame, adas.proc_size, interpolation=cv2.INTER_NEAREST)
            result = pipe.process(bgr, i)
            decision = engine.step(result, adas.read_btns())
            adas.write_dec(0, 0, 0, 0, 0, 0)
            out = compose(
                bgr, result, decision, adas.read_status(), adas.fps,
                mode="obstacle",
            )
            adas.video_out.writeframe(to_lcd(out))
            if i % 10 == 0:
                print("learning", i, result.obstacle.background_age, flush=True)

        print("READY: place a bottle/box/cup in the near zone", flush=True)
        for remaining in range(10, 0, -1):
            print("place object now: %d s" % remaining, flush=True)
            frame = adas.video_in.readframe()
            banner = cv2.resize(
                frame, adas.proc_size, interpolation=cv2.INTER_NEAREST
            )
            cv2.rectangle(banner, (0, 0), (banner.shape[1], 34), (0, 0, 0), -1)
            cv2.putText(banner, "PLACE OBJECT: %d s" % remaining,
                        (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                        (0, 255, 255), 2, cv2.LINE_AA)
            adas.video_out.writeframe(to_lcd(banner))
            time.sleep(1.0)
        deadline = time.time() + 30.0
        found = None
        frame_no = 48
        while time.time() < deadline:
            frame = adas.video_in.readframe()
            bgr = cv2.resize(frame, adas.proc_size, interpolation=cv2.INTER_NEAREST)
            result = pipe.process(bgr, frame_no)
            decision = engine.step(result, adas.read_btns())
            adas.write_dec(decision.tl_state, decision.lane_left,
                           decision.lane_right, decision.obstacle,
                           decision.force, decision.turn)
            out = compose(
                bgr, result, decision, adas.read_status(), adas.fps,
                mode="obstacle",
            )
            adas.video_out.writeframe(to_lcd(out))
            if result.obstacle.present:
                found = (bgr, result, decision)
                break
            if frame_no % 30 == 0:
                print("monitor", result.obstacle.boxes,
                      "near", result.obstacle.near, flush=True)
            frame_no += 1

        if found is None:
            print("TIMEOUT: no near object", flush=True)
            return
        bgr, result, decision = found
        time.sleep(0.1)
        status = adas.read_status()
        btns = adas.read_btns()
        osd_bgr = compose(
            bgr, result, decision, status, adas.fps, mode="obstacle"
        )
        cv2.imwrite(str(OUT / "osd.png"), osd_bgr)
        ob_img = bgr.copy()
        draw_obstacle(ob_img, result.obstacle, 1.0, 1.0)
        cv2.imwrite(str(OUT / "obstacle_bbox.png"), ob_img)
        meta = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "obstacle": {
                "present": result.obstacle.present,
                "near": result.obstacle.near,
                "boxes": result.obstacle.boxes,
                "background_age": result.obstacle.background_age,
                "shift": result.obstacle.shift,
            },
            "decision": decision.as_dict(),
            "status": status,
            "buttons": btns,
        }
        (OUT / "status.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        adas.display(osd_bgr)
        print("FOUND", meta, flush=True)
    finally:
        adas.stop()
        adas.restore_quiet_bitstream()
        print("stage2 restored", flush=True)


if __name__ == "__main__":
    main()
