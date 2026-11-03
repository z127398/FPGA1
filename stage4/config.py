"""Stage 4 ADAS configuration.

The values here are shared by the PC-side tests and the PYNQ board runtime.
Keep this file dependency-free so the decision/register tests can run on the
PC without OpenCV or PYNQ installed.
"""

from pathlib import Path


# ---------------------------------------------------------------------------
# Board paths
# ---------------------------------------------------------------------------
BOARD_HOME = Path("/home/xilinx")
BOARD_NOTEBOOK_ROOT = BOARD_HOME / "jupyter_notebooks"
BOARD_STAGE4_DIR = BOARD_NOTEBOOK_ROOT / "stage4"
BOARD_BITSTREAM = BOARD_NOTEBOOK_ROOT / "stage4_ready" / "ov5640_rgb2gray.bit"
BOARD_HWH = BOARD_NOTEBOOK_ROOT / "stage4_ready" / "ov5640_rgb2gray.hwh"
STAGE2_BITSTREAM = BOARD_NOTEBOOK_ROOT / "ready_to_test" / "ov5640_rgb2gray.bit"


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------
DISPLAY_SIZE = (800, 480)
PROC_SIZE = (320, 240)
FALLBACK_PROC_SIZE = (320, 240)
SKIP_FRAMES = 2
# Board calibration: the LCD VDMA path consumes OpenCV's BGR byte order.
LCD_FRAMEBUFFER_BGR = True
LANE_EVERY_N = 6
OSD_FONT = 0  # cv2.FONT_HERSHEY_SIMPLEX, kept numeric for easy config use


# ---------------------------------------------------------------------------
# AXI GPIO register contract (must match Stage 3)
# ---------------------------------------------------------------------------
DEC_BASE = 0x41220000
STATUS_BASE = 0x41230000
BTN_BASE = 0x41240000
SEL_BASE = 0x41210000

TL_NONE = 0
TL_RED = 1
TL_GREEN = 2
TL_YELLOW = 3

LN_NONE = 0
LN_SOLID = 1
LN_DASH = 2

TURN_NONE = 0
TURN_LEFT = 1
TURN_RIGHT = 2

TL_NAME_TO_CODE = {
    "NONE": TL_NONE,
    "RED": TL_RED,
    "GREEN": TL_GREEN,
    "YELLOW": TL_YELLOW,
}

LANE_NAME_TO_CODE = {
    "NONE": LN_NONE,
    "SOLID": LN_SOLID,
    "DASHED": LN_DASH,
    "DASH": LN_DASH,
}


# ---------------------------------------------------------------------------
# Traffic light detector
# ---------------------------------------------------------------------------
TL_H_RED_LO1, TL_H_RED_HI1 = 0, 18
TL_H_RED_LO2, TL_H_RED_HI2 = 170, 180
TL_H_YEL_LO, TL_H_YEL_HI = 20, 45
TL_H_GRN_LO, TL_H_GRN_HI = 40, 80

TL_S_RED, TL_V_RED = 120, 120
TL_S_YEL, TL_V_YEL = 90, 90
TL_S_GRN, TL_V_GRN = 80, 80

# Normalised to a 320x240 frame.  Scaling by the actual frame area keeps the
# same physical target size when the processing resolution changes.
TL_MIN_AREA_FRAC = 30.0 / (320.0 * 240.0)
TL_MAX_AREA_FRAC = 0.30  # allow close-up printed lights filling much of the frame
TL_MIN_ASPECT = 0.35
TL_MAX_ASPECT = 2.0
TL_MIN_FILL = 0.40
TL_MAX_FILL = 0.95
TL_MIN_CIRCULARITY = 0.50
TL_MIN_CONVEXITY = 0.60
TL_MIN_INERTIA_RATIO = 0.40
TL_MORPH_K = 3
TL_USE_MORPHOLOGY = False
TL_VOTE_N = 3
TL_ENTER_N = 2
TL_SWITCH_N = 3
TL_CLEAR_N = 3
TL_BOX_SMOOTH_N = 3
TL_EVERY_N = 4
TL_RELAXED_S = 50
TL_RELAXED_V = 50
TL_RELAXED_MIN_AREA_FRAC = 0.01
TL_RELAXED_MAX_AREA_FRAC = 0.40
TL_RELAXED_MIN_FILL = 0.28
TL_RELAXED_MAX_FILL = 0.97


