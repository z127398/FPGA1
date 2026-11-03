# =============================================================================
#  ADAS-PL / Stage 3 -- 视频处理分级流水线 + 决策闭环集成
# -----------------------------------------------------------------------------
#  工程 : D:/adas_pl/src/ip/7_ov5640_rgb2gray/vivado/ov5640_rgb2gray
#
#  本脚本做四件事：
#    (A) camera_in 内把单个"彩色/灰度"mux 升级成两级可旁路流水线
#          frontend -> stage_gray_0 -> stage_sobel_0 -> out_stream
#          stage_gray_0  的 px/pd 之间接 ov5640_rgb2gray_0
#          stage_sobel_0 的 px/pd 之间接 ov5640_sobel_0
#          axi_gpio_sel 由 1 位扩到 3 位：bit0 = 灰度级，bit1 = Sobel 级
#          （bit2 预留）。每一级都是独立 2:1 旁路，所以 PS 可以在运行期组合出
#          原彩 / 灰度 / 灰度+Sobel 三种视频源，只占一条 VDMA 通路。
#
#    (B) BD 顶层加决策闭环（软感知 / 硬执行）
#          adas_decision_0 : 决策 FSM + 看门狗 + 按键消抖（自研 IP）
#          gpio_dec    @0x41220000  16bit 全输出：PS 写感知结果
#          gpio_status @0x41230000   7bit 全输入：PS 回读 LED/蜂鸣器/看门狗/报警原因
#          gpio_btn    @0x41240000   2bit 全输入：板载按键回读
#          顶层新增端口 leds_tri_o[2:0] / beep_tri_o / btns_tri_i[1:0]，
#          引脚约束在 scripts/adas_io.xdc（本脚本自动加入 constrs_1）。
#
#    (C) 把两处 NUM_MI 扩到位：
#          ps7_0_axi_periph         NUM_MI 3 -> 6（挂三个新 GPIO）
#          video/axi_interconnect_0 NUM_MI 6 -> 7（给 ov5640_sobel_0 一个控制口）
#
#    (D) 门禁 + 构建：BD 拓扑断言 -> validate -> wrapper 位宽门禁 ->
#          综合/实现 -> 实现后指标门禁 -> 导出 .bit/.hwh 到 ready_to_test
#
#  用法 :
#     vivado -mode batch -nojournal -log D:/adas_pl/reports/stage3_build.log \
#            -source D:/adas_pl/scripts/stage3_add_adas_pipeline.tcl
#
#  说明 : 1) 控制台输出一律 ASCII（本机 cp936 下中文 puts 会损坏部分字符，
#            已实测）；中文只出现在注释里。
#         2) 幂等：可反复执行。BD 编辑全部走 ensure_* 过程（已连对的网络不动），
#            新建对象前先判断是否存在；基线备份只创建一次。
#         3) 先按 BUILD_BITSTREAM=0 跑一遍（只改 BD + validate），确认拓扑无误
#            再改 1 跑全量 —— Stage 2 踏坑后定下的流程。
#         4) 绝不删除既有网络：时钟/复位网络上挂着几十个引脚，误删一张就是
#            整树报废（Stage 2 真实踩过）。ensure_net 只在"有一侧未连接"时扩展
#            网络；两侧都已连且不是同一网络时直接报错交给人处理。
#         5) 脚本中途 die 时绝不 save_bd_design，磁盘工程保持原状。
# =============================================================================

# ------------------------------ 运行开关 -------------------------------------
set BUILD_BITSTREAM 1   ;# 1 = 继续生成比特流并导出；0 = 只改 BD + validate
set WITH_SOBEL      0   ;# 1 = 插入 Sobel 级（需 video interconnect 多一个 MI）
set JOBS            4   ;# 综合/实现并行任务数
set EXPORT_BD_AUX   1   ;# 1 = 同时刷新 ready_to_test 里的 .tcl/.xdc
set WRITE_REPORTS   1   ;# 1 = 输出时序/资源报告到 reports/
set LUT_FLOOR       7972  ;# Stage 1/2 实测灰度通路规模；低于它说明通路被优化掉了
set LUT_CEIL        14960 ;# 17600 * 85%，Zynq7010 资源上限的保守闸门
# 时序门禁开关。默认 0 = WNS<0 时拒绝导出比特流。
# Stage 3 第一版全量就是漏了这条门禁：三项数据通路指标全过、比特流正常写出，
# 但 WNS = -6.71ns（ov5640_sobel_0 内部 HLS 生成的 fsqrt 用了 41 级进位链）。
# 只有明确决定"先上板看现象、时序问题另说"时才把它改成 1。
set ALLOW_NEGATIVE_SLACK 0
# -----------------------------------------------------------------------------

set script_dir  [file normalize [file dirname [info script]]]
set root_dir    [file normalize [file join $script_dir ..]]
set proj_dir    [file join $root_dir src ip 7_ov5640_rgb2gray vivado ov5640_rgb2gray]
set xpr_file    [file join $proj_dir ov5640_rgb2gray.xpr]
set repo_dir    [file join $root_dir src ip ip_repo]
set xdc_file    [file join $script_dir adas_io.xdc]
set ready_dir   [file join $proj_dir ready_to_test]
set backup_dir  [file join $root_dir backups 7_ov5640_rgb2gray_baseline_stage3]
set report_dir  [file join $root_dir reports]
set status_file [file join $report_dir stage3_last_run.txt]
set topo_file   [file join $report_dir stage3_bd_topology.txt]
set LOGFILE     [file join $report_dir stage3_build.log]
set bit_name    ov5640_rgb2gray.bit
set hwh_name    ov5640_rgb2gray.hwh

set BD             base
set STAGE_VLNV     xilinx.com:user:axis_stage_bypass:1.0
set GRAY_VLNV      xilinx.com:hls:ov5640_rgb2gray:1.0
set SOBEL_VLNV     xilinx.com:hls:ov5640_sobel:1.0
set DEC_VLNV       xilinx.com:user:adas_decision:1.0
set GRAY_CELL      ov5640_rgb2gray_0
set SOBEL_CELL     ov5640_sobel_0
set OLD_MUX_CELL   axis_gray_bypass_0
set STAGE_G_CELL   stage_gray_0
set STAGE_S_CELL   stage_sobel_0
set CAM_HIER       /video/camera_in
set CAM_AXI_SOBEL  s_axi_sobel
set IC_CELL        /video/axi_interconnect_0
set IC_NUM_MI      7
set IC_SOBEL_MI    M06_AXI
set IC_SOBEL_NUM   M06
set PERIPH_CELL    /ps7_0_axi_periph
set PERIPH_NUM_MI  6
set FSM_CELL       adas_decision_0
set DEC_CELL       gpio_dec
set STA_CELL       gpio_status
set BTN_CELL       gpio_btn
set DEC_BASE       0x41220000
set STA_BASE       0x41230000
set BTN_BASE       0x41240000
set SEL_BASE       0x41210000
set SOBEL_BASE     0x40010000
set DEC_WIDTH      16
set STA_WIDTH      7
set BTN_WIDTH      2

# ------------------------------ 辅助过程 -------------------------------------
proc logi {m} { puts "\[INFO\] $m" }
proc logw {m} { puts "\[WARN\] $m" }
proc logk {m} { puts "\[ OK \] $m" }

