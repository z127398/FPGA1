# =============================================================================
#  ADAS-PL / Stage 1 -- 生成 7_ov5640_rgb2gray 比特流并导出 PYNQ 交付件
# -----------------------------------------------------------------------------
#  工程 : D:/adas_pl/src/ip/7_ov5640_rgb2gray/vivado/ov5640_rgb2gray
#  流程 : 打开工程 -> 基线备份 -> 校验 IP 仓库/BD 拓扑 -> 生成比特流
#         -> 导出 ov5640_rgb2gray.bit / .hwh 到 ready_to_test
#
#  用法 :
#     vivado -mode batch -source D:/adas_pl/scripts/stage1_build_bitstream.tcl
#
#  幂等 : 可反复执行。基线备份只创建一次，后续运行不会覆盖；
#         已是最新的综合/实现 run，Vivado 会自动跳过，不会白跑十几分钟。
#
#  说明 : 1) 本工程 BD 已处于目标状态（ov5640_rgb2gray_0 已插在 video/camera_in
#            内部、axi_interconnect_0 的 NUM_MI=5、基地址 0x40000000），
#            脚本只做校验与构建，不重新插 IP。
#         2) 脚本内所有控制台输出均为 ASCII。原因：中文 Windows 下 Vivado
#            Tcl 的 encoding system 是 cp936，中文输出到控制台会损坏部分字符
#            （已实测）；中文只出现在注释里，不影响解析。
#         3) 编辑本文件请保持 UTF-8；中文注释尽量以行尾结束，不要在同一行
#            紧跟 } 或 ] 这类结构字符（cp936 解码有概率把它吞掉）。
# =============================================================================

# ------------------------------ 运行开关 -------------------------------------
set FORCE_CLEAN_BUILD  1   ;# 1 = 先 reset_run 再跑（强制全量重建，约 10+ 分钟）
set JOBS               4   ;# 综合/实现并行任务数
set EXPORT_BD_AUX      0   ;# 1 = 同时刷新 ready_to_test 里的 .tcl/.xdc
set WRITE_REPORTS      1   ;# 1 = 额外输出时序/资源报告到 reports/
# -----------------------------------------------------------------------------

set script_dir  [file normalize [file dirname [info script]]]
set root_dir    [file normalize [file join $script_dir ..]]
set proj_dir    [file join $root_dir src ip 7_ov5640_rgb2gray vivado ov5640_rgb2gray]
set xpr_file    [file join $proj_dir ov5640_rgb2gray.xpr]
set repo_dir    [file join $root_dir src ip ip_repo]
set ready_dir   [file join $proj_dir ready_to_test]
set backup_dir  [file join $root_dir backups 7_ov5640_rgb2gray_baseline]
set report_dir  [file join $root_dir reports]
set status_file [file join $report_dir stage1_last_run.txt]
set bit_name    ov5640_rgb2gray.bit
set hwh_name    ov5640_rgb2gray.hwh

set BD              base
set GRAY_CELL       /video/camera_in/ov5640_rgb2gray_0
set GRAY_IP_VLNV    xilinx.com:hls:ov5640_rgb2gray:1.0
set GRAY_IP_INST    base_ov5640_rgb2gray_0_0
set GRAY_BASEADDR   0x40000000

# ------------------------------ 辅助过程 -------------------------------------
# 控制台输出一律 ASCII，避免 cp936 下中文乱码
proc logi {m} { puts "\[INFO\] $m" }
proc logw {m} { puts "\[WARN\] $m" }
proc logk {m} { puts "\[ OK \] $m" }

proc die {m} {
    global status_file
    puts "\[FAIL\] $m"
    catch { close_project -quiet }
    if {[catch { set fh [open $status_file w]
                 puts $fh "FAIL: $m"
                 close $fh }]} {}
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

# BD 接口引脚是否有连线
proc bd_intf_connected {pin} {
    set p [get_bd_intf_pins -quiet $pin]
    if {[llength $p] == 0} { return 0 }
    return [expr {[llength [get_bd_intf_nets -quiet -of_objects $p]] > 0}]
}

# BD 普通引脚是否有连线
proc bd_net_connected {pin} {
    set p [get_bd_pins -quiet $pin]
    if {[llength $p] == 0} { return 0 }
    return [expr {[llength [get_bd_nets -quiet -of_objects $p]] > 0}]
}

# 取某个接口引脚所在网络上的全部接口引脚（用于校验上下游）
proc peer_pins_of {pin} {
    set nets [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins $pin]]
    if {[llength $nets] == 0} { return "" }
    return [get_bd_intf_pins -quiet -of_objects $nets]
}

