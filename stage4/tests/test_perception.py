import unittest
from collections import deque

import cv2
import numpy as np

import config
from decision import Decision
from osd import color_bars, compose, to_lcd
from perception import (
    LaneDetector,
    ObstacleDetector,
    PerceptionPipeline,
    PerceptionResult,
    TrafficLightDetector,
)


def blank(w=640, h=480, value=70):
    return np.full((h, w, 3), value, dtype=np.uint8)


def dashed_line(img, p1, p2, color=(255, 255, 255), thickness=5,
                dash=18, gap=14):
    x1, y1 = p1
    x2, y2 = p2
    length = int(np.hypot(x2 - x1, y2 - y1))
    if length <= 0:
        return
    dx = (x2 - x1) / float(length)
    dy = (y2 - y1) / float(length)
    pos = 0
    while pos < length:
        a = (int(x1 + dx * pos), int(y1 + dy * pos))
        b = (int(x1 + dx * min(length, pos + dash)), int(y1 + dy * min(length, pos + dash)))
        cv2.line(img, a, b, color, thickness, cv2.LINE_AA)
        pos += dash + gap


class TrafficLightTest(unittest.TestCase):
    def test_red_green_yellow(self):
        det = TrafficLightDetector(vote_n=1)
        for bgr, expected in (
            ((0, 0, 255), "RED"),
            ((0, 255, 0), "GREEN"),
            ((0, 255, 255), "YELLOW"),
        ):
            img = blank(320, 240, 20)
            cv2.circle(img, (160, 120), 22, bgr, -1, cv2.LINE_AA)
            result = det.detect(img)
            self.assertEqual(result.state, expected, (expected, result.boxes))
            self.assertGreaterEqual(result.circularity, config.TL_MIN_CIRCULARITY)
            self.assertGreaterEqual(result.convexity, config.TL_MIN_CONVEXITY)
            self.assertGreaterEqual(
                result.inertia_ratio, config.TL_MIN_INERTIA_RATIO
            )

    def test_non_circular_colour_regions_are_rejected(self):
        det = TrafficLightDetector(vote_n=1)
        square = blank(320, 240, 20)
        cv2.rectangle(square, (120, 80), (200, 160), (0, 0, 255), -1)
        self.assertEqual(det.detect(square).state, "NONE")
        strip = blank(320, 240, 20)
        cv2.rectangle(strip, (40, 105), (280, 135), (0, 0, 255), -1)
        self.assertEqual(det.detect(strip).state, "NONE")

    def test_vote_holds_through_one_missed_frame(self):
        det = TrafficLightDetector(vote_n=3)
        red = blank(320, 240, 20)
        cv2.circle(red, (160, 120), 22, (0, 0, 255), -1, cv2.LINE_AA)
        empty = blank(320, 240, 20)
        det.update(red)
        det.update(red)
        result = det.update(empty)
        self.assertEqual(result.state, "RED")

    def test_colour_switch_requires_three_confirmations(self):
        det = TrafficLightDetector(vote_n=3)
        red = blank(320, 240, 20)
        cv2.circle(red, (160, 120), 22, (0, 0, 255), -1, cv2.LINE_AA)
        yellow = blank(320, 240, 20)
        cv2.circle(yellow, (160, 120), 22, (0, 255, 255), -1, cv2.LINE_AA)
        det.update(red)
        det.update(red)
        result = det.update(red)
        self.assertEqual(result.state, "RED")
        self.assertEqual(det.update(yellow).state, "RED")
        self.assertEqual(det.update(yellow).state, "RED")
        self.assertEqual(det.update(yellow).state, "YELLOW")

    def test_small_jitter_keeps_traffic_state_stable(self):
        for bgr, expected in (
            ((0, 0, 255), "RED"),
            ((0, 255, 0), "GREEN"),
            ((0, 255, 255), "YELLOW"),
        ):
            det = TrafficLightDetector(vote_n=3)
            states = []
            for index in range(30):
                img = blank(320, 240, 20)
                x = 158 + (index % 5)
                cv2.circle(img, (x, 120), 22, bgr, -1, cv2.LINE_AA)
                states.append(det.update(img).state)
            self.assertTrue(
                all(state == expected for state in states[2:]),
                (expected, states),
            )

    def test_traffic_track_id_persists_and_reacquires(self):
        det = TrafficLightDetector(vote_n=3)
        red = blank(320, 240, 20)
        cv2.circle(red, (160, 120), 22, (0, 0, 255), -1, cv2.LINE_AA)
        empty = blank(320, 240, 20)
        for _ in range(3):
            result = det.update(red)
        first_id = result.track_id
        self.assertGreater(first_id, 0)
        for _ in range(3):
            result = det.update(empty)
        self.assertEqual(result.track_id, 0)
        for _ in range(2):
            result = det.update(red)
        self.assertGreater(result.track_id, first_id)

    def test_overexposed_red_ring_falls_back(self):
        det = TrafficLightDetector(vote_n=1)
        img = blank(320, 240, 70)
        cv2.circle(img, (160, 120), 52, (150, 150, 255), -1, cv2.LINE_AA)
        cv2.circle(img, (160, 120), 34, (255, 255, 255), -1, cv2.LINE_AA)
        result = det.detect(img)
        self.assertEqual(result.state, "RED", result.boxes)
        self.assertTrue(result.relaxed)

    def test_red_emitter_wins_over_larger_green_background(self):
        det = TrafficLightDetector(vote_n=1)
        img = blank(320, 240, 20)
        cv2.rectangle(img, (120, 20), (300, 220), (0, 110, 0), -1)
        cv2.circle(img, (160, 120), 14, (0, 0, 255), -1, cv2.LINE_AA)
        result = det.detect(img)
        self.assertEqual(result.state, "RED", result.boxes)


