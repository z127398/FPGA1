# Stage 2 调试记录：彩色/灰度二选一 mux 集成

日期：2026-09-27
工程：`D:/adas_pl/src/ip/7_ov5640_rgb2gray/vivado/ov5640_rgb2gray`
相关脚本：`scripts/stage2_add_color_gray_mux.tcl`
相关 RTL / IP：`src/rtl/axis_gray_bypass.v`、`src/ip/ip_repo/axis_gray_bypass_1_0/`

---

## 1. 目标

原来整条视频通路都过灰度 IP，PS 端只能拿到灰度帧，无法做红绿灯 HSV 识别。
需求是在 `video/camera_in` 内加一个二选一 mux：

```
frontend/video_out ─┬─► mux/s_axis  --(旁通)--------------------------┐
                    └─► mux/gp_axis ─► ov5640_rgb2gray_0/video_in    │
                        ov5640_rgb2gray_0/video_out ─► mux/gd_axis ──┤
                        mux/m_axis ─► out_stream ─► axi_vdma/S_AXIS_S2MM
axi_gpio_sel.gpio_io_o[0] ─► mux/sel        (0 = 彩色直通, 1 = 灰度)
```

---

## 2. 最危险的坑：`out_stream` 层次引脚被截位（会导致"能生成、能过时序、但不能工作"的比特流）

### 2.1 现象

全量构建报"成功"：时序收敛（WNS +0.891 / WHS +0.015）、DRC 无 critical、
比特流正常写出。但资源**不升反降**：

| 资源 | Stage 1 | Stage 2（坏） | 变化 |
|---|---|---|---|
| Slice LUTs | 7972 | 7334 | **-638** |
| Slice Registers | 14147 | 12879 | -1268 |
| Block RAM Tile | 10 | 9 | -1 |
| DSPs | 3 | **0** | **-3** |

DSP 从 3 变 0 是关键红旗——那 3 个 DSP 是 rgb2gray 的 RGB→Y 乘法器。

### 2.2 证据链

1. 生成的 BD wrapper `.../bd/base/synth/base.v` 里：

   ```verilog
   assign out_stream_tdata = axis_gray_bypass_0_m_axis_TDATA[0];   // 只连出第 0 位！
   assign out_stream_tkeep = axis_gray_bypass_0_m_axis_TKEEP[0];
   ```

2. 层次化资源报告里 `camera_in` 只剩 108 LUT：
   - `cmos_capture_data_0`、`v_vid_in_axi4s_0`（采集前端）**完全消失**
   - `axis_gray_bypass_0` **完全消失**
   - `ov5640_rgb2gray_0` 只剩 74 LUT / 106 FF，内部只有 `control_s_axi_U`
     （AXI 寄存器），`rgb2gray_480_800_U0`、`gray2rgb_480_800_U0`、
     `mac_muladd` 乘法器、FIFO **全部消失**

结论：24 位视频只连出第 0 位，下游看到的几乎是常量，综合把采集前端与整条
灰度数据通路判为死逻辑清掉了。**只保留被寻址的 AXI 从设备，所以地址映射、
DRC、时序全都正常——这类故障没有任何自动报错。**

### 2.3 根因

`camera_in/out_stream` 这个**层次引脚**的 AXIS 接口参数在原 BD 里从来没有被
显式保存过，它的位宽完全靠"参数传播"推导。

| 接口 | TDATA_NUM_BYTES |
|---|---|
| `ov5640_rgb2gray_0/video_in`、`/video_out` | 3（component.xml 中显式声明） |
| `axi_vdma/S_AXIS_S2MM` | 3 |
| `camera_in/axis_gray_bypass_0/*`（packaged IP 后） | 3 |
| **`camera_in/out_stream`** | **未设置 → 退回总线定义默认值 1** |

Stage 1 之所以正常：驱动 `out_stream` 的是灰度 IP——一个 component.xml 里
带 `<spirit:parameters><TDATA_NUM_BYTES>3</...>` 的**正式 IP**。
Stage 2 把驱动源换成 mux 后，Vivado 对该层次引脚重新推导时退回了默认 1 字节。

