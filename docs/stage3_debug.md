# Stage 3 调试记录：分级流水线 + 决策闭环集成

日期：2026-10-05
工程：`D:/adas_pl/src/ip/7_ov5640_rgb2gray/vivado/ov5640_rgb2gray/ov5640_rgb2gray.xpr`
脚本：`scripts/pkg_rtl_as_ip.tcl`、`scripts/xml_param_inject.tcl`、`scripts/stage3_add_adas_pipeline.tcl`
单测：`sim/test_xml_param_inject.tcl`（`xtclsh` 离线跑，不需要 Vivado 工程）

## 1. 本阶段做了什么

| 位置 | 内容 |
|---|---|
| `video/camera_in` | 单级 mux 升级为两级可旁路流水线：`frontend → stage_gray_0 → stage_sobel_0 → out_stream`；`axi_gpio_sel` 由 1 位扩到 3 位（bit0 灰度、bit1 Sobel、bit2 预留） |
| BD 顶层 | 新增 `adas_decision_0`（决策 FSM + 看门狗 + 按键消抖）、`gpio_dec`(16b@0x41220000)、`gpio_status`(7b@0x41230000)、`gpio_btn`(2b@0x41240000)、7 个 `xlslice` 分发控制字、1 个 `xlconcat` 拼状态字 |
| 顶层端口 | 新增 `leds_tri_o[2:0]` / `beep_tri_o` / `btns_tri_i[1:0]`，约束文件 `scripts/adas_io.xdc` 加入 `constrs_1` |
| 总线 | `ps7_0_axi_periph` NUM_MI 3→6；`video/axi_interconnect_0` NUM_MI 6→7（Sobel 控制口 @0x40010000） |

软硬分工：**感知全在 PS（Python/OpenCV），决策与执行在 PL**。PS 每帧写一次 16 位控制字、回读 7 位状态字；PS 卡死时 PL 看门狗 500ms 超时进安全态（LED 交替闪 + 蜂鸣器 1Hz）。

## 2. 门禁结果（BUILD_BITSTREAM=0 那次，`reports/stage3_bd_edit.log`）

```
[ OK ] camera_in video path verified
[ OK ] all stage buses are 24-bit            <- 12 条 tdata 全是 [23:0]
[ OK ] FSM clock/reset verified on the real 100MHz peripheral tree
[ OK ] gpio_dec base = 0x41220000 / gpio_status = 0x41230000 / gpio_btn = 0x41240000
[ OK ] axi_gpio_sel base = 0x41210000 / ov5640_sobel_0 base = 0x40010000
[ OK ] validate_bd_design: PASS
```

拓扑快照：`reports/stage3_bd_topology.txt`。

## 3. 踩到的坑（按代价从大到小）

### 坑 1（最严重）：Tcl ARE 正则的 leftmost-longest，让参数注入全部错位

`pkg_rtl_as_ip.tcl` 旧版用一条跨标签懒匹配正则给 AXIS 接口注入 `TDATA_NUM_BYTES` 等参数：

```tcl
set pat "(<spirit:busInterface>\\s*<spirit:name>$ifname</spirit:name>.*?)(</spirit:busInterface>)"
regsub -all $pat $t "\\1$block\\2"
```

直觉上 `.*?` 会停在**第一个**闭合标签。实测不是：Tcl 的 ARE 引擎对**整体匹配**采用
leftmost-longest 规则，`.*?` 只是子表达式之间的取舍，结果它一路吃到文档里**最后**一个
`</spirit:busInterface>`。于是五个接口的参数块全部塞进了最后一个接口 `aclk`：

* `aclk` 里出现 6 个 `<spirit:parameters>`（schema 规定至多 1 个）
* `BUSIFPARAM_VALUE.ACLK.ASSOCIATED_BUSIF` 出现两次（重复 id）
* `s_axis/px_axis/pd_axis/m_axis` 一条参数都没有

后果非常隐蔽：Vivado 只在加载 IP 仓库时打一行

```
WARNING: [IP_Flow 19-395] Problem validating against XML schema: see 'spirit:busInterface' : Bad end of element
CRITICAL WARNING: [IP_Flow 19-1977] Unable to read IP file .../adas_decision_1_0/component.xml.
                   This IP will not be included in the IP Catalog.
```