# ---------------------------------------------------------------------------
# Lane detector
# ---------------------------------------------------------------------------
LANE_ROI_Y0 = 0.52
LANE_WORK_WIDTH = 208
LANE_CANNY_LO, LANE_CANNY_HI = 40, 120
LANE_WHITE_MAX_S = 95
LANE_WHITE_MIN_V = 90
LANE_WHITE_LOCAL_DELTA = 12
LANE_YELLOW_H_MIN = 15
LANE_YELLOW_H_MAX = 40
LANE_YELLOW_MIN_S = 70
LANE_YELLOW_MIN_V = 80
LANE_PAINT_MIN_SUPPORT = 0.15
LANE_HOUGH_THRESHOLD = 15
LANE_HOUGH_MIN_LINE_FRAC = 0.025
LANE_HOUGH_MAX_GAP_FRAC = 0.04
LANE_CLUSTER_X_FRAC = 0.04
LANE_SLOPE_MIN = 0.35
LANE_SLOPE_MAX = 6.0
LANE_SCAN_ROWS = 64
LANE_HALF_WIDTH_FRAC = 0.004  # about 2.5 px at 640 wide
LANE_SOLID_COVERAGE = 0.80
LANE_SOLID_MAX_GAP = 0.25
LANE_SOLID_MAX_GAP_RUNS = 2
LANE_DASH_MIN_COVERAGE = 0.15
LANE_BRIGHT_MIN = 90
LANE_BRIGHT_DELTA = 20
LANE_VOTE_N = 5
LANE_ENTER_N = 2
LANE_SWITCH_N = 3
LANE_CLEAR_N = 3
LANE_TRACK_X_FRAC = 0.18
LANE_TRACK_SLOPE_RATIO = 0.60
LANE_LINE_SMOOTH_N = 3
LANE_CURVE_SMOOTH_N = 3
LANE_CURVE_MIN_IMPROVEMENT = 0.20
LANE_WIDTH_MIN_FRAC = 0.15
LANE_WIDTH_MAX_FRAC = 1.10
LANE_DEPARTURE_OFFSET_MAX = 0.20
LANE_DEPARTURE_CONFIRM_N = 3
LANE_DEPARTURE_CLEAR_N = 2
LANE_BEV_SIZE = (160, 96)


# ---------------------------------------------------------------------------
# Obstacle detector
# ---------------------------------------------------------------------------
OBSTACLE_WORK_SIZE = (160, 120)
OBSTACLE_LEARN_FRAMES = 24
OBSTACLE_DIFF_THRESHOLD = 20
OBSTACLE_MIN_AREA_FRAC = 0.008
OBSTACLE_MAX_AREA_FRAC = 0.35
OBSTACLE_ASPECT_MIN = 0.20
OBSTACLE_ASPECT_MAX = 5.0
OBSTACLE_CONFIRM_FRAMES = 3
OBSTACLE_HOLD_FRAMES = 10
OBSTACLE_NEAR_Y0 = 0.55
OBSTACLE_NEAR_X0 = 0.20
OBSTACLE_NEAR_X1 = 0.80
OBSTACLE_MAX_SHIFT_PX = 8.0
OBSTACLE_MIN_CORR = 0.08
OBSTACLE_BG_ALPHA = 0.02
OBSTACLE_EVERY_N = 2
OBSTACLE_GUARD_FRAMES = 6
OBSTACLE_SMOOTH_ALPHA = 0.35
TRACK_MAX_DISTANCE_FACTOR = 0.90


# ---------------------------------------------------------------------------
# Heartbeat / watchdog
# ---------------------------------------------------------------------------
HEARTBEAT_PERIOD_S = 0.10
WATCHDOG_TIMEOUT_MS = 500