# 读文本文件：显式 UTF-8 + binary translation，别让 Windows 的 \n <-> \r\n
# 自动转换在比较 wrapper 文本时捣乱
proc read_all {path} {
    set fh [open $path r]
    fconfigure $fh -encoding utf-8 -translation binary
    set t [read $fh]
    close $fh
    return $t
}

# 引脚/端口统一解析。顺序很关键，必须**先查 ports 再查 pins**：
# 实测 get_bd_pins leds_tri_o 与 get_bd_ports leds_tri_o 返回的是同名但不同类
# 的对象，只有 port 对象能被 get_bd_nets -of_objects 查到网络；拿 pin 对象去查
# 会返回空，于是幂等复跑时误判"端口未连接"，connect_bd_net -net 直接报
# [BD 41-395] all ports/pins are already connected。见 probe_bus_port.tcl。
proc pin_of {name} {
    set p [get_bd_ports -quiet $name]
    if {[llength $p] > 0} { return $p }
    return [get_bd_pins -quiet $name]
}

proc log_note {} {
    global LOGFILE
    if {[file exists $LOGFILE]} {
        puts "\[INFO\] console log : $LOGFILE ([file size $LOGFILE] bytes)"
    } else {
        puts "\[WARN\] console log not found: $LOGFILE"
        puts "\[WARN\] to capture it: vivado -mode batch -nojournal -log $LOGFILE -source <this script>"
    }
}

proc die {m} {
    global status_file
    puts "\[FAIL\] $m"
    catch { close_project -quiet }
    catch { set fh [open $status_file w]
            puts $fh "FAIL: $m"
            close $fh }
    catch { log_note }
    puts "\[FAIL\] BD changes are NOT saved when this script dies; the on-disk project stays unchanged."
    exit 1
}

proc finish {m} {
    global status_file
    puts "\[DONE\] $m"
    catch { set fh [open $status_file w]
            puts $fh "PASS: $m"
            close $fh }
    exit 0
}

# 两个接口引脚是否在同一网络：用"端点集合相同"判定（层次引脚从不同层次解析
# 出的网络对象不同，直接比名字会误判）。
proc intf_same_net {a b} {
    set na [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins -quiet $a]]
    set nb [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins -quiet $b]]
    if {[llength $na] == 0 || [llength $nb] == 0} { return 0 }
    set pa [lsort [get_bd_intf_pins -quiet -of_objects $na]]
    set pb [lsort [get_bd_intf_pins -quiet -of_objects $nb]]
    return [expr {$pa eq $pb}]
}

proc net_same {a b} {
    set na [get_bd_nets -quiet -of_objects [pin_of $a]]
    set nb [get_bd_nets -quiet -of_objects [pin_of $b]]
    if {[llength $na] == 0 || [llength $nb] == 0} { return 0 }
    set pa [lsort [get_bd_pins -quiet -of_objects $na]]
    set pb [lsort [get_bd_pins -quiet -of_objects $nb]]
    return [expr {$pa eq $pb}]
}

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

# 普通引脚：绝不删除已有网络
# 关键：把引脚挂到"已存在的网络"上必须用 connect_bd_net -net <net> <pin>，
# 不能用 connect_bd_net <pinA> <pinB>。后者在 ps7_0_axi_periph 这种 appcore
# 型层次上会被拒绝（[BD 41-738] ... is part of the appcore ... cannot be
# modified directly），实测确认；-net 形式则正常工作。
proc ensure_net {a b} {
    set pa [pin_of $a]
    set pb [pin_of $b]
    if {[llength $pa] == 0} { error "pin not found: $a" }
    if {[llength $pb] == 0} { error "pin not found: $b" }
    set na [get_bd_nets -quiet -of_objects $pa]
    set nb [get_bd_nets -quiet -of_objects $pb]
    if {[llength $na] > 0 && [llength $nb] > 0} {
        if {[net_same $a $b]} { return 0 }
        error "refusing to rewire: '$a' and '$b' are on different nets; this script never deletes an existing net (clock/reset trees are shared)."
    }
    if {[llength $na] > 0} {
        connect_bd_net -net [lindex $na 0] $pb
    } elseif {[llength $nb] > 0} {
        connect_bd_net -net [lindex $nb 0] $pa
    } else {
        connect_bd_net $pa $pb
    }
    return 1
}

# 软连接：给 appcore 型层次（ps7_0_axi_periph）新增的 MI 用。
# 这类层次内部已经把 MI 的复位耦合器接到 cell 的 ARESETN 上了，外部 ARESETN
# 引脚往往自带一张内部网络；此时"两侧都已连但不是同一张网"是正常状态，
# 不能按错误处理，只提示一句即可。
proc ensure_net_soft {a b} {
    set pa [pin_of $a]
    set pb [pin_of $b]
    if {[llength $pa] == 0} { error "pin not found: $a" }
    if {[llength $pb] == 0} { error "pin not found: $b" }
    set na [get_bd_nets -quiet -of_objects $pa]
    set nb [get_bd_nets -quiet -of_objects $pb]
    if {[llength $na] > 0 && [llength $nb] > 0} {
        if {[net_same $a $b]} { return 0 }
        puts "\[INFO\] $a and $b are on different nets (appcore-internal); left untouched"
        return 0
    }
    if {[llength $na] > 0} {
        connect_bd_net -net [lindex $na 0] $pb
    } elseif {[llength $nb] > 0} {
        connect_bd_net -net [lindex $nb 0] $pa
    } else {
        connect_bd_net $pa $pb
    }
    return 1
}

# 注意：get_bd_intf_pins -of_objects <整张网> 会同时返回两端的引脚，而且顺序
# 不保证目标在后。所以必须逐元素匹配，不能用 string match 拿整串去比
# （Stage 3 第一次就因为这个假报错，把 m_axis <-> out_stream 判成拓扑错误）。
proc assert_intf_peer {pin expect} {
    set nets  [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins $pin]]
    set peers [get_bd_intf_pins -quiet -of_objects $nets]
    set hit 0
    foreach p $peers { if {[string match $expect $p]} { set hit 1; break } }
    if {!$hit} {
        die "topology check failed: $pin peers='$peers' expected match '$expect'"
    }
}

# 断言某引脚所在网络里存在匹配 pattern 的对端（确认真接上了时钟/复位树，
# 而不是两个孤立引脚互连出一张假网）
proc assert_net_peer {pin expect} {
    set nets [get_bd_nets -quiet -of_objects [get_bd_pins -quiet $pin]]
    if {[llength $nets] == 0} { die "net check failed: $pin is unconnected" }
    set peers [get_bd_pins -quiet -of_objects $nets]
    set hit 0
    foreach p $peers { if {[string match $expect $p]} { set hit 1; break } }
    if {!$hit} {
        die "net check failed: $pin peers='$peers' expected match '$expect'"
    }
}

# 断言 BD 引脚是 24 位总线。参数传播一坏就会退化成 1 位（Stage 2 的血泪），
# 这里在 BD 阶段就拦住，不等综合后的指标门禁。
proc assert_width24 {pin} {
    set p [get_bd_pins -quiet $pin]
    if {[llength $p] == 0} { die "pin not found: $pin" }
    set l [get_property -quiet LEFT $p]
    set r [get_property -quiet RIGHT $p]
    if {$l ne "23" || $r ne "0"} {
        die "bus width check failed: $pin is \[$l:$r\], expected \[23:0\]"
    }
}

proc cell_exists {name} { return [expr {[llength [get_bd_cells -quiet $name]] > 0}] }
proc pin_exists  {name} { return [expr {[llength [get_bd_pins -quiet $name]] > 0}] }

