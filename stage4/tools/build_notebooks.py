"""Generate one standalone notebook for each Stage 4 operating mode."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks"


def md(text):
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": text.splitlines(True),
    }


def code(text):
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": text.splitlines(True),
    }


SETUP = (
    "from pathlib import Path\n"
    "import sys\n"
    "\n"
    "ROOT = Path.cwd()\n"
    "if not (ROOT / 'demo.py').exists():\n"
    "    ROOT = ROOT.parent\n"
    "sys.path.insert(0, str(ROOT))\n"
    "\n"
    "from demo import (\n"
    "    start_passthrough, start_traffic_light, start_lane, start_obstacle,\n"
    "    run_traffic_light, stop_all, status_line, relearn_background,\n"
    "    video_probe, show_color_bars, start_watchdog_monitor,\n"
    "    stop_watchdog_monitor, read_image_demo,\n"
    ")\n"
    "\n"
    "print('Stage 4 ready:', ROOT)\n"
)


def notebook(title, cells):
    return {
        "cells": [md(title), code(SETUP)] + cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.8.2"},
        },
        "nbformat": 4,
        "nbformat_minor": 4,
    }


def write(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(path)


write(
    "traffic_light.ipynb",
    notebook(
        "# 红绿灯模式\n\n"
        "本 notebook 独立启动红绿灯检测。运行新的启动单元格会停止上一模式。",
        [
            code(
                "start_traffic_light()\n"
                "print(status_line())\n"
            ),
            md(
                "## 预期结果\n\n"
                "- 红卡：三灯灭，短鸣一次；\n"
                "- 绿卡：LED1 点亮；\n"
                "- 黄卡：短鸣提示；\n"
                "- KEY1 配合红灯：三灯闪烁并持续报警；\n"
                "- 矩形路牌和彩色非圆形区域不应触发。"
            ),
            code(
                "print(status_line())\n"
            ),
            md("## 停止\n\n停止 OSD 并恢复安静的 Stage 2。"),
            code(
                "stop_all()\n"
                "print('stopped; Stage 2 restored')\n"
            ),
        ],
    ),
)


write(
    "lane.ipynb",
    notebook(
        "# 车道线模式\n\n"
        "独立运行左右车道、SOLID/DASHED、BEV、偏移和偏航报警。",
        [
            md(
                "## 启动\n\n"
                "默认使用 PL RGB→灰度预处理，减少 PS 端重复颜色转换。"
            ),
            code(
                "start_lane()\n"
                "print(status_line())\n"
            ),
            md(
                "## 彩色回退\n\n"
                "需要保留黄车道色相信息时，可以改用下面的单元格。"
            ),
            code(
                "# start_lane(input_mode='color')\n"
                "# print(status_line())\n"
            ),
            md(
                "## 演示方式\n\n"
                "1. 实线卡居中，应显示 `L SOLID / R SOLID`；\n"
                "2. 明确向右移动，`OFF` 超过约 20% 后显示 `DEPART`；\n"
                "3. 移回中心并保持在画面内，应恢复 `OK`。"
            ),
            code(
                "print(status_line())\n"
            ),
            code(
                "stop_all()\n"
                "print('stopped; Stage 2 restored')\n"
            ),
        ],
    ),
)


write(
    "obstacle.ipynb",
    notebook(
        "# 障碍物模式\n\n"
        "独立运行小环境静态障碍物检测。相机必须固定。",
        [
            md(
                "## 启动\n\n"
                "先清空桌面并让双手离开画面，再运行下面单元格。"
            ),
            code(
                "start_obstacle()\n"
                "print('background learning:', status_line())\n"
            ),
            md(
                "## 重新学习背景\n\n"
                "需要清空场景后重新建模时运行。"
            ),
            code(
                "relearn_background()\n"
                "print('relearn requested; keep scene empty')\n"
            ),
            md(
                "## 预期结果\n\n"
                "空场景学习完成后，在下半屏中央放入静止物体。双手移出画面后，"
                "LCD 应显示 `OBJECT NEAR` 并短鸣；移除物体后框和报警应消失。"
            ),
            code(
                "print(status_line())\n"
            ),
            code(
                "stop_all()\n"
                "print('stopped; Stage 2 restored')\n"
            ),
        ],
    ),
)


write(
    "full_demo.ipynb",
    notebook(
        "# Stage 4 完整演示\n\n"
        "按顺序演示实时直通、三种感知模式、看门狗和图片注入兜底。",
        [
            md("## 0. 颜色链路自检"),
            code(
                "print(video_probe())\n"
                "show_color_bars()\n"
            ),
            md("## 1. PL 实时直通"),
            code(
                "fps = start_passthrough(3.0)\n"
                "print('passthrough FPS: %.2f' % fps)\n"
            ),
            md("## 2. 红绿灯模式"),
            code(
                "start_traffic_light()\n"
                "print(status_line())\n"
            ),
            md("## 3. 车道线模式"),
            code(
                "start_lane()\n"
                "print(status_line())\n"
            ),
            md("## 4. 障碍物模式"),
            code(
                "start_obstacle()\n"
                "print(status_line())\n"
            ),
            md("## 5. 看门狗演示"),
            code(
                "start_watchdog_monitor()\n"
                "fps = run_traffic_light(\n"
                "    duration=12.0, stall_after=4.0, stall_duration=1.5\n"
                ")\n"
                "events = stop_watchdog_monitor()\n"
                "print('FPS:', fps)\n"
                "print('watchdog:', events)\n"
            ),
            md("## 6. 图片注入兜底"),
            code(
                "read_image_demo()\n"
            ),
            md("## 7. 停止并恢复 Stage 2"),
            code(
                "stop_all()\n"
                "print('stopped; Stage 2 restored')\n"
            ),
        ],
    ),
)
