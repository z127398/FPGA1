"""PYNQ overlay, camera, VDMA and heartbeat wrapper for Stage 4.

The module is importable on a PC (PYNQ/OpenCV are imported lazily or by the
caller) so the register/decision tests do not need board hardware.
"""

import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import config
from decision import DecisionEngine, button_fields, dec_word, status_fields
from osd import color_bars, compose, to_lcd
from perception import PERCEPTION_MODES, PerceptionPipeline


class _VideoInAdapter:
    """Minimal VideoIn-compatible wrapper around AxiVDMA.S2MMChannel."""

    def __init__(self, vdma):
        self.channel = vdma.readchannel

    def configure(self, mode) -> None:
        self.channel.mode = mode

    def start(self) -> None:
        self.channel.start()

    def readframe(self):
        return self.channel.readframe()

    async def readframe_async(self):
        return await self.channel.readframe_async()

    def tie(self, output) -> None:
        target = getattr(output, "channel", output)
        self.channel.tie(target)

    def close(self) -> None:
        try:
            self.channel.stop()
        except Exception:
            pass


class _VideoOutAdapter:
    """Minimal VideoOut-compatible wrapper around AxiVDMA.MM2SChannel."""

    def __init__(self, vdma, frontend, mode):
        self.channel = vdma.writechannel
        self.frontend = frontend
        self._mode = mode

    @property
    def mode(self):
        return self._mode

    def configure(self, is_lcd: int = 1, mode=None) -> None:
        if mode is not None:
            self._mode = mode
        self.frontend.mode = self._mode
        self.channel.mode = self._mode
        self.frontend.start()

    def start(self) -> None:
        self.channel.start()

    def newframe(self):
        return self.channel.newframe()

    def writeframe(self, frame) -> None:
        if not hasattr(frame, "flush"):
            # VDMA.writeframe expects a PYNQ VideoFrame.  Accept OpenCV/
            # numpy frames by copying into a DMA-owned frame.
            import numpy as np
            owned = self.channel.newframe()
            np.copyto(owned, frame)
            frame = owned
        self.channel.writeframe(frame)

    async def writeframe_async(self, frame) -> None:
        if not hasattr(frame, "flush"):
            import numpy as np
            owned = self.channel.newframe()
            np.copyto(owned, frame)
            frame = owned
        await self.channel.writeframe_async(frame)

    def close(self) -> None:
        try:
            self.channel.stop()
        except Exception:
            pass
        try:
            self.frontend.stop()
        except Exception:
            pass


