# =============================================================================
#  ADAS-PL / Stage 2 -- 给 7_ov5640_rgb2gray 增加 "彩色直通 / 灰度" 二选一
# -----------------------------------------------------------------------------
#  工程 : D:/adas_pl/src/ip/7_ov5640_rgb2gray/vivado/ov5640_rgb2gray
#  目标 : 在 video/camera_in 内插入自研 2:1 AXIS mux (axis_gray_bypass)
#         以及一个 axi_gpio 控制选择位，重建比特流并导出 ready_to_test
#
#  用法 :
#     vivado -mode batch -nojournal -log D:/adas_pl/reports/stage2_full_build.log -source D:/adas_pl/scripts/stage2_add_color_gray_mux.tcl
#
#     说明：完整控制台日志由 Vivado 的 -log 开关产生。已实测 -log 会同时记录
#           脚本 puts 输出与 Vivado 自身的 INFO/WARNING/ERROR；纯 Tcl 层的 tee
#           抓不到 Vivado 内部消息，所以不自己实现重定向。不带 -log 时脚本
#           结束会给出提示。
#
#  幂等 : 可反复执行。BD 编辑通过 ensure_* 过程实现（已连对的网络不动，
#         缺失或连错的才重建）；基线备份只创建一次，不会覆盖 Stage 1 的基线。
#
#  拓扑 :
#     frontend/video_out --+--> axis_gray_bypass_0/s_axis  --(旁通)--------+
#                          +--> axis_gray_bypass_0/gp_axis --> ov5640_rgb2gray_0/video_in
#                               ov5640_rgb2gray_0/video_out --> gd_axis ----+
#                               axis_gray_bypass_0/m_axis --> out_stream --> axi_vdma/S_AXIS_S2MM
#     axi_gpio_sel.gpio_io_o[0] --> axis_gray_bypass_0/sel
#          sel = 0 -> 彩色直通 ;  sel = 1 -> 灰度
#
#  说明 : 1) 控制台输出一律 ASCII（cp936 下中文输出会损坏部分字符，已实测）；
#            中文只出现在注释里。
#         2) 脚本只改 BD 与工程源文件，不动 PS 侧配置，不烧板。
#         3) 本脚本执行后 stage1_build_bitstream.tcl 的视频通路断言
#            （frontend -> gray -> out_stream）不再成立，请以本脚本作为
#            后续唯一的重建入口。
#         4) mux 以正式打包 IP 形式引用（xilinx.com:user:axis_gray_bypass:1.0，
#            放在 src/ip/ip_repo/axis_gray_bypass_1_0/）。不能用 module
#            reference：那种方式不会声明 AXIS 接口参数，会让 camera_in/out_stream
#            层次引脚退回默认 1 字节，24 位视频只连出第 0 位，综合把采集前端与
#            灰度通路整体判为死逻辑删掉，产出一个"时序全过但完全不能工作"的
#            比特流。详见 docs/stage2_调试记录.md。
#         5) 脚本末尾有硬门禁 + 自愈：门禁检查生成的 wrapper 里 out_stream 是否
#            为 24 位；若被截位则自动重建该层次引脚、重新生成并复查，仍失败则
#            直接报错退出，绝不产出坏比特流。
# =============================================================================

# ------------------------------ 运行开关 -------------------------------------
set BUILD_BITSTREAM    1   ;# 1 = 改完 BD 后继续生成比特流并导出；0 = 只改 BD 并保存
set JOBS               4   ;# 综合/实现并行任务数
set EXPORT_BD_AUX      0   ;# 1 = 同时刷新 ready_to_test 里的 .tcl/.xdc
set WRITE_REPORTS      1   ;# 1 = 输出时序/资源报告到 reports/
# -----------------------------------------------------------------------------

set script_dir  [file normalize [file dirname [info script]]]
set root_dir    [file normalize [file join $script_dir ..]]
set proj_dir    [file join $root_dir src ip 7_ov5640_rgb2gray vivado ov5640_rgb2gray]
set xpr_file    [file join $proj_dir ov5640_rgb2gray.xpr]
set repo_dir    [file join $root_dir src ip ip_repo]
set rtl_file    [file join $root_dir src rtl axis_gray_bypass.v]
set ready_dir   [file join $proj_dir ready_to_test]
set backup_dir  [file join $root_dir backups 7_ov5640_rgb2gray_baseline_stage2]
set report_dir  [file join $root_dir reports]
set status_file [file join $report_dir stage2_last_run.txt]
set LOGFILE     [file join $report_dir stage2_full_build.log]
set bit_name    ov5640_rgb2gray.bit
set hwh_name    ov5640_rgb2gray.hwh

