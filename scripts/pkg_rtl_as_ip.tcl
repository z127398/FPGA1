# =============================================================================
#  pkg_rtl_as_ip.tcl -- 把自研 RTL 打包成 ip_repo 里的正式 IP
# -----------------------------------------------------------------------------
#  用法：
#     vivado -mode batch -nojournal -nolog -notrace -source D:/adas_pl/scripts/pkg_rtl_as_ip.tcl
#
#  为什么要打包而不能用 module reference：
#     Stage 2 实测过——module reference 引入的 RTL，其 AXIS 接口参数在 BD 里是
#     只读的、也推不出来，会让层次引脚退回总线默认值（TDATA_NUM_BYTES=1），
#     24 位视频只连出第 0 位，综合把整条数据通路当死逻辑删掉，产出"能生成、
#     能过时序、但完全不能工作"的比特流。打包成正式 IP 并在 component.xml 里
#     显式声明接口参数，才能避免这一类静默故障。
#
#  v2（2026-10-05）修掉一个真实缺陷：
#     旧版用一条跨标签懒匹配正则注入参数。Tcl 的 ARE 引擎对整体匹配采用
#     leftmost-longest，`.*?</spirit:busInterface>` 一路吃到文档最后一个闭合
#     标签，五个参数块全塞进 aclk 一个接口里；component.xml 于是 schema 非法：
#         CRITICAL WARNING: [IP_Flow 19-1977] Unable to read IP file .../component.xml
#     结果是 IP 被静默踢出 catalog，BD 里 create_bd_cell 才失败（或者更糟：
#     用旧缓存继续构建）。现在改成 xml_param_inject.tcl 里的字符串精确定位，
#     并且每份 component.xml 都要过三道 XML 门禁 + 一道 catalog 门禁。
#
#  门禁：
#     gate 1  XML 标签配对
#     gate 2  每个 busInterface 至多一个 <spirit:parameters>
#     gate 3  BUSIFPARAM_VALUE id 不重复
#     gate 4  Vivado 能真的把这份 IP 读进 catalog（get_ipdefs 返回非空）
# =============================================================================

set script_dir [file normalize [file dirname [info script]]]
set root_dir   [file normalize [file join $script_dir ..]]
set rtl_dir    [file join $root_dir src rtl]
set repo_dir   [file join $root_dir src ip ip_repo]
set work_root  [file join $env(TEMP) adas_ip_pkg]

proc logi {m} { puts "\[INFO\] $m" }
proc logk {m} { puts "\[ OK \] $m" }
proc logw {m} { puts "\[WARN\] $m" }
proc die  {m} { puts "\[FAIL\] $m"; exit 1 }

# ---- 待打包的 IP 清单 ----
#   axis  : 需要注入参数的 AXIS 接口列表（空串表示该 IP 没有 AXIS 接口）
#   bytes : TDATA_NUM_BYTES（本工程视频流固定 3 字节 = 24bit）
set ip_list [list \
    [dict create name axis_stage_bypass files {axis_stage_bypass.v} \
         axis {s_axis px_axis pd_axis m_axis} bytes 3 clk aclk] \
    [dict create name adas_decision     files {adas_decision.v} \
         axis {} bytes 0 clk aclk] \
]

# ---- 引入 XML 注入库（纯 Tcl，已离线单测：sim/test_xml_param_inject.tcl）----
set lib_file [file join $script_dir xml_param_inject.tcl]
if {![file exists $lib_file]} { die "missing helper: $lib_file" }
source $lib_file

if {![file isdirectory $repo_dir]} { die "ip_repo not found: $repo_dir" }

puts ""
puts "============================================================================="
puts " package in-house RTL as IP"
puts "   rtl  : $rtl_dir"
puts "   repo : $repo_dir"
puts "   work : $work_root"
puts "============================================================================="

foreach ip $ip_list {
    set name  [dict get $ip name]
    set files [dict get $ip files]
    set axis  [dict get $ip axis]
    set bytes [dict get $ip bytes]
    set clk   [dict get $ip clk]

    puts ""
    puts "=================== package $name ==================="
    set work [file join $work_root $name]
    file delete -force $work
    file mkdir $work

    create_project pkg_$name $work -part xc7z010clg400-1 -force
    foreach f $files {
        set rtl_file [file join $rtl_dir $f]
        if {![file exists $rtl_file]} { die "RTL not found: $rtl_file" }
        add_files -norecurse $rtl_file
    }
    set_property top $name [current_fileset]
    update_compile_order -fileset sources_1

    if {[catch { ipx::package_project -root_dir $work -vendor xilinx.com \
                    -library user -taxonomy /UserIP -import_files } e]} {
        die "ipx::package_project failed: $e"
    }
    catch { ipx::create_xgui_files [ipx::current_core] }
    catch { ipx::save_core [ipx::current_core] }

    set cx [file join $work component.xml]
    if {![file exists $cx]} { die "no component.xml produced: $cx" }

    # ---- 注入接口参数（打包流程的关键补丁）----
    set touched [concat $axis [list $clk]]
    foreach a $axis {
        set r [xmlp_add_busif_params $cx $a [xmlp_axis_param_pairs $a $bytes]]
        logk "$a : added=[lindex $r 0] kept_existing=[lindex $r 1] (TDATA_NUM_BYTES=$bytes)"
    }
    set r [xmlp_add_busif_params $cx $clk [xmlp_clk_param_pairs $clk $axis]]
    logk "$clk : added=[lindex $r 0] kept_existing=[lindex $r 1] (FREQ_HZ=100000000)"

    # ---- gate 1/2/3：XML 结构门禁 ----
    set probs [xmlp_check_file $cx $touched]
    if {[llength $probs] > 0} {
        foreach p $probs { puts "\[FAIL\] xml gate: $p" }
        die "$name : component.xml failed XML gates -- refusing to install a broken IP"
    }
    set nitems [regexp -all -- {<spirit:parameter>} [xmlp_read_file $cx]]
    logk "$name : XML gates PASS (spirit:parameter count = $nitems)"

    # ---- 安装到 ip_repo ----
    set dst [file join $repo_dir ${name}_1_0]
    file delete -force $dst
    file mkdir $dst
    file copy -force $cx [file join $dst component.xml]
    foreach sub {src xgui} {
        set s [file join $work $sub]
        if {[file isdirectory $s]} { file copy -force $s $dst }
    }
    logk "$name installed to $dst"

    # ---- gate 4：Vivado 必须真的能把这 IP 读进 catalog ----
    # 这一步直接复现之前那个静默故障：component.xml 非法时 Vivado 只打印
    # CRITICAL WARNING [IP_Flow 19-1977] 然后"忽略"这个 IP，构建照常进行，
    # 直到 BD 里找不到 IP 才炸。这里把它变成硬门禁。
    set_property ip_repo_paths [list $repo_dir] [current_project]
    update_ip_catalog
    set vlnv "xilinx.com:user:${name}:1.0"
    if {[llength [get_ipdefs -quiet $vlnv]] == 0} {
        die "$name : catalog gate FAILED -- Vivado cannot read $vlnv (see IP_Flow 19-1977 warning above)"
    }
    logk "$name : catalog gate PASS ($vlnv is loadable)"

    close_project
}

puts ""
puts "============================================================================="
puts " packaging finished. all XML gates and catalog gates passed."
puts " next: confirm the project's ip_repo_paths points to $repo_dir and run update_ip_catalog"
puts "============================================================================="
exit 0
