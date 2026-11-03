import unittest

import config
from decision import (
    DecisionEngine,
    button_fields,
    dec_word,
    status_fields,
    unpack_dec,
)


class FakeTL:
    def __init__(self, state):
        self.state = state


class FakeLanes:
    def __init__(self, left, right, departure=False):
        self.left_state = left
        self.right_state = right
        self.departure = departure


class FakeObs:
    def __init__(self, present):
        self.present = present


class FakePerception:
    def __init__(self, tl="NONE", left="NONE", right="NONE", obs=False,
                 departure=False):
        self.traffic_light = FakeTL(tl)
        self.lanes = FakeLanes(left, right, departure)
        self.obstacle = FakeObs(obs)


class DecisionContractTest(unittest.TestCase):
    def test_word_matches_stage3_layout(self):
        word = dec_word(tl=1, ll=2, lr=2, obs=1, force=1, turn=1, hb=1)
        self.assertEqual(word, 0x0000 | 1 | (2 << 2) | (2 << 4) |
                         (1 << 6) | (1 << 7) | (1 << 8) | (1 << 10))
        fields = unpack_dec(word)
        self.assertEqual(fields["tl"], 1)
        self.assertEqual(fields["ll"], 2)
        self.assertEqual(fields["lr"], 2)
        self.assertEqual(fields["obs"], 1)
        self.assertEqual(fields["force"], 1)
        self.assertEqual(fields["turn"], 1)
        self.assertEqual(fields["hb"], 1)
        self.assertEqual(fields["reserved"], 0)

    def test_status_decode(self):
        self.assertEqual(status_fields(0b0000000)["wd_timeout"], 0)
        s = status_fields((1 << 4) | (3 << 5) | 0b101)
        self.assertEqual(s["led"], 0b101)
        self.assertEqual(s["wd_timeout"], 1)
        self.assertEqual(s["alarm_reason"], 3)

    def test_button_polarity(self):
        self.assertEqual(button_fields(0b11)["key0"], 0)
        self.assertEqual(button_fields(0b11)["key1"], 0)
        self.assertEqual(button_fields(0b10)["key0"], 1)
        self.assertEqual(button_fields(0b10)["key1"], 0)
        self.assertEqual(button_fields(0b01)["key0"], 0)
        self.assertEqual(button_fields(0b01)["key1"], 1)

    def test_traffic_mode_only_publishes_light(self):
        engine = DecisionEngine()
        dec = engine.step(FakePerception("RED", "SOLID", "DASHED", True),
                          buttons={"raw": 0b10, "key0": 1, "key1": 0})
        self.assertEqual(dec.tl_state, config.TL_RED)
        self.assertEqual(dec.lane_left, config.LN_NONE)
        self.assertEqual(dec.lane_right, config.LN_NONE)
        self.assertEqual(dec.obstacle, 0)
        self.assertEqual(dec.force, 0)
        self.assertEqual(dec.turn, config.TURN_NONE)

    def test_lane_mode_uses_green_enable_sentinel(self):
        engine = DecisionEngine(mode="lane")
        dec = engine.step(FakePerception("RED", "SOLID", "DASHED", True))
        self.assertEqual(dec.tl_state, config.TL_GREEN)
        self.assertEqual(dec.lane_left, config.LN_SOLID)
        self.assertEqual(dec.lane_right, config.LN_DASH)
        self.assertEqual(dec.obstacle, 0)
        empty = engine.step(FakePerception("GREEN", "NONE", "NONE"))
        self.assertEqual(empty.tl_state, config.TL_NONE)

    def test_obstacle_mode_only_publishes_obstacle(self):
        engine = DecisionEngine(mode="obstacle")
        dec = engine.step(FakePerception("RED", "SOLID", "DASHED", True))
        self.assertEqual(dec.tl_state, config.TL_NONE)
        self.assertEqual(dec.lane_left, config.LN_NONE)
        self.assertEqual(dec.lane_right, config.LN_NONE)
        self.assertEqual(dec.obstacle, 1)

    def test_lane_departure_uses_shared_short_alarm_channel(self):
        engine = DecisionEngine(mode="lane")
        dec = engine.step(
            FakePerception("NONE", "SOLID", "SOLID", departure=True)
        )
        self.assertEqual(dec.tl_state, config.TL_GREEN)
        self.assertEqual(dec.obstacle, 1)

    def test_software_override_is_opt_in(self):
        engine = DecisionEngine(force_override=True, turn_override=config.TURN_RIGHT)
        dec = engine.step(FakePerception("GREEN"))
        self.assertEqual(dec.force, 1)
        self.assertEqual(dec.turn, config.TURN_RIGHT)
        engine.set_overrides(force=False, turn=config.TURN_LEFT)
        dec = engine.step(FakePerception("GREEN"))
        self.assertEqual(dec.force, 0)
        self.assertEqual(dec.turn, config.TURN_LEFT)


if __name__ == "__main__":
    unittest.main()