# 门禁：检查生成的 BD wrapper 里 out_stream 是否为 24 位。
# 返回 OK / MISSING / NARROWED_DECL / NARROWED_ASSIGN
# 截位形式是 assign out_stream_tdata = <某个 24 位源>[0]; —— 只连出第 0 位。
proc check_out_stream {} {
    global proj_dir
    set bv [file join $proj_dir ov5640_rgb2gray.srcs sources_1 bd base synth base.v]
    if {![file exists $bv]} { return "MISSING" }
    set t [read_all $bv]
    if {![regexp {output\s*\[23:0\]\s*out_stream_tdata\s*;} $t]} { return "NARROWED_DECL" }
    foreach ln [split $t "\n"] {
        if {[regexp {assign\s+out_stream_tdata\s*(\[[^\]]*\])?\s*=\s*(\S+)} $ln -> idx src]} {
            if {[string first "\[" $src] >= 0} { return "NARROWED_ASSIGN" }
        }
    }
    return "OK"
}

# 自愈：删除并重建 camera_in/out_stream 层次引脚，再重新连内外两侧。
# 该引脚的 AXIS 参数在 BD 里从未显式保存，位宽靠"驱动源盖章"推导：驱动源一换
# （Stage 3 从 axis_gray_bypass_0 换成 stage_sobel_0）就可能退回默认 1 字节，
# 且再也推不回来（参数只读、换驱动源无效、插参数锚点无效），只能重建对象。
proc rebuild_outstream_pin {} {
    global STAGE_G_CELL STAGE_S_CELL WITH_SOBEL
    set drv [expr {$WITH_SOBEL ? $STAGE_S_CELL : $STAGE_G_CELL}]
    set root [current_bd_instance .]
    current_bd_instance /video/camera_in
    foreach n [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins out_stream]] {
        delete_bd_objs $n
    }
    delete_bd_objs [get_bd_intf_pins out_stream]
    create_bd_intf_pin -mode Master -vlnv xilinx.com:interface:axis_rtl:1.0 out_stream
    connect_bd_intf_net [get_bd_intf_pins $drv/m_axis] [get_bd_intf_pins out_stream]
    current_bd_instance $root
    set outer [get_bd_intf_pins -quiet /video/camera_in/out_stream]
    set vdma  [get_bd_intf_pins -quiet /video/axi_vdma/S_AXIS_S2MM]
    if {[llength $outer] == 0} { error "recreated out_stream pin not found" }
    if {[llength $vdma]  == 0} { error "axi_vdma/S_AXIS_S2MM not found" }
    if {[llength [get_bd_intf_nets -quiet -of_objects $outer]] == 0} {
        connect_bd_intf_net $outer $vdma
    }
}

# 新建一个 xlslice：从 win 位总线上取 [hi:lo]
proc make_slice {cell win hi lo} {
    if {[cell_exists $cell]} { logi "slice $cell already exists, skip create"; return }
    create_bd_cell -type ip -vlnv xilinx.com:ip:xlslice:1.0 $cell
    set w [expr {$hi - $lo + 1}]
    set_property -dict [list CONFIG.DIN_WIDTH $win CONFIG.DIN_FROM $hi \
                             CONFIG.DIN_TO $lo CONFIG.DOUT_WIDTH $w] [get_bd_cells $cell]
}

proc make_gpio {cell width mode} {
    if {[cell_exists $cell]} { logi "gpio $cell already exists, skip create"; return }
    create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 $cell
    set cfg [list CONFIG.C_GPIO_WIDTH $width CONFIG.C_IS_DUAL {0} \
                  CONFIG.C_INTERRUPT_PRESENT {0}]
    if {$mode eq "out"} {
        lappend cfg CONFIG.C_ALL_OUTPUTS {1}
    } else {
        lappend cfg CONFIG.C_ALL_INPUTS {1}
    }
    set_property -dict $cfg [get_bd_cells $cell]
}

puts ""
puts "============================================================================="
puts " Stage 3 : ADAS pipeline (gray + sobel stages) + decision FSM + board IO"
puts " build_bitstream = $BUILD_BITSTREAM , with_sobel = $WITH_SOBEL"
puts " start : [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts "============================================================================="

file mkdir $report_dir
log_note

# =============================================================================
# Step 0 : 前置检查
# =============================================================================
logi "project root : $root_dir"
if {![file exists $xpr_file]}   { die "project not found: $xpr_file" }
if {![file isdirectory $repo_dir]} { die "ip_repo not found: $repo_dir" }
if {![file exists $xdc_file]}   { die "constraint file not found: $xdc_file" }
logk "project / ip_repo / adas_io.xdc all present"

# =============================================================================
# Step 1 : 基线备份（Stage 3 专属目录）
# =============================================================================
set backup_items [list \
    [list $xpr_file                                                                    "ov5640_rgb2gray.xpr"] \
    [list [file join $proj_dir ov5640_rgb2gray.srcs sources_1 bd base base.bd]          "base.bd"] \
    [list [file join $proj_dir ov5640_rgb2gray.srcs sources_1 bd base hdl base_wrapper.v] "base_wrapper.v"] \
    [list [file join $proj_dir ov5640_rgb2gray.srcs constrs_1 new base.xdc]             "base.xdc"] \
    [list [file join $ready_dir $bit_name]                                              "ready_to_test/$bit_name"] \
    [list [file join $ready_dir $hwh_name]                                              "ready_to_test/$hwh_name"] \
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
    puts $fh "stage       : 3 (ADAS pipeline + decision FSM)"
    puts $fh "source proj : $proj_dir"
    close $fh
    logk "baseline backup done: $backup_dir"
}

# =============================================================================
# Step 2 : 打开工程 + 注册 IP 仓库 + IP 定义门禁
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

# 门禁：四个 IP 必须都在 catalog 里。打包脚本的 XML 注入一坏，Vivado 只会打
# CRITICAL WARNING [IP_Flow 19-1977] 然后静默忽略该 IP，直到 create_bd_cell
# 才炸；这里提前拦住并给出明确原因。
foreach {vlnv what} [list $STAGE_VLNV "axis_stage_bypass" \
                          $DEC_VLNV   "adas_decision" \
                          $GRAY_VLNV  "ov5640_rgb2gray" \
                          $SOBEL_VLNV "ov5640_sobel"] {
    if {[llength [get_ipdefs -quiet $vlnv]] == 0} {
        die "IP definition not found: $vlnv ($what). If it is an in-house IP, re-run scripts/pkg_rtl_as_ip.tcl and check its XML gates."
    }
    logk "IP definition ready: $vlnv ($what)"
}

# =============================================================================
# Step 3 : 打开 Block Design
# =============================================================================
set bd_files [get_files -quiet *$BD.bd]
if {[llength $bd_files] == 0} { die "cannot find $BD.bd in project" }
open_bd_design [lindex $bd_files 0]
logi "block design opened: [current_bd_design]"
set root_inst [current_bd_instance .]

# =============================================================================
# Step 4 : camera_in -- 单 mux 升级为两级可旁路流水线
# =============================================================================
current_bd_instance $CAM_HIER

if {![cell_exists $GRAY_CELL]} { die "$CAM_HIER/$GRAY_CELL not found -- run Stage 1 first" }

