# 面向 ADAS 算法验证的 Zynq 软硬协同实时视觉平台

本项目基于 AMD ZYNQ-7010、OV5640 和 800×480 LCD，构建
`摄像头 → PL → VDMA → PS 感知/OSD → LCD` 的实时视觉闭环。作品采用
照片 HIL 验证 ADAS 视觉算法，并用 PL 决策 FSM 与 500 ms 看门狗形成
不依赖 Linux 的硬件安全岛。

## 模式入口

在板子的 Jupyter 中打开对应 notebook：

| 模式 | 入口 |
|---|---|
| 红绿灯 | `stage4/notebooks/traffic_light.ipynb` |
| 车道线 | `stage4/notebooks/lane.ipynb` |
| 障碍物 | `stage4/notebooks/obstacle.ipynb` |
| 完整演示 | `stage4/notebooks/full_demo.ipynb` |

三个感知模式严格互斥。启动新模式会停止上一模式，`stop_all()` 会恢复
安静的 Stage 2。

## 主要结果

| 项目 | 结果 |
|---|---|
| 自动测试 | 45/45 PASS |
| BSTLD 圆形灯留出集 | 31/40，77.5%；无灯 10/10 |
| TuSimple 虚实线留出集 | 16/20，80.0% |
| 实线/虚线控制卡 | 12/12、12/12 |
| PL 灰度加速 | 同场景 19.54 → 20.52 FPS，提升 5.02% |
| 看门狗 | 卡死注入后 `wd_timeout=0→1→0` |
| 资源 | LUT 55.34%、FF 47.06%、BRAM 16.67%、DSP 3.75% |
| 时序 | WNS +0.757 ns，全部约束满足 |

## 仓库结构

| 路径 | 内容 |
|---|---|
| `src/`、`scripts/`、`sim/` | RTL、Vivado 构建脚本和仿真 |
| `release/stage4/` | 最终比特流与 HWH |
| `demo/` | 现场演示流程与讲解稿 |
| `reports/` | 各阶段 Vivado 时序与资源报告 |
| `stage4/` | PYNQ/OpenCV 运行代码、测试、notebook 和工具 |
| `docs/` | 报告、调试记录、验收证据和比赛材料 |
| `skill/` | 可复用 PYNQ、证据统计、调试与大模型工作流 |

## 板上运行

准备板端目录：

```text
/home/xilinx/jupyter_notebooks/stage4
```

参考 [复现指南](docs/reproducibility.md) 安装依赖、运行测试和恢复 Stage 2。
板端测试命令：

```bash
cd /home/xilinx/jupyter_notebooks/stage4
PYTHONPATH=. /usr/local/share/pynq-venv/bin/python3 -m pytest -q \
  tests/test_cards.py tests/test_overlay.py \
  tests/test_decision.py tests/test_perception.py
```

预期结果：`45 passed`。

## 文档

- [复现指南](docs/reproducibility.md)
- [证据目录](docs/evidence/README.md)
- [照片拍摄指南](docs/photo_capture_guide.md)
- [Stage 4 验收记录](docs/stage4_acceptance.md)
- [Stage 4 调试记录](docs/stage4_debug.md)
- [AMD 赛道定位](docs/competition/amd_track.md)
- [项目简介与 15 字名称](docs/competition/project_intro.md)
- [大模型协作记录](docs/competition/llm_collaboration.md)
- [答辩问答](docs/competition/qa.md)
- [提交清单](docs/submission_checklist.md)
- [设计报告](docs/report/adas_report.md)
- [PDF 报告](docs/report/adas_report_final.pdf)

许可证见 [LICENSE](LICENSE)。
