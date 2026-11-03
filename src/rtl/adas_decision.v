`timescale 1ns / 1ps
// ============================================================================
//  adas_decision -- ADAS 决策 FSM + 看门狗 + 板级输出
// ----------------------------------------------------------------------------
//  软硬分工：
//    PS 负责感知（红绿灯 / 车道线 / 行人障碍），结果写进本模块的输入寄存器；
//    PL 负责决策与执行，直接驱动 LED0/1/2 与蜂鸣器。决策延迟固定，不随 PS 负载
//    波动；PS 与 PL 之间只有每帧一次的寄存器写入，无逐像素交互。
//
//  看门狗：PS 每帧翻转 heartbeat。若超时未翻转（PS 卡死 / Jupyter 挂起 /
//   网线掉了），本模块进入安全态（蜂鸣器 1Hz 间断响 + LED 交替闪），
//   并把 wd_timeout 置位供 PS 回读。这是"感知可以软、执行必须硬"的落点。
//
//  决策优先级（高到低）：
//    WD 安全态 > 红灯强制行驶报警 > 实线强制变道报警 > 红灯停车
//    > 正常行驶（LED 按转向指令点亮）
//  蜂鸣器与 LED 分立：报警为持续响，停车/障碍物/黄灯为单次短鸣。
// ============================================================================
module adas_decision #(
    parameter integer TICK_DIV   = 100000,   // 每个 ms 的时钟数：100MHz -> 100000
    parameter integer WD_MS      = 500,      // 心跳超时门限
    parameter integer BEEP_MS    = 200,      // 单次短鸣时长
    parameter integer BLINK_MS   = 250,      // 报警闪烁半周期（2Hz）
    parameter integer WD_BEEP_MS = 500,      // 安全态蜂鸣器半周期（1Hz）
    parameter integer DB_MS      = 20        // 按键消抖
)(
    input  wire        aclk,
    input  wire        aresetn,

    // ---- 来自 PS 的感知结果（AXI GPIO 输出）----
    input  wire [1:0]  tl_state,      // 0 无 / 1 红 / 2 绿 / 3 黄
    input  wire [1:0]  lane_left,     // 0 无 / 1 实线 / 2 虚线
    input  wire [1:0]  lane_right,
    input  wire        obstacle,      // 行人或障碍物
    input  wire        force_ps,      // PS 侧强制指令
    input  wire [1:0]  turn_ps,       // 0 无 / 1 左 / 2 右
    input  wire        heartbeat,     // PS 每帧翻转

    // ---- 板载按键（PL 直连，不经 PS）----
    input  wire [1:0]  btn,           // btn0 车道切换, btn1 强制指令

    // ---- 板级输出 ----
    output reg  [2:0]  led,           // [0] 左转 [1] 直行 [2] 右转
    output reg         beep,
    output reg  [1:0]  alarm_reason,  // 0 无 / 1 红灯强制行驶 / 2 实线强制变道 / 3 障碍物
    output reg         wd_timeout
);

    // ---------------- 编码常量 ----------------
    localparam [1:0] TL_NONE = 2'd0, TL_RED = 2'd1, TL_GREEN = 2'd2, TL_YEL = 2'd3;
    localparam [1:0] LN_NONE = 2'd0, LN_SOLID = 2'd1, LN_DASH = 2'd2;
    localparam [1:0] TP_NONE = 2'd0, TP_LEFT = 2'd1, TP_RIGHT = 2'd2;
    localparam [1:0] LN_POS_L = 2'd0, LN_POS_S = 2'd1, LN_POS_R = 2'd2;

    // ---------------- 1ms 节拍 ----------------
    reg [31:0] tick_cnt;
    reg        tick;
    always @(posedge aclk) begin
        if (!aresetn) begin
            tick_cnt <= 32'd0;
            tick     <= 1'b0;
        end else if (tick_cnt >= TICK_DIV - 1) begin
            tick_cnt <= 32'd0;
            tick     <= 1'b1;
        end else begin
            tick_cnt <= tick_cnt + 32'd1;
            tick     <= 1'b0;
        end
    end

    // ---------------- 按键同步 / 消抖 / 上升沿 ----------------
    reg [1:0] btn_sync, btn_stable;
    reg [7:0] db_cnt0, db_cnt1;
    reg       btn0_d, btn1_d;
    reg       btn0_rise, btn1_rise;
    always @(posedge aclk) begin
        if (!aresetn) begin
            btn_sync    <= 2'b00;
            btn_stable  <= 2'b00;
            db_cnt0     <= 8'd0;
            db_cnt1     <= 8'd0;
            btn0_d      <= 1'b0;
            btn1_d      <= 1'b0;
            btn0_rise   <= 1'b0;
            btn1_rise   <= 1'b0;
        end else begin
            // 板载 PL_KEY 未按下时为高电平、按下为低电平（正点原子 PYNQ 指南：
            // "领航者开发板上的按键默认为高电平"，按下后读到 0）。
            // 这里统一反相成"按下 = btn_sync=1"，后续消抖/边沿逻辑全部沿用"1 = 按下"。
            btn_sync  <= ~btn;
            btn0_rise <= 1'b0;
            btn1_rise <= 1'b0;
            if (tick) begin
                // -- btn0 --
                if (btn_sync[0] != btn_stable[0]) begin
                    if (db_cnt0 >= DB_MS) begin
                        btn_stable[0] <= btn_sync[0];
                        db_cnt0       <= 8'd0;
                    end else begin
                        db_cnt0 <= db_cnt0 + 8'd1;
                    end
                end else begin
                    db_cnt0 <= 8'd0;
                end
                // -- btn1 --
                if (btn_sync[1] != btn_stable[1]) begin
                    if (db_cnt1 >= DB_MS) begin
                        btn_stable[1] <= btn_sync[1];
                        db_cnt1       <= 8'd0;
                    end else begin
                        db_cnt1 <= db_cnt1 + 8'd1;
                    end
                end else begin
                    db_cnt1 <= 8'd0;
                end
                // -- 上升沿 --
                if (btn_stable[0] && !btn0_d) btn0_rise <= 1'b1;
                if (btn_stable[1] && !btn1_d) btn1_rise <= 1'b1;
                btn0_d <= btn_stable[0];
                btn1_d <= btn_stable[1];
            end
        end
    end

    // ---------------- 车道位置轮转（按键切换左/直/右）----------------
    reg [1:0] lane_sel;
    always @(posedge aclk) begin
        if (!aresetn) begin
            lane_sel <= LN_POS_S;                 // 上电默认直行
        end else if (btn0_rise) begin
            if (lane_sel == LN_POS_R) lane_sel <= LN_POS_L;
            else                      lane_sel <= lane_sel + 2'd1;
        end
    end

    // ---------------- 看门狗 ----------------
    reg [1:0]  hb_sync;
    reg        hb_d;
    reg [31:0] wd_cnt;
    always @(posedge aclk) begin
        if (!aresetn) begin
            hb_sync    <= 2'b00;
            hb_d       <= 1'b0;
            wd_cnt     <= 32'd0;
            wd_timeout <= 1'b0;
        end else begin
            hb_sync <= {hb_sync[0], heartbeat};
            if (hb_sync[1] != hb_d) begin          // PS 心跳翻转 -> 喂狗
                hb_d       <= hb_sync[1];
                wd_cnt     <= 32'd0;
                wd_timeout <= 1'b0;
            end else if (tick) begin
                if (wd_cnt >= WD_MS) wd_timeout <= 1'b1;
                else                 wd_cnt     <= wd_cnt + 32'd1;
            end
        end
    end

    // ---------------- 转向与强制指令 ----------------
    wire       force_now = btn_stable[1] | force_ps;
    reg  [1:0] turn_now;
    always @(*) begin
        if      (turn_ps == TP_LEFT)  turn_now = LN_POS_L;
        else if (turn_ps == TP_RIGHT) turn_now = LN_POS_R;
        else                           turn_now = lane_sel;
    end

    // ---------------- 报警与停车判定 ----------------
    wire solid_line  = (lane_left == LN_SOLID) | (lane_right == LN_SOLID);
    wire stop_req    = (tl_state == TL_RED) & ~force_now;
    wire red_force   = (tl_state == TL_RED) &  force_now;
    wire solid_force = solid_line & (turn_now != LN_POS_S);
    wire alarm_cont  = red_force | solid_force;

    // ---------------- 闪烁 / 单次短鸣 / 安全态间歇响 ----------------
    reg [31:0] blink_cnt;
    reg        blink;
    always @(posedge aclk) begin
        if (!aresetn) begin
            blink_cnt <= 32'd0;
            blink     <= 1'b0;
        end else if (tick) begin
            if (blink_cnt >= BLINK_MS) begin
                blink_cnt <= 32'd0;
                blink     <= ~blink;
            end else begin
                blink_cnt <= blink_cnt + 32'd1;
            end
        end
    end

    reg [31:0] wdb_cnt;
    reg        wd_beep;
    always @(posedge aclk) begin
        if (!aresetn) begin
            wdb_cnt <= 32'd0;
            wd_beep <= 1'b0;
        end else if (tick) begin
            if (wdb_cnt >= WD_BEEP_MS) begin
                wdb_cnt <= 32'd0;
                wd_beep <= ~wd_beep;
            end else begin
                wdb_cnt <= wdb_cnt + 32'd1;
            end
        end
    end

    // 单次短鸣：触发条件上升沿响一次，条件持续不会重复响
    wire trig = ~wd_timeout & ~alarm_cont &
                (stop_req | obstacle | (tl_state == TL_YEL));
    reg        trig_d;
    reg [31:0] beep_hold;
    always @(posedge aclk) begin
        if (!aresetn) begin
            trig_d    <= 1'b0;
            beep_hold <= 32'd0;
        end else begin
            trig_d <= trig;
            if (trig & ~trig_d)                     beep_hold <= BEEP_MS;
            else if (beep_hold != 32'd0 && tick)    beep_hold <= beep_hold - 32'd1;
        end
    end
    wire beep_once = (beep_hold != 32'd0);

    // ---------------- 正常行驶时的 LED ----------------
    reg [2:0] led_normal;
    always @(*) begin
        case (turn_now)
            LN_POS_L: led_normal = 3'b001;   // LED0 左转
            LN_POS_R: led_normal = 3'b100;   // LED2 右转
            default:  led_normal = 3'b010;   // LED1 直行
        endcase
    end

    // ---------------- 输出寄存器 ----------------
    always @(posedge aclk) begin
        if (!aresetn) begin
            led          <= 3'b000;
            beep         <= 1'b0;
            alarm_reason <= 2'd0;
        end else if (wd_timeout) begin
            // 安全态：LED 交替闪 + 蜂鸣器 1Hz 间断响
            led          <= blink ? 3'b101 : 3'b010;
            beep         <= wd_beep;
            alarm_reason <= 2'd0;
        end else if (alarm_cont) begin
            // 报警：三灯 2Hz 同闪 + 持续响
            led          <= blink ? 3'b111 : 3'b000;
            beep         <= 1'b1;
            alarm_reason <= red_force ? 2'd1 : 2'd2;
        end else if (stop_req) begin
            // 红灯停车：LED 全灭 + 短鸣一次
            led          <= 3'b000;
            beep         <= beep_once;
            alarm_reason <= 2'd0;
        end else if (tl_state == TL_NONE) begin
            // 尚未收到感知结果（上电初期 / PS 未写入）：一律不指示可行驶，
            // 这是安全默认——不知道路况就不该点亮"可以走"的指示灯。
            led          <= 3'b000;
            beep         <= beep_once;
            alarm_reason <= obstacle ? 2'd3 : 2'd0;
        end else begin
            // 正常行驶 / 障碍物短鸣 / 黄灯提示
            led          <= led_normal;
            beep         <= beep_once;
            alarm_reason <= obstacle ? 2'd3 : 2'd0;
        end
    end

endmodule
