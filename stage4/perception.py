"""OpenCV perception for the Stage 4 photo-based ADAS demo.

All coordinates returned by this module are in the *input* frame coordinate
system.  The demo loop resizes camera frames to ``config.PROC_SIZE`` before
calling these detectors, so callers can draw the results directly on the
processing frame and then scale for the 800x480 LCD.
"""

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

import config


Box = Tuple[int, int, int, int]
ColoredBox = Tuple[int, int, int, int, str, int]
Line = Tuple[int, int, int, int]


@dataclass
class TrafficLightResult:
    state: str = "NONE"
    boxes: List[ColoredBox] = field(default_factory=list)
    mask: Optional[np.ndarray] = None
    area: int = 0
    relaxed: bool = False
    circularity: float = 0.0
    convexity: float = 0.0
    inertia_ratio: float = 0.0
    track_id: int = 0


@dataclass
class LaneResult:
    left_state: str = "NONE"
    right_state: str = "NONE"
    left_line: Optional[Line] = None
    right_line: Optional[Line] = None
    coverage_left: float = 0.0
    coverage_right: float = 0.0
    max_gap_left: float = 1.0
    max_gap_right: float = 1.0
    gap_runs_left: int = 0
    gap_runs_right: int = 0
    left_curve: Optional[Tuple[float, float, float]] = None
    right_curve: Optional[Tuple[float, float, float]] = None
    center_offset: float = 0.0
    curvature: float = 0.0
    departure: bool = False
    bev: Optional[np.ndarray] = field(default=None, repr=False)
    edges: Optional[np.ndarray] = None


@dataclass
class ObstacleResult:
    present: bool = False
    boxes: List[Box] = field(default_factory=list)
    track_ids: List[int] = field(default_factory=list)
    motion_area: float = 0.0
    kind: str = "OBJECT"
    near: bool = False
    learning: bool = False
    background_age: int = 0
    shift: Tuple[float, float] = (0.0, 0.0)


@dataclass
class PerceptionResult:
    traffic_light: TrafficLightResult
    lanes: LaneResult
    obstacle: ObstacleResult