# ---- 4.0 删掉 Stage 2 的单级 mux（它的位置由 stage_gray_0 取代）----
if {[cell_exists $OLD_MUX_CELL]} {
    set old_vlnv [get_property -quiet VLNV [get_bd_cells $OLD_MUX_CELL]]
    delete_bd_objs [get_bd_cells $OLD_MUX_CELL]
    logw "removed Stage-2 mux cell: $OLD_MUX_CELL ($old_vlnv) and its nets"
} else {
    logi "Stage-2 mux cell already absent, skip delete"
}

# ---- 4.1 两级旁路 mux（必须是打包 IP，不能是 module reference）----
# WITH_SOBEL=0 时不但不建 Sobel 级，还要把上一轮可能留下的整级摘干净：
# 只"不连接"是不够的，悬空的 stage_sobel_0/s_axis 与 ov5640_sobel_0/INPUT_STREAM
# 会让 validate_bd_design 直接报错。
if {!$WITH_SOBEL} {
    foreach c [list $SOBEL_CELL $STAGE_S_CELL sel_slice_sobel] {
        if {[cell_exists $c]} {
            delete_bd_objs [get_bd_cells $c]
            logw "WITH_SOBEL=0 : removed leftover cell $c"
        }
    }
    if {[llength [get_bd_intf_pins -quiet $CAM_AXI_SOBEL]] > 0} {
        foreach nt [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins $CAM_AXI_SOBEL]] {
            delete_bd_objs $nt
        }
        delete_bd_objs [get_bd_intf_pins $CAM_AXI_SOBEL]
        logw "WITH_SOBEL=0 : removed hier pin $CAM_AXI_SOBEL"
    }
} else {
    # WITH_SOBEL=1 时才需要 Sobel 的 AXI 从口
    if {[llength [get_bd_intf_pins -quiet $CAM_AXI_SOBEL]] == 0} {
        create_bd_intf_pin -mode Slave -vlnv xilinx.com:interface:aximm_rtl:1.0 $CAM_AXI_SOBEL
        logk "created hier pin: $CAM_AXI_SOBEL (sobel control)"
    } else {
        logi "hier pin $CAM_AXI_SOBEL already exists"
    }
}

set stage_cells [list $STAGE_G_CELL]
if {$WITH_SOBEL} { lappend stage_cells $STAGE_S_CELL }
foreach cell $stage_cells {
    if {![cell_exists $cell]} {
        create_bd_cell -type ip -vlnv $STAGE_VLNV $cell
        logk "created stage mux: $cell ($STAGE_VLNV)"
    } else {
        set v [get_property -quiet VLNV [get_bd_cells $cell]]
        if {$v ne $STAGE_VLNV} {
            die "$cell has VLNV '$v', expected '$STAGE_VLNV'. A module-reference cell cannot carry AXIS interface parameters and will silently narrow out_stream to 1 byte."
        }
        logi "stage mux $cell already exists with correct VLNV"
    }
    foreach p {s_axis px_axis pd_axis m_axis} {
        catch { set_property -dict [list CONFIG.FREQ_HZ {100000000}] [get_bd_intf_pins $cell/$p] }
    }
}

# ---- 4.2 Sobel IP ----
if {$WITH_SOBEL} {
    if {![cell_exists $SOBEL_CELL]} {
        create_bd_cell -type ip -vlnv $SOBEL_VLNV $SOBEL_CELL
        logk "created HLS IP: $SOBEL_CELL ($SOBEL_VLNV)"
    } else {
        logi "sobel cell already exists, skip create"
    }
}

# ---- 4.3 axi_gpio_sel 由 1 位扩到 3 位 ----
if {![cell_exists axi_gpio_sel]} { die "$CAM_HIER/axi_gpio_sel not found" }
set cur_w [get_property -quiet CONFIG.C_GPIO_WIDTH [get_bd_cells axi_gpio_sel]]
if {[expr {$cur_w + 0}] < 3} {
    set_property -dict [list CONFIG.C_GPIO_WIDTH {3}] [get_bd_cells axi_gpio_sel]
    logw "axi_gpio_sel width $cur_w -> 3 (bit0 gray, bit1 sobel, bit2 spare)"
} else {
    logi "axi_gpio_sel width already $cur_w, skip widen"
}

# ---- 4.4 选择位切片 ----
make_slice sel_slice_gray  3 0 0
make_slice sel_slice_sobel 3 1 1

# ---- 4.5 视频数据通路 ----
set n 0
incr n [ensure_intf_conn frontend/video_out          $STAGE_G_CELL/s_axis]
incr n [ensure_intf_conn $STAGE_G_CELL/px_axis       $GRAY_CELL/video_in]
incr n [ensure_intf_conn $GRAY_CELL/video_out        $STAGE_G_CELL/pd_axis]
if {$WITH_SOBEL} {
    incr n [ensure_intf_conn $STAGE_G_CELL/m_axis        $STAGE_S_CELL/s_axis]
    incr n [ensure_intf_conn $STAGE_S_CELL/px_axis       $SOBEL_CELL/INPUT_STREAM]
    incr n [ensure_intf_conn $SOBEL_CELL/OUTPUT_STREAM   $STAGE_S_CELL/pd_axis]
    incr n [ensure_intf_conn $STAGE_S_CELL/m_axis        out_stream]
} else {
    incr n [ensure_intf_conn $STAGE_G_CELL/m_axis        out_stream]
}
logk "video data path rebuilt where needed (changed=$n)"

# ---- 4.6 时钟 / 复位 / 选择位 ----
# 以同层次内已连好的灰度 IP 引脚当参照（层次引脚从不同层次解析出的网络对象
# 不同，不能用 clk_100M 当参照）。
set n 0
incr n [ensure_net $GRAY_CELL/ap_clk   $STAGE_G_CELL/aclk]
# 注意：xlslice / xlconcat 是纯组合 IP，没有时钟引脚，不要试图给它们连 aclk
if {$WITH_SOBEL} {
    incr n [ensure_net $GRAY_CELL/ap_clk   $STAGE_S_CELL/aclk]
    incr n [ensure_net $GRAY_CELL/ap_clk   $SOBEL_CELL/ap_clk]
    incr n [ensure_net $GRAY_CELL/ap_rst_n $SOBEL_CELL/ap_rst_n]
}
incr n [ensure_net axi_gpio_sel/gpio_io_o sel_slice_gray/Din]
incr n [ensure_net axi_gpio_sel/gpio_io_o sel_slice_sobel/Din]
incr n [ensure_net sel_slice_gray/Dout   $STAGE_G_CELL/sel]
if {$WITH_SOBEL} {
    incr n [ensure_net sel_slice_sobel/Dout $STAGE_S_CELL/sel]
}
logk "clock/reset/select nets connected where needed (changed=$n)"

# ---- 4.7 Sobel 的 AXI 从口接线（层次引脚已在 4.1 建好）----
if {$WITH_SOBEL} {
    ensure_intf_conn $CAM_AXI_SOBEL $SOBEL_CELL/s_axi_control
    logk "sobel control port wired to $CAM_HIER/$SOBEL_CELL/s_axi_control"
}

current_bd_instance $root_inst

# =============================================================================
# Step 5 : BD 顶层 -- 决策 FSM + 三个 AXI GPIO + 板级端口
# =============================================================================

# ---- 5.1 决策 FSM ----
if {![cell_exists $FSM_CELL]} {
    create_bd_cell -type ip -vlnv $DEC_VLNV $FSM_CELL
    logk "created decision FSM: $FSM_CELL ($DEC_VLNV)"
} else {
    logi "decision FSM already exists, skip create"
}

