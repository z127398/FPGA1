"""Notebook-facing Stage 4 demo API."""

import time

from config import BOARD_STAGE4_DIR
from overlay import AdasOverlay


_demo = None


def _ensure() -> AdasOverlay:
    global _demo
    if _demo is None:
        _demo = AdasOverlay()
        _demo.start()
    return _demo


def start_passthrough(duration: float = 3.0) -> float:
    """Tie camera to LCD through the VDMA and return measured camera FPS."""

    adas = _ensure()
    return adas.measure_passthrough_fps(duration)


def start_osd(mode: str = "traffic_light", stall_after=None,
              stall_duration: float = 1.5,
              input_mode=None) -> AdasOverlay:
    """Start the perception/OSD loop in a background thread."""

    adas = _ensure()
    adas.start_osd(
        mode=mode, stall_after=stall_after, stall_duration=stall_duration,
        input_mode=input_mode,
    )
    return adas


def start_traffic_light(stall_after=None, stall_duration: float = 1.5):
    return start_osd(
        mode="traffic_light", stall_after=stall_after,
        stall_duration=stall_duration,
    )


def start_lane(stall_after=None, stall_duration: float = 1.5,
               input_mode=None):
    return start_osd(
        mode="lane", stall_after=stall_after,
        stall_duration=stall_duration, input_mode=input_mode,
    )


def start_obstacle(stall_after=None, stall_duration: float = 1.5):
    return start_osd(
        mode="obstacle", stall_after=stall_after,
        stall_duration=stall_duration,
    )

def video_probe() -> dict:
    """Check that colour mode, grey mode and selector restoration all work."""

    return _ensure().probe_video_modes()


def show_color_bars() -> None:
    """Display a known red/green/blue pattern for LCD channel-order checks."""

    _ensure().show_color_bars()


def run_osd(duration: float = 180.0, mode: str = "traffic_light",
            stall_after=None, stall_duration: float = 1.5,
            input_mode=None) -> float:
    """Run the OSD loop in the notebook thread and return measured FPS."""

    return _ensure().run_osd(
        mode=mode, duration=duration,
        stall_after=stall_after, stall_duration=stall_duration,
        input_mode=input_mode,
    )


def run_traffic_light(duration: float = 180.0, stall_after=None,
                      stall_duration: float = 1.5) -> float:
    return run_osd(
        duration=duration, mode="traffic_light",
        stall_after=stall_after, stall_duration=stall_duration,
    )


def run_lane(duration: float = 180.0, stall_after=None,
             stall_duration: float = 1.5,
             input_mode=None) -> float:
    return run_osd(
        duration=duration, mode="lane",
        stall_after=stall_after, stall_duration=stall_duration,
        input_mode=input_mode,
    )


def run_obstacle(duration: float = 180.0, stall_after=None,
                 stall_duration: float = 1.5) -> float:
    return run_osd(
        duration=duration, mode="obstacle",
        stall_after=stall_after, stall_duration=stall_duration,
    )


def start_watchdog_monitor() -> None:
    _ensure().start_watchdog_monitor()


def stop_watchdog_monitor():
    adas = _ensure()
    adas.stop_watchdog_monitor()
    return adas._watchdog_events


def relearn_background() -> None:
    """Discard the current background and learn an empty scene again."""

    _ensure().relearn_background()


def read_image_demo(path: str = str(BOARD_STAGE4_DIR / "assets" / "demo.ppm")) -> None:
    """Fallback: write one image directly to the LCD."""

    adas = _ensure()
    adas.stop_osd()
    adas.inject_image(path)


def status_line() -> str:
    return _ensure().status_line()


def watchdog_demo(seconds: float = 1.5):
    """Stop feeding the heartbeat and return the PL status after timeout."""

    adas = _ensure()
    adas.stop_heartbeat()
    time.sleep(seconds)
    return adas.read_status()


def stop_all(restore_stage2: bool = True) -> None:
    """Stop OSD, keep the FSM quiet, and optionally load the no-FSM image."""

    global _demo
    if _demo is None:
        return
    _demo.stop(keep_heartbeat=True)
    if restore_stage2:
        _demo.restore_quiet_bitstream()
    _demo = None


__all__ = [
    "read_image_demo",
    "relearn_background",
    "run_osd",
    "run_lane",
    "run_obstacle",
    "run_traffic_light",
    "start_osd",
    "start_lane",
    "start_obstacle",
    "start_passthrough",
    "start_traffic_light",
    "start_watchdog_monitor",
    "status_line",
    "stop_all",
    "stop_watchdog_monitor",
    "show_color_bars",
    "video_probe",
    "watchdog_demo",
]
