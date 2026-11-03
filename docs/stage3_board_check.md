# Stage 3 板级核对（LED 映射 / 极性 / 看门狗）

适用产物：`ready_to_test/ov5640_rgb2gray.bit` + `.hwh`（Stage 3，WITH_SOBEL=0，时序已收敛）

## 0. 为什么要专门核一遍

RTL 里对三组板级信号的"有效电平"是有假设的，而假设错了不会报错、只会表现得像功能 bug：

| 信号 | RTL 的假设 | 依据 |
|---|---|---|
| `leds_tri_o[2:0]` | 高电平点亮 | 正点原子 PYNQ 指南："配置数据寄存器为 0x1 点亮 PL led0" |
| `beep_tri_o` | 高电平响 | 指南："蜂鸣器高电平有效，不触碰 tpad 时无响应" |
| `btns_tri_i[1:0]` | **按下 = 低电平** | 指南："领航者开发板上的按键默认为高电平"；RTL 内部已 `~btn` 反相 |

## 1. 地址与 PYNQ 对象名

| 作用 | 基地址 | PYNQ 访问方式 | ip_dict key |
|---|---|---|---|
| 视频通路选择（bit0 灰度、bit1 预留） | `0x41210000` | `ol.video.camera_in.axi_gpio_sel.channel1.write(v,0x1)` | `video/camera_in/axi_gpio_sel` |
| 决策控制字（16bit 写） | `0x41220000` | `ol.gpio_dec.channel1.write(v,0xFFFF)` | `gpio_dec` |
| 状态回读（7bit 读） | `0x41230000` | `ol.gpio_status.channel1.read()` | `gpio_status` |
| 按键回读（2bit 读） | `0x41240000` | `ol.gpio_btn.channel1.read()` | `gpio_btn` |
| 决策 FSM（无寄存器） | — | `ol.adas_decision_0` | `adas_decision_0` |

> **PYNQ 2.7 注意**：`Channel.write(val, mask)` 只更新 mask 为 1 的位。
> 旧写法 `write(v,0)` 一位都不会写；`gpio_dec` 必须用 `0xFFFF`，
> `axi_gpio_sel` 用 `0x1`。Stage 4 已按此修正。

## 2. 控制字 / 状态字位域

`gpio_dec` 写 16 bit：

```
[1:0] tl_state   0 无 / 1 红 / 2 绿 / 3 黄
[3:2] lane_left  0 无 / 1 实线 / 2 虚线
[5:4] lane_right
[6]   obstacle
[7]   force_ps     强制指令（红灯强制行驶报警 / 实线强制变道报警）
[9:8] turn_ps    0 无 / 1 左 / 2 右
[10]  heartbeat   每帧翻转，喂看门狗
[15:11] 保留
```

`gpio_status` 读 7 bit：`[2:0] led` `[3] beep` `[4] wd_timeout` `[6:5] alarm_reason`
（`alarm_reason`：1 红灯强制行驶 / 2 实线强制变道 / 3 障碍物）

## 3. 核对用 Jupyter 代码

> **注意**：看门狗门限 500ms。任何"观察 LED/蜂鸣器"的测试都必须持续喂心跳，
> 否则半秒后 FSM 进入安全态（LED 交替闪 + 蜂鸣器 1Hz 间断响），把测试结果盖掉。
> 下面 `feed()` 就是干这个的。