# ---- 5.2 三个 AXI GPIO ----
make_gpio $DEC_CELL $DEC_WIDTH out
make_gpio $STA_CELL $STA_WIDTH in
make_gpio $BTN_CELL $BTN_WIDTH in

# ---- 5.3 PS -> FSM 的字段切片（16 位控制字拆成 7 个字段）----
#   [1:0] tl_state  [3:2] lane_left  [5:4] lane_right  [6] obstacle
#   [7] force_ps    [9:8] turn_ps   [10] heartbeat     [15:11] 未用
make_slice dec_slice_tl    16 1  0
make_slice dec_slice_ll    16 3  2
make_slice dec_slice_lr    16 5  4
make_slice dec_slice_obs   16 6  6
make_slice dec_slice_force 16 7  7
make_slice dec_slice_turn  16 9  8
make_slice dec_slice_hb    16 10 10

# ---- 5.4 FSM -> PS 的状态拼接（led3 + beep1 + wd1 + reason2 = 7 位）----
if {![cell_exists status_concat]} {
    create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 status_concat
    set_property -dict [list CONFIG.NUM_PORTS {4} CONFIG.IN0_WIDTH {3} \
                             CONFIG.IN1_WIDTH {1} CONFIG.IN2_WIDTH {1} \
                             CONFIG.IN3_WIDTH {2}] [get_bd_cells status_concat]
    logk "created status_concat (led[2:0]+beep+wd_timeout+alarm_reason[1:0] = 7 bits)"
} else {
    logi "status_concat already exists, skip create"
}

# ---- 5.5 板级端口 ----
if {[llength [get_bd_ports -quiet leds_tri_o]] == 0} {
    create_bd_port -dir O -from 2 -to 0 leds_tri_o
    logk "created port leds_tri_o[2:0]"
} else { logi "port leds_tri_o already exists" }
if {[llength [get_bd_ports -quiet beep_tri_o]] == 0} {
    create_bd_port -dir O beep_tri_o
    logk "created port beep_tri_o"
} else { logi "port beep_tri_o already exists" }
if {[llength [get_bd_ports -quiet btns_tri_i]] == 0} {
    create_bd_port -dir I -from 1 -to 0 btns_tri_i
    logk "created port btns_tri_i[1:0]"
} else { logi "port btns_tri_i already exists" }

# ---- 5.6 控制字分发 ----
set n 0
incr n [ensure_net $DEC_CELL/gpio_io_o dec_slice_tl/Din]
foreach s {ll lr obs force turn hb} {
    incr n [ensure_net $DEC_CELL/gpio_io_o dec_slice_$s/Din]
}
logk "control word fanned out to 7 slices (changed=$n)"

set n 0
incr n [ensure_net dec_slice_tl/Dout    $FSM_CELL/tl_state]
incr n [ensure_net dec_slice_ll/Dout    $FSM_CELL/lane_left]
incr n [ensure_net dec_slice_lr/Dout    $FSM_CELL/lane_right]
incr n [ensure_net dec_slice_obs/Dout   $FSM_CELL/obstacle]
incr n [ensure_net dec_slice_force/Dout $FSM_CELL/force_ps]
incr n [ensure_net dec_slice_turn/Dout  $FSM_CELL/turn_ps]
incr n [ensure_net dec_slice_hb/Dout    $FSM_CELL/heartbeat]
logk "FSM inputs connected from slices (changed=$n)"

# ---- 5.7 FSM 输出 -> 端口 + 状态回读 ----
set n 0
incr n [ensure_net $FSM_CELL/led  leds_tri_o]
incr n [ensure_net $FSM_CELL/beep beep_tri_o]
incr n [ensure_net btns_tri_i    $FSM_CELL/btn]
logk "board IO ports connected (changed=$n)"

set n 0
incr n [ensure_net $FSM_CELL/led          status_concat/In0]
incr n [ensure_net $FSM_CELL/beep         status_concat/In1]
incr n [ensure_net $FSM_CELL/wd_timeout   status_concat/In2]
incr n [ensure_net $FSM_CELL/alarm_reason status_concat/In3]
incr n [ensure_net status_concat/Dout     $STA_CELL/gpio_io_i]
incr n [ensure_net btns_tri_i             $BTN_CELL/gpio_io_i]
logk "status readback path connected (changed=$n)"

# ---- 5.8 时钟 / 复位 ----
# 参照点选根层次的普通 IP（axi_intc_0）：它的 s_axi_aclk 在 ps7_0_FCLK_CLK0 上，
# s_axi_aresetn 在 rst_ps7_0_fclk0/peripheral_aresetn 上。不要拿
# ps7_0_axi_periph/M00_ARESETN 当参照——那是 appcore 内部网络，连不出去。
set n 0
incr n [ensure_net $FSM_CELL/aclk          axi_intc_0/s_axi_aclk]
incr n [ensure_net $FSM_CELL/aresetn       axi_intc_0/s_axi_aresetn]
foreach g [list $DEC_CELL $STA_CELL $BTN_CELL] {
    incr n [ensure_net $g/s_axi_aclk    axi_intc_0/s_axi_aclk]
    incr n [ensure_net $g/s_axi_aresetn axi_intc_0/s_axi_aresetn]
}
logk "clock/reset tied to the existing 100MHz peripheral tree (changed=$n)"

# ---- 5.9 顺手清掉 axi_intc_0 的既有告警 ----
# 告警原文（只有 validate_bd_design -force 才会跑 IP 级深检查，Stage 2 没看见）：
#   [xilinx.com:ip:axi_intc:4.1-13] /axi_intc_0: Interrupt output connection
#   Bus is selected, but the interrupt bus interface is not connected to a
#   matching interface. Please consider selecting Single instead.
# 本设计的中断汇总是 xlconcat -> ps7_0/IRQ_F2P 的 1 位链，不需要 Bus 模式。
if {[cell_exists axi_intc_0]} {
    set irq_conn [get_property -quiet CONFIG.C_IRQ_CONNECTION [get_bd_cells axi_intc_0]]
    logi "axi_intc_0 CONFIG.C_IRQ_CONNECTION = '$irq_conn' (1=Bus, 0=Single)"
    if {$irq_conn ne "" && $irq_conn ne "0"} {
        if {[catch { set_property -dict [list CONFIG.C_IRQ_CONNECTION {0}] \
                        [get_bd_cells axi_intc_0] } e]} {
            logw "could not switch axi_intc_0 to Single: $e"
        } else {
            logk "axi_intc_0 interrupt output switched to Single"
        }
    }
    set irqnet [get_bd_nets -quiet -of_objects [pin_of axi_intc_0/irq]]
    if {[llength $irqnet] == 0} {
        logw "axi_intc_0/irq is UNCONNECTED -- the interrupt controller output goes nowhere"
    } else {
        logk "axi_intc_0/irq peers: [get_bd_pins -quiet -of_objects [lindex $irqnet 0]]"
    }
}

# =============================================================================
# Step 6 : ps7_0_axi_periph NUM_MI 3 -> 6
# =============================================================================
set periph [get_bd_cells -quiet $PERIPH_CELL]
if {[llength $periph] == 0} { die "$PERIPH_CELL not found" }
set cur_mi [get_property -quiet CONFIG.NUM_MI $periph]
if {[expr {$cur_mi + 0}] < $PERIPH_NUM_MI} {
    set_property -dict [list CONFIG.NUM_MI $PERIPH_NUM_MI] $periph
    logw "$PERIPH_CELL NUM_MI $cur_mi -> $PERIPH_NUM_MI"
} else {
    logi "$PERIPH_CELL NUM_MI already $cur_mi"
}