puts ""
puts "============================================================================="
puts " Stage 1 : 7_ov5640_rgb2gray -- build bitstream and export ready_to_test"
puts " start   : [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts "============================================================================="

file mkdir $report_dir

# =============================================================================
# Step 0 : 前置检查
# =============================================================================
logi "project root : $root_dir"
if {![file exists $xpr_file]} {
    die "project file not found: $xpr_file"
}
if {![file isdirectory $repo_dir]} {
    die "IP repo dir not found: $repo_dir  (unzip ip_repo from ZYNQ_7010_PYNQ.zip into this path)"
}
logk "project file and IP repo dir exist"

# =============================================================================
# Step 1 : 基线备份（只做一次，保护原始 BD / xpr / 约束 / 交付件）
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
    logi "baseline backup already exists, skip (never overwritten): $backup_dir"
} else {
    file mkdir $backup_dir
    set missing {}
    foreach item $backup_items {
        lassign $item src dst
        if {[file exists $src]} {
            set dst_full [file join $backup_dir $dst]
            file mkdir [file dirname $dst_full]
            file copy -force $src $dst_full
        } else {
            lappend missing $src
        }
    }
    set fh [open [file join $backup_dir MANIFEST.txt] w]
    puts $fh "backup time : [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
    puts $fh "source proj : $proj_dir"
    puts $fh "note        : baseline snapshot before Stage 1; design sources only, no runs/ products"
    puts $fh ""
    foreach item $backup_items {
        lassign $item src dst
        set dst_full [file join $backup_dir $dst]
        if {[file exists $dst_full]} {
            puts $fh [format "  %10d  %s" [file size $dst_full] $dst]
        } else {
            puts $fh [format "  %10s  %s" "MISSING" $dst]
        }
    }
    close $fh
    if {[llength $missing] > 0} {
        logw "these files were missing and not backed up: $missing"
    }
    logk "baseline backup done: $backup_dir"
}

# =============================================================================
# Step 2 : 打开工程 + 注册 IP 仓库 + 校验 IP 定义存在
# =============================================================================
catch { if {[llength [current_project -quiet]] > 0} { close_project } }
open_project $xpr_file
logk "project opened: [current_project]"

set repo_norm [file normalize $repo_dir]
set repo_list [get_property -quiet ip_repo_paths [current_project]]
if {[lsearch -exact $repo_list $repo_norm] < 0} {
    set repo_list [linsert $repo_list 0 $repo_norm]
    set_property ip_repo_paths $repo_list [current_project]
    logw "repo not in project ip_repo_paths, appended: $repo_norm"
}

update_ip_catalog
if {[llength [get_ipdefs -quiet $GRAY_IP_VLNV]] == 0} {
    logw "$GRAY_IP_VLNV not found on first scan, running update_ip_catalog -rebuild ..."
    update_ip_catalog -rebuild
}
if {[llength [get_ipdefs -quiet $GRAY_IP_VLNV]] == 0} {
    die "IP definition $GRAY_IP_VLNV still not found in catalog.\n       check: $repo_norm/xilinx_com_hls_ov5640_rgb2gray_1_0/component.xml"
}
logk "HLS IP definition ready: $GRAY_IP_VLNV"

# IP 实例若被标记锁定（源文件变动/版本差异），先解锁，避免 BD 输出产物生成失败
set gray_ip [get_ips -quiet $GRAY_IP_INST]
if {[llength $gray_ip] == 0} {
    logw "IP instance $GRAY_IP_INST not found yet, let BD generation handle it"
} elseif {[get_property -quiet IS_LOCKED $gray_ip] == 1} {
    logw "IP instance $GRAY_IP_INST is locked, running upgrade_ip"
    catch { upgrade_ip $gray_ip }
}