set BD              base
set GRAY_IP_VLNV    xilinx.com:hls:ov5640_rgb2gray:1.0
set GRAY_CELL       ov5640_rgb2gray_0
set MUX_MODULE      axis_gray_bypass
set MUX_CELL        axis_gray_bypass_0
set GPIO_CELL       axi_gpio_sel
set GPIO_BASEADDR   0x41210000
set CAM_HIER        /video/camera_in
set CAM_AXI_PIN     s_axi_GPIO
set IC_CELL         /video/axi_interconnect_0
set IC_NEW_MI       M05_AXI
set IC_NUM_MI       6

# ------------------------------ 辅助过程 -------------------------------------
proc logi {m} { puts "\[INFO\] $m" }
proc logw {m} { puts "\[WARN\] $m" }
proc logk {m} { puts "\[ OK \] $m" }

# 报告完整控制台日志的位置（由 vivado -log 产生）
proc log_note {} {
    global LOGFILE
    if {[file exists $LOGFILE]} {
        puts "\[INFO\] console log : $LOGFILE ([file size $LOGFILE] bytes)"
    } else {
        puts "\[WARN\] console log not found: $LOGFILE"
        puts "\[WARN\] to capture the full log next time, run:"
        puts "\[WARN\]   vivado -mode batch -nojournal -log $LOGFILE -source <this script>"
    }
}

proc die {m} {
    global status_file
    puts "\[FAIL\] $m"
    catch { close_project -quiet }
    if {[catch { set fh [open $status_file w]
                 puts $fh "FAIL: $m"
                 close $fh }]} {}
    catch { log_note }
    exit 1
}

proc finish {m} {
    global status_file
    puts "\[DONE\] $m"
    if {[catch { set fh [open $status_file w]
                 puts $fh "PASS: $m"
                 close $fh }]} {}
    exit 0
}

# 判断两个接口引脚是否连在同一网络上。
# 用"网络端点集合相同"来判定，而不是比较网络对象名：层次引脚从不同层次
# 看会解析到不同层次的网络对象，直接比名字会误判成"不同网络"。
proc intf_same_net {a b} {
    set na [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins -quiet $a]]
    set nb [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins -quiet $b]]
    if {[llength $na] == 0 || [llength $nb] == 0} { return 0 }
    set pa [lsort [get_bd_intf_pins -quiet -of_objects $na]]
    set pb [lsort [get_bd_intf_pins -quiet -of_objects $nb]]
    return [expr {$pa eq $pb}]
}

# 同上，针对普通引脚
proc net_same {a b} {
    set na [get_bd_nets -quiet -of_objects [get_bd_pins -quiet $a]]
    set nb [get_bd_nets -quiet -of_objects [get_bd_pins -quiet $b]]
    if {[llength $na] == 0 || [llength $nb] == 0} { return 0 }
    set pa [lsort [get_bd_pins -quiet -of_objects $na]]
    set pb [lsort [get_bd_pins -quiet -of_objects $nb]]
    return [expr {$pa eq $pb}]
}

# 确保两个接口引脚连在同一网络上。
# 接口引脚正常只有一个对端，所以"断开重连"是安全的；用它做真正的改线。
proc ensure_intf_conn {a b} {
    set pa [get_bd_intf_pins -quiet $a]
    set pb [get_bd_intf_pins -quiet $b]
    if {[llength $pa] == 0} { error "intf pin not found: $a" }
    if {[llength $pb] == 0} { error "intf pin not found: $b" }
    if {[intf_same_net $a $b]} { return 0 }
    foreach n [get_bd_intf_nets -quiet -of_objects $pa] { delete_bd_objs $n }
    foreach n [get_bd_intf_nets -quiet -of_objects $pb] { delete_bd_objs $n }
    connect_bd_intf_net $pa $pb
    return 1
}