set n 0
incr n [ensure_intf_conn $PERIPH_CELL/M03_AXI $DEC_CELL/S_AXI]
incr n [ensure_intf_conn $PERIPH_CELL/M04_AXI $STA_CELL/S_AXI]
incr n [ensure_intf_conn $PERIPH_CELL/M05_AXI $BTN_CELL/S_AXI]
logk "three new AXI slaves attached to $PERIPH_CELL (changed=$n)"

# 新 MI 的时钟/复位：用同一个 interconnect 内部的 M00 当参照，保证解析到同一张网
set n 0
foreach m {M03 M04 M05} {
    incr n [ensure_net_soft $PERIPH_CELL/${m}_ACLK    $PERIPH_CELL/M00_ACLK]
    incr n [ensure_net_soft $PERIPH_CELL/${m}_ARESETN $PERIPH_CELL/M00_ARESETN]
}
logk "new MI clock/reset tied to M00 nets (changed=$n)"

# 硬断言：三个新 MI 的时钟必须真的落在 100MHz 那颗时钟树上
foreach m {M03 M04 M05} {
    assert_net_peer $PERIPH_CELL/${m}_ACLK "*ps7_0/FCLK_CLK0*"
}
logk "new MI ACLK verified on the ps7_0_FCLK_CLK0 tree"

# =============================================================================
# Step 7 : video/axi_interconnect_0 NUM_MI 6 -> 7（Sobel 控制口）
# =============================================================================
if {$WITH_SOBEL} {
    current_bd_instance /video
    set vic [get_bd_cells -quiet axi_interconnect_0]
    if {[llength $vic] == 0} { die "/video/axi_interconnect_0 not found" }
    set cur_mi [get_property -quiet CONFIG.NUM_MI $vic]
    if {[expr {$cur_mi + 0}] < $IC_NUM_MI} {
        set_property -dict [list CONFIG.NUM_MI $IC_NUM_MI] $vic
        logw "/video/axi_interconnect_0 NUM_MI $cur_mi -> $IC_NUM_MI"
    } else {
        logi "/video/axi_interconnect_0 NUM_MI already $cur_mi"
    }
    set n 0
    incr n [ensure_net_soft axi_interconnect_0/${IC_SOBEL_NUM}_ACLK    axi_interconnect_0/M00_ACLK]
    incr n [ensure_net_soft axi_interconnect_0/${IC_SOBEL_NUM}_ARESETN axi_interconnect_0/M00_ARESETN]
    logk "sobel MI clock/reset tied to M00 nets (changed=$n)"
    current_bd_instance $root_inst
    ensure_intf_conn $IC_CELL/$IC_SOBEL_MI $CAM_HIER/$CAM_AXI_SOBEL
    logk "sobel MI connected to $CAM_HIER/$CAM_AXI_SOBEL"
} else {
    # WITH_SOBEL=0：把上一轮留下的 M06 收回去，避免它悬空
    current_bd_instance /video
    set vic [get_bd_cells -quiet axi_interconnect_0]
    if {[llength $vic] > 0} {
        set cur_mi [get_property -quiet CONFIG.NUM_MI $vic]
        if {[expr {$cur_mi + 0}] > 6} {
            set_property -dict [list CONFIG.NUM_MI {6}] $vic
            logw "/video/axi_interconnect_0 NUM_MI $cur_mi -> 6 (WITH_SOBEL=0)"
        } else {
            logi "/video/axi_interconnect_0 NUM_MI already $cur_mi"
        }
    }
    current_bd_instance $root_inst
}

# =============================================================================
# Step 8 : 地址分配
# =============================================================================
proc assign_addr {seg base} {
    set s [get_bd_addr_segs -quiet $seg]
    if {[llength $s] == 0} { die "address segment not found: $seg" }
    assign_bd_address -offset $base -range 0x00010000 \
        -target_address_space [get_bd_addr_spaces ps7_0/Data] $s -force
}

assign_addr $DEC_CELL/S_AXI/Reg  $DEC_BASE
assign_addr $STA_CELL/S_AXI/Reg  $STA_BASE
assign_addr $BTN_CELL/S_AXI/Reg  $BTN_BASE
if {$WITH_SOBEL} { assign_addr $CAM_HIER/$SOBEL_CELL/s_axi_control/Reg $SOBEL_BASE }
logk "addresses assigned: dec=$DEC_BASE status=$STA_BASE btn=$BTN_BASE sobel=$SOBEL_BASE sel=$SEL_BASE"

# =============================================================================
# Step 9 : 板级 IO 约束加入工程
# =============================================================================
set xdc_norm [file normalize $xdc_file]
if {[lsearch -exact [get_files -quiet] $xdc_norm] < 0} {
    add_files -fileset constrs_1 -norecurse $xdc_norm
    logk "added constraint file: $xdc_norm"
} else {
    logi "constraint file already in project"
}
catch { set_property used_in_synthesis true [get_files $xdc_norm] }
catch { set_property used_in_implementation true [get_files $xdc_norm] }

# =============================================================================
# Step 10 : 拓扑自检 + validate + 保存
# =============================================================================
current_bd_instance $CAM_HIER
assert_intf_peer frontend/video_out        "*$CAM_HIER/$STAGE_G_CELL/s_axis"
assert_intf_peer $STAGE_G_CELL/px_axis     "*$CAM_HIER/$GRAY_CELL/video_in"
assert_intf_peer $GRAY_CELL/video_out      "*$CAM_HIER/$STAGE_G_CELL/pd_axis"
if {$WITH_SOBEL} {
    assert_intf_peer $STAGE_G_CELL/m_axis      "*$CAM_HIER/$STAGE_S_CELL/s_axis"
    assert_intf_peer $STAGE_S_CELL/px_axis     "*$CAM_HIER/$SOBEL_CELL/INPUT_STREAM"
    assert_intf_peer $SOBEL_CELL/OUTPUT_STREAM "*$CAM_HIER/$STAGE_S_CELL/pd_axis"
    assert_intf_peer $STAGE_S_CELL/m_axis      "*$CAM_HIER/out_stream"
} else {
    assert_intf_peer $STAGE_G_CELL/m_axis      "*$CAM_HIER/out_stream"
}
logk "camera_in video path verified"

# 位宽门禁：每一级都必须是 24 位。参数传播一旦退化，这里立刻失败。
foreach p [list $STAGE_G_CELL/s_axis_tdata $STAGE_G_CELL/px_axis_tdata \
                $STAGE_G_CELL/pd_axis_tdata $STAGE_G_CELL/m_axis_tdata \
                $GRAY_CELL/video_in_TDATA $GRAY_CELL/video_out_TDATA] {
    assert_width24 $p
}
if {$WITH_SOBEL} {
    foreach p [list $STAGE_S_CELL/s_axis_tdata $STAGE_S_CELL/px_axis_tdata \
                    $STAGE_S_CELL/pd_axis_tdata $STAGE_S_CELL/m_axis_tdata \
                    $SOBEL_CELL/INPUT_STREAM_TDATA $SOBEL_CELL/OUTPUT_STREAM_TDATA] {
        assert_width24 $p
    }
}
logk "all stage buses are 24-bit"
current_bd_instance $root_inst