然后把 IP **静默忽略**。构建流程照常走，直到 BD 里 `create_bd_cell` 找不到 IP 才炸；
更糟的情况是命中旧缓存，继续产出"看着正常"的结果。

**修复**：把 XML 处理抽成 `scripts/xml_param_inject.tcl`，全部改用
`string first` / `string range` 精确定位元素边界，并在写回后跑三道门禁：

1. `xmlp_wellformed` —— 标签配对（自己写的栈式检查，不依赖 XML 库）
2. `xmlp_busif_param_blocks` —— 每个 busInterface 的 `<spirit:parameters>` 至多 1 个
3. `xmlp_duplicate_ids` —— `BUSIFPARAM_VALUE.*` 不重复

再加一道**端到端**门禁：打包完立刻把 `ip_repo_paths` 指向仓库、`update_ip_catalog`，
要求 `get_ipdefs` 能返回该 VLNV，否则直接失败退出。

**回归证据**：`sim/test_xml_param_inject.tcl` 用 `xtclsh` 离线跑，23 项全 PASS，其中

* T3 在合成文件上复现了旧正则的错位（参数跑到元素外 + 某接口出现 2 个 parameters 块）
* T4 拿 D 盘上那份真实的坏 `component.xml` 去跑门禁，被准确抓出：
  `interface 'aclk' has 6 <spirit:parameters> blocks (max 1)` +
  `duplicate bus parameter id(s): BUSIFPARAM_VALUE.ACLK.ASSOCIATED_BUSIF`

### 坑 2：`xlslice` / `xlconcat` 没有时钟引脚

写脚本时顺手给选择位切片连 `aclk`，直接报 `pin not found: sel_slice_gray/aclk`。
这两个 IP 是纯组合逻辑，只数据进数据出。**代价**：一次 30s 的空跑。

### 坑 3：appcore 型层次不能用"引脚对引脚"连网络

`ps7_0_axi_periph` 的 `TYPE` 是 `hier`（appcore），给它新增的 MI 连时钟时：

```tcl
connect_bd_net [get_bd_pins ps7_0_axi_periph/M03_ACLK] [get_bd_pins ps7_0_axi_periph/M00_ACLK]
-> ERROR: [BD 41-738] the object '/ps7_0_axi_periph' is part of the appcore
          'ps7_0_axi_periph' and cannot be modified directly.
```

**修复**：把引脚挂到**已存在的网络**上要用 `-net` 形式：

```tcl
connect_bd_net -net <已有的net对象> <新引脚>
```

实测这样写同一根 100MHz 时钟树就挂得上。另外这类层次的 MI 复位在内部已经由
coupler 接到 cell 的 ARESETN 上，外部 ARESETN 引脚自带一张内部网络，
"两侧都已连但不是同一张网"是**正常状态**，不能按错误处理（脚本里用
`ensure_net_soft` 区分）。

同时注意：FSM / GPIO 的时钟复位**参照点**不能用 appcore 内部的 `M00_ARESETN`，
要用根层次的普通 IP（本工程选 `axi_intc_0/s_axi_aclk`、`axi_intc_0/s_axi_aresetn`）。

### 坑 4：总线端口 port 与同名 pin 是两个对象，只有 port 能查到网络

幂等复跑到"FSM 输出 → 顶层端口"时报：

```
WARNING: [BD 41-395] Exec TCL: all ports/pins are already connected to '/adas_decision_0_led'
ERROR: [BD 5-4] Error: running connect_bd_net.
```

探针 `probe_bus_port.tcl` 查清了：

| 表达式 | 结果 |
|---|---|
| `get_bd_pins leds_tri_o` | `/leds_tri_o`（pin 对象） |
| `get_bd_nets -of_objects <上面那个>` | **空** |
| `get_bd_ports leds_tri_o` | `/leds_tri_o`（port 对象） |
| `get_bd_nets -of_objects <上面那个>` | `/adas_decision_0_led` |

也就是说同名对象分属两个类，`get_bd_nets` 只认 port 对象。脚本里 `pin_of` 因此
**必须先查 ports 再查 pins**。这个坑会让"幂等"假成立：第一次跑没事，第二次跑必炸。

### 坑 5：`assert_intf_peer` 不能用整串 `string match`

`get_bd_intf_pins -of_objects <整张网>` 会同时返回网络两端的引脚，且顺序不保证目标
在后。写成 `string match $pattern $peers` 会把 `m_axis <-> out_stream` 这种
"目标在前"的连接误判成拓扑错误。必须**逐元素**匹配。