class LaneTest(unittest.TestCase):
    def _lanes(self, dashed=False):
        img = blank()
        left = ((70, 470), (300, 270))
        right = ((570, 470), (340, 270))
        if dashed:
            dashed_line(img, *left)
            dashed_line(img, *right)
        else:
            cv2.line(img, *left, (255, 255, 255), 6, cv2.LINE_AA)
            cv2.line(img, *right, (255, 255, 255), 6, cv2.LINE_AA)
        return img

    def test_solid_left_right(self):
        det = LaneDetector(vote_n=1)
        result = det.detect(self._lanes(False))
        self.assertEqual(result.left_state, "SOLID", result)
        self.assertEqual(result.right_state, "SOLID", result)
        self.assertIsNotNone(result.left_line)
        self.assertIsNotNone(result.right_line)

    def test_dashed_left_right(self):
        det = LaneDetector(vote_n=1)
        result = det.detect(self._lanes(True))
        self.assertEqual(result.left_state, "DASHED", result)
        self.assertEqual(result.right_state, "DASHED", result)

    def test_lane_detector_accepts_hardware_gray_input(self):
        det = LaneDetector(vote_n=1)
        color = self._lanes(False)
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        replicated = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        result = det.detect(replicated, input_gray=True)
        self.assertEqual(result.left_state, "SOLID", result)
        self.assertEqual(result.right_state, "SOLID", result)

    def test_solid_lane_survives_small_camera_jitter(self):
        det = LaneDetector(vote_n=5)
        base = self._lanes(False)
        states = []
        for index in range(30):
            dx = (-2, 0, 2)[index % 3]
            dy = (-1, 1)[index % 2]
            shifted = cv2.warpAffine(
                base, np.float32([[1, 0, dx], [0, 1, dy]]),
                (base.shape[1], base.shape[0]),
                borderMode=cv2.BORDER_REPLICATE,
            )
            states.append(det.update(shifted).left_state)
        self.assertTrue(all(state == "SOLID" for state in states[4:]), states)

    def test_lane_geometry_and_bev(self):
        det = LaneDetector(vote_n=5)
        result = None
        for _ in range(6):
            result = det.update(self._lanes(False))
        self.assertIsNotNone(result.left_curve)
        self.assertIsNotNone(result.right_curve)
        self.assertIsNotNone(result.bev)
        self.assertEqual(result.bev.shape[:2], (96, 160))
        self.assertLess(abs(result.center_offset), 0.05)
        self.assertGreaterEqual(result.curvature, 0.0)

    def test_straight_points_prefer_linear_fit(self):
        points = [
            (index / 100.0, 0.30 + index * 0.003)
            for index in range(30)
        ]
        curve = LaneDetector._fit_curve(points)
        self.assertIsNotNone(curve)
        self.assertAlmostEqual(curve[0], 0.0, places=6)

    def test_solid_tolerates_small_edge_gaps(self):
        self.assertEqual(
            LaneDetector._state_from_coverage(0.84, 0.20, 2),
            "SOLID",
        )
        self.assertEqual(
            LaneDetector._state_from_coverage(0.29, 0.90, 8),
            "DASHED",
        )
        self.assertEqual(
            LaneDetector._state_from_coverage(0.65, 0.38, 2),
            "SOLID",
        )

    def test_lane_paint_mask_accepts_white_and_yellow(self):
        image = blank(320, 240, 45)
        cv2.line(image, (30, 230), (130, 40), (245, 245, 245), 6)
        cv2.line(image, (290, 230), (190, 40), (0, 220, 220), 6)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        white = (
            (hsv[:, :, 1] <= config.LANE_WHITE_MAX_S) &
            (hsv[:, :, 2] >= config.LANE_WHITE_MIN_V)
        )
        self.assertGreater(int(white.sum()), 0)
        mask = LaneDetector._paint_mask(
            image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        )
        self.assertGreater(int(np.count_nonzero(mask)), 200)

    def test_single_background_line_is_rejected(self):
        image = blank()
        cv2.line(image, (70, 470), (300, 270), (255, 255, 255), 6)
        result = LaneDetector(vote_n=1).detect(image)
        self.assertEqual(result.left_state, "NONE")
        self.assertEqual(result.right_state, "NONE")

    def test_lane_departure_after_shift(self):
        det = LaneDetector(vote_n=5)
        shifted = cv2.warpAffine(
            self._lanes(False),
            np.float32([[1, 0, 70], [0, 1, 0]]),
            (640, 480),
            borderMode=cv2.BORDER_REPLICATE,
        )
        result = None
        for _ in range(8):
            result = det.update(shifted)
        self.assertGreater(result.center_offset, config.LANE_DEPARTURE_OFFSET_MAX)
        self.assertTrue(result.departure)

    def test_lane_switch_hysteresis(self):
        stable = LaneDetector._vote(
            deque(["SOLID", "SOLID"], maxlen=5), "DASHED", 5
        )
        self.assertEqual(stable, "DASHED")
        stable = LaneDetector._vote(
            deque(["SOLID", "SOLID", "SOLID"], maxlen=5), "DASHED", 5
        )
        self.assertEqual(stable, "SOLID")
        stable = LaneDetector._vote(
            deque(["DASHED"], maxlen=5), "NONE", 5
        )
        self.assertEqual(stable, "NONE")
        stable = LaneDetector._vote(
            deque(["DASHED", "DASHED"], maxlen=5), "NONE", 5
        )
        self.assertEqual(stable, "DASHED")