class TrafficLightDetector:
    """HSV traffic-light detector with a short majority vote."""

    def __init__(self, vote_n: int = config.TL_VOTE_N):
        self.vote_n = int(vote_n)
        self._history: Deque[str] = deque(maxlen=self.vote_n)
        self._stable = "NONE"
        self._boxes: Deque[ColoredBox] = deque(
            maxlen=max(1, int(config.TL_BOX_SMOOTH_N))
        )
        self._track_id = 0
        self._next_track_id = 1

    def reset(self) -> None:
        self._history.clear()
        self._stable = "NONE"
        self._boxes.clear()
        self._track_id = 0
        self._next_track_id = 1

    @staticmethod
    def _masks(hsv: np.ndarray) -> Dict[str, np.ndarray]:
        red = cv2.inRange(
            hsv,
            (config.TL_H_RED_LO1, config.TL_S_RED, config.TL_V_RED),
            (config.TL_H_RED_HI1, 255, 255),
        ) | cv2.inRange(
            hsv,
            (config.TL_H_RED_LO2, config.TL_S_RED, config.TL_V_RED),
            (config.TL_H_RED_HI2, 255, 255),
        )
        yellow = cv2.inRange(
            hsv,
            (config.TL_H_YEL_LO, config.TL_S_YEL, config.TL_V_YEL),
            (config.TL_H_YEL_HI, 255, 255),
        )
        green = cv2.inRange(
            hsv,
            (config.TL_H_GRN_LO, config.TL_S_GRN, config.TL_V_GRN),
            (config.TL_H_GRN_HI, 255, 255),
        )
        return {"RED": red, "YELLOW": yellow, "GREEN": green}

    @staticmethod
    def _relaxed_masks(hsv: np.ndarray) -> Dict[str, np.ndarray]:
        s = config.TL_RELAXED_S
        v = config.TL_RELAXED_V
        red = cv2.inRange(hsv, (config.TL_H_RED_LO1, s, v),
                          (config.TL_H_RED_HI1, 255, 255)) | \
            cv2.inRange(hsv, (config.TL_H_RED_LO2, s, v),
                        (config.TL_H_RED_HI2, 255, 255))
        yellow = cv2.inRange(hsv, (config.TL_H_YEL_LO, s, v),
                             (config.TL_H_YEL_HI, 255, 255))
        green = cv2.inRange(hsv, (config.TL_H_GRN_LO, s, v),
                            (config.TL_H_GRN_HI, 255, 255))
        return {"RED": red, "YELLOW": yellow, "GREEN": green}

    def detect(self, bgr: np.ndarray, with_mask: bool = False) -> TrafficLightResult:
        if bgr is None or bgr.size == 0:
            return TrafficLightResult()
        h, w = bgr.shape[:2]
        frame_area = float(h * w)
        min_area = max(6.0, frame_area * config.TL_MIN_AREA_FRAC)
        max_area = max(min_area + 1.0, frame_area * config.TL_MAX_AREA_FRAC)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (config.TL_MORPH_K, config.TL_MORPH_K)
        )

        boxes: List[ColoredBox] = []
        best_area: Dict[str, int] = {}
        best_score: Dict[str, float] = {}
        best_box: Dict[str, ColoredBox] = {}
        best_shape: Dict[str, Tuple[float, float, float]] = {}
        relaxed_names = set()
        combined_mask = np.zeros((h, w), dtype=np.uint8)

        def shape_metrics(contour) -> Optional[Tuple[float, float, float]]:
            contour_area = float(cv2.contourArea(contour))
            perimeter = float(cv2.arcLength(contour, True))
            hull_area = float(cv2.contourArea(cv2.convexHull(contour)))
            if contour_area <= 0 or perimeter <= 0 or hull_area <= 0:
                return None
            circularity = 4.0 * np.pi * contour_area / (perimeter * perimeter)
            convexity = contour_area / hull_area
            if len(contour) < 5:
                return None
            try:
                (_, _), (axis1, axis2), _ = cv2.fitEllipse(contour)
            except cv2.error:
                return None
            major, minor = max(axis1, axis2), min(axis1, axis2)
            if major <= 0:
                return None
            inertia = minor / major
            if (circularity < config.TL_MIN_CIRCULARITY or
                    convexity < config.TL_MIN_CONVEXITY or
                    inertia < config.TL_MIN_INERTIA_RATIO):
                return None
            return float(circularity), float(convexity), float(inertia)

        def candidate_score(area, x, y, bw, bh, component_mask):
            # Active lamps behave like small bright emitters.  Area alone
            # favours saturated foliage/signs, so use compact high-value
            # pixels with a mild central prior for close-up photo HIL.
            pixel_v = hsv[y:y + bh, x:x + bw, 2][
                component_mask[y:y + bh, x:x + bw] > 0
            ]
            if pixel_v.size == 0:
                return 0.0
            p90_v = float(np.percentile(pixel_v, 90))
            cx = (x + bw * 0.5) / float(w)
            cy = (y + bh * 0.5) / float(h)
            centre = max(0.05, 1.0 - float(np.hypot(cx - 0.5, cy - 0.5)))
            return (
                float(area) ** 0.5
                * (max(p90_v, 1.0) / 255.0) ** 4
                * centre ** 2
            )

        for name, raw_mask in self._masks(hsv).items():
            mask = raw_mask
            if config.TL_USE_MORPHOLOGY:
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            combined_mask = cv2.bitwise_or(combined_mask, mask)
            contours, _ = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for contour in contours:
                area = int(cv2.contourArea(contour))
                if area < min_area or area > max_area:
                    continue
                x, y, bw, bh = [int(v) for v in cv2.boundingRect(contour)]
                aspect = bw / float(bh) if bh else 0.0
                if aspect < config.TL_MIN_ASPECT or aspect > config.TL_MAX_ASPECT:
                    continue
                fill = area / float(bw * bh) if bw and bh else 0.0
                if fill < config.TL_MIN_FILL or fill > config.TL_MAX_FILL:
                    continue
                shape = shape_metrics(contour)
                if shape is None:
                    continue
                boxes.append((x, y, bw, bh, name, area))
                score = candidate_score(area, x, y, bw, bh, mask)
                if score > best_score.get(name, -1.0):
                    best_score[name] = score
                    best_area[name] = area
                    best_box[name] = (x, y, bw, bh, name, area)
                    best_shape[name] = shape

        # Overexposed phone screens can turn a filled light into a
        # low-saturation ring.  If one colour has no strict candidate, add
        # its relaxed candidates without allowing them to replace a strict
        # candidate of the same colour.  Components touching the border are
        # rejected so a wooden desk/wall is not mistaken for a light.
        relaxed_min = max(6.0, frame_area * config.TL_RELAXED_MIN_AREA_FRAC)
        relaxed_max = frame_area * config.TL_RELAXED_MAX_AREA_FRAC
        for name, raw_mask in self._relaxed_masks(hsv).items():
            combined_mask = cv2.bitwise_or(combined_mask, raw_mask)
            if name in best_score:
                continue
            contours, _ = cv2.findContours(
                raw_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for contour in contours:
                area = int(cv2.contourArea(contour))
                if area < relaxed_min or area > relaxed_max:
                    continue
                x, y, bw, bh = [int(v) for v in cv2.boundingRect(contour)]
                if x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1:
                    continue
                aspect = bw / float(bh) if bh else 0.0
                if aspect < config.TL_MIN_ASPECT or aspect > config.TL_MAX_ASPECT:
                    continue
                fill = area / float(bw * bh) if bw and bh else 0.0
                if (fill < config.TL_RELAXED_MIN_FILL or
                        fill > config.TL_RELAXED_MAX_FILL):
                    continue
                shape = shape_metrics(contour)
                if shape is None:
                    continue
                boxes.append((x, y, bw, bh, name, area))
                score = candidate_score(area, x, y, bw, bh, raw_mask)
                if score > best_score.get(name, -1.0):
                    best_score[name] = score
                    best_area[name] = area
                    best_box[name] = (x, y, bw, bh, name, area)
                    best_shape[name] = shape
                    relaxed_names.add(name)

        if not best_area:
            state = "NONE"
        else:
            state = max(best_score, key=best_score.get)
        relaxed = state in relaxed_names
        selected_boxes = [best_box[state]] if state in best_box else []
        circularity, convexity, inertia = best_shape.get(
            state, (0.0, 0.0, 0.0)
        )
        return TrafficLightResult(
            state=state,
            boxes=selected_boxes,
            mask=combined_mask if with_mask else None,
            area=best_area.get(state, 0),
            relaxed=relaxed,
            circularity=circularity,
            convexity=convexity,
            inertia_ratio=inertia,
        )

    def update(self, bgr: np.ndarray, with_mask: bool = False) -> TrafficLightResult:
        result = self.detect(bgr, with_mask=with_mask)
        self._history.append(result.state)
        if self.vote_n <= 1:
            self._stable = result.state
        elif result.state == self._stable:
            pass
        elif self._stable == "NONE":
            needed = min(self.vote_n, max(1, int(config.TL_ENTER_N)))
            if self._history.count(result.state) >= needed:
                self._stable = result.state
        else:
            needed = (
                config.TL_CLEAR_N
                if result.state == "NONE"
                else config.TL_SWITCH_N
            )
            needed = min(self.vote_n, max(1, int(needed)))
            if self._history.count(result.state) >= needed:
                self._stable = result.state

        if self._stable == "NONE":
            self._boxes.clear()
            self._track_id = 0
        elif result.boxes and result.state == self._stable:
            if self._track_id == 0:
                self._track_id = self._next_track_id
                self._next_track_id += 1
            self._boxes.append(result.boxes[0])
            coords = np.asarray([box[:4] for box in self._boxes], dtype=np.float32)
            x, y, w, h = [int(round(v)) for v in np.median(coords, axis=0)]
            _, _, _, _, name, area = result.boxes[0]
            result.boxes = [(x, y, w, h, name, area)]
        elif self._boxes:
            result.boxes = [self._boxes[-1]]
        result.state = self._stable
        result.track_id = self._track_id
        return result


class LaneDetector:
    """Canny/Hough lane detector with left/right and solid/dashed voting."""

    def __init__(self, vote_n: int = config.LANE_VOTE_N):
        self.vote_n = int(vote_n)
        self._left_hist: Deque[str] = deque(maxlen=self.vote_n)
        self._right_hist: Deque[str] = deque(maxlen=self.vote_n)
        self._left_stable = "NONE"
        self._right_stable = "NONE"
        self._left_lines: Deque[Line] = deque(
            maxlen=max(1, int(config.LANE_LINE_SMOOTH_N))
        )
        self._right_lines: Deque[Line] = deque(
            maxlen=max(1, int(config.LANE_LINE_SMOOTH_N))
        )
        self._left_curves: Deque[Tuple[float, float, float]] = deque(
            maxlen=max(1, int(config.LANE_CURVE_SMOOTH_N))
        )
        self._right_curves: Deque[Tuple[float, float, float]] = deque(
            maxlen=max(1, int(config.LANE_CURVE_SMOOTH_N))
        )
        self._track_x: Dict[str, Optional[float]] = {
            "left": None,
            "right": None,
        }
        self._track_slope: Dict[str, Optional[float]] = {
            "left": None,
            "right": None,
        }
        self._track_missed: Dict[str, int] = {"left": 0, "right": 0}
        self._departure_count = 0
        self._departure_clear_count = 0
        self._departure = False

    def reset(self) -> None:
        self._left_hist.clear()
        self._right_hist.clear()
        self._left_stable = "NONE"
        self._right_stable = "NONE"
        self._left_lines.clear()
        self._right_lines.clear()
        self._left_curves.clear()
        self._right_curves.clear()
        self._track_x = {"left": None, "right": None}
        self._track_slope = {"left": None, "right": None}
        self._track_missed = {"left": 0, "right": 0}
        self._departure_count = 0
        self._departure_clear_count = 0
        self._departure = False

    @staticmethod
    def _line_side(x1: int, y1: int, x2: int, y2: int, w: int, h: int) -> Optional[str]:
        dx = float(x2 - x1)
        dy = float(y2 - y1)
        if abs(dx) < 1e-6:
            return None
        slope = dy / dx  # image coordinates: y grows downwards
        if abs(slope) < config.LANE_SLOPE_MIN or abs(slope) > config.LANE_SLOPE_MAX:
            return None
        ys = max(y1, y2)
        x_bottom = x1 + (ys - y1) / slope
        margin = 0.04 * w
        # Classify by the line's x position at the bottom of the frame.  The
        # slope is only used to reject horizontal/vertical clutter; relying on
        # its sign alone breaks when the camera is tilted or the image is
        # cropped differently.
        if x_bottom < w * 0.5 - margin:
            return "left"
        if x_bottom > w * 0.5 + margin:
            return "right"
        return None

    @staticmethod
    def _fit(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
        if len(points) < 2:
            return None
        pts = np.asarray(points, dtype=np.float64)
        ys = pts[:, 0]
        xs = pts[:, 1]
        if np.allclose(ys, ys[0]):
            return None
        a, b = np.polyfit(ys, xs, 1)
        return float(a), float(b)

    @staticmethod
    def _fit_curve(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float, float]]:
        if len(points) < 2:
            return None
        pts = np.asarray(points, dtype=np.float64)
        ys = pts[:, 0]
        xs = pts[:, 1]
        if np.allclose(ys, ys[0]):
            return None
        unique_rows = np.unique(np.round(ys, 6))
        linear = np.polyfit(ys, xs, 1)
        if len(unique_rows) < 5 or np.ptp(ys) < 0.05:
            return 0.0, float(linear[0]), float(linear[1])

        linear_residual = float(
            np.sqrt(np.mean((xs - np.polyval(linear, ys)) ** 2))
        )
        quadratic = np.polyfit(ys, xs, 2)
        quadratic_residual = float(
            np.sqrt(np.mean((xs - np.polyval(quadratic, ys)) ** 2))
        )
        if linear_residual < 1e-6:
            improvement = 0.0
        else:
            improvement = 1.0 - quadratic_residual / linear_residual
        if improvement < config.LANE_CURVE_MIN_IMPROVEMENT:
            return 0.0, float(linear[0]), float(linear[1])
        return tuple(float(v) for v in quadratic)

    @staticmethod
    def _eval_curve(curve: Tuple[float, float, float], y: float) -> float:
        a, b, c = curve
        return a * y * y + b * y + c

    @staticmethod
    def _median_curve(
        curves: Deque[Tuple[float, float, float]],
        fallback: Optional[Tuple[float, float, float]],
    ) -> Optional[Tuple[float, float, float]]:
        if not curves:
            return fallback
        values = np.asarray(curves, dtype=np.float32)
        return tuple(float(v) for v in np.median(values, axis=0))

    @staticmethod
    def _paint_mask(
        bgr_roi: np.ndarray,
        gray_roi: np.ndarray,
        input_gray: bool = False,
    ) -> np.ndarray:
        local_background = cv2.GaussianBlur(gray_roi, (0, 0), 5.0)
        local_lift = cv2.subtract(gray_roi, local_background)
        if input_gray:
            white = (
                (gray_roi >= config.LANE_WHITE_MIN_V) &
                (local_lift >= config.LANE_WHITE_LOCAL_DELTA)
            )
            yellow = np.zeros_like(white)
        else:
            hsv = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2HSV)
            hue, saturation, value = cv2.split(hsv)
            white = (
                (saturation <= config.LANE_WHITE_MAX_S) &
                (value >= config.LANE_WHITE_MIN_V) &
                (local_lift >= config.LANE_WHITE_LOCAL_DELTA)
            )
            yellow = (
                (hue >= config.LANE_YELLOW_H_MIN) &
                (hue <= config.LANE_YELLOW_H_MAX) &
                (saturation >= config.LANE_YELLOW_MIN_S) &
                (value >= config.LANE_YELLOW_MIN_V) &
                (local_lift >= config.LANE_WHITE_LOCAL_DELTA)
            )
        mask = (white | yellow).astype(np.uint8) * 255
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        )
        return mask

    @staticmethod
    def _occupancy(
        mask: np.ndarray,
        fit: Tuple[float, float],
        h: int,
        w: int,
    ) -> Tuple[float, float, int]:
        a, b = fit
        rows = np.arange(max(2, int(h * 0.08)), h - 1, 1.0)
        half = max(2, int(round(w * config.LANE_HALF_WIDTH_FRAC)))
        present = []
        for y in rows:
            x = int(round(a * y + b))
            if x < half or x >= w - half:
                present.append(False)
                continue
            row = int(y)
            present.append(bool(np.any(mask[row, x - half:x + half + 1])))
        present = np.asarray(present, dtype=bool)
        coverage = float(present.mean()) if len(present) else 0.0
        longest = 0
        run = 0
        gap_runs = 0
        for index, value in enumerate(present):
            run = 0 if value else run + 1
            longest = max(longest, run)
            if not value and (index == 0 or present[index - 1]):
                gap_runs += 1
        max_gap = float(longest) / float(len(present)) if len(present) else 1.0
        return coverage, max_gap, gap_runs

    def _update_geometry(self, result: LaneResult, width: int) -> None:
        if result.left_curve is None or result.right_curve is None:
            self._departure_count = 0
            self._departure_clear_count += 1
            if self._departure_clear_count >= config.LANE_DEPARTURE_CLEAR_N:
                self._departure = False
            result.departure = self._departure
            return
        left_x = self._eval_curve(result.left_curve, 1.0) * width
        right_x = self._eval_curve(result.right_curve, 1.0) * width
        lane_width = right_x - left_x
        width_frac = lane_width / float(width)
        if not (config.LANE_WIDTH_MIN_FRAC <= width_frac <=
                config.LANE_WIDTH_MAX_FRAC):
            result.departure = self._departure
            return
        center = (left_x + right_x) * 0.5
        result.center_offset = (center - width * 0.5) / (width * 0.5)
        result.curvature = abs(
            (result.left_curve[0] + result.right_curve[0]) * 0.5
        )
        if abs(result.center_offset) >= config.LANE_DEPARTURE_OFFSET_MAX:
            self._departure_count += 1
            self._departure_clear_count = 0
        else:
            self._departure_count = 0
            self._departure_clear_count += 1
        if self._departure_count >= config.LANE_DEPARTURE_CONFIRM_N:
            self._departure = True
        if self._departure_clear_count >= config.LANE_DEPARTURE_CLEAR_N:
            self._departure = False
        result.departure = self._departure

    @staticmethod
    def _build_bev(
        bgr: np.ndarray,
        curves: Dict[str, Optional[Tuple[float, float, float]]],
    ) -> np.ndarray:
        height, width = bgr.shape[:2]
        bev_w, bev_h = config.LANE_BEV_SIZE
        top_y = int(round(height * config.LANE_ROI_Y0))
        source = np.float32([
            [0.08 * width, height - 1],
            [0.33 * width, top_y],
            [0.67 * width, top_y],
            [0.92 * width, height - 1],
        ])
        destination = np.float32([
            [0, bev_h - 1],
            [0, 0],
            [bev_w - 1, 0],
            [bev_w - 1, bev_h - 1],
        ])
        matrix = cv2.getPerspectiveTransform(source, destination)
        bev = np.full((bev_h, bev_w, 3), 18, dtype=np.uint8)
        for yn in np.linspace(0.18, 0.82, 4):
            y = int(round(yn * (bev_h - 1)))
            cv2.line(bev, (0, y), (bev_w - 1, y), (45, 45, 45), 1)
        center_x = bev_w // 2
        cv2.line(
            bev, (center_x, 0), (center_x, bev_h - 1),
            (90, 90, 90), 1, cv2.LINE_AA,
        )
        samples = np.linspace(0.0, 1.0, 24)
        transformed_by_side = {}
        for side, curve in curves.items():
            if curve is None:
                continue
            points = []
            for yn in samples:
                source_x = LaneDetector._eval_curve(curve, float(yn)) * width
                source_y = top_y + yn * (height - 1 - top_y)
                points.append([source_x, source_y])
            transformed = cv2.perspectiveTransform(
                np.asarray([points], dtype=np.float32), matrix
            )[0]
            transformed_by_side[side] = transformed
        if "left" in transformed_by_side and "right" in transformed_by_side:
            corridor = np.vstack([
                transformed_by_side["left"],
                transformed_by_side["right"][::-1],
            ]).astype(np.int32)
            cv2.fillPoly(bev, [corridor], (16, 34, 24))
        for side in ("left", "right"):
            transformed = transformed_by_side.get(side)
            if transformed is None:
                continue
            color = (255, 255, 0) if side == "left" else (255, 0, 255)
            cv2.polylines(
                bev, [np.round(transformed).astype(np.int32)],
                False, color, 2, cv2.LINE_AA,
            )
        if curves.get("left") is not None and curves.get("right") is not None:
            points = []
            for yn in samples:
                left_x = LaneDetector._eval_curve(curves["left"], float(yn))
                right_x = LaneDetector._eval_curve(curves["right"], float(yn))
                source_x = (left_x + right_x) * 0.5 * width
                source_y = top_y + yn * (height - 1 - top_y)
                points.append([source_x, source_y])
            transformed = cv2.perspectiveTransform(
                np.asarray([points], dtype=np.float32), matrix
            )[0]
            cv2.polylines(
                bev, [np.round(transformed).astype(np.int32)],
                False, (0, 255, 0), 2, cv2.LINE_AA,
            )
        return bev

    @staticmethod
    def _coverage(gray_roi: np.ndarray,
                  fit: Tuple[float, float], h: int,
                  w: int) -> Tuple[float, float, int]:
        a, b = fit
        # Sample every row instead of a coarse fixed grid.  A coarse grid can
        # alias with the dash period and make a dashed line look solid.
        rows = np.arange(max(2, int(h * 0.08)), h - 1, 1.0)
        half = max(2, int(round(w * config.LANE_HALF_WIDTH_FRAC)))
        present = []
        for y in rows:
            x = int(round(a * y + b))
            if x < half or x >= w - half:
                present.append(False)
                continue
            row = int(y)
            window = gray_roi[row, x - half:x + half + 1]
            # A painted lane line is brighter than its local background.
            # This distinguishes a solid line from the gaps of a dashed one;
            # Canny edges alone also fire at dash ends and inflate coverage.
            if window.size:
                hi = int(window.max())
                med = float(np.median(window))
                bright = (
                    hi >= config.LANE_BRIGHT_MIN
                    and (hi - med >= config.LANE_BRIGHT_DELTA or med >= 140)
                )
            else:
                bright = False
            present.append(bool(bright))
        present = np.asarray(present, dtype=bool)
        coverage = float(present.mean()) if len(present) else 0.0
        longest = 0
        run = 0
        gap_runs = 0
        for index, p in enumerate(present):
            run = 0 if p else run + 1
            longest = max(longest, run)
            if not p and (index == 0 or present[index - 1]):
                gap_runs += 1
        max_gap = float(longest) / float(len(present)) if len(present) else 1.0
        return coverage, max_gap, gap_runs

    @staticmethod
    def _state_from_coverage(
        coverage: float,
        max_gap: float,
        gap_runs: int = 0,
    ) -> str:
        if coverage < config.LANE_DASH_MIN_COVERAGE:
            return "NONE"
        if gap_runs > config.LANE_SOLID_MAX_GAP_RUNS:
            return "DASHED"
        if coverage >= 0.45 and max_gap <= 0.50:
            return "SOLID"
        return "DASHED"

    def detect(self, bgr: np.ndarray, input_gray: bool = False) -> LaneResult:
        if bgr is None or bgr.size == 0:
            return LaneResult()
        h, w = bgr.shape[:2]
        y0 = int(round(h * config.LANE_ROI_Y0))
        roi_bgr = bgr[y0:]
        gray = (
            bgr[:, :, 0]
            if input_gray else
            cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        )
        roi = gray[y0:]
        paint = self._paint_mask(
            roi_bgr, roi, input_gray=input_gray
        )
        # The online path is already 320 px wide; reduce only that fixed-size
        # input.  High-resolution offline/card checks keep native detail.
        work_w = min(w, int(config.LANE_WORK_WIDTH)) if w <= 320 else w
        scale = work_w / float(w)
        if work_w < w:
            roi = cv2.resize(
                roi,
                (work_w, max(1, int(round(roi.shape[0] * scale)))),
                interpolation=cv2.INTER_AREA,
            )
            paint = cv2.resize(
                paint,
                (work_w, max(1, int(round(paint.shape[0] * scale)))),
                interpolation=cv2.INTER_NEAREST,
            )
        work_h = roi.shape[0]
        blurred = cv2.GaussianBlur(roi, (5, 5), 0)
        raw_edges = cv2.Canny(
            blurred, config.LANE_CANNY_LO, config.LANE_CANNY_HI
        )
        paint_dilated = cv2.dilate(
            paint,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        )
        edges = cv2.bitwise_and(raw_edges, paint_dilated)
        min_len = max(6, int(work_w * config.LANE_HOUGH_MIN_LINE_FRAC))
        max_gap = max(3, int(work_w * config.LANE_HOUGH_MAX_GAP_FRAC))
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180.0,
            threshold=config.LANE_HOUGH_THRESHOLD,
            minLineLength=min_len,
            maxLineGap=max_gap,
        )

        segments: Dict[str, List[Tuple[float, Tuple[int, int, int, int]]]] = {
            "left": [],
            "right": [],
        }
        if lines is not None:
            lines = np.asarray(lines)
            if lines.ndim == 3:
                lines = lines[:, 0, :]
            for line in lines:
                x1, y1, x2, y2 = [int(v) for v in line]
                side = self._line_side(x1, y1, x2, y2, work_w, work_h)
                if side is None:
                    continue
                dx = float(x2 - x1)
                if abs(dx) < 1e-6:
                    continue
                slope = (y2 - y1) / dx
                bottom_y = work_h - 1
                bottom_x = x1 + (bottom_y - y1) / slope
                segments[side].append((bottom_x, (x1, y1, x2, y2)))

        # Hough returns many short pieces from every visible boundary.  Fitting
        # all pieces together merges different lanes.  Cluster by bottom-x
        # first, then choose the valid lane boundary closest to the image
        # centre on each side.
        fits: Dict[str, Optional[Tuple[float, float]]] = {
            "left": None,
            "right": None,
        }
        curves: Dict[str, Optional[Tuple[float, float, float]]] = {
            "left": None,
            "right": None,
        }
        metrics: Dict[str, Tuple[float, float, int]] = {
            "left": (0.0, 1.0, 0),
            "right": (0.0, 1.0, 0),
        }
        tolerance = max(4.0, work_w * config.LANE_CLUSTER_X_FRAC)
        for side in ("left", "right"):
            ordered = sorted(segments[side], key=lambda item: item[0])
            clusters: List[List[Tuple[float, Tuple[int, int, int, int]]]] = []
            for segment in ordered:
                if not clusters or segment[0] - clusters[-1][-1][0] > tolerance:
                    clusters.append([segment])
                else:
                    clusters[-1].append(segment)

            candidates = []
            for cluster in clusters:
                points = []
                for _, segment in cluster:
                    x1, y1, x2, y2 = segment
                    points.extend(((float(y1), float(x1)), (float(y2), float(x2))))
                fit = self._fit(points)
                if fit is None:
                    continue
                cov, gap, gap_runs = self._occupancy(
                    paint, fit, work_h, work_w
                )
                if cov < config.LANE_DASH_MIN_COVERAGE:
                    continue
                normalized_points = [
                    (y / float(max(1, work_h - 1)),
                     x / float(max(1, work_w - 1)))
                    for y, x in points
                ]
                curve = self._fit_curve(normalized_points)
                if curve is None:
                    continue
                bottom_x = fit[0] * (work_h - 1) + fit[1]
                candidates.append((bottom_x, cov, gap, gap_runs, fit, curve))
            if candidates:
                previous_x = self._track_x[side]
                previous_slope = self._track_slope[side]
                continuous = []
                if previous_x is not None and previous_slope is not None:
                    for candidate in candidates:
                        x_err = abs(candidate[0] / float(work_w) - previous_x)
                        slope_err = abs(
                            candidate[4][0] - previous_slope
                        ) / max(abs(previous_slope), 1e-3)
                        if (x_err <= config.LANE_TRACK_X_FRAC and
                                slope_err <= config.LANE_TRACK_SLOPE_RATIO):
                            continuous.append((x_err + 0.1 * slope_err, candidate))
                if continuous:
                    chosen = min(continuous, key=lambda item: item[0])[1]
                elif side == "left":
                    chosen = max(candidates, key=lambda item: item[0])
                else:
                    chosen = min(candidates, key=lambda item: item[0])
                fits[side] = chosen[4]
                curves[side] = chosen[5]
                metrics[side] = (chosen[1], chosen[2], chosen[3])
                self._track_x[side] = chosen[0] / float(work_w)
                self._track_slope[side] = chosen[4][0]
                self._track_missed[side] = 0
            else:
                self._track_missed[side] += 1
                if self._track_missed[side] >= config.LANE_CLEAR_N:
                    self._track_x[side] = None
                    self._track_slope[side] = None

        states = {"left": "NONE", "right": "NONE"}
        coverage = {"left": 0.0, "right": 0.0}
        gap_runs = {"left": 0, "right": 0}
        result_lines: Dict[str, Optional[Line]] = {"left": None, "right": None}

        for side in ("left", "right"):
            fit = fits[side]
            if fit is None:
                continue
            a, b = fit
            cov, gap, runs = metrics[side]
            coverage[side] = cov
            gap_runs[side] = runs
            states[side] = self._state_from_coverage(cov, gap, runs)
            y_top = int(work_h * 0.08)
            y_bottom = work_h - 2
            x_top = int(round(a * y_top + b))
            x_bottom = int(round(a * y_bottom + b))
            inv_scale = 1.0 / scale
            result_lines[side] = (
                int(round(x_top * inv_scale)),
                int(round(y_top * inv_scale + y0)),
                int(round(x_bottom * inv_scale)),
                int(round(y_bottom * inv_scale + y0)),
            )

        pair_valid = (
            curves["left"] is not None and
            curves["right"] is not None
        )
        if pair_valid:
            left_bottom = self._eval_curve(curves["left"], 1.0) * work_w
            right_bottom = self._eval_curve(curves["right"], 1.0) * work_w
            width_fraction = (right_bottom - left_bottom) / float(work_w)
            pair_valid = (
                right_bottom > left_bottom and
                config.LANE_WIDTH_MIN_FRAC <= width_fraction <=
                config.LANE_WIDTH_MAX_FRAC
            )
        if not pair_valid:
            states["left"] = "NONE"
            states["right"] = "NONE"
            curves["left"] = None
            curves["right"] = None
            result_lines["left"] = None
            result_lines["right"] = None

        return LaneResult(
            left_state=states["left"],
            right_state=states["right"],
            left_line=result_lines["left"],
            right_line=result_lines["right"],
            coverage_left=coverage["left"],
            coverage_right=coverage["right"],
            max_gap_left=metrics["left"][1],
            max_gap_right=metrics["right"][1],
            gap_runs_left=gap_runs["left"],
            gap_runs_right=gap_runs["right"],
            left_curve=curves["left"],
            right_curve=curves["right"],
            bev=self._build_bev(bgr, curves),
            edges=edges,
        )

    @staticmethod
    def _vote(history: Deque[str], stable: str, vote_n: int) -> str:
        if not history:
            return stable
        if vote_n <= 1:
            return history[-1]
        counts = Counter(history)
        if stable == "NONE":
            for name in ("SOLID", "DASHED"):
                needed = min(vote_n, max(1, int(config.LANE_ENTER_N)))
                if counts.get(name, 0) >= needed:
                    return name
            return "NONE"
        if counts.get(stable, 0) == len(history):
            return stable
        for name in ("SOLID", "DASHED", "NONE"):
            if name == stable:
                continue
            needed = (
                config.LANE_CLEAR_N
                if name == "NONE"
                else config.LANE_SWITCH_N
            )
            needed = min(vote_n, max(1, int(needed)))
            if counts.get(name, 0) >= needed:
                return name
        return stable

    @staticmethod
    def _median_line(lines: Deque[Line], fallback: Optional[Line]) -> Optional[Line]:
        if not lines:
            return fallback
        values = np.asarray(lines, dtype=np.float32)
        return tuple(int(round(v)) for v in np.median(values, axis=0))

    def update(self, bgr: np.ndarray, input_gray: bool = False) -> LaneResult:
        result = self.detect(bgr, input_gray=input_gray)
        self._left_hist.append(result.left_state)
        self._right_hist.append(result.right_state)
        self._left_stable = self._vote(self._left_hist, self._left_stable, self.vote_n)
        self._right_stable = self._vote(self._right_hist, self._right_stable, self.vote_n)
        if (result.left_line is not None and
                result.left_state == self._left_stable):
            self._left_lines.append(result.left_line)
        if (result.right_line is not None and
                result.right_state == self._right_stable):
            self._right_lines.append(result.right_line)
        if (result.left_curve is not None and
                result.left_state == self._left_stable):
            self._left_curves.append(result.left_curve)
        if (result.right_curve is not None and
                result.right_state == self._right_stable):
            self._right_curves.append(result.right_curve)
        if self._left_stable == "NONE":
            self._left_lines.clear()
            self._left_curves.clear()
            result.left_line = None
            result.left_curve = None
        else:
            result.left_line = self._median_line(
                self._left_lines, result.left_line
            )
            result.left_curve = self._median_curve(
                self._left_curves, result.left_curve
            )
        if self._right_stable == "NONE":
            self._right_lines.clear()
            self._right_curves.clear()
            result.right_line = None
            result.right_curve = None
        else:
            result.right_line = self._median_line(
                self._right_lines, result.right_line
            )
            result.right_curve = self._median_curve(
                self._right_curves, result.right_curve
            )
        result.left_state = self._left_stable
        result.right_state = self._right_stable
        self._update_geometry(result, bgr.shape[1])
        return result


