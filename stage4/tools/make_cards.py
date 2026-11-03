"""Generate phone/print traffic-light and lane cards with OpenCV."""

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
CARDS = ASSETS / "cards"
PRINT = ASSETS / "print"
W, H = 1200, 900
A4_W, A4_H = 2480, 3508


def traffic_card(bgr):
    img = np.full((H, W, 3), 25, dtype=np.uint8)
    cv2.circle(img, (W // 2, H // 2), 180, bgr, -1, cv2.LINE_AA)
    cv2.circle(img, (W // 2, H // 2), 180, (255, 255, 255), 8, cv2.LINE_AA)
    return img


def lane_card(dashed=False):
    img = np.full((H, W, 3), 70, dtype=np.uint8)
    left = ((150, H - 40), (500, 190))
    right = ((W - 150, H - 40), (W - 500, 190))
    for a, b in (left, right):
        if dashed:
            length = int(np.hypot(b[0] - a[0], b[1] - a[1]))
            dx = (b[0] - a[0]) / float(length)
            dy = (b[1] - a[1]) / float(length)
            pos = 0
            while pos < length:
                p1 = (int(a[0] + dx * pos), int(a[1] + dy * pos))
                p2 = (int(a[0] + dx * min(length, pos + 60)),
                      int(a[1] + dy * min(length, pos + 60)))
                cv2.line(img, p1, p2, (255, 255, 255), 12, cv2.LINE_AA)
                pos += 100
        else:
            cv2.line(img, a, b, (255, 255, 255), 12, cv2.LINE_AA)
    return img


def print_sheet(img, label):
    sheet = np.full((A4_H, A4_W, 3), 255, dtype=np.uint8)
    margin_x = int(A4_W * 0.05)
    margin_y = int(A4_H * 0.05)
    max_w = A4_W - 2 * margin_x
    max_h = int(A4_H * 0.72)
    scale = min(max_w / float(W), max_h / float(H))
    nw, nh = int(W * scale), int(H * scale)
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    x0 = (A4_W - nw) // 2
    y0 = margin_y
    sheet[y0:y0 + nh, x0:x0 + nw] = resized
    cv2.putText(sheet, label, (margin_x, A4_H - 250),
                cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(sheet, "A4 matte, image fills frame; label is outside the scene",
                (margin_x, A4_H - 160), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (80, 80, 80), 2, cv2.LINE_AA)
    return sheet


def main():
    CARDS.mkdir(parents=True, exist_ok=True)
    PRINT.mkdir(parents=True, exist_ok=True)
    items = [
        ("red", traffic_card((0, 0, 255))),
        ("green", traffic_card((0, 255, 0))),
        ("yellow", traffic_card((0, 255, 255))),
        ("lane_solid", lane_card(False)),
        ("lane_dashed", lane_card(True)),
    ]
    for name, img in items:
        card_path = CARDS / (name + ".png")
        cv2.imwrite(str(card_path), img)
        sheet_path = PRINT / ("print_" + name + ".png")
        cv2.imwrite(str(sheet_path), print_sheet(img, name))
        print(card_path, sheet_path)


if __name__ == "__main__":
    main()