# 普通引脚（时钟/复位/选择位）：绝不删除已有网络。
# clk_100M 这类网络上挂着几十个引脚，删掉任何一张都是灾难（实测拆掉过
# 整张 100MHz 时钟树）。所以只在"某一侧未连接"时扩展/新建网络；
# 两侧都已连且无法确认是同一网络时，直接报错交给人处理。
proc ensure_net {a b} {
    set pa [get_bd_pins -quiet $a]
    set pb [get_bd_pins -quiet $b]
    if {[llength $pa] == 0} { error "pin not found: $a" }
    if {[llength $pb] == 0} { error "pin not found: $b" }
    set na [get_bd_nets -quiet -of_objects $pa]
    set nb [get_bd_nets -quiet -of_objects $pb]
    if {[llength $na] > 0 && [llength $nb] > 0} {
        if {[net_same $a $b]} { return 0 }
        error "refusing to rewire: '$a' and '$b' are on different nets. This script never deletes an existing net (they can be shared clock/reset trees); please fix by hand."
    }
    connect_bd_net $pa $pb
    return 1
}

# 自检：某接口引脚的对端是否匹配期望模式
proc assert_intf_peer {pin expect} {
    set nets [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins $pin]]
    set peers [get_bd_intf_pins -quiet -of_objects $nets]
    if {![string match $expect $peers]} {
        die "topology check failed: $pin peers='$peers' expected match '$expect'"
    }
}

# 门禁：检查生成的 BD wrapper 里 out_stream 是否为 24 位。
# 返回 OK / MISSING / NARROWED_DECL / NARROWED_ASSIGN。
# 截位形式是 assign out_stream_tdata = <某个 24 位源>[0]; —— 只连出第 0 位。
proc check_out_stream {} {
    global proj_dir
    set bv [file join $proj_dir ov5640_rgb2gray.srcs sources_1 bd base synth base.v]
    if {![file exists $bv]} { return "MISSING" }
    set fh [open $bv r]
    set t [read $fh]
    close $fh
    if {![regexp {output\s*\[23:0\]\s*out_stream_tdata\s*;} $t]} { return "NARROWED_DECL" }
    foreach ln [split $t "\n"] {
        if {[regexp {assign\s+out_stream_tdata\s*(\[[^\]]*\])?\s*=\s*(\S+)} $ln -> idx src]} {
            if {[string first "\[" $src] >= 0} { return "NARROWED_ASSIGN" }
        }
    }
    return "OK"
}

# 自愈：删除并重建 camera_in/out_stream 层次引脚，再重新连接内/外两侧。
# 该引脚的 AXIS 参数在 BD 里从未显式保存，位宽靠参数传播推导；驱动源一换
# 就会被盖章成默认 1 字节且再也推不回来（设参数只读、换驱动源无效、中间插
# 真实 IP 锚点也无效），只能重建对象。
proc rebuild_outstream_pin {} {
    set root [current_bd_instance .]
    current_bd_instance /video/camera_in
    foreach n [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins out_stream]] {
        delete_bd_objs $n
    }
    delete_bd_objs [get_bd_intf_pins out_stream]
    create_bd_intf_pin -mode Master -vlnv xilinx.com:interface:axis_rtl:1.0 out_stream
    connect_bd_intf_net [get_bd_intf_pins axis_gray_bypass_0/m_axis] [get_bd_intf_pins out_stream]
    current_bd_instance $root
    set outer [get_bd_intf_pins -quiet /video/camera_in/out_stream]
    set vdma  [get_bd_intf_pins -quiet /video/axi_vdma/S_AXIS_S2MM]
    if {[llength $outer] == 0} { error "recreated out_stream pin not found" }
    if {[llength $vdma]  == 0} { error "axi_vdma/S_AXIS_S2MM not found" }
    if {[llength [get_bd_intf_nets -quiet -of_objects $outer]] == 0} {
        connect_bd_intf_net $outer $vdma
    }
}

puts ""
puts "============================================================================="
puts " Stage 2 : add color/gray mux to 7_ov5640_rgb2gray"
puts " start   : [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts "============================================================================="

file mkdir $report_dir
log_note

# =============================================================================
# Step 0 : 前置检查
# =============================================================================
logi "project root : $root_dir"
if {![file exists $xpr_file]}  { die "project file not found: $xpr_file" }
if {![file isdirectory $repo_dir]} { die "IP repo dir not found: $repo_dir" }
if {![file exists $rtl_file]}  { die "RTL file not found: $rtl_file" }
logk "project / IP repo / RTL file all present"

