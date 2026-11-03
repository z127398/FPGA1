# =============================================================================
#  test_xml_param_inject.tcl -- 离线单测：IP-XACT 参数注入
# -----------------------------------------------------------------------------
#  用法（不需要 Vivado）：
#     E:/Xilinx/Vivado/2020.2/bin/unwrapped/win64.o/tclsh85t.exe \
#         C:/Users/15491/.codex/tmp/adas/sim/test_xml_param_inject.tcl
#
#  用例：
#    T1 合成一份模拟 ipx::package_project 输出的 component.xml（5 个接口，
#       aclk 已有 ASSOCIATED_BUSIF），注入 5 组参数后三门禁全过，
#       且每个接口内恰好出现自己的参数 id。
#    T2 重复注入必须幂等（第二次 added=0）。
#    T3 回归对照：旧版"跨标签懒匹配正则"会把参数块塞进最后一个接口
#       —— 在合成文件上复现这个错误。
#    T4 真实现场的坏文件（D 盘 axis_stage_bypass_1_0）必须被门禁抓出来。
# =============================================================================
set here   [file normalize [file dirname [info script]]]
set root   [file normalize [file join $here ..]]
source [file join $root scripts xml_param_inject.tcl]

set pass 0
set fail 0
proc ok  {m} { puts "  PASS  $m"; incr ::pass }
proc bad {m} { puts "  FAIL  $m"; incr ::fail }
proc chk {cond m} { if {[expr $cond]} { ok $m } else { bad $m } }

set work [file join $env(TEMP) adas_xml_test]
file delete -force $work
file mkdir $work

# -----------------------------------------------------------------------------
#  合成 component.xml：结构与 ipx 输出一致 —— aclk 已经带一份 parameters，
#  四个 AXIS 接口只有 portMaps。
# -----------------------------------------------------------------------------
set axis_ifaces {m_axis pd_axis px_axis s_axis}
set t "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
append t "<spirit:component xmlns:xilinx=\"http://www.xilinx.com\" xmlns:spirit=\"http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009\">\n"
append t "  <spirit:vendor>xilinx.com</spirit:vendor>\n"
append t "  <spirit:library>user</spirit:library>\n"
append t "  <spirit:name>axis_stage_bypass</spirit:name>\n"
append t "  <spirit:version>1.0</spirit:version>\n"
append t "  <spirit:busInterfaces>\n"
foreach ifn $axis_ifaces {
    append t "    <spirit:busInterface>\n"
    append t "      <spirit:name>$ifn</spirit:name>\n"
    append t "      <spirit:busType spirit:vendor=\"xilinx.com\" spirit:library=\"interface\" spirit:name=\"axis\" spirit:version=\"1.0\"/>\n"
    append t "      <spirit:abstractionType spirit:vendor=\"xilinx.com\" spirit:library=\"interface\" spirit:name=\"axis_rtl\" spirit:version=\"1.0\"/>\n"
    append t "      <spirit:slave/>\n"
    append t "      <spirit:portMaps>\n"
    foreach sig {TDATA TKEEP TLAST TUSER TVALID TREADY} {
        append t "        <spirit:portMap>\n"
        append t "          <spirit:logicalPort>\n            <spirit:name>$sig</spirit:name>\n          </spirit:logicalPort>\n"
        append t "          <spirit:physicalPort>\n            <spirit:name>${ifn}_[string tolower $sig]</spirit:name>\n          </spirit:physicalPort>\n"
        append t "        </spirit:portMap>\n"
    }
    append t "      </spirit:portMaps>\n"
    append t "    </spirit:busInterface>\n"
}
append t "    <spirit:busInterface>\n"
append t "      <spirit:name>aclk</spirit:name>\n"
append t "      <spirit:busType spirit:vendor=\"xilinx.com\" spirit:library=\"signal\" spirit:name=\"clock\" spirit:version=\"1.0\"/>\n"
append t "      <spirit:slave/>\n"
append t "      <spirit:portMaps>\n"
append t "        <spirit:portMap>\n          <spirit:logicalPort>\n            <spirit:name>CLK</spirit:name>\n          </spirit:logicalPort>\n"
append t "          <spirit:physicalPort>\n            <spirit:name>aclk</spirit:name>\n          </spirit:physicalPort>\n        </spirit:portMap>\n"
append t "      </spirit:portMaps>\n"
append t "      <spirit:parameters>\n"
append t "        <spirit:parameter>\n          <spirit:name>ASSOCIATED_BUSIF</spirit:name>\n"
append t "          <spirit:value spirit:id=\"BUSIFPARAM_VALUE.ACLK.ASSOCIATED_BUSIF\">m_axis:pd_axis:px_axis:s_axis</spirit:value>\n"
append t "        </spirit:parameter>\n      </spirit:parameters>\n"
append t "    </spirit:busInterface>\n"
append t "  </spirit:busInterfaces>\n"
append t "</spirit:component>\n"

