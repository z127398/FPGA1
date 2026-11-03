import unittest
from pathlib import Path

import cv2

from perception import LaneDetector, PerceptionPipeline, TrafficLightDetector


ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "assets" / "cards"


@unittest.skipUnless(CARDS.exists(), "generated cards are not present")
class GeneratedCardTest(unittest.TestCase):
    def test_traffic_cards(self):
        det = TrafficLightDetector(vote_n=1)
        for name, expected in (("real_red", "RED"), ("real_green", "GREEN"),
                               ("red", "RED"), ("green", "GREEN"),
                               ("yellow", "YELLOW")):
            img = cv2.imread(str(CARDS / (name + ".png")))
            self.assertIsNotNone(img, name)
            result = det.detect(img)
            self.assertEqual(result.state, expected, (name, result.boxes))

    def test_lane_cards(self):
        det = LaneDetector(vote_n=1)
        solid = det.detect(cv2.imread(str(CARDS / "lane_solid.png")))
        self.assertEqual(solid.left_state, "SOLID", solid)
        self.assertEqual(solid.right_state, "SOLID", solid)
        dashed = det.detect(cv2.imread(str(CARDS / "lane_dashed.png")))
        self.assertEqual(dashed.left_state, "DASHED", dashed)
        self.assertEqual(dashed.right_state, "DASHED", dashed)

    def test_strict_mode_twenty_frame_regression(self):
        for name, expected in (
            ("red", "RED"),
            ("green", "GREEN"),
            ("yellow", "YELLOW"),
        ):
            pipeline = PerceptionPipeline(mode="traffic_light")
            img = cv2.imread(str(CARDS / (name + ".png")))
            for idx in range(20):
                result = pipeline.process(img, idx)
                self.assertFalse(result.obstacle.present)
                self.assertFalse(result.obstacle.boxes)
                self.assertFalse(result.obstacle.learning)
                self.assertEqual(result.lanes.left_state, "NONE")
                self.assertEqual(result.lanes.right_state, "NONE")
            self.assertEqual(result.traffic_light.state, expected)

        for name, expected in (
            ("lane_solid", "SOLID"),
            ("lane_dashed", "DASHED"),
        ):
            pipeline = PerceptionPipeline(mode="lane")
            img = cv2.imread(str(CARDS / (name + ".png")))
            for idx in range(20):
                result = pipeline.process(img, idx)
                self.assertFalse(result.obstacle.boxes)
                self.assertEqual(result.traffic_light.state, "NONE")
            self.assertEqual(result.lanes.left_state, expected)
            self.assertEqual(result.lanes.right_state, expected)


if __name__ == "__main__":
    unittest.main()