class ObstacleDetector:
    """Multi-frame background model for static small-environment objects.

    The camera is assumed to be fixed or gently shaken.  A short empty-scene
    learning phase builds a median background; phase correlation compensates
    small translation.  Objects introduced after learning are boxed regardless
    of whether they move.  A large camera pan or low phase-correlation response
    forces a fresh background learning pass instead of reporting the whole
    scene as an obstacle.
    """

    def __init__(self, learn_frames: Optional[int] = None):
        self.learn_frames = int(learn_frames or config.OBSTACLE_LEARN_FRAMES)
        self.enabled = True
        self._samples: List[np.ndarray] = []
        self._background: Optional[np.ndarray] = None
        self._background_age = 0
        self._confirm = 0
        self._hold = 0
        self._last_boxes: List[Box] = []
        self._last_ids: List[int] = []
        self._last_shift: Tuple[float, float] = (0.0, 0.0)
        self._next_track_id = 1

    def reset(self) -> None:
        self._samples = []
        self._background = None
        self._background_age = 0
        self._confirm = 0
        self._hold = 0
        self._last_boxes = []
        self._last_ids = []
        self._last_shift = (0.0, 0.0)
        self._next_track_id = 1

    def relearn(self) -> None:
        self.reset()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self.reset()

    @staticmethod
    def _nms(boxes: List[Box], threshold: float = 0.25) -> List[Box]:
        boxes = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
        kept: List[Box] = []
        for box in boxes:
            x, y, w, h = box
            area = float(w * h)
            keep = True
            for kx, ky, kw, kh in kept:
                x1 = max(x, kx)
                y1 = max(y, ky)
                x2 = min(x + w, kx + kw)
                y2 = min(y + h, ky + kh)
                inter = max(0, x2 - x1) * max(0, y2 - y1)
                union = area + kw * kh - inter
                if union > 0 and inter / union > threshold:
                    keep = False
                    break
            if keep:
                kept.append(box)
        return kept[:6]

    @staticmethod
    def _merge_boxes(boxes: List[Box], width: int, height: int) -> List[Box]:
        """Merge fragments of one nearby object split by lighting/shadows."""

        def should_merge(a: Box, b: Box) -> bool:
            ax, ay, aw, ah = a
            bx, by, bw, bh = b
            ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
            iy = max(0, min(ay + ah, by + bh) - max(ay, by))
            union = aw * ah + bw * bh - ix * iy
            iou = (ix * iy) / float(union) if union else 0.0
            if iou > 0.04:
                return True
            gap_x = max(0, max(ax, bx) - min(ax + aw, bx + bw))
            gap_y = max(0, max(ay, by) - min(ay + ah, by + bh))
            if (iy >= 0.30 * min(ah, bh) and gap_x <= 0.04 * width):
                return True
            if (ix >= 0.30 * min(aw, bw) and gap_y <= 0.03 * height):
                return True
            return False

        merged = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
        changed = True
        while changed:
            changed = False
            out: List[Box] = []
            for box in merged:
                placed = False
                for i, other in enumerate(out):
                    if should_merge(box, other):
                        x1 = min(box[0], other[0])
                        y1 = min(box[1], other[1])
                        x2 = max(box[0] + box[2], other[0] + other[2])
                        y2 = max(box[1] + box[3], other[1] + other[3])
                        out[i] = (x1, y1, x2 - x1, y2 - y1)
                        placed = True
                        changed = True
                        break
                if not placed:
                    out.append(box)
            merged = out
        return sorted(merged, key=lambda b: b[2] * b[3], reverse=True)[:6]

    @staticmethod
    def _smooth_boxes(boxes: List[Box], previous: List[Box],
                      alpha: float) -> List[Box]:
        """Associate nearby boxes between updates and damp coordinate jumps."""

        if not previous:
            return boxes
        alpha = min(1.0, max(0.05, float(alpha)))
        unmatched = list(previous)
        smoothed: List[Box] = []
        for box in boxes:
            x, y, w, h = box
            cx, cy = x + w * 0.5, y + h * 0.5
            best = None
            best_distance = None
            for old in unmatched:
                ox, oy, ow, oh = old
                ocx, ocy = ox + ow * 0.5, oy + oh * 0.5
                distance = float(np.hypot(cx - ocx, cy - ocy))
                limit = 0.75 * max(w, h, ow, oh)
                if distance <= limit and (best_distance is None or distance < best_distance):
                    best = old
                    best_distance = distance
            if best is None:
                smoothed.append(box)
                continue
            unmatched.remove(best)
            blended = [
                (1.0 - alpha) * old + alpha * new
                for old, new in zip(best, box)
            ]
            smoothed.append(tuple(int(round(v)) for v in blended))
        return smoothed

    def _assign_track_ids(
        self, boxes: List[Box], previous_boxes: List[Box]
    ) -> List[int]:
        previous = list(zip(previous_boxes, self._last_ids))
        assigned = []
        for box in boxes:
            x, y, w, h = box
            cx, cy = x + w * 0.5, y + h * 0.5
            best = None
            best_distance = None
            for index, (old, track_id) in enumerate(previous):
                ox, oy, ow, oh = old
                distance = float(np.hypot(
                    cx - (ox + ow * 0.5), cy - (oy + oh * 0.5)
                ))
                limit = config.TRACK_MAX_DISTANCE_FACTOR * max(w, h, ow, oh)
                if distance <= limit and (
                        best_distance is None or distance < best_distance):
                    best = (index, track_id)
                    best_distance = distance
            if best is None:
                assigned.append(self._next_track_id)
                self._next_track_id += 1
            else:
                index, track_id = best
                previous.pop(index)
                assigned.append(track_id)
        return assigned

    def _align(self, gray: np.ndarray):
        assert self._background is not None
        bg = np.clip(self._background, 0, 255).astype(np.uint8)
        try:
            (dx, dy), response = cv2.phaseCorrelate(
                np.float32(bg), np.float32(gray)
            )
        except cv2.error:
            return None
        if (abs(dx) > config.OBSTACLE_MAX_SHIFT_PX or
                abs(dy) > config.OBSTACLE_MAX_SHIFT_PX):
            return None
        if response < config.OBSTACLE_MIN_CORR:
            # A large new object can reduce the phase-correlation response
            # even when the camera is fixed.  Keep the current background
            # (zero shift) instead of throwing the object into a relearn.
            dx = 0.0
            dy = 0.0
        matrix = np.float32([[1, 0, -dx], [0, 1, -dy]])
        aligned = cv2.warpAffine(
            gray, matrix, (gray.shape[1], gray.shape[0]),
            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
        )
        return aligned, (float(dx), float(dy)), float(response)

    def update(self, bgr: np.ndarray) -> ObstacleResult:
        if not self.enabled or bgr is None or bgr.size == 0:
            return ObstacleResult()
        h, w = bgr.shape[:2]
        work = cv2.resize(
            bgr, config.OBSTACLE_WORK_SIZE, interpolation=cv2.INTER_AREA
        )
        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

        if self._background is None:
            self._samples.append(gray.astype(np.float32))
            if len(self._samples) < self.learn_frames:
                return ObstacleResult(
                    learning=True,
                    background_age=len(self._samples),
                )
            self._background = np.median(
                np.stack(self._samples, axis=0), axis=0
            ).astype(np.float32)
            self._samples = []
            self._background_age = self.learn_frames
            return ObstacleResult(
                learning=False,
                background_age=self._background_age,
            )

        aligned_result = self._align(gray)
        if aligned_result is None:
            self.relearn()
            return ObstacleResult(learning=True, background_age=0)
        aligned, shift, _response = aligned_result
        self._last_shift = shift

        diff = cv2.absdiff(self._background, aligned.astype(np.float32))
        mask = cv2.threshold(
            diff, config.OBSTACLE_DIFF_THRESHOLD, 255, cv2.THRESH_BINARY
        )[1].astype(np.uint8)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        frame_area = float(gray.shape[0] * gray.shape[1])
        boxes: List[Box] = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            frac = area / frame_area
            if frac < config.OBSTACLE_MIN_AREA_FRAC or frac > config.OBSTACLE_MAX_AREA_FRAC:
                continue
            x, y, bw, bh = cv2.boundingRect(contour)
            aspect = bw / float(bh) if bh else 0.0
            if aspect < config.OBSTACLE_ASPECT_MIN or aspect > config.OBSTACLE_ASPECT_MAX:
                continue
            sx = w / float(gray.shape[1])
            sy = h / float(gray.shape[0])
            boxes.append((int(x * sx), int(y * sy), int(bw * sx), int(bh * sy)))
        boxes = self._merge_boxes(self._nms(boxes), w, h)

        if boxes:
            self._confirm += 1
            self._hold = config.OBSTACLE_HOLD_FRAMES
            previous_boxes = self._last_boxes
            self._last_boxes = self._smooth_boxes(
                boxes, self._last_boxes, config.OBSTACLE_SMOOTH_ALPHA
            )
            self._last_ids = self._assign_track_ids(
                self._last_boxes, previous_boxes
            )
        else:
            self._confirm = 0
            if self._hold > 0:
                self._hold -= 1
            if self._hold == 0:
                self._last_boxes = []
                self._last_ids = []

        confirmed = (self._confirm >= config.OBSTACLE_CONFIRM_FRAMES or
                     self._hold > 0)
        out_boxes = self._last_boxes if confirmed else []
        near = False
        for x, y, bw, bh in out_boxes:
            cx = (x + bw * 0.5) / float(w)
            cy = (y + bh * 0.5) / float(h)
            if (cy >= config.OBSTACLE_NEAR_Y0 and
                    config.OBSTACLE_NEAR_X0 <= cx <= config.OBSTACLE_NEAR_X1):
                near = True

        # Update only pixels not covered by foreground objects.  This keeps a
        # newly placed bottle/box from being absorbed into the background.
        update_mask = mask == 0
        if np.any(update_mask):
            a = np.float32(config.OBSTACLE_BG_ALPHA)
            bg = self._background
            bg[update_mask] = ((1.0 - a) * bg[update_mask] +
                               a * aligned.astype(np.float32)[update_mask])
            self._background = bg
        self._background_age += 1

        return ObstacleResult(
            present=bool(confirmed and near),
            boxes=out_boxes,
            track_ids=self._last_ids if confirmed else [],
            motion_area=float(np.count_nonzero(mask)) / float(mask.size),
            kind="OBJECT",
            near=near,
            learning=False,
            background_age=self._background_age,
            shift=self._last_shift,
        )