# =============================================================================
# Step 3 : Block Design 拓扑校验（只读断言，不重新插 IP）
# =============================================================================
set bd_files [get_files -quiet *$BD.bd]
if {[llength $bd_files] == 0} { die "cannot find $BD.bd in project" }
open_bd_design [lindex $bd_files 0]
logi "block design opened: [current_bd_design]"

if {[llength [get_bd_cells -quiet $GRAY_CELL]] == 0} {
    die "cell $GRAY_CELL not found -- this BD is not in the expected target state"
}
set actual_vlnv [get_property -quiet VLNV [get_bd_cells $GRAY_CELL]]
if {$actual_vlnv ne $GRAY_IP_VLNV} {
    die "cell $GRAY_CELL has VLNV $actual_vlnv, expected $GRAY_IP_VLNV"
}
logk "gray IP instance present with correct VLNV: $GRAY_CELL"

if {![bd_intf_connected $GRAY_CELL/video_in]}      { die "$GRAY_CELL/video_in is not connected" }
if {![bd_intf_connected $GRAY_CELL/video_out]}     { die "$GRAY_CELL/video_out is not connected" }
if {![bd_intf_connected $GRAY_CELL/s_axi_control]} { die "$GRAY_CELL/s_axi_control is not connected" }
if {![bd_net_connected  $GRAY_CELL/ap_clk]}        { die "$GRAY_CELL/ap_clk is not connected" }
if {![bd_net_connected  $GRAY_CELL/ap_rst_n]}      { die "$GRAY_CELL/ap_rst_n is not connected" }

set vi_peers [peer_pins_of $GRAY_CELL/video_in]
if {![string match "*frontend/video_out*" $vi_peers]} {
    die "video_in upstream is not camera_in/frontend/video_out (peers: $vi_peers)"
}
set vo_peers [peer_pins_of $GRAY_CELL/video_out]
if {![string match "*camera_in/out_stream*" $vo_peers]} {
    die "video_out downstream is not camera_in/out_stream (peers: $vo_peers)"
}
logk "video path correct: frontend/video_out -> ov5640_rgb2gray_0 -> out_stream"

set ic_cell /video/axi_interconnect_0
set num_mi [get_property -quiet CONFIG.NUM_MI [get_bd_cells $ic_cell]]
if {$num_mi ne "5"} {
    die "$ic_cell NUM_MI = $num_mi, expected 5 (VDMA + video_out x3 + gray IP)"
}
logk "axi_interconnect_0 NUM_MI = 5"

# 注意：从机侧地址段 /video/.../s_axi_control/Reg 不带 OFFSET，要读的是主机地址空间
# ps7_0/Data 下映射出来的段（/ps7_0/Data/SEG_ov5640_rgb2gray_0_Reg）的 OFFSET。
set addr ""
foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces ps7_0/Data]] {
    if {[string match "*ov5640_rgb2gray_0*" $s]} {
        set candidate [get_property -quiet OFFSET $s]
        if {$candidate ne ""} { set addr $candidate; break }
    }
}
if {$addr eq ""} {
    die "no mapped address segment for ov5640_rgb2gray_0 in address space ps7_0/Data"
}
if {[expr {$addr}] != [expr {$GRAY_BASEADDR}]} {
    die "gray IP base address = $addr, expected $GRAY_BASEADDR"
}
logk "gray IP reg base = [format 0x%08X [expr {$addr}]] (rows@0x10, cols@0x18)"

validate_bd_design
save_bd_design
close_bd_design [current_bd_design]
logk "BD validated and saved (originals kept in $backup_dir)"

catch { if {[llength [current_design -quiet]] > 0} { close_design } }

# =============================================================================
# Step 4 : 可选强制全量重建
# =============================================================================
if {$FORCE_CLEAN_BUILD} {
    foreach r {synth_1 impl_1} {
        if {[llength [get_runs -quiet $r]] > 0} { reset_run $r }
    }
    logw "FORCE_CLEAN_BUILD=1, synth_1 / impl_1 have been reset"
}

