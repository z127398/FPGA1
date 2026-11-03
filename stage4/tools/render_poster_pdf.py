"""Render the optional one-page A4 landscape competition poster."""

import argparse
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(FONT))


def paragraph(text, size=10, color=colors.black, leading=None):
    return Paragraph(
        text,
        ParagraphStyle(
            "poster",
            fontName=FONT,
            fontSize=size,
            leading=leading or size * 1.45,
            textColor=color,
        ),
    )


def image(path, width, height):
    return Image(str(path), width=width, height=height, kind="proportional")


def main(output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output),
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=10 * mm,
    )
    page_width, page_height = landscape(A4)
    story = []

    story.append(
        paragraph(
            "Zynq软硬协同ADAS平台",
            size=25,
            color=colors.HexColor("#16324f"),
            leading=30,
        )
    )
    story.append(
        paragraph(
            "面向 ADAS 算法验证的软硬协同实时视觉平台 · 照片 HIL · 硬件安全岛",
            size=11,
            color=colors.HexColor("#4b6780"),
        )
    )
    story.append(Spacer(1, 5 * mm))

    architecture = paragraph(
        "<b>系统闭环</b><br/>"
        "OV5640 → PL 彩色/灰度预处理 → AXI VDMA → PS OpenCV 感知/OSD "
        "→ LCD<br/><br/>"
        "<b>硬件安全岛</b><br/>"
        "PS 每成功处理一帧才翻转心跳；500 ms 未收到心跳时，PL 独立进入 "
        "LED/蜂鸣器安全报警。",
        size=10,
    )
    modes = paragraph(
        "<b>三种严格互斥模式</b><br/>"
        "红绿灯：HSV + 圆形/凸度/惯性比门控，拒绝非圆形颜色区域。<br/>"
        "车道线：白黄涂料掩膜约束 Hough，虚实线间隙分类、BEV、偏移/曲率与偏航报警。<br/>"
        "障碍物：空场景背景学习、配准差分、近区框选与目标 ID 跟踪。",
        size=9.3,
    )
    left = Table(
        [[architecture], [modes]],
        colWidths=[117 * mm],
    )
    left.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#b8c8d8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d5e0ea")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f8fb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))

    metrics = [
        ["指标", "结果"],
        ["自动测试", "45/45"],
        ["BSTLD 留出集", "31/40 · 77.5%"],
        ["TuSimple 留出集", "16/20 · 80%"],
        ["实线/虚线控制样本", "12/12 · 12/12"],
        ["PL 灰度加速", "19.54 → 20.52 FPS"],
        ["资源占用", "LUT 55.34% · FF 47.06%"],
        ["时序", "WNS +0.757 ns"],
        ["看门狗", "wd 0→1→0 自动恢复"],
    ]
    metric_table = Table(
        [[paragraph(str(cell), size=8.5) for cell in row] for row in metrics],
        colWidths=[40 * mm, 55 * mm],
        repeatRows=1,
    )
    metric_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d5f86")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9fb5c8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
            colors.white, colors.HexColor("#eef5f8")
        ]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))

    top = Table(
        [[left, metric_table]],
        colWidths=[120 * mm, 105 * mm],
        hAlign="LEFT",
    )
    top.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(top)
    story.append(Spacer(1, 5 * mm))

    evidence = [
        (
            ROOT / "docs/evidence/red/osd.png",
            "红绿灯：圆形门控与硬件输出",
        ),
        (
            ROOT / "docs/evidence/lane_type_tuning/solid/osd.png",
            "实线：SOLID/SOLID + BEV",
        ),
        (
            ROOT / "docs/evidence/lane_geometry/departure/osd.png",
            "偏航：OFF +38% · DEPART 报警",
        ),
        (
            ROOT / "docs/evidence/environment/osd.png",
            "障碍物：OBJECT NEAR",
        ),
    ]
    image_row = []
    for path, caption in evidence:
        image_row.append([
            image(path, 58 * mm, 35 * mm),
            paragraph(caption, size=7.5, leading=10),
        ])
    thumbnails = Table(
        [image_row],
        colWidths=[62 * mm] * 4,
    )
    thumbnails.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(thumbnails)

    doc.build(story)
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    main(args.output)
