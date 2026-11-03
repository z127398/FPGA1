# Stage 4 验收记录

日期：2026-10-26

## 环境

- 板子：PYNQ-Z2 / Zynq-7010/7020，IP `192.168.137.172`
- PYNQ 2.7.0，Linux 5.4.0-xilinx-v2020.2，armv7l
- Python 3.8.2，OpenCV 4.2.0，NumPy 1.20.3
- Stage 3 比特流 MD5 `1f18cca001db496408ec85ec9cb301ea`

## 软件测试

命令：

```bash
cd /home/xilinx/jupyter_notebooks/stage4
PYTHONPATH=. /usr/local/share/pynq-venv/bin/python3 -m pytest -q \
  tests/test_cards.py tests/test_overlay.py \
  tests/test_decision.py tests/test_perception.py
```

结果：**45/45 PASS**

测试覆盖寄存器契约、三模式隔离、红绿灯圆形门控、车道颜色掩膜、
直线/曲线选择、虚实线间隙分类、偏航迟滞、障碍物跟踪、OSD 和看门狗。

## 板级结果

| 项目 | 结果 | 证据 |
|---|---|---|
| PL 直通 | 约 37.8 FPS | `tools/bench_passthrough.py` |
| OSD 主循环 | 当前交通灯模式约 23.0 FPS | `tools/smoke_modes.py` |
| 早期 OSD 5 分钟 | mean 20.18 / min 17.58 / max 22.54 FPS | `evidence/soak/summary.json` |
| 颜色/灰度链路 | 通道差 9.21/0.0，选择位 `0→1→0` | `evidence/safety/video_probe.json` |
| 帧驱动看门狗 | `wd=0→1→0`；1.5 s 卡死后自动恢复 | `evidence/safety/watchdog_smoke.json` |
| 三严格感知模式 | 红绿灯、车道线、障碍物互斥运行 | `tests/test_perception.py` |
| 三模式 FPS | 红绿灯 23.0 / 车道线 20.5 / 障碍物 26.8 | `evidence/safety/modes_smoke.json` |
| PL 灰度加速 | 19.54 → 20.52 FPS，提升 5.02% | `evidence/lane_input_bench.json` |
| 圆形灯约束 | 圆/过曝圆环通过；矩形和灯带拒绝 | `tests/test_perception.py` |
| BSTLD 60+40 | 调参 46/60；留出 31/40；无灯负样本 10/10 | `report/metrics/bstld_*_results.json` |
| TuSimple 10+10 帧 | 调参 15/20；留出 16/20 侧标签 | `report/metrics/tusimple_*_results.json` |
| 分模式延迟 | 保留逐帧 CSV，最终报告按同一冻结版本复核 | `evidence/latency_*.csv` |
| 彩色/灰度切换 | 可切换，彩色/灰度均值≈127 | `tools/probe_video.py` |
| 心跳/看门狗 | OSD 卡死 1.5 s 后 `wd=1`、LED/蜂鸣安全态、恢复清零 | `tools/smoke_liveness.py` |
| 红绿灯卡 | RED/GREEN/YELLOW 全对 | 生成卡 + `tests/test_cards.py` |
| BSTLD 真图近景卡 | real_red→RED，real_green→GREEN | 公开样本裁切 |
| 实线/虚线卡 | SOLID/SOLID、DASHED/DASHED | 生成卡 + 测试 |
| 图片注入 | PPM 注入 LCD 成功 | `read_image_demo()` |
| 生成卡 manifest | TL 5/5=1.0，lane 4/4=1.0 | `tools/eval_manifest.py` |
| 现场灯卡 20 帧 | 红 20/20、绿 20/20、黄 20/20 | `docs/evidence/count_*.json` |
| 小环境静态障碍物 | 近区 `OBJECT` + `alarm_reason=3` | `docs/evidence/environment/` |
| 小环境干净单框 | 156×192 OBJECT，近区短鸣 | `docs/evidence/environment/osd.png` |

### 现场实拍证据（OV5640 + 手机显示）

| 卡 | 结果 | 证据 |
|---|---|---|
| 红 | RED（低饱和回退） | `docs/evidence/red/` |
| 绿 | GREEN，LED2，obstacle=false | `docs/evidence/green/` |
| 黄 | YELLOW，短鸣 | `docs/evidence/yellow/` |
| 实线 | SOLID / SOLID，12/12 | `docs/evidence/lane_type_tuning/solid/` |
| 虚线 | DASHED / DASHED，12/12 | `docs/evidence/lane_type_tuning/dashed/` |

黄色阈值按实拍 HSV 调整为 H 20–45、S/V 90，调整后 20/20。
虚线证据的左侧背景有一个绿色物体被误判为 GREEN，但左右车道线结果正确；
该现象保留在原始证据中，后续可用更纯净的背景复拍。

OV5640 闪光灯旧序列 `0x3016=0x02` 实际使能了 pad；已改为 `0x3016=0x00`，
并增加严格失败时的低饱和红环回退。

启动初期 AWB/曝光尚未收敛时，FPS 可能短暂下降；报告使用稳定段数据并
注明处理分辨率、输入模式和测试条件。

## 现场卡

`stage4/assets/cards/`：

- `red.png`、`green.png`、`yellow.png`
- `lane_solid.png`、`lane_dashed.png`

`stage4/assets/print/` 是 A4 300 dpi 打印版（2480×3508），图中场景占 90%，
标签在图外，避免标签干扰检测。

## 未完成/待现场

- 三分钟现场视频：已完成并发布到 GitHub `stage4-freeze` Release；上传版本
  时长 2:59、960×544、30 FPS。若最终提交规则严格要求 1080P，需使用高分辨率
  母版重新导出。
- PDF 报告：内容冻结后从 Markdown 重新生成。

## 验收结论

核心闭环（实时视频、红绿灯、车道线、小环境静态障碍物、决策 FSM、看门狗、OSD、图片兜底）
已达到可演示状态；工程侧可以按 10/27 冻结。