### 坑 6：`format` 串里的方括号会被当命令替换

```tcl
puts $fh [format "  %-48s [%s:%s]" ...]   ;# 错：[%s:%s] 被当命令执行
puts $fh [format "  %-48s \[%s:%s\]" ...] ;# 对
```

### 坑 7：`out_stream` 层次引脚**再次**被静默截位（这次被门禁拦住）

流水线末端驱动源从 `axis_gray_bypass_0/m_axis` 换成 `stage_sobel_0/m_axis` 之后，
`camera_in/out_stream` 这个层次引脚的 AXIS 参数又一次退回默认 1 字节。
脚本 Step 11 的门禁读出 `NARROWED_DECL`，自动删除并重建该层次引脚、重新生成产物，
第二次检查 `gate PASS`。生成的 wrapper 现在是：

```verilog
output [23:0] out_stream_tdata;
assign out_stream_tdata[23:0] = stage_sobel_0_m_axis_TDATA;   // 赋值右值不带位选
```

**结论**：只要流水线末端换过驱动源，就必须重跑这道门禁。Stage 2 的教训（能生成、
能过时序、DSP 归零、完全不能工作）在这里差点原样重演，靠门禁兜住了。

## 4. 遗留告警的判断

| 告警 | 判断 |
|---|---|
| `[BD 41-926]` `stage_gray_0/s_axis` LAYERED_METADATA 不能同步进 cell | **无害**。这是视频 datatype 注解（G_B_R_444，24bit），我们的自研 IP 只声明 `TDATA_NUM_BYTES=3`，不参与综合。位宽本身在 BD 与 wrapper 两处都被门禁验过是 24bit。Stage 2 曾把同类告警误判成"无害"而漏掉真正的截位问题，所以这次一律以**位宽实测**为准，不看告警文字。 |
| `[axi_intc:4.1-13]` 中断输出选 Bus 但未连匹配接口 | **既有现象**，Stage 2 用不带 `-force` 的 validate 没暴露；用 `-force` 才会跑 IP 级深检查。与本次改动无关，validate 仍 PASS。建议 W3 顺手改成 Single 消除。 |
| `[BD 41-434] Could not find an IP with XCI file...` + `Design successfully migrated to use XCI files` | 改 `ps7_0_axi_periph` 的 NUM_MI 时 Vivado 会重建该 appcore 的内部 IP 文件，重开工程时先报"找不到"再自动迁移。属一次性现象。 |
| `[BD 41-176]` `M_AXI_GP0_aximm_wr_socket` 等 | 原设计既有，与本次改动无关。 |

## 5. 如何复跑

```bat
:: 只改 BD + validate（不烧板、不生成比特流）
vivado -mode batch -nojournal -log D:/adas_pl/reports/stage3_bd_edit.log ^
       -source D:/adas_pl/scripts/stage3_add_adas_pipeline.tcl

:: 全量（BD 产物 + 综合 + 实现 + 写比特流 + 导出）
:: 把脚本顶部 BUILD_BITSTREAM 改成 1 后再执行同一条命令，日志换 stage3_full_build.log
```

脚本是幂等的：所有 BD 编辑走 `ensure_*`，新建对象前先判断存在性，基线备份只建一次
（`backups/7_ov5640_rgb2gray_baseline_stage3/`）。中途 `die` 时绝不
`save_bd_design`，磁盘工程保持原状。

自研 IP 改动后必须先重打包（会跑 XML 门禁 + catalog 门禁）：

```bat
E:/Xilinx/Vivado/2020.2/bin/xtclsh.bat D:/adas_pl/sim/test_xml_param_inject.tcl
vivado -mode batch -nojournal -log D:/adas_pl/reports/stage3_pkg_ip.log ^
       -source D:/adas_pl/scripts/pkg_rtl_as_ip.tcl
```

## 6. 回滚 BD 时踩到的三个新坑（2026-10-06 补）

### 坑 8：只回滚 `base.bd` 不够，appcore 的展开状态藏在生成产物里