class ObstacleTest(unittest.TestCase):
    def textured(self, seed=1):
        rng = np.random.RandomState(seed)
        noise = rng.randint(0, 55, (240, 320), dtype=np.uint8)
        noise = cv2.GaussianBlur(noise, (7, 7), 0)
        return cv2.cvtColor(noise, cv2.COLOR_GRAY2BGR)

    def learned(self, det, bg, frames=6):
        result = None
        for _ in range(frames):
            result = det.update(bg)
        return result

    def test_static_object_after_background_learning(self):
        bg = self.textured()
        det = ObstacleDetector(learn_frames=6)
        self.learned(det, bg)
        obj = bg.copy()
        cv2.rectangle(obj, (125, 120), (200, 225), (240, 240, 240), -1)
        for _ in range(3):
            result = det.update(obj)
        self.assertTrue(result.boxes, result)
        self.assertTrue(all(track_id > 0 for track_id in result.track_ids))
        self.assertEqual(result.track_ids, [1])
        self.assertTrue(result.present, result)
        self.assertTrue(result.near, result)
        for _ in range(4):
            result = det.update(obj)
        self.assertTrue(result.present, result)
        for _ in range(12):
            result = det.update(bg)
        self.assertFalse(result.present, result)

    def test_far_object_is_boxed_but_not_near_alarm(self):
        bg = self.textured(2)
        det = ObstacleDetector(learn_frames=6)
        self.learned(det, bg)
        obj = bg.copy()
        cv2.rectangle(obj, (125, 15), (200, 75), (240, 240, 240), -1)
        for _ in range(3):
            result = det.update(obj)
        self.assertTrue(result.boxes, result)
        self.assertFalse(result.present, result)
        self.assertFalse(result.near, result)

    def test_small_camera_shift_is_compensated(self):
        bg = self.textured(3)
        det = ObstacleDetector(learn_frames=6)
        self.learned(det, bg)
        shifted = cv2.warpAffine(
            bg, np.float32([[1, 0, 3], [0, 1, 2]]), (320, 240),
            borderMode=cv2.BORDER_REPLICATE,
        )
        result = None
        for _ in range(4):
            result = det.update(shifted)
        self.assertFalse(result.boxes, result)
        self.assertFalse(result.present, result)

    def test_large_shift_relearns_background(self):
        bg = self.textured(4)
        det = ObstacleDetector(learn_frames=6)
        self.learned(det, bg)
        shifted = cv2.warpAffine(
            bg, np.float32([[1, 0, 20], [0, 1, 0]]), (320, 240),
            borderMode=cv2.BORDER_REPLICATE,
        )
        result = det.update(shifted)
        self.assertTrue(result.learning, result)
        self.assertFalse(result.present, result)

    def test_traffic_mode_disables_other_detectors(self):
        pipe = PerceptionPipeline(mode="traffic_light")
        bg = self.textured(5)
        obj = bg.copy()
        cv2.rectangle(obj, (120, 120), (200, 225), (240, 240, 240), -1)
        result = None
        for i in range(8):
            result = pipe.process(obj, i)
        self.assertFalse(result.obstacle.present, result.obstacle)
        self.assertFalse(result.obstacle.boxes, result.obstacle)
        self.assertEqual(result.lanes.left_state, "NONE")
        self.assertEqual(result.lanes.right_state, "NONE")

    def test_lane_mode_disables_other_detectors(self):
        pipe = PerceptionPipeline(mode="lane")
        image = LaneTest()._lanes(False)
        for i in range(8):
            result = pipe.process(image, i)
        self.assertEqual(result.traffic_light.state, "NONE")
        self.assertFalse(result.obstacle.present)
        self.assertFalse(result.obstacle.boxes)

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            PerceptionPipeline(mode="cards")
        with self.assertRaises(ValueError):
            PerceptionPipeline(mode="environment")

    def test_mode_switch_clears_previous_state(self):
        pipe = PerceptionPipeline(mode="traffic_light")
        red = blank(320, 240, 20)
        cv2.circle(red, (160, 120), 22, (0, 0, 255), -1, cv2.LINE_AA)
        pipe.process(red, 0)
        pipe.process(red, 4)
        self.assertEqual(
            pipe.traffic_light._stable,
            "RED",
        )
        pipe.set_mode("lane")
        switched = pipe.process(blank(320, 240, 20), 0)
        self.assertEqual(switched.traffic_light.state, "NONE")
        self.assertFalse(switched.obstacle.present)
        pipe.set_mode("obstacle")
        learning = pipe.process(blank(320, 240, 20), 0)
        self.assertTrue(learning.obstacle.learning)
        self.assertEqual(learning.traffic_light.state, "NONE")
        self.assertEqual(learning.lanes.left_state, "NONE")

    def test_obstacle_box_smoothing(self):
        smooth = ObstacleDetector._smooth_boxes(
            [(104, 48, 156, 192)],
            [(100, 50, 156, 192)],
            0.35,
        )
        self.assertEqual(len(smooth), 1)
        self.assertGreater(smooth[0][0], 100)
        self.assertLess(smooth[0][0], 104)