# =============================================================================
# Step 5 : 刷新 BD 输出产物（从恢复的 IP 仓库重新生成 IP 输出）
# =============================================================================
logi "generating BD output products ..."
generate_target all [lindex $bd_files 0]
logk "BD output products updated"

# =============================================================================
# Step 6 : 综合
# =============================================================================
logi "launch synth_1 (jobs=$JOBS) ..."
launch_runs synth_1 -jobs $JOBS
wait_on_run synth_1
set synth_status [get_property -quiet STATUS [get_runs synth_1]]
if {[get_property -quiet PROGRESS [get_runs synth_1]] ne "100%"} {
    die "synthesis did not complete: $synth_status"
}
logk "synthesis done: $synth_status"

# =============================================================================
# Step 7 : 实现 + 写比特流
# =============================================================================
logi "launch impl_1 -to_step write_bitstream (jobs=$JOBS) ..."
launch_runs impl_1 -to_step write_bitstream -jobs $JOBS
wait_on_run impl_1
set impl_status [get_property -quiet STATUS [get_runs impl_1]]
if {[get_property -quiet PROGRESS [get_runs impl_1]] ne "100%"} {
    die "implementation/bitstream did not complete: $impl_status"
}
logk "implementation and bitstream done: $impl_status"

set wns [get_property -quiet STATS.WNS [get_runs impl_1]]
set whs [get_property -quiet STATS.WHS [get_runs impl_1]]
logi "timing: WNS = $wns ns , WHS = $whs ns"
if {$wns ne "" && $wns < 0} { logw "setup violation, WNS = $wns ns" }
if {$whs ne "" && $whs < 0} { logw "hold violation, WHS = $whs ns" }

# =============================================================================
# Step 8 : 导出 .bit / .hwh 到 ready_to_test
# =============================================================================
set impl_dir [file join $proj_dir ov5640_rgb2gray.runs impl_1]
set bit_list [glob -nocomplain -directory $impl_dir *.bit]
if {[llength $bit_list] == 0} { die "no .bit found in $impl_dir" }
if {[llength $bit_list] > 1} { logw "multiple .bit in impl_1, using [lindex $bit_list 0]" }
set bit_src [lindex $bit_list 0]

set hwh_list [glob -nocomplain [file join $proj_dir ov5640_rgb2gray.srcs sources_1 bd * hw_handoff *.hwh]]
if {[llength $hwh_list] == 0} { die "no hw_handoff/*.hwh found, cannot export for PYNQ" }
set hwh_src [lindex $hwh_list 0]

file mkdir $ready_dir
set bit_dst [file join $ready_dir $bit_name]
set hwh_dst [file join $ready_dir $hwh_name]
file copy -force $bit_src $bit_dst
file copy -force $hwh_src $hwh_dst

if {[file size $bit_dst] <= 0} { die "exported bitstream is empty: $bit_dst" }

# PYNQ Overlay 依赖 .hwh 里的 IP 地址映射，这里做一次落地校验
set fh [open $hwh_dst r]
set hwh_text [read $fh]
close $fh
if {[string first "ov5640_rgb2gray_0" $hwh_text] < 0} {
    die "exported $hwh_name does not contain ov5640_rgb2gray_0 -- PYNQ cannot see the IP"
}
if {[string first "40000000" [string tolower $hwh_text]] < 0} {
    logw "0x40000000 not found in $hwh_name, re-check base addr via ip_dict on PYNQ side"
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

# =============================================================================
# Step 9 : 可选报告
# =============================================================================
if {$WRITE_REPORTS} {
    if {[catch {
        open_run impl_1
        report_utilization    -file [file join $report_dir stage1_utilization.rpt]
        report_timing_summary -file [file join $report_dir stage1_timing_summary.rpt]
        close_design
        logk "reports written to $report_dir (stage1_utilization.rpt / stage1_timing_summary.rpt)"
    } emsg]} {
        logw "report generation failed (bitstream and deliverables not affected): $emsg"
    }
}

puts ""
puts "============================================================================="
puts " Stage 1 finished"
puts "   bit     : $bit_dst"
puts "   hwh     : $hwh_dst"
puts "   backup  : $backup_dir"
puts "   end     : [clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}]"
puts "============================================================================="

finish "7_ov5640_rgb2gray bitstream built and exported"
