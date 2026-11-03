# =============================================================================
#  xml_param_inject.tcl -- IP-XACT (component.xml) 参数注入工具，纯 Tcl
# -----------------------------------------------------------------------------
#  为什么单独成文件：这里全是字符串 / XML 处理，不需要 Vivado 就能用 tclsh
#  离线单测（见 sim/test_xml_param_inject.tcl），打包脚本 source 本文件。
#
#  为什么必须自己做字符串手术：
#    ipx::package_project 不会给 AXIS 接口写 TDATA_NUM_BYTES 等参数，缺了它
#    BD 里的层次引脚会退回默认 1 字节（Stage 2 踩过的大坑：24 位视频只连出
#    第 0 位，综合把整条通路当死逻辑删掉）。而注入时不能用"跨标签懒匹配"
#    的正则：Tcl 的 ARE 引擎对整体匹配采用 leftmost-longest，`.*?</spirit:
#    busInterface>` 会一路吃到文档里最后一个闭合标签，结果是五个参数块全塞
#    进 aclk 一个接口，component.xml 变成 schema 非法，Vivado 直接把 IP 踢出
#    catalog（CRITICAL WARNING IP_Flow 19-1977 "Unable to read IP file"）。
#    这里改用 string first / string range 精确定位元素边界，并在写回后做三道
#    门禁：标签配对、每个 busInterface 的 <spirit:parameters> 至多一个、
#    BUSIFPARAM_VALUE id 不重复。
# =============================================================================

set ::XMLP_BAXI_OPEN   "<spirit:busInterface>"
set ::XMLP_BAXI_CLOSE  "</spirit:busInterface>"
set ::XMLP_PARAM_OPEN  "<spirit:parameters>"
set ::XMLP_PARAM_CLOSE "</spirit:parameters>"

# -----------------------------------------------------------------------------
#  文件读写：显式 UTF-8 + binary translation，避免 Windows 下 \n <-> \r\n
#  自动转换把整个 component.xml 改花。
# -----------------------------------------------------------------------------
proc xmlp_read_file {path} {
    set fh [open $path r]
    fconfigure $fh -encoding utf-8 -translation binary
    set t [read $fh]
    close $fh
    return $t
}

proc xmlp_write_file {path text} {
    set fh [open $path w]
    fconfigure $fh -encoding utf-8 -translation binary
    puts -nonewline $fh $text
    close $fh
}

# -----------------------------------------------------------------------------
#  门禁 1：标签配对检查（不依赖任何 XML 库）
#  返回 "" 表示通过，否则返回描述问题的字符串。
# -----------------------------------------------------------------------------
proc xmlp_wellformed {text} {
    set stack {}
    set i 0
    set n [string length $text]
    while {$i < $n} {
        set lt [string first "<" $text $i]
        if {$lt < 0} { break }
        if {[string range $text $lt [expr {$lt + 3}]] eq "<!--"} {
            set ce [string first "-->" $text $lt]
            if {$ce < 0} { return "unterminated comment at offset $lt" }
            set i [expr {$ce + 3}]
            continue
        }
        if {[string range $text $lt [expr {$lt + 1}]] eq "<?"} {
            set ce [string first "?>" $text $lt]
            if {$ce < 0} { return "unterminated processing instruction at offset $lt" }
            set i [expr {$ce + 2}]
            continue
        }
        set gt [string first ">" $text $lt]
        if {$gt < 0} { return "unterminated tag at offset $lt" }
        set tag [string trim [string range $text [expr {$lt + 1}] [expr {$gt - 1}]]]
        set i [expr {$gt + 1}]
        if {$tag eq ""} { continue }
        if {[string index $tag 0] eq "/"} {
            set nm [string trim [string range $tag 1 end]]
            if {[llength $stack] == 0} { return "unexpected closing tag </$nm> at offset $lt" }
            set top [lindex $stack end]
            if {$top ne $nm} { return "mismatched tag: expected </$top> but found </$nm> at offset $lt" }
            set stack [lrange $stack 0 end-1]
        } elseif {[string index $tag end] eq "/"} {
            continue
        } else {
            set nm [lindex [split $tag " \t\n\r"] 0]
            lappend stack $nm
        }
    }
    if {[llength $stack] > 0} { return "unclosed element(s): $stack" }
    return ""
}

# -----------------------------------------------------------------------------
#  定位某个 busInterface 元素的边界（返回 {起始索引 闭合标签起始索引}）
#  用 string first 逐段扫描，绝不跨元素匹配。
# -----------------------------------------------------------------------------
proc xmlp_find_busif_span {text ifname} {
    set pos 0
    set open  $::XMLP_BAXI_OPEN
    set close $::XMLP_BAXI_CLOSE
    while {1} {
        set s [string first $open $text $pos]
        if {$s < 0} { return {} }
        set e [string first $close $text $s]
        if {$e < 0} { return {} }
        set elem [string range $text $s [expr {$e + [string length $close] - 1}]]
        if {[string first "<spirit:name>$ifname</spirit:name>" $elem] >= 0} {
            return [list $s $e]
        }
        set pos [expr {$e + 1}]
    }
}

# -----------------------------------------------------------------------------
#  单个 <spirit:parameter> 片段（与 Xilinx 生成格式一致：8 空格缩进）
# -----------------------------------------------------------------------------
proc xmlp_param_block {u pn pv} {
    return "        <spirit:parameter>\n          <spirit:name>$pn</spirit:name>\n          <spirit:value spirit:id=\"BUSIFPARAM_VALUE.$u.$pn\">$pv</spirit:value>\n        </spirit:parameter>\n"
}