class OsdTest(unittest.TestCase):
    def test_compose_and_lcd_shape(self):
        bgr = blank(640, 480, 80)
        from perception import (
            LaneResult, ObstacleResult, TrafficLightResult,
        )
        perception = PerceptionResult(
            traffic_light=TrafficLightResult(state="RED"),
            lanes=LaneResult(left_state="SOLID", right_state="DASHED"),
            obstacle=ObstacleResult(present=False),
        )
        decision = Decision(tl_state=1, lane_left=1, lane_right=2)
        out = compose(bgr, perception, decision, {"led": 2, "beep": 0,
                      "wd_timeout": 0, "alarm_reason": 0}, 12.5)
        self.assertEqual(out.shape, (480, 800, 3))
        lcd = to_lcd(out)
        self.assertEqual(lcd.shape, (480, 800, 3))
        self.assertEqual(lcd.dtype, np.uint8)

    def test_lcd_red_channel_order_and_bars(self):
        red_bgr = np.zeros((480, 800, 3), dtype=np.uint8)
        red_bgr[:, :] = (0, 0, 255)
        lcd = to_lcd(red_bgr)
        # The physical LCD path was verified on the board to require BGR
        # framebuffer bytes; keeping the default OpenCV order prevents red and
        # blue from being exchanged on screen.
        self.assertTrue(config.LCD_FRAMEBUFFER_BGR)
        self.assertLess(int(lcd[240, 400, 0]), 5)
        self.assertGreater(int(lcd[240, 400, 2]), 250)
        bars = color_bars()
        self.assertEqual(bars.shape, (480, 800, 3))
        self.assertGreater(int(bars[300, 600, 2]), 250)

    def test_lane_mode_draws_curve_and_bev(self):
        from perception import ObstacleResult, TrafficLightResult

        lanes = LaneTest()._lanes(False)
        detector = LaneDetector(vote_n=5)
        result = None
        for _ in range(6):
            result = detector.update(lanes)
        perception = PerceptionResult(
            traffic_light=TrafficLightResult(),
            lanes=result,
            obstacle=ObstacleResult(),
        )
        decision = Decision(tl_state=2, lane_left=1, lane_right=1)
        out = compose(
            lanes, perception, decision,
            {"led": 2, "beep": 0, "wd_timeout": 0, "alarm_reason": 0},
            15.0, mode="lane",
        )
        self.assertEqual(out.shape, (480, 800, 3))


if __name__ == "__main__":
    unittest.main()