# =============================================================================
# Step 1 : 基线备份（Stage 2 专属目录，不覆盖 Stage 1 基线）
# =============================================================================
set backup_items [list \
    [list $xpr_file                                                                  "ov5640_rgb2gray.xpr"] \
    [list [file join $proj_dir ov5640_rgb2gray.srcs sources_1 bd base base.bd]       "base.bd"] \
    [list [file join $proj_dir ov5640_rgb2gray.srcs sources_1 bd base hdl base_wrapper.v] "base_wrapper.v"] \
    [list [file join $proj_dir ov5640_rgb2gray.srcs constrs_1 new base.xdc]          "base.xdc"] \
    [list [file join $ready_dir $bit_name]                                           "ready_to_test/$bit_name"] \
    [list [file join $ready_dir $hwh_name]                                           "ready_to_test/$hwh_name"] \
]

if {[file exists $backup_dir]} {
    logi "baseline backup already exists, skip: $backup_dir"
} else {
    file mkdir $backup_dir
    foreach item $backup_items {
        lassign $item src dst
        if {[file exists $src]} {
            set dst_full [file join $backup_dir $dst]
            file mkdir [file dirname $dst_full]
            file copy -force $src $dst_full
        }
    }
    set fh [open [file join $backup_dir MANIFEST.txt] w]
    puts $fh "backup time : [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
    puts $fh "stage       : 2 (add color/gray mux)"
    puts $fh "source proj : $proj_dir"
    close $fh
    logk "baseline backup done: $backup_dir"
}

# =============================================================================
# Step 2 : 打开工程 + 注册 IP 仓库 + 把 mux RTL 加入工程源
# =============================================================================
catch { if {[llength [current_project -quiet]] > 0} { close_project } }
open_project $xpr_file
logk "project opened: [current_project]"

set repo_norm [file normalize $repo_dir]
set repo_list [get_property -quiet ip_repo_paths [current_project]]
if {[lsearch -exact $repo_list $repo_norm] < 0} {
    set repo_list [linsert $repo_list 0 $repo_norm]
    set_property ip_repo_paths $repo_list [current_project]
}
update_ip_catalog
if {[llength [get_ipdefs -quiet $GRAY_IP_VLNV]] == 0} {
    die "IP definition $GRAY_IP_VLNV not found in catalog"
}
logk "HLS IP definition ready: $GRAY_IP_VLNV"

# mux 现在以打包 IP 形式引用，其 HDL 由 ip_repo/axis_gray_bypass_1_0/src/
# 提供。如果同一个 .v 还挂在工程 sources_1 里，会与 IP 内部的模块定义重名
# （[Synth 8-296] module already declared），必须从工程源里移除。
set rtl_norm [file normalize $rtl_file]
if {[lsearch -exact [get_files -quiet] $rtl_norm] >= 0} {
    remove_files -fileset sources_1 $rtl_norm
    logk "RTL removed from project sources (now shipped inside the packaged IP)"
} else {
    logi "RTL not in project sources, nothing to remove"
}
update_compile_order -fileset sources_1

# =============================================================================
# Step 3 : 打开 Block Design
# =============================================================================
set bd_files [get_files -quiet *$BD.bd]
if {[llength $bd_files] == 0} { die "cannot find $BD.bd in project" }
open_bd_design [lindex $bd_files 0]
logi "block design opened: [current_bd_design]"

# =============================================================================
# Step 4 : 在 video/camera_in 内插入 mux 与 GPIO
# =============================================================================
set old_inst [current_bd_instance .]
current_bd_instance $CAM_HIER

if {[llength [get_bd_cells -quiet $GRAY_CELL]] == 0} {
    die "$CAM_HIER/$GRAY_CELL not found -- run Stage 1 first"
}

# ---- 4.1 mux cell：必须是打包 IP，不能是 module reference ----
set MUX_VLNV xilinx.com:user:axis_gray_bypass:1.0
if {[llength [get_ipdefs -quiet $MUX_VLNV]] == 0} {
    die "packaged mux IP not found: $MUX_VLNV (expect $repo_norm/axis_gray_bypass_1_0)"
}
if {[llength [get_bd_cells -quiet $MUX_CELL]] == 0} {
    create_bd_cell -type ip -vlnv $MUX_VLNV $MUX_CELL
    logk "created mux cell as packaged IP: $MUX_CELL ($MUX_VLNV)"
    foreach p {s_axis gp_axis gd_axis m_axis} {
        catch { set_property -dict [list CONFIG.FREQ_HZ {100000000}] \
                    [get_bd_intf_pins $MUX_CELL/$p] }
    }
} else {
    set cur_vlnv [get_property -quiet VLNV [get_bd_cells $MUX_CELL]]
    if {$cur_vlnv ne $MUX_VLNV} {
        die "$MUX_CELL has VLNV '$cur_vlnv', expected '$MUX_VLNV'. A module-reference cell cannot carry AXIS interface parameters and will silently narrow out_stream to 1 byte; delete that cell and re-run."
    }
    logi "mux cell already exists with correct VLNV, skip create"
}