assert_net_peer $FSM_CELL/aclk    "*ps7_0/FCLK_CLK0*"
assert_net_peer $FSM_CELL/aresetn "*rst_ps7_0_fclk0/peripheral_aresetn*"
logk "FSM clock/reset verified on the real 100MHz peripheral tree"

# 地址回读（基地址必须从主机地址空间读：从机侧段不带 OFFSET，Stage 1 踩过）
proc check_addr {cell base} {
    set found ""
    foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces ps7_0/Data]] {
        if {[string match "*$cell*" $s]} {
            set off [get_property -quiet OFFSET $s]
            if {$off ne ""} { set found $off; break }
        }
    }
    if {$found eq ""} { die "mapped segment for $cell not found" }
    if {[expr {$found}] != [expr {$base}]} {
        die "$cell base = $found, expected $base"
    }
    logk "$cell base = [format 0x%08X [expr {$found}]]"
}
check_addr $DEC_CELL $DEC_BASE
check_addr $STA_CELL $STA_BASE
check_addr $BTN_CELL $BTN_BASE
check_addr axi_gpio_sel $SEL_BASE
if {$WITH_SOBEL} { check_addr $SOBEL_CELL $SOBEL_BASE }

# ---- 拓扑快照（给人和报告看）----
set fh [open $topo_file w]
puts $fh "Stage 3 BD topology snapshot"
puts $fh "time : [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts $fh ""
puts $fh "== camera_in interface nets =="
current_bd_instance $CAM_HIER
foreach nt [get_bd_intf_nets -quiet] {
    puts $fh [format "  %-30s : %s" [get_property -quiet NAME $nt] \
                  [join [get_bd_intf_pins -quiet -of_objects $nt] "  <->  "]]
}
puts $fh ""
puts $fh "== camera_in video bus widths =="
foreach cell [list $STAGE_G_CELL $STAGE_S_CELL $GRAY_CELL $SOBEL_CELL] {
    if {[cell_exists $cell]} {
        foreach p [lsort [get_bd_pins -quiet $cell/*tdata]] {
            # 注意转义：format 串里的方括号必须写成 \[ \]，否则会被当命令替换执行
            puts $fh [format "  %-48s \[%s:%s\]" $p \
                          [get_property -quiet LEFT [get_bd_pins $p]] \
                          [get_property -quiet RIGHT [get_bd_pins $p]]]
        }
    }
}
puts $fh ""
puts $fh "== camera_in sel path =="
foreach p {axi_gpio_sel/gpio_io_o sel_slice_gray/Dout sel_slice_sobel/Dout} {
    set pin [get_bd_pins -quiet $p]
    if {[llength $pin] == 0} { puts $fh "  $p : MISSING"; continue }
    set nt [get_bd_nets -quiet -of_objects $pin]
    puts $fh [format "  %-30s net=%-24s peers=%s" $p \
                  [get_property -quiet NAME [lindex $nt 0]] \
                  [join [get_bd_pins -quiet -of_objects $nt] " , "]]
}
current_bd_instance $root_inst
puts $fh ""
puts $fh "== root cells =="
foreach c [lsort [get_bd_cells -quiet]] {
    puts $fh [format "  %-28s %s" $c [get_property -quiet VLNV $c]]
}
puts $fh ""
puts $fh "== ps7_0/Data address map =="
foreach s [lsort [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces ps7_0/Data]]] {
    puts $fh [format "  %-52s %-12s %s" $s \
                  [get_property -quiet OFFSET $s] [get_property -quiet RANGE $s]]
}
close $fh
logk "topology snapshot written: $topo_file"

catch { regenerate_bd_layout }
set vmsg ""
if {[catch { set vmsg [validate_bd_design -force] } e]} {
    die "validate_bd_design FAILED: $e"
}
logk "validate_bd_design: PASS"
if {[string trim $vmsg] ne ""} { puts "\[INFO\] validate output: [string trim $vmsg]" }

save_bd_design
close_bd_design [current_bd_design]
logk "BD validated and saved"

catch { if {[llength [current_design -quiet]] > 0} { close_design } }

if {!$BUILD_BITSTREAM} {
    puts ""
    puts "============================================================================="
    puts " BUILD_BITSTREAM=0 -> BD edited, validated and saved. Bitstream skipped."
    puts " review: $topo_file"
    puts " review: $LOGFILE"
    puts "============================================================================="
    log_note
    finish "Stage 3 BD edit done (bitstream skipped by switch)"
}

# =============================================================================
# Step 11 : 生成 BD 输出产物 + wrapper 位宽门禁（带自愈）
# -----------------------------------------------------------------------------
# out_stream 是层次引脚，它的 AXIS 参数在 BD 里从未显式保存，位宽靠"驱动源
# 盖章"推导。驱动源一换（Stage 3 从 axis_gray_bypass_0 换成 stage_sobel_0）
# 就可能退回默认 1 字节，且再也推不回来（设参数只读、换驱动源无效）——
# 只能删除重建该引脚。这里用 -force 重新生成（普通 generate_target 会以
# "up-to-date"为由跳过，Stage 2 因此读到过陈旧的 base.v 而误判）。
# =============================================================================
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

# 板级端口必须出现在 wrapper 里（端口/约束没接上时这里会拦下来）
set bv [file join $proj_dir ov5640_rgb2gray.srcs sources_1 bd base synth base.v]
set ftxt [read_all $bv]
foreach p {leds_tri_o beep_tri_o btns_tri_i} {
    if {[string first $p $ftxt] < 0} { die "wrapper base.v does not export $p" }
}
logk "wrapper exports leds_tri_o / beep_tri_o / btns_tri_i"

# ---- 11b 确保 BD wrapper 仍在 sources_1 里 ----
# 教训：把 bd/base 下的生成产物整体删掉（为了强制重生成 appcore）之后，
# Vivado 打开工程会因为 hdl/base_wrapper.v 缺失而把它从源列表里摘掉；
# generate_target 只负责把文件写回来，不会自动加回 fileset，于是综合阶段
# 直接报 [Synth 8-439] module 'base_wrapper' not found。
set wv [file join $proj_dir ov5640_rgb2gray.srcs sources_1 bd base hdl base_wrapper.v]
if {![file exists $wv]} { die "BD wrapper missing after generate_target: $wv" }
set wv_norm [file normalize $wv]
if {[lsearch -exact [get_files -quiet] $wv_norm] < 0} {
    add_files -fileset sources_1 -norecurse $wv_norm
    update_compile_order -fileset sources_1
    logw "re-added BD wrapper to sources_1 (it had been dropped while the file was missing)"
} else {
    logi "BD wrapper already present in sources_1"
}
set cur_top [get_property -quiet top [current_fileset]]
if {$cur_top ne "base_wrapper"} {
    set_property top base_wrapper [current_fileset]
    logw "top was '$cur_top', re-set to base_wrapper"
}

# =============================================================================
# Step 12 : 综合 + 实现 + 写比特流
# =============================================================================
logi "launch synth_1 (jobs=$JOBS) ..."
if {[catch { launch_runs synth_1 -jobs $JOBS } emsg]} {
    if {[string match "*needs to be reset*" $emsg]} {
        logw "synth_1 out of date, reset_run and relaunch"
        reset_run synth_1
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

# 提前资源门禁：综合后先看一次 LUT 规模。综合完就已经能判断资源是否爆掉，
# 超上限直接停在这里，不浪费十几分钟跑实现。
set synth_util ""
open_run synth_1
catch { set synth_util [report_utilization -return_string] }
close_design
set synth_lut ""
if {[regexp -line {^\|\s+Slice LUTs\s+\|\s+(\d+)\s+\|} $synth_util -> synth_lut]} {
    logi "post-synthesis Slice LUTs = $synth_lut (ceiling $LUT_CEIL)"
    if {$synth_lut > $LUT_CEIL} {
        die "post-synthesis LUT usage $synth_lut exceeds the ceiling $LUT_CEIL -- the design does not fit comfortably on xc7z010; stopping before implementation."
    }
} else {
    logw "could not parse post-synthesis LUT count; the post-implementation gate still applies"
}

logi "launch impl_1 -to_step write_bitstream (jobs=$JOBS) ..."
if {[catch { launch_runs impl_1 -to_step write_bitstream -jobs $JOBS } emsg]} {
    if {[string match "*needs to be reset*" $emsg]} {
        logw "impl_1 out of date, reset_run and relaunch"
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
# Step 12b : 时序门禁（必须在导出比特流之前）
# -----------------------------------------------------------------------------
# 只看"构建成功 / DRC 干净"是不够的：负裕量的比特流照样能写出来。
# 这里把 setup 裕量挂上硬闸门，并打印最差路径的首尾端点，方便直接定位到
# 是哪个 IP 内部没收敛。
# =============================================================================
if {$wns ne "" && $wns < 0 && !$ALLOW_NEGATIVE_SLACK} {
    puts "\[WARN\] worst setup path (for triage):"
    open_run impl_1
    catch {
        foreach ln [split [report_timing -return_string -max_paths 1] "\n"] {
            if {[string match "*Source:*" $ln] || [string match "*Destination:*" $ln] ||
                [string match "*Data Path Delay:*" $ln] || [string match "*Logic Levels:*" $ln] ||
                [string match "*Slack*VIOLATED*" $ln]} {
                puts "\[WARN\] [string trim $ln]"
            }
        }
    }
    close_design
    die "timing gate FAILED: WNS = $wns ns -- refusing to export a bitstream whose setup timing is not met (set ALLOW_NEGATIVE_SLACK=1 only if you deliberately accept it)."
}
logk "timing gate PASS: WNS = $wns ns"

# =============================================================================
# Step 13 : 实现后指标门禁（必须在导出比特流之前）
# -----------------------------------------------------------------------------
# 只看"构建成功"是不够的：Stage 2 产出过一版时序全过、DRC 干净、比特流正常
# 写出，但采集前端与处理通路被整体优化掉的产物。导出前核对：
#   1) 灰度数据通路真实存在（cell 名含 rgb2gray_480_800）
#   2) Sobel 数据通路真实存在
#   3) 决策 FSM 真实存在
#   4) DSP48 数量 >= 3（灰度 IP 的 RGB->Y 乘法器），并打印实际值
#   5) Slice LUT 数在 [LUT_FLOOR, LUT_CEIL] 之间
# =============================================================================
open_run impl_1
set dsp_cnt [llength [get_cells -hier -quiet -filter {REF_NAME =~ "DSP48*"}]]
set gray_cnt [llength [get_cells -hier -quiet -filter {NAME =~ "*rgb2gray_480_800*"}]]
set sob_cnt  [llength [get_cells -hier -quiet -filter {NAME =~ "*sobel*"}]]
set dec_cnt  [llength [get_cells -hier -quiet -filter {NAME =~ "*adas_decision_0*"}]]
set util_txt ""
catch { set util_txt [report_utilization -return_string] }
close_design
set lut_cnt ""
regexp -line {^\|\s+Slice LUTs\s+\|\s+(\d+)\s+\|} $util_txt -> lut_cnt
logi "metric 1/5 : gray datapath cells (rgb2gray_480_800) = $gray_cnt"
logi "metric 2/5 : sobel datapath cells (*sobel*)          = $sob_cnt"
logi "metric 3/5 : decision FSM cells (adas_decision_0)    = $dec_cnt"
logi "metric 4/5 : DSP48 count                            = $dsp_cnt (expect >= 3)"
logi "metric 5/5 : Slice LUTs                             = '$lut_cnt' (expect $LUT_FLOOR..$LUT_CEIL)"
set metric_bad 0
if {$gray_cnt == 0} { logw "metric FAIL: gray datapath not found in netlist"; set metric_bad 1 }
if {$WITH_SOBEL && $sob_cnt == 0} { logw "metric FAIL: sobel datapath not found in netlist"; set metric_bad 1 }
if {$dec_cnt == 0} { logw "metric FAIL: adas_decision_0 not found in netlist"; set metric_bad 1 }
if {$dsp_cnt < 3} { logw "metric FAIL: DSP48 = $dsp_cnt"; set metric_bad 1 }
if {$lut_cnt eq "" || $lut_cnt < $LUT_FLOOR || $lut_cnt > $LUT_CEIL} {
    logw "metric FAIL: Slice LUTs = '$lut_cnt' outside [$LUT_FLOOR,$LUT_CEIL]"
    set metric_bad 1
}
if {$metric_bad} {
    die "post-implementation metric gate failed -- refusing to export a non-working bitstream"
}
if {$WITH_SOBEL} {
    logk "metric gate PASS: gray + sobel + FSM all present, resources in range"
} else {
    logk "metric gate PASS: gray + FSM present (sobel stage not built), resources in range"
}

# =============================================================================
# Step 14 : 导出 .bit / .hwh 到 ready_to_test
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

set hwh_text [read_all $hwh_dst]
foreach cell [list $STAGE_G_CELL $GRAY_CELL $DEC_CELL $STA_CELL $BTN_CELL $FSM_CELL] {
    if {[string first $cell $hwh_text] < 0} { die "exported $hwh_name does not contain $cell" }
}
if {$WITH_SOBEL && [string first $STAGE_S_CELL $hwh_text] < 0} {
    die "exported $hwh_name does not contain $STAGE_S_CELL"
}
foreach {base what} [list [format %08x $DEC_BASE] "gpio_dec" \
                          [format %08x $STA_BASE] "gpio_status" \
                          [format %08x $BTN_BASE] "gpio_btn"] {
    if {[string first $base [string tolower $hwh_text]] < 0} {
        logw "$what base $base not found in $hwh_name, re-check on PYNQ side"
    }
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
        report_utilization     -file [file join $report_dir stage3_utilization.rpt]
        report_utilization -hierarchical -file [file join $report_dir stage3_util_hier.rpt]
        report_timing_summary  -file [file join $report_dir stage3_timing_summary.rpt]
        close_design
        logk "reports written: stage3_utilization / stage3_util_hier / stage3_timing_summary"
    } emsg]} {
        logw "report generation failed (not affecting deliverables): $emsg"
    }
}

puts ""
puts "============================================================================="
puts " Stage 3 finished"
puts "   bit       : $bit_dst"
puts "   hwh       : $hwh_dst"
puts "   video sel : $CAM_HIER/axi_gpio_sel @ [format 0x%08X $SEL_BASE]  channel1 bit0=gray bit1=sobel"
puts "   decision  : $DEC_CELL @ [format 0x%08X $DEC_BASE] (write)  $STA_CELL @ [format 0x%08X $STA_BASE] (read)"
puts "   buttons   : $BTN_CELL @ [format 0x%08X $BTN_BASE] (read)"
puts "   backup    : $backup_dir"
puts "   end       : [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts "============================================================================="
log_note

finish "Stage 3 done: pipeline + decision FSM integrated, bitstream built and exported"
