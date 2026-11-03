"""Render the Stage 4 Markdown report to PDF with ReportLab.

This avoids Word/WPS automation and works headless.  It handles the subset of
Markdown used by docs/report/adas_report.md: headings, paragraphs, bullets,
fenced code and pipe tables.
"""

import argparse
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = next(
    p for p in (
        ROOT.parent / "docs" / "report" / "adas_report.md",
        ROOT / "docs" / "report" / "adas_report.md",
    ) if p.exists()
)
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
FONT = "STSong-Light"


def clean(text):
    text = text.replace("**", "").replace("`", "")
    text = html.escape(text, quote=False)
    return text


def styles():
    return {
        "title": ParagraphStyle("title", fontName=FONT, fontSize=20,
                                leading=26, alignment=1, spaceAfter=16),
        "h2": ParagraphStyle("h2", fontName=FONT, fontSize=14, leading=19,
                             spaceBefore=14, spaceAfter=6),
        "h3": ParagraphStyle("h3", fontName=FONT, fontSize=11.5, leading=15,
                             spaceBefore=9, spaceAfter=4),
        "body": ParagraphStyle("body", fontName=FONT, fontSize=10.5,
                               leading=16, spaceAfter=6),
        "bullet": ParagraphStyle("bullet", fontName=FONT, fontSize=10.5,
                                 leading=16, leftIndent=12, spaceAfter=3),
        "code": ParagraphStyle("code", fontName=FONT, fontSize=8.5,
                               leading=11, backColor=colors.HexColor("#f3f3f3")),
        "cell": ParagraphStyle("cell", fontName=FONT, fontSize=8.5, leading=11),
        "caption": ParagraphStyle(
            "caption", fontName=FONT, fontSize=8.5, leading=12,
            alignment=1, spaceBefore=3, spaceAfter=10,
            textColor=colors.HexColor("#444444"),
        ),
        "placeholder": ParagraphStyle(
            "placeholder", fontName=FONT, fontSize=9, leading=14,
            alignment=1, textColor=colors.HexColor("#777777"),
        ),
    }


def make_table(rows, st):
    parsed = []
    for row in rows:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        parsed.append(cells)
    if len(parsed) < 2:
        return None
    header = parsed[0]
    body = parsed[2:] if re.match(r"^\s*\|?[\s:|-]+\|?\s*$", rows[1]) else parsed[1:]
    data = [[Paragraph(clean(c), st["cell"]) for c in header]]
    for row in body:
        row = row + [""] * (len(header) - len(row))
        data.append([Paragraph(clean(c), st["cell"]) for c in row[:len(header)]])
    table = Table(data, repeatRows=1, colWidths=[170 / len(header) * mm] * len(header))
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#777777")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def make_figure(path, caption, st):
    max_width = 165 * mm
    max_height = 92 * mm
    if path.exists():
        image_width, image_height = ImageReader(str(path)).getSize()
        width = max_width
        height = width * image_height / max(1, image_width)
        if height > max_height:
            height = max_height
            width = height * image_width / max(1, image_height)
        flowable = Image(str(path), width=width, height=height)
    else:
        flowable = Table(
            [[Paragraph(
                "待补实拍照片<br/><br/>" + html.escape(path.name),
                st["placeholder"],
            )]],
            colWidths=[max_width],
            rowHeights=[55 * mm],
            style=[
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#9aa7b2")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f7f9")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ],
        )
    return [flowable, Paragraph(clean(caption), st["caption"])]


def build(output=None):
    st = styles()
    text = SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines()
    story = []
    i = 0
    in_code = False
    code_lines = []
    table_lines = []

    def flush_table():
        nonlocal table_lines
        if table_lines:
            table = make_table(table_lines, st)
            if table is not None:
                story.append(table)
                story.append(Spacer(1, 4))
            table_lines = []

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush_table()
            if in_code:
                story.append(Preformatted("\n".join(code_lines), st["code"]))
                story.append(Spacer(1, 4))
                code_lines = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        if line.strip().startswith("|") and line.strip().endswith("|"):
            table_lines.append(line)
            i += 1
            continue
        flush_table()
        s = line.strip()
        if not s:
            i += 1
            continue
        image_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", s)
        if image_match:
            caption, relative = image_match.groups()
            figure_path = (SOURCE.parent / relative).resolve()
            story.extend(make_figure(figure_path, caption, st))
            i += 1
            continue
        if s.startswith("# "):
            story.append(Paragraph(clean(s[2:]), st["title"]))
        elif s.startswith("## "):
            story.append(Paragraph(clean(s[3:]), st["h2"]))
        elif s.startswith("### "):
            story.append(Paragraph(clean(s[4:]), st["h3"]))
        elif s.startswith("- "):
            story.append(Paragraph("• " + clean(s[2:]), st["bullet"]))
        elif re.match(r"^\d+\.\s+", s):
            story.append(Paragraph(clean(s), st["bullet"]))
        else:
            story.append(Paragraph(clean(s), st["body"]))
        i += 1
    flush_table()
    if code_lines:
        story.append(Preformatted("\n".join(code_lines), st["code"]))

    output = Path(output) if output else SOURCE.with_suffix(".pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="基于 Zynq 的实时 ADAS 视觉演示系统",
        author="ADAS Stage 4",
    )
    doc.build(story)
    print("wrote", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    build(args.output)