# ---- 4.2 AXI GPIO（1 位全输出，复位值 0 = 彩色）----
if {[llength [get_bd_cells -quiet $GPIO_CELL]] == 0} {
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 $GPIO_CELL
    set_property -dict [list \
        CONFIG.C_GPIO_WIDTH        {1} \
        CONFIG.C_ALL_OUTPUTS       {1} \
        CONFIG.C_IS_DUAL           {0} \
        CONFIG.C_INTERRUPT_PRESENT {0} \
    ] [get_bd_cells $GPIO_CELL]
    logk "created AXI GPIO: $GPIO_CELL (width=1, all outputs, reset=0 -> color)"
} else {
    logi "AXI GPIO already exists, skip create"
}

# ---- 4.3 camera_in 新增一个 AXI 从口给 GPIO ----
if {[llength [get_bd_intf_pins -quiet $CAM_AXI_PIN]] == 0} {
    create_bd_intf_pin -mode Slave -vlnv xilinx.com:interface:aximm_rtl:1.0 $CAM_AXI_PIN
    logk "created hier pin: $CAM_AXI_PIN"
} else {
    logi "hier pin $CAM_AXI_PIN already exists, skip create"
}

# ---- 4.4 视频数据通路 ----
set n 0
incr n [ensure_intf_conn frontend/video_out   $MUX_CELL/s_axis]
incr n [ensure_intf_conn $MUX_CELL/gp_axis    $GRAY_CELL/video_in]
incr n [ensure_intf_conn $GRAY_CELL/video_out $MUX_CELL/gd_axis]
incr n [ensure_intf_conn $MUX_CELL/m_axis     out_stream]
incr n [ensure_intf_conn $CAM_AXI_PIN         $GPIO_CELL/S_AXI]
logk "video/axi nets rebuilt where needed (changed=$n)"

# ---- 4.5 时钟 / 复位 / 选择位 ----
# 引用同一层次内的既有引脚（灰度 IP 的 ap_clk / ap_rst_n），保证两边
# 解析到的是同一层次的网络对象；不要用层次引脚（clk_100M）当参照。
set n 0
incr n [ensure_net $GRAY_CELL/ap_clk   $MUX_CELL/aclk]
incr n [ensure_net $GRAY_CELL/ap_clk   $GPIO_CELL/s_axi_aclk]
incr n [ensure_net $GRAY_CELL/ap_rst_n $GPIO_CELL/s_axi_aresetn]
incr n [ensure_net $GPIO_CELL/gpio_io_o $MUX_CELL/sel]
logk "clock/reset/select nets connected where needed (changed=$n)"

# ---- 4.6 关于 out_stream 的 AXIS 参数 ----
# 层次引脚的接口参数是只读的（set_property 报 BD 41-737），也不能靠改驱动源
# 重新推导：实测换成真实 IP 驱动、中间插 axis_register_slice 做参数锚点，
# 都无法把已盖章的 1 字节改回 3 字节。所以这里不再尝试设参数，
# 改由 Step 8 的门禁 + 自愈（重建该层次引脚）兜底。
logi "note: hierarchy-pin AXIS params are read-only; handled by Step 8 gate/self-heal"

current_bd_instance $old_inst

# =============================================================================
# Step 5 : 把 GPIO 挂到现有 axi_interconnect_0（NUM_MI 5 -> 6）
# =============================================================================
set ic [get_bd_cells -quiet $IC_CELL]
if {[llength $ic] == 0} { die "$IC_CELL not found" }
set num_mi [get_property -quiet CONFIG.NUM_MI $ic]
if {$num_mi < $IC_NUM_MI} {
    set_property -dict [list CONFIG.NUM_MI $IC_NUM_MI] $ic
    logw "$IC_CELL NUM_MI changed: $num_mi -> $IC_NUM_MI"
} else {
    logi "$IC_CELL NUM_MI already $num_mi, skip change"
}