为了拿到"时序干净的 WITH_SOBEL=0 版本"，我把 `backups/.../base.bd`（Stage 2 状态）
盖回工程。JSON 本身是对的（`ps7_0_axi_periph` 的 `NUM_MI` 是 3、`video/axi_interconnect_0`
是 6），但打开工程后脚本读到 `CONFIG.NUM_MI = 6`，接着连 `M03_AXI` 时报
`intf pin not found`——**"属性说 6、边界引脚只有 M00..M02"的不一致状态**。

原因：`axi_interconnect` 是"BD 型 IP"（appcore），它按 NUM_MI 展开出来的东西
（`m03_couplers`、`base_m03_regslice_14` 之类）会**立刻落盘**到
`bd/base/ip/`、`bd/base/base.bda` 等生成产物里。回滚 `.bd` 不会回滚这些。
`reset_target all`（Vivado 官方 Reset Output Products）也只清了 sim/synth/hw_handoff，
`ip/` 原封不动，所以还是不生效。

**修法**：把 `bd/base/` 下**除 `base.bd` 之外**的全部内容删掉，让 `.bd` 成为唯一真源。
下一次打开工程 + `generate_target all -force` 会把所有 IP 实例、wrapper、handoff
全部按 `.bd` 重新生成。删之前必须校验绝对路径（脚本外的一次性操作）。

### 坑 9：清掉生成产物后要手动把 wrapper 加回 fileset

`bd/base/hdl/base_wrapper.v` 一起被删掉后，Vivado 打开工程时会：

```
CRITICAL WARNING: [Project 1-19] Could not find the file '.../bd/base/hdl/base_wrapper.v'
```

并把它**从 `sources_1` 里摘掉**。`generate_target` 只负责把文件写回来，
**不会自动加回 fileset**，于是综合阶段报：

```
ERROR: [Synth 8-439] module 'base_wrapper' not found
```

**修法**：脚本新增 Step 11b——`generate_target` 之后检查该文件是否在
`get_files` 列表里，缺了就 `add_files -fileset sources_1` + `update_compile_order`，
并复核 `top` 仍是 `base_wrapper`。

### 坑 10：别用 Select-String 去 grep `base.bd`

`base.bd` 是 CRLF + 超长行的 JSON。用 `Select-String -SimpleMatch` 搜
`axis_gray_bypass_0` 会返回 0 个匹配，让人误判"BD 里没有这个 cell / BD 没被改过"。
（本项目就真的先误判过一次，靠文件时间戳才发现不对。）
**改用字节级或 UTF8 解码后的正则**：

```powershell
$t=[Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($bd))
([regex]::Matches($t,[regex]::Escape('axis_gray_bypass_0'))).Count   # -> 11
```

## 7. 流程修正：门禁集合必须包含时序

Stage 3 第一版（含 Sobel）三项数据通路指标全过、DRC 干净、比特流正常写出，
但 **WNS = -6.71ns**——因为当时定的三条门禁里没有时序这一条，脚本就放行了。

现在的 Stage 3 脚本里已加入：

```tcl
set ALLOW_NEGATIVE_SLACK 0   ;# 默认：WNS < 0 直接拒绝导出，并打印最差路径首尾端点
```

最终 WITH_SOBEL=0 版本的实测：**WNS = +0.757ns，WHS = +0.011ns，时序全部满足**。
注意裕量并不宽（不到 1ns），后续再往这条 100MHz 通路上加东西必须重新过这道闸。

## 8. Sobel 的最终处置（决定 + 依据）

HLS 生成的 `fsqrt_32ns_32ns_32_7_no_dsp_1` 用 41 级 CARRY4 串出 32 位开方，
数据路径 16.47ns（要求 10ns），把 89 个端点全部拖到负裕量。正解是把
`sqrt(Gx²+Gy²)` 换成 `|Gx|+|Gy|`，但**正点原子资料盘里没有该 IP 的 HLS C++ 源码**
（`9_ov5640_sobel` 只有 Vivado 工程与 notebook，无 .cpp/.h/run_hls.tcl），
改 `hdl/verilog/` 里工具生成的 RTL 属于不可维护的做法。

因此决定：**永久放弃 PL 端 Sobel**，车道线检测改在 PS 用 `cv2.Canny + HoughLinesP`
直接吃 PL 灰度通路的帧。脚本保留 `WITH_SOBEL` 开关但不启用；残留的 Sobel 级
（cell + 层次引脚 + M06）在 `WITH_SOBEL=0` 分支里会被自动清理干净。