对照：仓库里灰度 IP 的 component.xml 每个 AXIS 接口都有
`TDATA_NUM_BYTES=3 / TUSER_WIDTH=1` 这类声明；而用
`create_bd_cell -type module -reference` 引入的 RTL，其接口参数在 BD 里是
**只读**的，`ipx::package_project` 打包出来的 component.xml 也**不含**这些参数。

### 2.4 尝试过但无效的方案（别再重复踩）

| 方案 | 结果 |
|---|---|
| 直接 `set_property CONFIG.TDATA_NUM_BYTES 3` 到 `out_stream`（层次引脚） | `CRITICAL WARNING [BD 41-737] ... It is read-only.` |
| 同上，设到 mux 的接口引脚（module-ref cell） | 同样 read-only（只有 FREQ_HZ 可写） |
| 把驱动源换成"参数完整"的真实 IP 后重连 | 仍为 1 位 |
| 中间插 `axis_register_slice`（显式 TDATA_NUM_BYTES=3）做参数锚点 | 仍为 1 位 |
| 只重连（不重建引脚对象） | 仍为 1 位 |

即：该层次引脚一旦被盖章成 1 字节，**设参数、换驱动源、加锚点、重连都推不回来**。

### 2.5 最终修复

两条一起做，缺一不可：

1. **把 mux 做成正式 IP**：`ipx::package_project` 打包到
   `src/ip/ip_repo/axis_gray_bypass_1_0/`，并**手工注入** component.xml 的
   AXIS 参数（`TDATA_NUM_BYTES=3`、`TUSER_WIDTH=1`、`HAS_TKEEP/TLAST/TREADY=1`），
   VLNV = `xilinx.com:user:axis_gray_bypass:1.0`。
2. **删除并重建 `camera_in/out_stream` 层次引脚**，再重新连接内/外两侧。

修复后 `base.v` 变为：

```verilog
output [23:0] out_stream_tdata;
assign out_stream_tdata[23:0] = axis_gray_bypass_0_m_axis_TDATA;   // 整宽直连
wire [23:0] camera_in_out_stream_TDATA;
.s_axis_s2mm_tdata(camera_in_out_stream_TDATA),                    // 直连 VDMA
```

（网络名里残留的 `axis_rs_0_M_AXIS` 只是名字，端点已是打包 IP 的 `m_axis`。）

---

## 3. 其他过程中踩到的坑

### 3.1 `get_property OFFSET` 读不到基地址

从机侧地址段 `/video/.../s_axi_control/Reg` **不带 OFFSET**。
基地址要读主机地址空间下映射出来的段：
`/ps7_0/Data/SEG_<cell>_Reg`。Stage 2 脚本已按此实现。

### 3.2 `ensure_net` 不能删除已有网络

给新引脚接时钟时，"两侧不同网络就删掉重连"的逻辑会把 `clk_100M` 这类挂着
几十个引脚的**共享时钟网**拆掉（实测拆过整张 100MHz 时钟树）。
现在 `ensure_net` 的规则是：

- 某一侧未连接 → `connect_bd_net` 直接挂到已有网络（扩展）
- 两侧都已连接且确认同网 → 不动
- 两侧都已连接但不同网 → **报错退出，绝不删除**

跨层次比较网络要用"网络端点集合是否相同"，不能比较网络对象名：
层次引脚从不同层次看会解析到不同层次的网络对象。

### 3.3 `generate_target` 会以 up-to-date 为由跳过重新生成

调试期间出现过生成的门禁读到**陈旧 `base.v`**（里面还引用已删除的单元）。
凡是"改完 BD 要立刻验证生成结果"的地方，必须用 `generate_target all -force`。

### 3.4 run 过期需要显式 reset

BD 改动后 `launch_runs synth_1` 会报
`[Common 17-69] Run 'synth_1' needs to be reset before launching`。
脚本改为自适应：先直接启动，只有报这个错才 `reset_run` 后重启（并顺带 reset impl_1），
这样没改 BD 时仍能秒过。

### 3.5 打包 IP 后必须把同名 RTL 从工程源移除

