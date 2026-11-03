"""Decision contract shared by the PS perception loop and the PL FSM.

The PL ``adas_decision`` block owns the hard real-time outputs (LEDs, buzzer,
watchdog).  The PS only publishes the current scene state once per frame.
This module deliberately contains no PYNQ or OpenCV dependency so it can be
unit-tested on the PC.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from config import (
    LANE_NAME_TO_CODE,
    LN_DASH,
    LN_NONE,
    LN_SOLID,
    TL_NAME_TO_CODE,
    TL_NONE,
    TURN_NONE,
)


def dec_word(
    tl: int = TL_NONE,
    ll: int = LN_NONE,
    lr: int = LN_NONE,
    obs: int = 0,
    force: int = 0,
    turn: int = TURN_NONE,
    hb: int = 0,
) -> int:
    """Pack the Stage 3 AXI GPIO control word.

    Bit layout (must not change without rebuilding/inspecting the PL):
        [1:0] tl, [3:2] left lane, [5:4] right lane, [6] obstacle,
        [7] force, [9:8] turn, [10] heartbeat, [15:11] reserved.
    """

    return (
        (int(tl) & 0x3)
        | ((int(ll) & 0x3) << 2)
        | ((int(lr) & 0x3) << 4)
        | ((int(obs) & 0x1) << 6)
        | ((int(force) & 0x1) << 7)
        | ((int(turn) & 0x3) << 8)
        | ((int(hb) & 0x1) << 10)
    )


def unpack_dec(word: int) -> Dict[str, int]:
    """Inverse of :func:`dec_word`, useful for logs and tests."""

    word = int(word) & 0xFFFF
    return {
        "tl": word & 0x3,
        "ll": (word >> 2) & 0x3,
        "lr": (word >> 4) & 0x3,
        "obs": (word >> 6) & 0x1,
        "force": (word >> 7) & 0x1,
        "turn": (word >> 8) & 0x3,
        "hb": (word >> 10) & 0x1,
        "reserved": (word >> 11) & 0x1F,
    }


def status_fields(raw: int) -> Dict[str, int]:
    """Decode the 7-bit PL status register."""

    raw = int(raw) & 0x7F
    return {
        "raw": raw,
        "led": raw & 0x7,
        "beep": (raw >> 3) & 0x1,
        "wd_timeout": (raw >> 4) & 0x1,
        "alarm_reason": (raw >> 5) & 0x3,
    }


def button_fields(raw: int) -> Dict[str, int]:
    """Decode the active-low PL keys.

    Released: raw=0b11, KEY0=0b10, KEY1=0b01.  The returned booleans are
    true when the corresponding physical key is pressed.
    """

    raw = int(raw) & 0x3
    return {
        "raw": raw,
        "key0": 0 if (raw & 0x1) else 1,
        "key1": 0 if (raw & 0x2) else 1,
    }


@dataclass
class Decision:
    tl_state: int = TL_NONE
    lane_left: int = LN_NONE
    lane_right: int = LN_NONE
    obstacle: int = 0
    force: int = 0
    turn: int = TURN_NONE

    def to_word(self, hb: int = 0) -> int:
        return dec_word(
            self.tl_state,
            self.lane_left,
            self.lane_right,
            self.obstacle,
            self.force,
            self.turn,
            hb,
        )

    def as_dict(self) -> Dict[str, int]:
        return {
            "tl": self.tl_state,
            "ll": self.lane_left,
            "lr": self.lane_right,
            "obs": self.obstacle,
            "force": self.force,
            "turn": self.turn,
        }


def _tl_code(value: Any) -> int:
    if isinstance(value, str):
        return TL_NAME_TO_CODE.get(value.upper(), TL_NONE)
    return int(value or 0) & 0x3


def _lane_code(value: Any) -> int:
    if isinstance(value, str):
        return LANE_NAME_TO_CODE.get(value.upper(), LN_NONE)
    return int(value or 0) & 0x3


class DecisionEngine:
    """Convert perception results into the PS-side register fields.

    Important: the PL already handles KEY0 (lane cycling) and KEY1 (forced
    command).  Consequently the default PS output is ``turn=NONE`` and
    ``force=0``; the PS must not fight the hard-wired button logic.  The
    overrides below exist for scripted tests and for a deliberate future
    software-only mode.
    """

    MODES = ("traffic_light", "lane", "obstacle")

    def __init__(self, force_override: Optional[bool] = None,
                 turn_override: Optional[int] = None,
                 mode: str = "traffic_light"):
        if mode not in self.MODES:
            raise ValueError("unsupported decision mode: %s" % mode)
        self.mode = mode
        self.force_override = force_override
        self.turn_override = turn_override

    def set_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError("unsupported decision mode: %s" % mode)
        self.mode = mode

    def set_overrides(self, force: Optional[bool] = None,
                      turn: Optional[int] = None) -> None:
        if force is not None:
            self.force_override = bool(force)
        if turn is not None:
            self.turn_override = int(turn) & 0x3

    def step(self, perception: Any, buttons: Optional[Dict[str, int]] = None) -> Decision:
        """Build one decision.

        ``perception`` may be a result object with ``traffic_light``,
        ``lanes`` and ``obstacle`` attributes, or a plain mapping with the
        same keys.  Keeping this duck-typed makes the board loop and tests
        share exactly the same path.
        """

        tl_obj = getattr(perception, "traffic_light", None)
        lanes_obj = getattr(perception, "lanes", None)
        obs_obj = getattr(perception, "obstacle", None)

        tl_state = getattr(tl_obj, "state", "NONE") if tl_obj is not None else "NONE"
        left = getattr(lanes_obj, "left_state", "NONE") if lanes_obj is not None else "NONE"
        right = getattr(lanes_obj, "right_state", "NONE") if lanes_obj is not None else "NONE"
        lane_departure = bool(
            getattr(lanes_obj, "departure", False)
            if lanes_obj is not None else False
        )
        obstacle = 1 if (obs_obj is not None and getattr(obs_obj, "present", False)) else 0

        if self.mode == "traffic_light":
            left = right = "NONE"
            obstacle = 0
        elif self.mode == "lane":
            # The existing PL FSM requires a known traffic state before it
            # enables normal turn LEDs.  GREEN is used only as a bench-mode
            # enable sentinel; the lane HUD never presents it as a real light.
            has_lane = left != "NONE" or right != "NONE"
            tl_state = "GREEN" if has_lane else "NONE"
            obstacle = 1 if lane_departure else 0
        else:
            tl_state = "NONE"
            left = right = "NONE"

        force = 1 if self.force_override else 0
        turn = TURN_NONE if self.turn_override is None else int(self.turn_override) & 0x3

        return Decision(
            tl_state=_tl_code(tl_state),
            lane_left=_lane_code(left),
            lane_right=_lane_code(right),
            obstacle=obstacle,
            force=force,
            turn=turn,
        )

    def describe(self, decision: Decision, status: Optional[Dict[str, int]] = None) -> str:
        """Human-readable one-line state for OSD/logs."""

        tl_names = {0: "NONE", 1: "RED", 2: "GREEN", 3: "YELLOW"}
        lane_names = {0: "-", 1: "SOLID", 2: "DASH"}
        turn_names = {0: "STRAIGHT", 1: "LEFT", 2: "RIGHT"}
        parts = [
            "TL=" + tl_names.get(decision.tl_state, "?"),
            "L=" + lane_names.get(decision.lane_left, "?"),
            "R=" + lane_names.get(decision.lane_right, "?"),
            "TURN=" + turn_names.get(decision.turn, "?"),
        ]
        if decision.obstacle:
            parts.append("OBS")
        if decision.force:
            parts.append("FORCE")
        if status:
            parts.append("WD=%d" % int(status.get("wd_timeout", 0)))
            parts.append("LED=%d" % int(status.get("led", 0)))
        return " ".join(parts)


__all__ = [
    "Decision",
    "DecisionEngine",
    "button_fields",
    "dec_word",
    "status_fields",
    "unpack_dec",
    "LN_DASH",
    "LN_SOLID",
]