set good [file join $work component_good.xml]
xmlp_write_file $good $t

puts ""
puts "=========== T1 : inject into a clean component.xml ==========="
foreach ifn $axis_ifaces {
    set r [xmlp_add_busif_params $good $ifn [xmlp_axis_param_pairs $ifn 3]]
    chk "[lindex $r 0] == 5" "$ifn : 5 params added (got [lindex $r 0])"
}
set r [xmlp_add_busif_params $good aclk [xmlp_clk_param_pairs aclk $axis_ifaces]]
chk "[lindex $r 0] == 1" "aclk : FREQ_HZ added, ASSOCIATED_BUSIF kept (added=[lindex $r 0] skipped=[lindex $r 1])"

set probs [xmlp_check_file $good [concat $axis_ifaces aclk]]
chk "[llength $probs] == 0" "three gates pass on injected file (problems: $probs)"

set txt [xmlp_read_file $good]
foreach ifn $axis_ifaces {
    set U [string toupper $ifn]
    set span [xmlp_find_busif_span $txt $ifn]
    lassign $span s e
    set elem [string range $txt $s [expr {$e + [string length $::XMLP_BAXI_CLOSE] - 1}]]
    set n [regexp -all -- "BUSIFPARAM_VALUE\.$U\.TDATA_NUM_BYTES" $elem]
    set v3 [string first {TDATA_NUM_BYTES">3<} $elem]
    set nb [xmlp_busif_param_blocks $txt $ifn]
    chk "$n == 1" "$ifn : TDATA_NUM_BYTES lands INSIDE its own element (count=$n)"
    chk "$v3 >= 0" "$ifn : TDATA_NUM_BYTES = 3"
    chk "$nb == 1" "$ifn : exactly one <spirit:parameters> block"
}
set fr [regexp -- {BUSIFPARAM_VALUE\.ACLK\.FREQ_HZ">100000000<} $txt]
chk "$fr == 1" "aclk : FREQ_HZ = 100000000"

puts ""
puts "=========== T2 : idempotent re-injection ==========="
set added 0
foreach ifn [concat $axis_ifaces aclk] {
    if {$ifn eq "aclk"} {
        set r [xmlp_add_busif_params $good aclk [xmlp_clk_param_pairs aclk $axis_ifaces]]
    } else {
        set r [xmlp_add_busif_params $good $ifn [xmlp_axis_param_pairs $ifn 3]]
    }
    incr added [lindex $r 0]
}
chk "$added == 0" "second run adds nothing (added=$added)"
set probs [xmlp_check_file $good [concat $axis_ifaces aclk]]
chk "[llength $probs] == 0" "gates still pass after second run"

puts ""
puts "=========== T3 : reproduce the OLD regex bug ==========="
set t  [xmlp_read_file $good]
set old [file join $work component_oldregex.xml]
xmlp_write_file $old $t
# 旧实现：单个跨标签懒匹配正则
proc old_inject {path ifname block} {
    set tt [xmlp_read_file $path]
    set pat "(<spirit:busInterface>\\s*<spirit:name>$ifname</spirit:name>.*?)(</spirit:busInterface>)"
    set tt2 [regsub -all $pat $tt "\\1$block\\2"]
    xmlp_write_file $path $tt2
}
old_inject $old m_axis [xmlp_param_block M_AXIS TDATA_NUM_BYTES 3]
set tt [xmlp_read_file $old]
set span [xmlp_find_busif_span $tt m_axis]
set m_inside 0
set nblk 0
if {[llength $span] > 0} {
    lassign $span s e
    set elem [string range $tt $s [expr {$e + [string length $::XMLP_BAXI_CLOSE] - 1}]]
    set m_inside [regexp -- {BUSIFPARAM_VALUE\.M_AXIS\.TDATA_NUM_BYTES} $elem]
    foreach ifn [concat $axis_ifaces aclk] {
        set nb [xmlp_busif_param_blocks $tt $ifn]
        if {$nb > 1} { incr nblk }
    }
}
set oldprobs [xmlp_check_file $old [concat $axis_ifaces aclk]]
puts "  old-regex file: param_inside_m_axis=$m_inside overfull_interfaces=$nblk problems=$oldprobs"
chk "[llength $oldprobs] > 0" "old regex output is rejected by the gates"

puts ""
puts "=========== T4 : real broken file on disk must be rejected ==========="
set real D:/adas_pl/src/ip/ip_repo/axis_stage_bypass_1_0/component.xml
if {[file exists $real]} {
    set probs [xmlp_check_file $real [concat $axis_ifaces aclk]]
    puts "  real file gate output: $probs"
    chk "[llength $probs] > 0" "gates catch the shipped (broken) component.xml"
} else {
    puts "  (real file not present, skipped)"
}

puts ""
puts "=============================================================="
puts "  TEST RESULT: PASS=$pass  FAIL=$fail"
puts "=============================================================="
file delete -force $work
exit [expr {$fail == 0 ? 0 : 1}]