class AdasOverlay:
    def __init__(self, bitstream: str = str(config.BOARD_BITSTREAM),
                 proc_size=config.PROC_SIZE, skip: int = config.SKIP_FRAMES):
        self.bitstream = str(bitstream)
        self.proc_size = tuple(proc_size)
        self.skip = int(skip)

        self.ol = None
        self.video_in = None
        self.video_out = None
        self.sel = None
        self.gpio_dec = None
        self.gpio_status = None
        self.gpio_btn = None
        self.iic = None
        self.ov5640 = None

        self._lock = threading.RLock()
        self._dec = dict(tl=0, ll=0, lr=0, obs=0, force=0, turn=0)
        self._hb = 0
        self._hb_stop = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None
        self._heartbeat_mode = "free"
        self._osd_stop = threading.Event()
        self._osd_thread: Optional[threading.Thread] = None
        self._osd_running = False
        self._pipeline = None
        self.last_perception = None
        self.pipeline_mode = "color"
        self._input_mode = "color"
        self.last_run_fps = 0.0
        self.last_probe: Optional[Dict[str, object]] = None
        self.mode = "traffic_light"
        self.last_error: Optional[BaseException] = None
        self.fps = 0.0
        self._stall_at: Optional[float] = None
        self._stall_duration = 0.0
        self._stall_done = True
        self.stall_active = False
        self._monitor_stop = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._watchdog_events = []
        self._watchdog_log: Optional[Path] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> "AdasOverlay":
        if self.ol is not None:
            return self
        # A previous stop(keep_heartbeat=True) may still own a GPIO reference.
        self._stop_heartbeat()
        self.gpio_dec = None
        self.gpio_status = None
        self.gpio_btn = None
        import cv2  # noqa: F401  (verify the board runtime early)
        from pynq import Overlay
        from pynq.lib.iic import AxiIIC
        from pynq.lib.ov5640 import OV5640

        self.ol = Overlay(self.bitstream)
        required = ("gpio_dec", "gpio_status", "gpio_btn", "cam_iic")
        missing = [name for name in required if name not in self.ol.ip_dict]
        if missing or not hasattr(self.ol, "video"):
            raise RuntimeError(
                "bitstream is missing %s; upload the Stage 3 bitstream with "
                "adas_decision/gpio_dec/gpio_status/gpio_btn" % ", ".join(missing)
            )

        self._build_video_adapters()
        self.sel = self.ol.video.camera_in.axi_gpio_sel
        self.gpio_dec = self.ol.gpio_dec
        self.gpio_status = self.ol.gpio_status
        self.gpio_btn = self.ol.gpio_btn

        self.iic = AxiIIC(self.ol.ip_dict["cam_iic"])
        self.ov5640 = OV5640(0x3C, self.iic)
        self.ov5640.init()
        # OV5640 datasheet: 0x3016 = PAD OUTPUT ENABLE, 0x3019 = PAD OUTPUT
        # VALUE.  Write value 0 and disable all pad outputs.  The old
        # 0x3016=0x02 sequence enabled a pad (the flash/strobe path) instead
        # of turning the light off.
        self.iic.send(0x3C, bytes([0x30, 0x19, 0x00]), 3)
        self.iic.send(0x3C, bytes([0x30, 0x16, 0x00]), 3)

        self.video_out.configure(1)
        self.video_in.configure(self.video_out.mode)
        try:
            gray_ip = self.ol.video.camera_in.ov5640_rgb2gray_0
            gray_ip.mmio.write(16, self.video_out.mode.height)
            gray_ip.mmio.write(24, self.video_out.mode.width)
        except Exception:
            # The Stage 3 build used for the demo always has this IP, but do
            # not make the whole overlay unusable if a future build removes it.
            pass

        self.video_in.start()
        self.video_out.start()
        self.video_in.tie(self.video_out)
        self.set_pipeline("color")
        self.write_dec(0, 0, 0, 0, 0, 0)
        self._set_heartbeat_mode("free")
        # Let the first heartbeat edge clear a watchdog state inherited from
        # the previous overlay before the caller reads status or hears beeps.
        time.sleep(0.15)
        return self

    def _build_video_adapters(self) -> None:
        """Bypass PYNQ 2.7's broken VideoOut hierarchy matcher.

        The Stage 3 HWH adds stage_gray_0 under video/camera_in; on this
        PYNQ image that leaves video/video_out as a DocumentedHierarchy
        instead of VideoOut, so ol.video.video_in is never created.  The
        underlying VDMA and HDMIOutFrontend objects are intact, so use them
        directly through two tiny adapters.
        """

        from pynq.lib.video2lcd.common import VideoMode
        from pynq.lib.video2lcd.dvi import HDMIOutFrontend

        video = self.ol.video
        if not hasattr(video, "axi_vdma"):
            raise RuntimeError("video hierarchy has no axi_vdma")
        # The PYNQ overlay auto-binds pynq.lib.video.dvi.HDMIOutFrontend,
        # whose mode table has HDMI modes only.  The Alientek LCD path needs
        # the video2lcd variant, which includes 800x480 and _lcd_id.
        frontend = HDMIOutFrontend(video.video_out.frontend.description)
        mode = VideoMode(800, 480, 24)
        self.video_in = _VideoInAdapter(video.axi_vdma)
        self.video_out = _VideoOutAdapter(video.axi_vdma, frontend, mode)

    def stop(self, keep_heartbeat: bool = True) -> None:
        """Stop video and OSD.

        By default keep the 10 Hz heartbeat alive and the decision word at
        zero.  This leaves the Stage 3 FSM in a quiet state instead of letting
        the 500 ms watchdog start the 1 Hz beeper.  Pass
        ``keep_heartbeat=False`` for the explicit watchdog demonstration.
        """

        self.stop_osd()
        try:
            self.write_dec(0, 0, 0, 0, 0, 0)
        except Exception:
            pass
        if not keep_heartbeat:
            self._stop_heartbeat()
        for obj, name in ((self.video_in, "video_in"), (self.video_out, "video_out")):
            if obj is None:
                continue
            try:
                if name == "video_in":
                    obj.tie(None)
                obj.close()
            except Exception:
                pass
        try:
            self.set_pipeline("color")
        except Exception:
            pass
        self.ol = None
        self.video_in = None
        self.video_out = None
        if not keep_heartbeat:
            self.gpio_dec = None
            self.gpio_status = None
            self.gpio_btn = None

    def stop_heartbeat(self) -> None:
        """Stop feeding the PL watchdog (used by the watchdog demo)."""

        self._stop_heartbeat()

    def restore_quiet_bitstream(self) -> None:
        """Load the no-FSM Stage 2 image so the board is guaranteed silent."""

        self._stop_heartbeat()
        try:
            self.write_dec(0, 0, 0, 0, 0, 0)
        except Exception:
            pass
        from pynq import Overlay
        Overlay(str(config.STAGE2_BITSTREAM))
        self.ol = None
        self.video_in = None
        self.video_out = None
        self.gpio_dec = None
        self.gpio_status = None
        self.gpio_btn = None

    # ------------------------------------------------------------------
    # Register contract
    # ------------------------------------------------------------------
    def _write_locked(self) -> None:
        if self.gpio_dec is None:
            return
        word = dec_word(
            self._dec["tl"], self._dec["ll"], self._dec["lr"],
            self._dec["obs"], self._dec["force"], self._dec["turn"], self._hb,
        )
        # PYNQ 2.7's Channel.write(val, mask) updates only the bits in mask.
        # The Stage 3 notes used write(v, 0), which silently wrote nothing.
        self.gpio_dec.channel1.write(word & 0xFFFF, 0xFFFF)

    def write_dec(self, tl: int = 0, ll: int = 0, lr: int = 0,
                  obs: int = 0, force: int = 0, turn: int = 0,
                  feed_heartbeat: bool = False) -> int:
        with self._lock:
            self._dec.update(dict(tl=int(tl) & 3, ll=int(ll) & 3,
                                  lr=int(lr) & 3, obs=int(obs) & 1,
                                  force=int(force) & 1, turn=int(turn) & 3))
            if feed_heartbeat and self._heartbeat_mode == "frame":
                self._hb ^= 1
            self._write_locked()
            return dec_word(self._dec["tl"], self._dec["ll"], self._dec["lr"],
                            self._dec["obs"], self._dec["force"],
                            self._dec["turn"], self._hb)

    def read_status(self) -> Dict[str, int]:
        if self.gpio_status is None:
            return status_fields(0)
        return status_fields(self.gpio_status.channel1.read())

    def read_btns(self) -> Dict[str, int]:
        if self.gpio_btn is None:
            return button_fields(0x3)
        return button_fields(self.gpio_btn.channel1.read())

    def _start_heartbeat(self) -> None:
        self._hb_stop.clear()
        if self._hb_thread is not None and self._hb_thread.is_alive():
            return
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, name="adas-heartbeat", daemon=True
        )
        self._hb_thread.start()

    def _stop_heartbeat(self) -> None:
        self._hb_stop.set()
        if self._hb_thread is not None:
            self._hb_thread.join(timeout=1.0)
            self._hb_thread = None

    def _heartbeat_loop(self) -> None:
        while not self._hb_stop.wait(config.HEARTBEAT_PERIOD_S):
            with self._lock:
                if self._heartbeat_mode != "free":
                    return
                self._hb ^= 1
                self._write_locked()

    def _set_heartbeat_mode(self, mode: str) -> None:
        if mode not in ("free", "frame"):
            raise ValueError("heartbeat mode must be 'free' or 'frame'")
        if mode == "frame":
            self._stop_heartbeat()
        self._heartbeat_mode = mode
        if mode == "free" and self.ol is not None:
            self._start_heartbeat()

    def _schedule_stall(self, delay: Optional[float],
                        duration: float) -> None:
        if delay is None:
            self._stall_at = None
            self._stall_duration = 0.0
            self._stall_done = True
            return
        self._stall_at = time.monotonic() + max(0.0, float(delay))
        self._stall_duration = max(0.0, float(duration))
        self._stall_done = False

    def _maybe_stall(self, stop_event: Optional[threading.Event] = None) -> None:
        if self._stall_done or self._stall_at is None:
            return
        if time.monotonic() < self._stall_at:
            return
        self._stall_done = True
        self.stall_active = True
        deadline = time.monotonic() + self._stall_duration
        try:
            while time.monotonic() < deadline:
                if stop_event is not None and stop_event.is_set():
                    break
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        finally:
            self.stall_active = False

    def start_watchdog_monitor(self, path: Optional[str] = None) -> None:
        """Poll PL status independently and record watchdog transitions."""

        if self.gpio_status is None:
            raise RuntimeError("overlay not started")
        self.stop_watchdog_monitor()
        self._monitor_stop.clear()
        self._watchdog_events = []
        self._watchdog_log = (
            Path(path)
            if path
            else config.BOARD_STAGE4_DIR / "evidence" / "watchdog_timeline.json"
        )

        def monitor_loop():
            previous = None
            started = time.monotonic()
            while not self._monitor_stop.wait(0.05):
                status = self.read_status()
                wd = int(status.get("wd_timeout", 0))
                if wd != previous:
                    self._watchdog_events.append({
                        "elapsed_s": round(time.monotonic() - started, 3),
                        "wd_timeout": wd,
                        "led": int(status.get("led", 0)),
                        "beep": int(status.get("beep", 0)),
                        "alarm_reason": int(status.get("alarm_reason", 0)),
                    })
                    previous = wd

        self._monitor_thread = threading.Thread(
            target=monitor_loop, name="adas-watchdog-monitor", daemon=True
        )
        self._monitor_thread.start()

    def stop_watchdog_monitor(self) -> None:
        self._monitor_stop.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=1.0)
            self._monitor_thread = None
        if self._watchdog_log is not None:
            self._watchdog_log.parent.mkdir(parents=True, exist_ok=True)
            self._watchdog_log.write_text(
                json.dumps(self._watchdog_events, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # ------------------------------------------------------------------
    # Video helpers
    # ------------------------------------------------------------------
    def set_pipeline(self, mode: str) -> None:
        if self.sel is None:
            raise RuntimeError("overlay not started")
        mode = mode.lower()
        if mode not in ("color", "gray"):
            raise ValueError("pipeline mode must be 'color' or 'gray'")
        # bit0 selects grey and bit1 selects the optional processing stage.
        # Clear both so an old Sobel/gray selection cannot survive a switch
        # back to the colour path.
        self.sel.channel1.write(0 if mode == "color" else 1, 0x3)
        self.pipeline_mode = mode

    def _frame_stats(self, frame) -> Dict[str, object]:
        import numpy as np
        means = np.asarray(frame, dtype=np.float32).reshape(-1, 3).mean(axis=0)
        spread = float(means.max() - means.min())
        return {
            "bgr_mean": [round(float(value), 2) for value in means],
            "channel_spread": round(spread, 2),
        }

    def probe_video_modes(self) -> Dict[str, object]:
        """Capture colour and grey frames and report selector/channel health."""

        if self.video_in is None or self.sel is None:
            raise RuntimeError("overlay not started")
        self.stop_osd()
        self.video_in.tie(self.video_out)
        self.set_pipeline("color")
        color_sel = int(self.sel.channel1.read()) & 0x7
        color = self._read_and_copy(self.skip)
        self.set_pipeline("gray")
        gray_sel = int(self.sel.channel1.read()) & 0x7
        gray = self._read_and_copy(self.skip)
        self.set_pipeline("color")
        restored_sel = int(self.sel.channel1.read()) & 0x7
        result = {
            "color": self._frame_stats(color),
            "gray": self._frame_stats(gray),
            "sel_color": color_sel,
            "sel_gray": gray_sel,
            "sel_restored": restored_sel,
        }
        result["color_pass"] = (
            color_sel == 0
            and restored_sel == 0
            and float(result["color"]["channel_spread"]) >= 5.0
        )
        result["gray_pass"] = (
            gray_sel == 1
            and float(result["gray"]["channel_spread"]) <= 5.0
        )
        self.last_probe = result
        return result

    def show_color_bars(self) -> None:
        if self.video_out is None:
            raise RuntimeError("overlay not started")
        self.stop_osd()
        self.video_out.writeframe(to_lcd(color_bars()))

    def _read_and_copy(self, skip: Optional[int] = None):
        n = self.skip if skip is None else int(skip)
        frame = None
        for _ in range(n + 1):
            frame = self.video_in.readframe()
            # Writing the input frame breaks the zero-copy tie, which is what
            # the OSD path wants.  Passthrough mode does not call this helper.
            self.video_out.writeframe(frame)
        if frame is None:
            raise RuntimeError("camera returned no frame")
        return frame.copy()

    def grab(self, skip: Optional[int] = None) -> "object":
        import cv2
        self.set_pipeline("color")
        frame = self._read_and_copy(skip)
        if frame.shape[1] != self.proc_size[0] or frame.shape[0] != self.proc_size[1]:
            frame = cv2.resize(frame, self.proc_size, interpolation=cv2.INTER_NEAREST)
        return frame

    def display(self, bgr) -> None:
        if self.video_out is None:
            raise RuntimeError("overlay not started")
        self.video_out.writeframe(to_lcd(bgr))

    def inject_image(self, path: str) -> None:
        import cv2
        import numpy as np
        img = cv2.imread(path)
        if img is None:
            raise FileNotFoundError(path)
        h, w = img.shape[:2]
        dw, dh = config.DISPLAY_SIZE
        scale = min(dw / float(w), dh / float(h))
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((dh, dw, 3), dtype=np.uint8)
        x0, y0 = (dw - nw) // 2, (dh - nh) // 2
        canvas[y0:y0 + nh, x0:x0 + nw] = resized
        self.video_out.writeframe(to_lcd(canvas))

    # ------------------------------------------------------------------
    # Display modes
    # ------------------------------------------------------------------
    def start_passthrough(self, duration: float = 0.0) -> None:
        self.set_pipeline("color")
        self.video_in.tie(self.video_out)
        if duration and duration > 0:
            time.sleep(duration)

    def measure_passthrough_fps(self, duration: float = 3.0) -> float:
        """Count camera frames while the VDMA tie drives the LCD.

        No per-frame ``writeframe`` is issued, so this is the true zero-CPU
        passthrough path.  Reading a frame only observes the S2MM stream.
        """

        self.start_passthrough(0)
        t0 = time.time()
        n = 0
        while time.time() - t0 < duration:
            self.video_in.readframe()
            n += 1
        elapsed = max(1e-6, time.time() - t0)
        return n / elapsed

    @staticmethod
    def select_input_mode(mode: str,
                          requested: Optional[str] = None) -> str:
        selected = requested or ("gray" if mode == "lane" else "color")
        if selected not in ("color", "gray"):
            raise ValueError("input mode must be 'color' or 'gray'")
        return selected

    def start_osd(self, mode: str = "traffic_light",
                  stall_after: Optional[float] = None,
                  stall_duration: float = 1.5,
                  input_mode: Optional[str] = None) -> None:
        if self.video_in is None:
            raise RuntimeError("overlay not started")
        if mode not in PERCEPTION_MODES:
            raise ValueError("unsupported mode: %s" % mode)
        self.stop_osd()
        self._input_mode = self.select_input_mode(mode, input_mode)
        self.set_pipeline(self._input_mode)
        self.mode = mode
        self._set_heartbeat_mode("frame")
        self._schedule_stall(stall_after, stall_duration)
        self._osd_stop.clear()
        self._osd_thread = threading.Thread(
            target=self._osd_loop, name="adas-osd", daemon=True
        )
        self._osd_thread.start()

    def relearn_background(self) -> None:
        if self._pipeline is not None:
            self._pipeline.relearn_background()

    def stop_osd(self, timeout: float = 2.0) -> None:
        self._osd_stop.set()
        if self._osd_thread is not None:
            self._osd_thread.join(timeout=timeout)
            self._osd_thread = None
        self._osd_running = False
        if self.ol is not None:
            self._set_heartbeat_mode("free")

    def _osd_loop(self) -> None:
        import asyncio
        import cv2
        import numpy as np
        # PYNQ 2.7's VDMA waits using asyncio.get_event_loop().  A worker
        # thread has no loop by default; short demos may never block, but a
        # long soak eventually does and raises "no current event loop".
        try:
            osd_loop = asyncio.get_event_loop()
        except RuntimeError:
            osd_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(osd_loop)
        pipeline = PerceptionPipeline(
            mode=self.mode, input_gray=self._input_mode == "gray"
        )
        self._pipeline = pipeline
        engine = DecisionEngine(mode=self.mode)
        self._osd_running = True
        self.last_error = None
        # Break the zero-copy tie before writing processed frames.
        try:
            self.video_out.writeframe(to_lcd(np.zeros((480, 800, 3), dtype=np.uint8)))
        except Exception:
            pass

        idx = 0
        count = 0
        t_fps = time.time()
        try:
            while not self._osd_stop.is_set():
                self._maybe_stall(self._osd_stop)
                frame = self.video_in.readframe()
                bgr = frame
                if bgr.shape[1] != self.proc_size[0] or bgr.shape[0] != self.proc_size[1]:
                    bgr = cv2.resize(bgr, self.proc_size, interpolation=cv2.INTER_NEAREST)
                result = pipeline.process(bgr, idx)
                self.last_perception = result
                decision = engine.step(result, self.read_btns())
                self.write_dec(decision.tl_state, decision.lane_left,
                               decision.lane_right, decision.obstacle,
                               decision.force, decision.turn,
                               feed_heartbeat=True)
                status = self.read_status()
                out = compose(
                    bgr, result, decision, status, self.fps, mode=self.mode,
                    heartbeat_source=self._heartbeat_mode.upper(),
                )
                self.video_out.writeframe(to_lcd(out))
                idx += 1
                count += 1
                now = time.time()
                if now - t_fps >= 1.0:
                    self.fps = count / (now - t_fps)
                    count = 0
                    t_fps = now
        except BaseException as exc:  # keep the notebook alive and expose the cause
            self.last_error = exc
        finally:
            try:
                self.write_dec(0, 0, 0, 0, 0, 0)
            except Exception:
                pass
            try:
                self.video_in.tie(self.video_out)
            except Exception:
                pass
            self._osd_running = False
            self._pipeline = None
            try:
                osd_loop.close()
            except Exception:
                pass

    def run_osd(self, mode: str = "traffic_light", duration: float = 0.0,
                stall_after: Optional[float] = None,
                stall_duration: float = 1.5,
                input_mode: Optional[str] = None) -> float:
        """Run OSD synchronously in the caller thread.

        PYNQ 2.7 creates asyncio objects that must stay on the loop owned by
        the overlay.  Long notebook runs therefore use this path instead of a
        persistent worker thread.  Each DMA operation is bounded so a missing
        camera frame cannot hang the notebook indefinitely.
        """

        if self.video_in is None:
            raise RuntimeError("overlay not started")
        if mode not in PERCEPTION_MODES:
            raise ValueError("unsupported mode: %s" % mode)

        import asyncio
        import cv2
        import numpy as np

        self.stop_osd()
        self._input_mode = self.select_input_mode(mode, input_mode)
        self.set_pipeline(self._input_mode)
        self.mode = mode
        self._set_heartbeat_mode("frame")
        self._schedule_stall(stall_after, stall_duration)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        pipeline = PerceptionPipeline(
            mode=mode, input_gray=self._input_mode == "gray"
        )
        engine = DecisionEngine(mode=mode)
        self._pipeline = pipeline
        self._osd_stop.clear()
        self._osd_running = True
        self.last_error = None
        start = time.time()
        idx = 0
        count = 0
        t_fps = start
        timeouts = 0
        try:
            self.video_out.writeframe(
                to_lcd(np.zeros((480, 800, 3), dtype=np.uint8))
            )
            while not self._osd_stop.is_set():
                if duration > 0 and time.time() - start >= duration:
                    break
                self._maybe_stall(self._osd_stop)
                try:
                    frame = loop.run_until_complete(
                        asyncio.wait_for(self.video_in.readframe_async(), 1.0)
                    )
                    timeouts = 0
                except asyncio.TimeoutError:
                    timeouts += 1
                    if timeouts >= 3:
                        raise RuntimeError("camera DMA read timed out")
                    continue

                bgr = frame
                if (bgr.shape[1] != self.proc_size[0]
                        or bgr.shape[0] != self.proc_size[1]):
                    bgr = cv2.resize(
                        bgr, self.proc_size, interpolation=cv2.INTER_NEAREST
                    )
                result = pipeline.process(bgr, idx)
                self.last_perception = result
                decision = engine.step(result, self.read_btns())
                self.write_dec(
                    decision.tl_state,
                    decision.lane_left,
                    decision.lane_right,
                    decision.obstacle,
                    decision.force,
                    decision.turn,
                    feed_heartbeat=True,
                )
                status = self.read_status()
                out = compose(
                    bgr, result, decision, status, self.fps, mode=self.mode,
                    heartbeat_source=self._heartbeat_mode.upper(),
                )
                loop.run_until_complete(
                    asyncio.wait_for(
                        self.video_out.writeframe_async(to_lcd(out)), 1.0
                    )
                )
                idx += 1
                count += 1
                now = time.time()
                if now - t_fps >= 1.0:
                    self.fps = count / (now - t_fps)
                    count = 0
                    t_fps = now
        except KeyboardInterrupt:
            pass
        except BaseException as exc:
            self.last_error = exc
            raise
        finally:
            try:
                self.write_dec(0, 0, 0, 0, 0, 0)
            except Exception:
                pass
            try:
                self.video_in.tie(self.video_out)
            except Exception:
                pass
            self._osd_running = False
            self._pipeline = None
            if self.ol is not None:
                self._set_heartbeat_mode("free")
        self.last_run_fps = idx / max(time.time() - start, 1e-6)
        return self.fps

    def status_line(self) -> str:
        status = self.read_status()
        btns = self.read_btns()
        return (
            "mode=%s status=%s btns=%s fps=%.1f hb_source=%s stalled=%s"
            % (self.mode, status, btns, self.fps,
               self._heartbeat_mode, self.stall_active)
        )


__all__ = ["AdasOverlay"]