```python
import time
from pynq import Overlay

ol = Overlay("/home/xilinx/jupyter_notebooks/ov5640_rgb2gray.bit")   # 路径按你上传的位置改
dec    = ol.gpio_dec
status = ol.gpio_status
btns   = ol.gpio_btn

# 0) 先确认名字（把这一行结果贴给我就行）
print([k for k in ol.ip_dict if "gpio" in k or "adas" in k])

HB = 0
def word(tl=0, ll=0, lr=0, obs=0, force=0, turn=0, hb=0):
    return (tl & 3) | ((ll & 3) << 2) | ((lr & 3) << 4) | ((obs & 1) << 6) \
           | ((force & 1) << 7) | ((turn & 3) << 8) | ((hb & 1) << 10)

def feed(tl=2, ll=0, lr=0, obs=0, force=0, turn=0, hold=2.5):
    """持续喂心跳并保持给定状态，hold 秒后返回"""
    global HB
    t0 = time.time()
    while time.time() - t0 < hold:
        HB ^= 1
        dec.channel1.write(word(tl, ll, lr, obs, force, turn, HB), 0xFFFF)
        time.sleep(0.1)

def status_now():
    s = status.channel1.read()
    return dict(raw=s, led=s & 0x7, beep=(s >> 3) & 1,
                wd=(s >> 4) & 1, reason=(s >> 5) & 0x3)

# 1) 按键极性：不按 = 0b11，按下对应位变 0
print("release both keys  ->", bin(btns.channel1.read()))
print("hold  KEY0 (L14)   ->", bin(btns.channel1.read()))
print("hold  KEY1 (K16)   ->", bin(btns.channel1.read()))
#    期望：3 / 2 / 1   （若相反，说明按键是高电平按下，需要去掉 RTL 里的反相）

# 2) LED 逐位映射：看哪个物理灯亮，对照 leds_tri_o 的引脚
print("left  -> led=001 -> leds_tri_o[0] = J16"); feed(tl=2, turn=1, hold=3)
print("straight-> led=010 -> leds_tri_o[1] = H15"); feed(tl=2, turn=0, hold=3)
print("right -> led=100 -> leds_tri_o[2] = L15"); feed(tl=2, turn=2, hold=3)

# 3) 蜂鸣器：红灯 + 强制 => 持续报警（三灯 2Hz 闪 + 长响）
print("alarm ->"); feed(tl=1, force=1, hold=3); print(status_now())

# 4) 停车短鸣：红灯 + 不强制 => LED 全灭 + 单次短鸣
print("red stop ->"); feed(tl=1, force=0, hold=3); print(status_now())

# 5) 看门狗：停喂 1.5s，应看到 wd=1、LED 交替、蜂鸣器 1Hz
time.sleep(1.5)
print("after starving the dog ->", status_now())
#    期望：wd=1, beep 在 0/1 之间以 1Hz 跳，LED 在两个图案间交替

# 6) 恢复喂狗 + 停车
feed(tl=2, force=0, turn=0, hold=0.6)
dec.channel1.write(0, 0xFFFF)
```

## 4. 判定标准

| 检查项 | 通过 | 不通过时的修法 |
|---|---|---|
| `btns.channel1.read()` 释放=3、按 KEY0=2、按 KEY1=1 | ✓ | 若释放=0 / 按下=1，去掉 `adas_decision.v` 里的 `btn_sync <= ~btn;`（改成 `btn_sync <= btn;`）后重打包 IP + 重建 |
| 左转只亮 J16、直行只亮 H15、右转只亮 L15 | ✓ | 若灯序错位：只改 `scripts/adas_io.xdc` 的引脚分配，或改 RTL 里 `led_normal` 的位映射 |
| 报警时蜂鸣器**响**、静默时不响 | ✓ | 若反相：把 `beep <= ...` 换成 `beep <= ~...`（RTL 里注释已标注） |
| 停喂 1.5s 后 `wd=1` 且蜂鸣器 1Hz | ✓ | 说明看门狗链路通；若 wd 一直 0，检查心跳位是否真的在翻转 |

## 5. 引脚分配（与厂商原版 XDC 逐条一致）

来源：`src/ip/9_ov5640_sobel/vivado/ov5640_sobel/ready_to_test/ov5640_sobel.xdc`
（正点原子原版约束，注释 `#PL_LED 54-56 / #PL_KEY / #BEEP`），与本工程 `scripts/adas_io.xdc` 完全相同：

```
leds_tri_o[0] = J16     # PL_LED0
leds_tri_o[1] = H15     # PL_LED1
leds_tri_o[2] = L15     # PL_LED2
beep_tri_o    = M14     # BEEP
btns_tri_i[0] = L14     # PL_KEY0
btns_tri_i[1] = K16     # PL_KEY1
```

全部 `LVCMOS33`。