`src/rtl/axis_gray_bypass.v` 现在由 IP 自带
（`axis_gray_bypass_1_0/src/axis_gray_bypass.v`）。
如果同一份 .v 还挂在工程 `sources_1` 里，会与 IP 内部模块定义重名
（`[Synth 8-296]`）。脚本已改为执行时自动 `remove_files`。

### 3.6 Vivado Tcl 编码

中文 Windows 下 `encoding system` 是 cp936。实测：中文**注释**不会破坏解析
（`info complete` 通过、行数一致），但中文写入控制台会损坏约 2–5% 字符。
所以脚本内注释用中文、**所有 `puts`/日志一律 ASCII**。

### 3.7 完整日志要用 Vivado 的 `-log`

Tcl 层自己做 tee 抓不到 Vivado 自身的 INFO/WARNING/ERROR。
正确做法是启动参数加 `-log <file>`（实测能同时记录脚本 puts 与 Vivado 消息）：

```
vivado -mode batch -nojournal -log D:/adas_pl/reports/stage2_full_build.log \
       -source D:/adas_pl/scripts/stage2_add_color_gray_mux.tcl
```

---

## 4. 已固化的防护：门禁 + 自愈

`stage2_add_color_gray_mux.tcl` 的 Step 8 现在是一个循环：

1. `generate_target all -force`
2. `check_out_stream` 检查生成的 wrapper：
   - 端口声明必须是 `output [23:0] out_stream_tdata;`（否则 `NARROWED_DECL`）
   - `assign out_stream_tdata = <src>` 的右值**不得含位选**（否则 `NARROWED_ASSIGN`）
3. 不过 → 自动重建 `out_stream` 层次引脚 → 重新校验
4. 重建后仍不过 → 报错退出，**绝不产出坏比特流**

脚本还会校验 mux 单元的 VLNV 必须是
`xilinx.com:user:axis_gray_bypass:1.0`，防止有人误改回 module reference。

---

## 5. 后续串 median / sobel / otsu 时的检查清单

1. **新 IP 一律打包成正式 IP 放进 `ip_repo`**，不要在 BD 里用 module reference。
2. 打包后**检查 component.xml 是否真的声明了** `TDATA_NUM_BYTES` /
   `TUSER_WIDTH` / `HAS_TKEEP` / `HAS_TLAST`——`ipx::package_project` 默认不写，
   需要手工注入（参考 `axis_gray_bypass_1_0/component.xml`）。
3. 新 IP 接口位宽必须与上下游一致：本工程视频流是 **24 位（3 字节）、TUSER 1 位、
   带 TLAST/TKEEP**。
4. 每加一个 IP 后，**必须看生成 wrapper 里数据是不是整宽连到 `out_stream`**，
   并核对 **DSP/BRAM/FF 数量是否有不合理的下降**——下降往往意味着逻辑被优化掉。
5. 加完 IP 后跑一遍层次化资源报告
   （`report_utilization -hierarchical`），确认新 IP 的数据通路确实在网表里。
6. 交付件（`ready_to_test/*.bit/.hwh`）在确认上述检查通过前不要烧板。

---

## 6. 时间线（2026-09-27）

| 时间 | 事件 |
|---|---|
| 02:05 | Stage 2 只改 BD 版本跑通，`validate_bd_design` 通过 |
| 02:16 | 第一次全量构建在 `validate_bd_design` 报时钟源丢失（跨层次网络比较 bug） |
| 02:19–02:26 | 修复后全量构建"成功"，但产物被截位（当时未察觉） |
| 02:33 | 加入硬门禁后重跑，门禁拦下截位产物 |
| 02:35–02:50 | 定位根因：`out_stream` 层次引脚 AXIS 参数；验证 5 种无效方案 |
| 02:50–03:00 | mux 打包成 IP + 注入 AXIS 参数 |
| 03:0x | 删除并重建 `out_stream` 引脚，强制重新生成，门禁 **PASS（24 位）** |
| 03:0x | `ready_to_test/` 从 Stage 1 备份恢复并做 SHA256 校验 |