# AXIS 接口要注入的参数（IFNAME 大写作为 id 前缀）
proc xmlp_axis_param_pairs {ifname bytes} {
    set u [string toupper $ifname]
    set pairs {}
    foreach pn {TDATA_NUM_BYTES TUSER_WIDTH HAS_TKEEP HAS_TLAST HAS_TREADY} {
        set pv 1
        if {$pn eq "TDATA_NUM_BYTES"} { set pv $bytes }
        lappend pairs [list $pn [xmlp_param_block $u $pn $pv]]
    }
    return $pairs
}

# 时钟接口要注入的参数。ASSOCIATED_BUSIF 只在非空时注入——ipx 推理阶段
# 往往已经写过一份，此时由 inject 的"已存在即跳过"逻辑保留原值。
proc xmlp_clk_param_pairs {clkname axislist} {
    set u [string toupper $clkname]
    set pairs {}
    if {[llength $axislist] > 0} {
        lappend pairs [list ASSOCIATED_BUSIF \
            [xmlp_param_block $u ASSOCIATED_BUSIF [join $axislist ":"]]]
    }
    lappend pairs [list FREQ_HZ [xmlp_param_block $u FREQ_HZ 100000000]]
    return $pairs
}

# -----------------------------------------------------------------------------
#  核心：把参数注入到指定 busInterface 内
#  返回 {新增数 跳过数}
#  规则：
#    * 元素内已有 <spirit:parameters>  -> 插入其中（绝不产生第二个）
#    * 没有                              -> 在闭合标签前新建一个
#    * 同名参数已存在                    -> 跳过（保留原值）
# -----------------------------------------------------------------------------
proc xmlp_add_busif_params {path ifname pairs} {
    set t [xmlp_read_file $path]
    set span [xmlp_find_busif_span $t $ifname]
    if {[llength $span] == 0} { error "bus interface '$ifname' not found in $path" }
    lassign $span s e

    set elem [string range $t $s [expr {$e + [string length $::XMLP_BAXI_CLOSE] - 1}]]

    set add ""
    set added 0
    set skipped 0
    foreach pair $pairs {
        lassign $pair pn blk
        if {[string first "<spirit:name>$pn</spirit:name>" $elem] >= 0} {
            incr skipped
            continue
        }
        append add $blk
        incr added
    }
    if {$added == 0} { return [list $added $skipped] }

    set po [string first $::XMLP_PARAM_OPEN $t $s]
    if {$po >= 0 && $po < $e} {
        set pc [string first $::XMLP_PARAM_CLOSE $t $po]
        if {$pc < 0 || $pc > $e} {
            error "unbalanced <spirit:parameters> inside bus interface '$ifname'"
        }
        set t2 [string trimright [string range $t 0 [expr {$pc - 1}]]]
        append t2 "\n"
        append t2 $add
        append t2 "      "
        append t2 [string range $t $pc end]
    } else {
        set t2 [string trimright [string range $t 0 [expr {$e - 1}]]]
        append t2 "\n      <spirit:parameters>\n"
        append t2 $add
        append t2 "      </spirit:parameters>\n    "
        append t2 [string range $t $e end]
    }
    xmlp_write_file $path $t2
    return [list $added $skipped]
}

# -----------------------------------------------------------------------------
#  门禁 2：某接口内的 <spirit:parameters> 块数量（-1 表示找不到该接口）
# -----------------------------------------------------------------------------
proc xmlp_busif_param_blocks {text ifname} {
    set span [xmlp_find_busif_span $text $ifname]
    if {[llength $span] == 0} { return -1 }
    lassign $span s e
    set elem [string range $text $s [expr {$e + [string length $::XMLP_BAXI_CLOSE] - 1}]]
    return [regexp -all -- {<spirit:parameters>} $elem]
}

# -----------------------------------------------------------------------------
#  门禁 3：BUSIFPARAM_VALUE id 重复检查（返回重复 id 列表）
# -----------------------------------------------------------------------------
proc xmlp_duplicate_ids {text} {
    set ids {}
    foreach m [regexp -all -inline -- {BUSIFPARAM_VALUE\.[A-Za-z0-9_.]+} $text] {
        lappend ids $m
    }
    set dup {}
    foreach id [lsort -unique $ids] {
        if {[llength [lsearch -all -exact $ids $id]] > 1} { lappend dup $id }
    }
    return $dup
}

# -----------------------------------------------------------------------------
#  对一份 component.xml 跑全部门禁，返回问题列表（空列表 = 通过）
# -----------------------------------------------------------------------------
proc xmlp_check_file {path ifname_list} {
    set t [xmlp_read_file $path]
    set problems {}
    set wf [xmlp_wellformed $t]
    if {$wf ne ""} { lappend problems "xml not well-formed: $wf" }
    foreach ifn $ifname_list {
        set nb [xmlp_busif_param_blocks $t $ifn]
        if {$nb < 0} { lappend problems "interface '$ifn' not found" } \
        elseif {$nb > 1} { lappend problems "interface '$ifn' has $nb <spirit:parameters> blocks (max 1)" }
    }
    set dup [xmlp_duplicate_ids $t]
    if {[llength $dup] > 0} { lappend problems "duplicate bus parameter id(s): $dup" }
    return $problems
}
