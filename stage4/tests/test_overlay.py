import unittest

from overlay import AdasOverlay


class FakeChannel:
    def __init__(self):
        self.writes = []

    def write(self, value, mask):
        self.writes.append((int(value), int(mask)))

    def read(self):
        return 0


class FakeGPIO:
    def __init__(self):
        self.channel1 = FakeChannel()


class OverlayHeartbeatTest(unittest.TestCase):
    def test_frame_heartbeat_toggles_only_when_requested(self):
        adas = AdasOverlay()
        adas.gpio_dec = FakeGPIO()
        adas._heartbeat_mode = "frame"
        first = adas.write_dec(tl=2, feed_heartbeat=True)
        second = adas.write_dec(tl=2, feed_heartbeat=False)
        third = adas.write_dec(tl=2, feed_heartbeat=True)
        self.assertEqual((first >> 10) & 1, 1)
        self.assertEqual((second >> 10) & 1, 1)
        self.assertEqual((third >> 10) & 1, 0)

    def test_stall_schedule_runs_once(self):
        adas = AdasOverlay()
        adas._schedule_stall(0.0, 0.0)
        adas._maybe_stall()
        self.assertTrue(adas._stall_done)
        self.assertFalse(adas.stall_active)

    def test_lane_defaults_to_hardware_gray_input(self):
        self.assertEqual(
            AdasOverlay.select_input_mode("lane"), "gray"
        )
        self.assertEqual(
            AdasOverlay.select_input_mode("traffic_light"), "color"
        )
        self.assertEqual(
            AdasOverlay.select_input_mode("obstacle"), "color"
        )
        self.assertEqual(
            AdasOverlay.select_input_mode("lane", "color"), "color"
        )


if __name__ == "__main__":
    unittest.main()