set n 0
incr n [ensure_intf_conn $IC_CELL/$IC_NEW_MI $CAM_HIER/$CAM_AXI_PIN]
logk "new MI $IC_NEW_MI attached to camera_in/$CAM_AXI_PIN (changed=$n)"

# 新 MI 的时钟/复位：切到 /video 层次内部，直接挂到 M00 所在的那两张网上。
# （若在根层次用 /video/clk_100M 作参照，会解析到根层次的时钟网而与
#   M05_ACLK 所在的 video 内部网不是同一对象，进而误判。）
set root_inst [current_bd_instance .]
current_bd_instance /video
set n 0
incr n [ensure_net axi_interconnect_0/M00_ACLK    axi_interconnect_0/M05_ACLK]
incr n [ensure_net axi_interconnect_0/M00_ARESETN axi_interconnect_0/M05_ARESETN]
current_bd_instance $root_inst
logk "new MI $IC_NEW_MI clock/reset tied to M00 nets (changed=$n)"

# =============================================================================
# Step 6 : 给 GPIO 分配地址
# =============================================================================
set gpio_seg [get_bd_addr_segs -quiet $CAM_HIER/$GPIO_CELL/S_AXI/Reg]
if {[llength $gpio_seg] == 0} { die "GPIO address segment not found" }
assign_bd_address -offset $GPIO_BASEADDR -range 0x00010000 \
    -target_address_space [get_bd_addr_spaces ps7_0/Data] $gpio_seg -force
logk "GPIO address assigned: $GPIO_BASEADDR / 64KB"

# =============================================================================
# Step 7 : 自检 + 校验 + 保存 BD
# =============================================================================
assert_intf_peer $CAM_HIER/frontend/video_out        "*$CAM_HIER/$MUX_CELL/s_axis"
assert_intf_peer $CAM_HIER/$MUX_CELL/gp_axis         "*$CAM_HIER/$GRAY_CELL/video_in"
assert_intf_peer $CAM_HIER/$GRAY_CELL/video_out      "*$CAM_HIER/$MUX_CELL/gd_axis"
assert_intf_peer $CAM_HIER/$MUX_CELL/m_axis          "*$CAM_HIER/out_stream"
logk "video path verified: frontend -> {bypass, gray} -> mux -> out_stream"

set mi_now [get_property -quiet CONFIG.NUM_MI [get_bd_cells $IC_CELL]]
if {$mi_now ne "$IC_NUM_MI"} { die "$IC_CELL NUM_MI = $mi_now, expected $IC_NUM_MI" }
logk "$IC_CELL NUM_MI = $mi_now"

# 基地址要从主机地址空间里读（从机侧段不带 OFFSET，这个坑 Stage 1 踩过）
set addr ""
foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces ps7_0/Data]] {
    if {[string match "*$GPIO_CELL*" $s]} {
        set c [get_property -quiet OFFSET $s]
        if {$c ne ""} { set addr $c; break }
    }
}
if {$addr eq ""} { die "mapped address segment for $GPIO_CELL not found" }
if {[expr {$addr}] != [expr {$GPIO_BASEADDR}]} {
    die "$GPIO_CELL base address = $addr, expected $GPIO_BASEADDR"
}
logk "$GPIO_CELL base = [format 0x%08X [expr {$addr}]] (channel1 data @ +0x00)"

catch { regenerate_bd_layout }
validate_bd_design
save_bd_design
close_bd_design [current_bd_design]
logk "BD validated and saved"

catch { if {[llength [current_design -quiet]] > 0} { close_design } }

if {!$BUILD_BITSTREAM} {
    puts ""
    puts " BUILD_BITSTREAM=0 -> BD edited and saved only, bitstream skipped."
    puts "============================================================================="
    log_note
    finish "Stage 2 BD edit done (bitstream skipped by switch)"
}

