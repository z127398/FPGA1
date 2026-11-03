# Stage 4 调试记录（2026-10-19）

## 0. 起点

- Stage 3 最终比特流：`src/ip/7_ov5640_rgb2gray/vivado/ov5640_rgb2gray/ready_to_test/ov5640_rgb2gray.bit`
  - MD5 `1f18cca001db496408ec85ec9cb301ea`
  - HWH MD5 `ab0370e0a80c372616c8a7588088c512`
- 板上旧 `ready_to_test/ov5640_rgb2gray.hwh` 不含 `adas_decision/gpio_dec/gpio_status/gpio_btn`，
  是 Stage 2 旧构建；必须先上传 Stage 3 最终比特流到 `stage4_ready/`。
- 板上已有可运行的红绿灯 notebook：`stage4_traffic_light.ipynb`。
  实测红屏 BGR≈(33, 86, 200)，HSV H≈9.5、S≈213，输出 `RED`，说明
  摄像头、LCD、OV5640 I2C 和 320×240 取帧链路可用。

## 1. 第一个致命问题：`write(v, 0)` 实际不写

Stage 3 文档和旧 notebook 使用：

```python
dec.channel1.write(word, 0)
```

PYNQ 2.7 的 `pynq.lib.axigpio.Channel.write(val, mask)` 实现是：

```python
self._val = (self._val & ~mask) | (val & mask)
self._parent.write(self._channel * 8, self._val)
```

`mask=0` 时任何位都不会更新。结果是心跳位从未进入 PL：

- 绿灯状态读到 raw=0；
- 500 ms 后 FSM 进入看门狗安全态；
- 蜂鸣器 1 Hz 响，LED 交替闪；
- 所有“状态不对”的现象都被误判成 FSM 或接线问题。

修复：`dec.channel1.write(word & 0xFFFF, 0xFFFF)`。

修复后板级 smoke 结果：

| 写入 | status |
|---|---|
| 绿灯 | raw=2, led=2, beep=0, wd=0 |
| 红灯停车 | raw=0, led=0, beep=0, wd=0 |
| 红灯 + force | raw=40, led=0, beep=1, wd=0, reason=1 |
| 实线 + 左转 | raw=79, led=7, beep=1, wd=0, reason=2 |
| 停喂 1.0 s | raw=21, led=5, wd=1 |

## 2. PYNQ 层次驱动匹配失败

Stage 3 在 `video/camera_in` 下增加 `stage_gray_0` 后，PYNQ 2.7 把
`video/video_out` 绑定成 `DocumentedHierarchy`，而不是 `VideoOut`；
因此 `ol.video.video_in` 不存在：

```
AttributeError: Could not find IP or hierarchy video_in in overlay
```

底层 `video/axi_vdma` 和 `video/video_out/frontend` 都是好的。解决办法：

- 直接用 `video.axi_vdma.readchannel/writechannel`；
- 用 `video2lcd.dvi.HDMIOutFrontend` 重新绑定 LCD frontend；
- 两个薄适配器 `_VideoInAdapter/_VideoOutAdapter` 保持 `readframe/tie/writeframe` 接口。

注意：`ol.video.video_out.frontend` 自动绑定成 `pynq.lib.video.dvi.HDMIOutFrontend`，
它的模式表没有 800×480，会报 `Invalid Output resolution 800x480`。
必须显式构造 `pynq.lib.video2lcd.dvi.HDMIOutFrontend`。

## 3. VDMA 写帧只收 VideoFrame

直接传 numpy 数组会报：

```
AttributeError: 'numpy.ndarray' object has no attribute 'flush'
```

修复：`newframe()` 后用 `np.copyto` 拷贝，再 `writeframe`。

## 4. 颜色顺序

最终板级结论：LCD 视频通路实际接收 **BGR 字节序**。用标注色条实测时，
原先的 `BGR→RGB` 转换会让红色显示成蓝色、蓝色显示成红色；关闭转换后
蓝/绿/红/白顺序正确，用户现场确认“现在对了”。

最终配置：

```python
LCD_FRAMEBUFFER_BGR = True   # to_lcd 保持 OpenCV BGR 顺序
```

离线保存的 PNG 和物理 LCD 的字节解释可能不同，因此颜色顺序必须以板上
色条为准，不能只看 `cv2.imwrite` 的截图。

## 4.1 识别稳定层

- 红绿灯进入颜色需 2 个检测周期确认，换色/清除需 3 个周期，框取最近
  3 次中值；
