"""OSD drawing for the Stage 4 LCD demo."""

from typing import Dict, Optional, Tuple

import cv2
import numpy as np

import config
from perception import LaneResult, ObstacleResult, PerceptionResult, TrafficLightResult


TL_COLORS = {
    "RED": (0, 0, 255),
    "GREEN": (0, 255, 0),
    "YELLOW": (0, 255, 255),
    "NONE": (160, 160, 160),
}
LANE_COLORS = {
    "SOLID": (0, 255, 255),
    "DASHED": (255, 200, 0),
    "NONE": (100, 100, 100),
}
ALARM_REASONS = {0: "-", 1: "RED+FORCE", 2: "SOLID+TURN", 3: "OBSTACLE"}


def _eval_poly(curve, y):
    a, b, c = curve
    return a * y * y + b * y + c


def _sx_box(box, sx: float, sy: float):
    x, y, w, h = box[:4]
    return int(x * sx), int(y * sy), int(w * sx), int(h * sy)


def draw_traffic_light(dst: np.ndarray, result: TrafficLightResult,
                       sx: float, sy: float) -> None:
    for box in result.boxes:
        x, y, w, h, name, area = box
        x, y, w, h = _sx_box((x, y, w, h), sx, sy)
        color = TL_COLORS.get(name, TL_COLORS["NONE"])
        cv2.rectangle(dst, (x, y), (x + w, y + h), color, 2)
        label = "%s#%d C=%.2f" % (
            name, result.track_id, result.circularity
        )
        cv2.putText(dst, label, (x, max(16, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def draw_lanes(dst: np.ndarray, result: LaneResult,
               sx: float, sy: float) -> None:
    height, width = dst.shape[:2]
    y0 = int(round(height * config.LANE_ROI_Y0))
    for side, line, curve, state in (
        ("L", result.left_line, result.left_curve, result.left_state),
        ("R", result.right_line, result.right_curve, result.right_state),
    ):
        if line is None and curve is None:
            continue
        color = LANE_COLORS.get(state, LANE_COLORS["NONE"])
        if curve is not None:
            points = []
            for yn in np.linspace(0.0, 1.0, 20):
                x = _eval_poly(curve, float(yn)) * width
                y = y0 + yn * (height - 1 - y0)
                points.append((int(x * sx), int(y * sy)))
            cv2.polylines(
                dst, [np.asarray(points, dtype=np.int32)],
                False, color, 3, cv2.LINE_AA,
            )
            p2 = points[-1]
        else:
            x1, y1, x2, y2 = line
            p1 = (int(x1 * sx), int(y1 * sy))
            p2 = (int(x2 * sx), int(y2 * sy))
            cv2.line(dst, p1, p2, color, 4, cv2.LINE_AA)
        cv2.putText(dst, "%s:%s" % (side, state),
                    (p2[0] - 24, max(18, p2[1] - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    if result.left_curve is not None and result.right_curve is not None:
        center_points = []
        for yn in np.linspace(0.0, 1.0, 20):
            left_x = _eval_poly(result.left_curve, float(yn))
            right_x = _eval_poly(result.right_curve, float(yn))
            x = (left_x + right_x) * 0.5 * width
            y = y0 + yn * (height - 1 - y0)
            center_points.append((int(x * sx), int(y * sy)))
        cv2.polylines(
            dst, [np.asarray(center_points, dtype=np.int32)],
            False, (0, 255, 0), 2, cv2.LINE_AA,
        )


def draw_obstacle(dst: np.ndarray, result: ObstacleResult,
                  sx: float, sy: float) -> None:
    for index, box in enumerate(result.boxes):
        x, y, w, h = _sx_box(box, sx, sy)
        cx = (x + w * 0.5) / float(dst.shape[1])
        cy = (y + h * 0.5) / float(dst.shape[0])
        box_near = (cy >= config.OBSTACLE_NEAR_Y0 and
                    config.OBSTACLE_NEAR_X0 <= cx <= config.OBSTACLE_NEAR_X1)
        color = (0, 0, 255) if box_near else (0, 255, 255)
        track_id = (
            result.track_ids[index]
            if index < len(result.track_ids) else 0
        )
        label = "OBJ#%d %s" % (track_id, "NEAR" if box_near else "")
        cv2.rectangle(dst, (x, y), (x + w, y + h), color, 2)
        cv2.putText(dst, label, (x, max(16, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def draw_arrow(dst: np.ndarray, turn: int) -> None:
    h, w = dst.shape[:2]
    base = (w // 2, h - 36)
    color = (0, 255, 255)
    if turn == config.TURN_LEFT:
        tip = (base[0] - 70, base[1])
    elif turn == config.TURN_RIGHT:
        tip = (base[0] + 70, base[1])
    else:
        tip = (base[0], base[1] - 70)
    cv2.arrowedLine(dst, base, tip, color, 5, cv2.LINE_AA, tipLength=0.25)
    label = {config.TURN_LEFT: "LEFT", config.TURN_RIGHT: "RIGHT"}.get(turn, "STRAIGHT")
    cv2.putText(dst, label, (base[0] - 36, h - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def draw_hud(dst: np.ndarray, fps: float, status: Optional[Dict[str, int]],
             decision, obstacle: Optional[ObstacleResult] = None,
             heartbeat_source: str = "FRAME",
             mode: str = "traffic_light",
             lanes: Optional[LaneResult] = None) -> None:
    h, w = dst.shape[:2]
    cv2.rectangle(dst, (0, 0), (w, 34), (0, 0, 0), -1)
    tl_names = {0: "NONE", 1: "RED", 2: "GREEN", 3: "YELLOW"}
    tl_name = tl_names.get(decision.tl_state, "?")
    if obstacle is not None and obstacle.learning:
        obs_text = "LEARN"
    elif obstacle is not None and obstacle.near:
        obs_text = "NEAR"
    elif obstacle is not None and obstacle.boxes:
        obs_text = "OBJ"
    else:
        obs_text = "OBS" if decision.obstacle else "CLEAR"
    if mode == "traffic_light":
        detail = "TL %s" % tl_name
    elif mode == "lane":
        departure = "DEPART" if lanes is not None and lanes.departure else "OK"
        detail = "LANE | OFF %+d%% | L %s | R %s | %s" % (
            int(round((lanes.center_offset if lanes is not None else 0.0) * 100)),
            {0: "-", 1: "SOLID", 2: "DASH"}.get(decision.lane_left, "?"),
            {0: "-", 1: "SOLID", 2: "DASH"}.get(decision.lane_right, "?"),
            departure,
        )
    else:
        detail = "OBSTACLE | %s" % obs_text
    text = "FPS %4.1f | %s" % (fps, detail)
    cv2.putText(dst, text, (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (255, 255, 255), 1, cv2.LINE_AA)
    if status:
        wd = int(status.get("wd_timeout", 0))
        reason = int(status.get("alarm_reason", 0))
        color = (0, 0, 255) if wd else (0, 255, 255)
        hb = "F" if str(heartbeat_source).upper() == "FRAME" else "FREE"
        cv2.putText(dst, "HB=%s WD=%d LED=%d %s" % (hb, wd,
                    int(status.get("led", 0)),
                    ALARM_REASONS.get(reason, "-")),
                    (w - 292, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def compose(proc_bgr: np.ndarray, perception: PerceptionResult, decision,
            status: Optional[Dict[str, int]], fps: float,
            heartbeat_source: str = "FRAME",
            mode: str = "traffic_light") -> np.ndarray:
    """Draw all OSD elements and return an 800x480 BGR frame."""

    out_w, out_h = config.DISPLAY_SIZE
    # Draw boxes/lines at processing resolution (cheap on the ARM core),
    # then upscale once.  Only the HUD text is drawn at LCD resolution.
    dst = proc_bgr.copy()
    if mode == "traffic_light":
        draw_traffic_light(dst, perception.traffic_light, 1.0, 1.0)
    elif mode == "lane":
        draw_lanes(dst, perception.lanes, 1.0, 1.0)
        draw_arrow(dst, decision.turn)
    elif mode == "obstacle":
        draw_obstacle(dst, perception.obstacle, 1.0, 1.0)
    dst = cv2.resize(dst, (out_w, out_h), interpolation=cv2.INTER_NEAREST)
    if mode == "obstacle" and perception.obstacle.learning:
        cv2.rectangle(dst, (0, 40), (out_w, 82), (0, 0, 0), -1)
        cv2.putText(dst, "LEARNING BACKGROUND - KEEP SCENE EMPTY",
                    (18, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 255, 255), 2, cv2.LINE_AA)
    if mode == "lane" and perception.lanes.departure:
        cv2.rectangle(dst, (0, 40), (out_w, 82), (0, 0, 0), -1)
        cv2.putText(
            dst, "LANE DEPARTURE DETECTED", (210, 70),
            cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2, cv2.LINE_AA,
        )
    if mode == "lane" and perception.lanes.bev is not None:
        bev = perception.lanes.bev
        bev = cv2.resize(
            bev, (180, 108), interpolation=cv2.INTER_NEAREST
        )
        x0, y0 = out_w - 190, 42
        dst[y0:y0 + bev.shape[0], x0:x0 + bev.shape[1]] = bev
        cv2.rectangle(
            dst, (x0, y0), (x0 + bev.shape[1], y0 + bev.shape[0]),
            (255, 255, 255), 1,
        )
        cv2.putText(
            dst, "LANE BEV", (x0 + 4, y0 + 14),
            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255),
            1, cv2.LINE_AA,
        )
    draw_hud(
        dst, fps, status, decision, perception.obstacle,
        heartbeat_source=heartbeat_source,
        mode=mode,
        lanes=perception.lanes,
    )
    return dst


def to_lcd(bgr: np.ndarray) -> np.ndarray:
    """Convert a BGR frame to the byte order expected by the LCD VDMA.

    Verified on the board: camera frames are BGR and the rgb2lcd block maps
    the top byte of each pixel to red, so the framebuffer must contain R,G,B.
    """

    if bgr.shape[1] != config.DISPLAY_SIZE[0] or bgr.shape[0] != config.DISPLAY_SIZE[1]:
        bgr = cv2.resize(bgr, config.DISPLAY_SIZE, interpolation=cv2.INTER_NEAREST)
    if config.LCD_FRAMEBUFFER_BGR:
        return np.ascontiguousarray(bgr)
    # Some PYNQ display integrations expect R,G,B bytes instead.
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def color_bars() -> np.ndarray:
    """Return a labelled BGR test pattern for LCD channel-order checks."""

    width, height = config.DISPLAY_SIZE
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    bars = (
        ("BLUE", (255, 0, 0)),
        ("GREEN", (0, 255, 0)),
        ("RED", (0, 0, 255)),
        ("WHITE", (255, 255, 255)),
    )
    bar_w = width // len(bars)
    for index, (label, color) in enumerate(bars):
        x0 = index * bar_w
        x1 = width if index == len(bars) - 1 else x0 + bar_w
        cv2.rectangle(canvas, (x0, 100), (x1 - 1, height - 1), color, -1)
        text_color = (255, 255, 255) if label != "WHITE" else (0, 0, 0)
        cv2.putText(
            canvas, label, (x0 + 22, 72),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, text_color, 2, cv2.LINE_AA,
        )
    cv2.putText(
        canvas, "LCD COLOR ORDER TEST: BLUE GREEN RED WHITE",
        (18, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
        (255, 255, 255), 1, cv2.LINE_AA,
    )
    return canvas


__all__ = [
    "compose",
    "color_bars",
    "draw_arrow",
    "draw_hud",
    "draw_lanes",
    "draw_obstacle",
    "draw_traffic_light",
    "to_lcd",
]
