# =============================================================================
#  adas_io.xdc -- ADAS 决策闭环的板级 IO 约束（LED / 蜂鸣器 / 按键）
# -----------------------------------------------------------------------------
#  引脚分配取自正点原子领航者 ZYNQ 底板原始约束文件，勿随意改动：
#    PL_LED0 = J16、PL_LED1 = H15、PL_LED2 = L15
#    蜂鸣器  = M14
#    PL_KEY0 = L14、PL_KEY1 = K16
#  本文件由 stage3 脚本加入工程；与 base.xdc（摄像头 + LCD）互不重叠。
# =============================================================================

# ---------------- LED：LED0 左转 / LED1 直行 / LED2 右转 ----------------
set_property -dict {PACKAGE_PIN J16 IOSTANDARD LVCMOS33} [get_ports {leds_tri_o[0]}]
set_property -dict {PACKAGE_PIN H15 IOSTANDARD LVCMOS33} [get_ports {leds_tri_o[1]}]
set_property -dict {PACKAGE_PIN L15 IOSTANDARD LVCMOS33} [get_ports {leds_tri_o[2]}]

# ---------------- 蜂鸣器：报警 ----------------
# 注意：若实测蜂鸣器逻辑反相（静音时反而响），把 adas_decision 的输出改成
# `beep <= ~beep;` 即可，不要改这里的约束。
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {beep_tri_o}]

# ---------------- 按键：KEY0 切换车道 / KEY1 强制指令 ----------------
set_property -dict {PACKAGE_PIN L14 IOSTANDARD LVCMOS33} [get_ports {btns_tri_i[0]}]
set_property -dict {PACKAGE_PIN K16 IOSTANDARD LVCMOS33} [get_ports {btns_tri_i[1]}]