# =============================================================================
# Step 8 : 生成比特流
# =============================================================================
# 必须用 -force：实测普通 generate_target 会以"已是 up-to-date"为由跳过重新
# 生成，门禁会读到陈旧的 base.v 而给出错误结论（本轮调试中真实踩过）。
# 门禁不过就自愈：重建 out_stream 层次引脚后再复查一次，仍不过则报错退出。
set bd_file [lindex $bd_files 0]
set repaired 0
while {1} {
    logi "generate BD output products (-force) ..."
    generate_target all -force $bd_file
    set verdict [check_out_stream]
    if {$verdict eq "OK"} {
        logk "gate PASS: out_stream is 24-bit in the generated wrapper"
        break
    }
    logw "gate: out_stream width check -> $verdict"
    if {$repaired} {
        die "out_stream is still narrowed after rebuilding its hierarchy pin; refusing to build a non-working bitstream"
    }
    logw "self-heal: rebuilding camera_in/out_stream hierarchy pin"
    open_bd_design $bd_file
    rebuild_outstream_pin
    validate_bd_design
    save_bd_design
    close_bd_design [current_bd_design]
    set repaired 1
}

# BD 改动后综合 run 会变成"过期"状态，Vivado 要求先 reset 才允许启动。
# 这里自适应处理：先直接启动，只有报 needs to be reset 时才 reset 再启动，
# 这样在没改 BD 的情况下仍然能秒过（不白跑一次全量综合）。
logi "launch synth_1 (jobs=$JOBS) ..."
if {[catch { launch_runs synth_1 -jobs $JOBS } emsg]} {
    if {[string match "*needs to be reset*" $emsg]} {
        logw "synth_1 is out of date, reset_run and relaunch"
        reset_run synth_1
        # 综合重跑后实现必然过期，一并复位，避免用到旧的 dcp
        if {[llength [get_runs -quiet impl_1]] > 0} { catch { reset_run impl_1 } }
        launch_runs synth_1 -jobs $JOBS
    } else {
        die "launch synth_1 failed: $emsg"
    }
}
wait_on_run synth_1
if {[get_property -quiet PROGRESS [get_runs synth_1]] ne "100%"} {
    die "synthesis did not complete: [get_property -quiet STATUS [get_runs synth_1]]"
}
logk "synthesis done: [get_property -quiet STATUS [get_runs synth_1]]"

logi "launch impl_1 -to_step write_bitstream (jobs=$JOBS) ..."
if {[catch { launch_runs impl_1 -to_step write_bitstream -jobs $JOBS } emsg]} {
    if {[string match "*needs to be reset*" $emsg]} {
        logw "impl_1 is out of date, reset_run and relaunch"
        reset_run impl_1
        launch_runs impl_1 -to_step write_bitstream -jobs $JOBS
    } else {
        die "launch impl_1 failed: $emsg"
    }
}
wait_on_run impl_1
if {[get_property -quiet PROGRESS [get_runs impl_1]] ne "100%"} {
    die "implementation/bitstream did not complete: [get_property -quiet STATUS [get_runs impl_1]]"
}
logk "implementation and bitstream done: [get_property -quiet STATUS [get_runs impl_1]]"

set wns [get_property -quiet STATS.WNS [get_runs impl_1]]
set whs [get_property -quiet STATS.WHS [get_runs impl_1]]
logi "timing: WNS = $wns ns , WHS = $whs ns"
if {$wns ne "" && $wns < 0} { logw "setup violation, WNS = $wns ns" }
if {$whs ne "" && $whs < 0} { logw "hold violation, WHS = $whs ns" }