- 车道线优先跟随上一轮位置和斜率，端点取最近 3 次中值，类别切换需要
  3 次一致；
- 障碍物按中心距离关联相邻框，坐标使用 0.35 低通系数；
- 圆形约束、固定卡片抖动和三模式测试已纳入当前 45 项自动测试。

## 4.2 OV5640 闪光灯：旧寄存器序列反而使能了 pad

旧 notebook 写：

```python
iic.send(0x3C, bytes([0x30, 0x19, 0x00]), 3)
iic.send(0x3C, bytes([0x30, 0x16, 0x02]), 3)
```

OV5640 数据手册 4.10 节：

- `0x3016` = PAD OUTPUT ENABLE
- `0x3019` = PAD OUTPUT VALUE

`0x3016=0x02` 使能了一个 pad（闪光/频闪路径），不是关闭。现场红卡中心出现过曝
白斑、红色只剩低饱和光环时，用户首先怀疑闪光灯，核对寄存器后确认该序列有误。
Stage 4 改为：

```python
iic.send(0x3C, bytes([0x30, 0x19, 0x00]), 3)
iic.send(0x3C, bytes([0x30, 0x16, 0x00]), 3)
```

另外保留严格 HSV 检测，严格失败时才启用低饱和大目标回退；回退拒绝贴边连通域，
避免木桌/墙面误报。

实拍黄卡的 H 中位数约 30、H 90 分位约 38，S/V 中位数约 123/112；手机显示会
在黄/绿边缘漂移。最终黄色区间放宽为 H 20–45、S/V 90，调整后黄卡 20/20。
红/绿卡仍为 20/20。

## 4.2 障碍物改为小环境多帧背景

原来用相邻帧差，相机轻微晃动/换卡会把整片背景判成障碍物；墙也是静态背景，
帧差抓不到。最终做法：

- `traffic_light` 模式只跑圆形灯检测；
- `lane` 模式只跑左右车道线，GREEN 仅作为执行器使能哨兵；
- `obstacle` 模式只跑障碍物，先采集 24 帧空场景中值背景；
- 相位相关补偿小抖动；位移 >8 px 或大幅平移时重新学背景；
- 背景与当前帧差、5×5 形态学、面积/宽高比过滤、相邻碎片合并；
- 3 帧确认、10 帧保持；近区（下方 45%×中央 60%）才置 obstacle 位；
- 墙/桌面作为背景，不画 WALL；物体统一标 `OBJECT`。

板级实拍：空场景学习后放入瓶子，出现 `OBJECT NEAR`，`obstacle=1`，
`alarm_reason=3`。最终干净复拍为单个 156×192 框；首轮手拿瓶子时手和瓶子
曾分别框为两个 OBJECT（手也是障碍物），加入 10 秒放置缓冲和碎片合并后复核通过。

## 5. 性能迭代

| 版本 | 处理分辨率 | 直通 | OSD | 主要瓶颈 |
|---|---:|---:|---:|---|
| 初版 | 640×480 | 35.9 FPS | 2.2 FPS | 红绿灯 263 ms、缩放 51 ms、LCD 64 ms |
| 去形态学 + 轮廓 | 640×480 | — | 4.5 FPS | 红绿灯仍 135 ms |
| 320×240 + 每 4 帧红绿灯 | 320×240 | 37.8 FPS | 20.2 FPS（5 分钟均值） | 模式互斥后计算量降低 |

最终配置：

- 处理 320×240，显示 800×480；
- 红绿灯每 4 帧一次，3 帧投票；
- 车道线每 6 帧一次，5 帧投票；
- 障碍物 160×120，每 2 帧一次；
- 画框/线在 320×240 上完成，最后一次性放大到 800×480；
- LCD 转换用 `cv2.cvtColor`，不再重复 resize。

## 6. 板子收尾

`stop_all()` 默认保留 10 Hz 心跳并把控制字清零，避免 Stage 3 FSM 进入
看门狗安全态后一直响。演示结束再调用 `restore_quiet_bitstream()` 切回
无 FSM 的 Stage 2，保证实验室静音。

## 7. 复现命令

```bash
cd /home/xilinx/jupyter_notebooks/stage4
PYTHONPATH=. python3 -m unittest discover -s tests -v
sudo env HOME=/home/xilinx XILINX_XRT=/usr PYNQ_PYTHON=python3.8 \
  /usr/local/share/pynq-venv/bin/python3 tools/bench_passthrough.py
```

> 板子没有外网；文件用 PC 的 `scp` 上传，不要在板上 `pip install`。
