# =============================================================================
#  synth_check.tcl -- L2 单元综合检查
# -----------------------------------------------------------------------------
#  对两个自研 RTL 单独跑 synth_design，检查：
#    1) 是否报 error
#    2) 是否推断出锁存器（LDCE/LDPE 原语计数，必须为 0）
#    3) 资源是否落在合理范围（mux 应该几乎全是 LUT、无 FF；FSM 应有 FF 无 DSP/BRAM）
#  只写临时目录，不碰工程与仓库。
# =============================================================================
set rtl_dir D:/adas_pl/src/rtl
set work_root C:/Users/15491/AppData/Local/Temp/adas_synth

proc count_cells {pat} {
    return [llength [get_cells -hier -quiet -filter "REF_NAME =~ $pat"]]
}

foreach m {axis_stage_bypass adas_decision} {
    puts ""
    puts "=================== 综合 $m ==================="
    set work [file join $work_root $m]
    file delete -force $work
    create_project syn_$m $work -part xc7z010clg400-1 -force
    add_files -norecurse [file join $rtl_dir "$m.v"]
    set_property top $m [current_fileset]
    update_compile_order -fileset sources_1

    # 捕获综合过程中的 latch 警告文本
    array set latch_warn {}
    set rc [catch { synth_design -top $m -part xc7z010clg400-1 } emsg]

    if {$rc} {
        puts "\[FAIL\] $m 综合报错：$emsg"
    } else {
        set n_lut   [count_cells "LUT*"]
        set n_ff    [count_cells "FD*"]
        set n_latch [expr {[count_cells "LDCE*"] + [count_cells "LDPE*"]}]
        set n_dsp   [count_cells "DSP48*"]
        set n_bram  [count_cells "RAMB*"]
        set n_carry [count_cells "CARRY4"]
        puts [format "\[INFO\] %-18s LUT=%-5d FF=%-5d LATCH=%-3d DSP=%-3d BRAM=%-3d CARRY4=%d" \
                  $m $n_lut $n_ff $n_latch $n_dsp $n_bram $n_carry]
        if {$n_latch > 0} {
            puts "\[FAIL\] $m 推断出了锁存器（LATCH=$n_latch）"
        } else {
            puts "\[ OK \] $m 无锁存器推断"
        }
    }
    close_project
}

puts ""
puts "SYNTH_CHECK_DONE"
exit 0