# =============================================================================
# Step 8b : 三项可验证指标门禁（必须在导出比特流之前）
# -----------------------------------------------------------------------------
# 只看"构建成功"是不够的：本工程曾产出过一版时序全过、DRC 干净、比特流正常
# 写出，但采集前端与灰度数据通路被整体优化掉的产物。导出前核对：
#   1) DSP48 数量 == 3        （rgb2gray 的 RGB->Y 乘法器）
#   2) ov5640_rgb2gray_0 内重新出现 rgb2gray_480_800 数据通路
#   3) Slice LUT 数 >= 7972   （Stage 1 实测值，45.30%）
# 任一项不满足 -> 直接报错退出，不导出 .bit/.hwh。
# =============================================================================
set LUT_FLOOR 7972
set DSP_EXPECT 3
open_run impl_1
set dsp_cnt [llength [get_cells -hier -quiet -filter {REF_NAME =~ "DSP48*"}]]
set dp_cnt  [llength [get_cells -hier -quiet -filter {NAME =~ "*rgb2gray_480_800*"}]]
set util_txt ""
catch { set util_txt [report_utilization -return_string] }
close_design
set lut_cnt ""
regexp -line {^\|\s+Slice LUTs\s+\|\s+(\d+)\s+\|} $util_txt -> lut_cnt
logi "metric 1/3 : DSP48 count = $dsp_cnt (expect $DSP_EXPECT)"
logi "metric 2/3 : gray datapath cells (NAME =~ *rgb2gray_480_800*) = $dp_cnt"
logi "metric 3/3 : Slice LUTs = '$lut_cnt' (floor $LUT_FLOOR)"
set metric_bad 0
if {$dsp_cnt != $DSP_EXPECT} { logw "metric FAIL: DSP48 = $dsp_cnt, expected $DSP_EXPECT"; set metric_bad 1 }
if {$dp_cnt == 0} { logw "metric FAIL: rgb2gray_480_800 datapath not found in netlist"; set metric_bad 1 }
if {$lut_cnt eq "" || $lut_cnt < $LUT_FLOOR} { logw "metric FAIL: Slice LUTs = '$lut_cnt', expected >= $LUT_FLOOR"; set metric_bad 1 }
if {$metric_bad} {
    die "post-implementation metric gate failed -- refusing to export a non-working bitstream"
}
logk "metric gate PASS: gray datapath present in the netlist"

# =============================================================================
# Step 9 : 导出 .bit / .hwh 到 ready_to_test
# =============================================================================
set impl_dir [file join $proj_dir ov5640_rgb2gray.runs impl_1]
set bl [glob -nocomplain -directory $impl_dir *.bit]
if {[llength $bl] == 0} { die "no .bit found in $impl_dir" }
set bit_src [lindex $bl 0]

set hl [glob -nocomplain [file join $proj_dir ov5640_rgb2gray.srcs sources_1 bd * hw_handoff *.hwh]]
if {[llength $hl] == 0} { die "no hw_handoff/*.hwh found" }
set hwh_src [lindex $hl 0]

file mkdir $ready_dir
set bit_dst [file join $ready_dir $bit_name]
set hwh_dst [file join $ready_dir $hwh_name]
file copy -force $bit_src $bit_dst
file copy -force $hwh_src $hwh_dst
if {[file size $bit_dst] <= 0} { die "exported bitstream is empty" }

set fh [open $hwh_dst r]
set hwh_text [read $fh]
close $fh
if {[string first $MUX_CELL $hwh_text] < 0} {
    die "exported $hwh_name does not contain $MUX_CELL"
}
if {[string first $GPIO_CELL $hwh_text] < 0} {
    die "exported $hwh_name does not contain $GPIO_CELL"
}
if {[string first "41210000" [string tolower $hwh_text]] < 0} {
    logw "0x41210000 not found in $hwh_name, re-check GPIO base on PYNQ side"
}
logk "exported: $bit_dst  ([file size $bit_dst] bytes)"
logk "exported: $hwh_dst  ([file size $hwh_dst] bytes)"

if {$EXPORT_BD_AUX} {
    file copy -force [file join $proj_dir ov5640_rgb2gray.srcs sources_1 bd base hw_handoff base_bd.tcl] \
                    [file join $ready_dir ov5640_rgb2gray.tcl]
    file copy -force [file join $proj_dir ov5640_rgb2gray.srcs constrs_1 new base.xdc] \
                    [file join $ready_dir ov5640_rgb2gray.xdc]
    logk "ready_to_test .tcl / .xdc refreshed"
}

if {$WRITE_REPORTS} {
    if {[catch {
        open_run impl_1
        report_utilization    -file [file join $report_dir stage2_utilization.rpt]
        report_utilization -hierarchical -file [file join $report_dir stage2_util_hier.rpt]
        report_timing_summary -file [file join $report_dir stage2_timing_summary.rpt]
        close_design
        logk "reports written to $report_dir (stage2_utilization/stage2_util_hier/stage2_timing_summary)"
    } emsg]} {
        logw "report generation failed (not affecting deliverables): $emsg"
    }
}

puts ""
puts "============================================================================="
puts " Stage 2 finished"
puts "   bit     : $bit_dst"
puts "   hwh     : $hwh_dst"
puts "   select  : $GPIO_CELL channel1 bit0   (0=color, 1=gray)"
puts "   backup  : $backup_dir"
puts "   end     : [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts "============================================================================="
log_note

finish "Stage 2 done: color/gray mux added, bitstream built and exported"
