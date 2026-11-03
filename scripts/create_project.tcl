set proj_name   "adas_pl"
set part        "xc7z010clg400-1"
set top_module  "top"

set script_dir  [file normalize [file dirname [info script]]]
set root_dir    [file normalize [file join $script_dir ..]]
set build_dir   [file join $root_dir build]
set rtl_dir     [file join $root_dir src rtl]
set xdc_dir     [file join $root_dir src xdc]

file mkdir $build_dir

create_project $proj_name $build_dir/$proj_name -part $part -force

set_property target_language Verilog [current_project]

set rtl_files [glob -nocomplain -directory $rtl_dir *.v]
if {[llength $rtl_files] > 0} {
    add_files -norecurse -fileset sources_1 $rtl_files
}

set xdc_files [glob -nocomplain -directory $xdc_dir *.xdc]
if {[llength $xdc_files] > 0} {
    add_files -norecurse -fileset constrs_1 $xdc_files
}

set_property top $top_module [current_fileset]
update_compile_order -fileset sources_1

puts "工程创建完成: $build_dir/$proj_name"