PERCEPTION_MODES = ("traffic_light", "lane", "obstacle")


class PerceptionPipeline:
    """Per-frame orchestration for exactly one active perception mode."""

    def __init__(self, lane_every: int = config.LANE_EVERY_N,
                 mode: str = "traffic_light", input_gray: bool = False):
        if mode not in PERCEPTION_MODES:
            raise ValueError(
                "mode must be one of: %s" % ", ".join(PERCEPTION_MODES)
            )
        self.mode = mode
        self.input_gray = bool(input_gray)
        self.traffic_light = TrafficLightDetector()
        self.lanes = LaneDetector()
        self.obstacle = ObstacleDetector()
        self.lane_every = max(1, int(lane_every))
        self.tl_every = max(1, int(config.TL_EVERY_N))
        self.obstacle_every = max(1, int(config.OBSTACLE_EVERY_N))
        self._tl_cache = TrafficLightResult()
        self._lane_cache = LaneResult()
        self._obstacle_cache = ObstacleResult()
        self.obstacle.set_enabled(self.mode == "obstacle")

    def reset(self) -> None:
        self.traffic_light.reset()
        self.lanes.reset()
        self.obstacle.set_enabled(self.mode == "obstacle")
        self._tl_cache = TrafficLightResult()
        self._lane_cache = LaneResult()
        self._obstacle_cache = ObstacleResult()

    def set_mode(self, mode: str) -> None:
        if mode not in PERCEPTION_MODES:
            raise ValueError(
                "mode must be one of: %s" % ", ".join(PERCEPTION_MODES)
            )
        self.mode = mode
        self.reset()

    def relearn_background(self) -> None:
        if self.mode != "obstacle":
            raise RuntimeError("background relearn is only valid in obstacle mode")
        self.obstacle.relearn()

    def process(self, bgr: np.ndarray, frame_idx: int) -> PerceptionResult:
        if self.mode == "traffic_light":
            if frame_idx % self.tl_every == 0:
                self._tl_cache = self.traffic_light.update(bgr)
            return PerceptionResult(
                traffic_light=self._tl_cache,
                lanes=LaneResult(),
                obstacle=ObstacleResult(),
            )
        if self.mode == "lane":
            if frame_idx % self.lane_every == 0:
                self._lane_cache = self.lanes.update(
                    bgr, input_gray=self.input_gray
                )
            return PerceptionResult(
                traffic_light=TrafficLightResult(),
                lanes=self._lane_cache,
                obstacle=ObstacleResult(),
            )
        if frame_idx % self.obstacle_every == 0:
            self._obstacle_cache = self.obstacle.update(bgr)
        return PerceptionResult(
            traffic_light=TrafficLightResult(),
            lanes=LaneResult(),
            obstacle=self._obstacle_cache,
        )


__all__ = [
    "LaneDetector",
    "LaneResult",
    "ObstacleDetector",
    "ObstacleResult",
    "PerceptionPipeline",
    "PerceptionResult",
    "PERCEPTION_MODES",
    "TrafficLightDetector",
    "TrafficLightResult",
]
