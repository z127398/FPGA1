`timescale 1ns / 1ps
// ============================================================================
//  tb_adas_decision -- adas_decision 决策 FSM / 看门狗 / 键盘 功能验证
// ----------------------------------------------------------------------------
//  把 TICK_DIV 置 1，于是"1 个时钟 = 1ms"，仿真可在微秒级跑完所有时序行为。
//  验证项：
//    T0 复位状态
//    T1 绿灯直行        -> LED1，静音
//    T2 红灯未强制      -> LED 全灭 + 短鸣一次后停
//    T3 红灯 + 强制     -> 持续报警 + 三灯 2Hz 闪，alarm_reason=1
//    T4 实线 + 转向指令 -> 报警 alarm_reason=2
//    T5 障碍物          -> 短鸣 + alarm_reason=3
//    T6 按键轮转车道    -> 直 -> 右 -> 左 -> 直，LED 跟随
//    T7 看门狗          -> 停心跳后超时进安全态（LED 交替闪），恢复心跳后退出
// ============================================================================
module tb_adas_decision;

    reg aclk = 1'b0;
    reg aresetn = 1'b0;
    always #5 aclk = ~aclk;

    integer errors = 0;
    integer k;

    reg [1:0] tl_state  = 2'd0;
    reg [1:0] lane_left = 2'd0;
    reg [1:0] lane_right= 2'd0;
    reg [1:0] turn_ps   = 2'd0;
    reg       obstacle  = 1'b0;
    reg       force_ps  = 1'b0;
    reg       heartbeat = 1'b0;
    // 板载按键未按下为高电平、按下为低电平，这里按真实电平驱动
    reg [1:0] btn       = 2'b11;

    wire [2:0] led;
    wire       beep;
    wire [1:0] alarm_reason;
    wire       wd_timeout;

    adas_decision #(
        .TICK_DIV   (1),
        .WD_MS      (500),
        .BEEP_MS    (200),
        .BLINK_MS   (250),
        .WD_BEEP_MS (500),
        .DB_MS      (20)
    ) dut (
        .aclk(aclk), .aresetn(aresetn),
        .tl_state(tl_state), .lane_left(lane_left), .lane_right(lane_right),
        .obstacle(obstacle), .force_ps(force_ps), .turn_ps(turn_ps),
        .heartbeat(heartbeat), .btn(btn),
        .led(led), .beep(beep), .alarm_reason(alarm_reason), .wd_timeout(wd_timeout)
    );

    // ---------------- 心跳源：默认持续翻转，可关闭以测看门狗 ----------------
    reg     hb_en  = 1'b1;
    integer hb_cnt = 0;
    always @(posedge aclk) begin
        if (!aresetn) begin
            hb_cnt    <= 0;
            heartbeat <= 1'b0;
        end else if (hb_en) begin
            if (hb_cnt >= 100) begin
                hb_cnt    <= 0;
                heartbeat <= ~heartbeat;
            end else begin
                hb_cnt <= hb_cnt + 1;
            end
        end
    end

    // ---------------- 按键：按下（拉低）40ms，松开（拉高）30ms ----------------
    task press_btn(input integer idx);
        begin
            @(negedge aclk);
            btn[idx] = 1'b0;            // 按下 = 低电平
            repeat (40) @(posedge aclk);
            @(negedge aclk);
            btn[idx] = 1'b1;            // 松开 = 高电平
            // 松开窗口必须长于 DB_MS，否则消抖还没认出"已松开"，
            // 下一次按下就不会产生新的上升沿（这不是 RTL 的问题）。
            repeat (30) @(posedge aclk);
        end
    endtask

    // ---------------- 主激励 ----------------
    initial begin
        aresetn = 1'b0;
        repeat (20) @(posedge aclk);
        aresetn = 1'b1;
        repeat (20) @(posedge aclk);

        // ---- T0 复位状态 ----
        if (led !== 3'b000 || beep !== 1'b0 || wd_timeout !== 1'b0) begin
            $display("[FAIL] T0 复位状态 led=%b beep=%b wd=%b", led, beep, wd_timeout);
            errors = errors + 1;
        end else $display("[ OK ] T0 复位状态");

        // ---- T1 绿灯 + 直行 ----
        tl_state = 2'd2; lane_left = 2'd0; lane_right = 2'd0;
        force_ps = 1'b0; turn_ps = 2'd0; obstacle = 1'b0;
        repeat (50) @(posedge aclk);
        if (led !== 3'b010 || beep !== 1'b0) begin
            $display("[FAIL] T1 绿灯直行 led=%b beep=%b", led, beep);
            errors = errors + 1;
        end else $display("[ OK ] T1 绿灯直行 -> LED1 静音");

        // ---- T2 红灯未强制 -> 停车 + 短鸣一次 ----
        tl_state = 2'd1;
        repeat (30) @(posedge aclk);
        if (led !== 3'b000) begin
            $display("[FAIL] T2 红灯停车 LED 未灭 led=%b", led);
            errors = errors + 1;
        end else $display("[ OK ] T2 红灯停车 LED 全灭");
        if (beep !== 1'b1) begin
            $display("[FAIL] T2 短鸣未触发");
            errors = errors + 1;
        end else $display("[ OK ] T2 红灯短鸣触发");
        repeat (400) @(posedge aclk);
        if (beep !== 1'b0) begin
            $display("[FAIL] T2 短鸣未按时停止 beep=%b", beep);
            errors = errors + 1;
        end else $display("[ OK ] T2 短鸣按时停止（条件持续不重复响）");

        // ---- T3 红灯 + 强制 -> 持续报警 + 闪烁 ----
        force_ps = 1'b1;
        repeat (30) @(posedge aclk);
        if (beep !== 1'b1) begin
            $display("[FAIL] T3 强制红灯未持续报警");
            errors = errors + 1;
        end else $display("[ OK ] T3 强制红灯持续报警");
        if (alarm_reason !== 2'd1) begin
            $display("[FAIL] T3 报警原因=%0d 期望 1", alarm_reason);
            errors = errors + 1;
        end else $display("[ OK ] T3 报警原因=1");
        begin : t3_blink
            reg [2:0] led0; integer nv;
            led0 = led; nv = 0;
            for (k = 0; k < 600; k = k + 1) begin
                @(posedge aclk);
                if (led !== led0) nv = nv + 1;
            end
            if (nv < 2) begin
                $display("[FAIL] T3 LED 未闪烁 nv=%0d", nv);
                errors = errors + 1;
            end else $display("[ OK ] T3 LED 2Hz 闪烁");
        end
        force_ps = 1'b0;

        // ---- T4 实线 + 转向指令 -> 报警原因 2 ----
        tl_state = 2'd2; lane_left = 2'd1; turn_ps = 2'd1;
        repeat (30) @(posedge aclk);
        if (alarm_reason !== 2'd2 || beep !== 1'b1) begin
            $display("[FAIL] T4 实线强制变道 reason=%0d beep=%b", alarm_reason, beep);
            errors = errors + 1;
        end else $display("[ OK ] T4 实线强制变道报警");
        lane_left = 2'd0; turn_ps = 2'd0;
        repeat (400) @(posedge aclk);

        // ---- T5 障碍物 -> 短鸣 + 原因 3 ----
        tl_state = 2'd2; obstacle = 1'b1;
        repeat (30) @(posedge aclk);
        if (alarm_reason !== 2'd3) begin
            $display("[FAIL] T5 障碍物 reason=%0d", alarm_reason);
            errors = errors + 1;
        end else $display("[ OK ] T5 障碍物报警原因=3");
        obstacle = 1'b0;
        repeat (400) @(posedge aclk);

        // ---- T8 组合冲突优先级：红灯强制 + 实线转向 同时成立 ----
        // 红force 的优先级应高于 solid_force，报警原因必须是 1 而不是 2
        tl_state = 2'd1; force_ps = 1'b1; lane_left = 2'd1; turn_ps = 2'd1;
        repeat (30) @(posedge aclk);
        if (alarm_reason !== 2'd1) begin
            $display("[FAIL] T8 组合冲突优先级错误 reason=%0d 期望 1", alarm_reason);
            errors = errors + 1;
        end else $display("[ OK ] T8 组合冲突：红灯强制优先于实线变道");
        force_ps = 1'b0; lane_left = 2'd0; turn_ps = 2'd0; tl_state = 2'd2;
        repeat (400) @(posedge aclk);

        // ---- T6 按键轮转车道：直 -> 右 -> 左 -> 直 ----
        tl_state = 2'd2;
        press_btn(0);
        repeat (5) @(posedge aclk);
        if (led !== 3'b100) begin
            $display("[FAIL] T6 未切到右转 led=%b", led);
            errors = errors + 1;
        end else $display("[ OK ] T6 按键切右转 LED2");
        press_btn(0);
        repeat (5) @(posedge aclk);
        if (led !== 3'b001) begin
            $display("[FAIL] T6 未切到左转 led=%b", led);
            errors = errors + 1;
        end else $display("[ OK ] T6 按键切左转 LED0");
        press_btn(0);
        repeat (5) @(posedge aclk);
        if (led !== 3'b010) begin
            $display("[FAIL] T6 未切回直行 led=%b", led);
            errors = errors + 1;
        end else $display("[ OK ] T6 按键切回直行 LED1");

        // ---- T7 看门狗：停心跳 -> 超时安全态 -> 恢复心跳退出 ----
        hb_en = 1'b0;
        repeat (600) @(posedge aclk);
        if (wd_timeout !== 1'b1) begin
            $display("[FAIL] T7 看门狗未超时");
            errors = errors + 1;
        end else $display("[ OK ] T7 看门狗超时置位");
        begin : t7_blink
            reg [2:0] led1; integer nv2;
            led1 = led; nv2 = 0;
            for (k = 0; k < 600; k = k + 1) begin
                @(posedge aclk);
                if (led !== led1) nv2 = nv2 + 1;
            end
            if (nv2 < 2) begin
                $display("[FAIL] T7 安全态 LED 未交替闪 nv=%0d", nv2);
                errors = errors + 1;
            end else $display("[ OK ] T7 安全态 LED 交替闪");
        end
        hb_en = 1'b1;
        repeat (150) @(posedge aclk);
        if (wd_timeout !== 1'b0) begin
            $display("[FAIL] T7 心跳恢复后未退出安全态");
            errors = errors + 1;
        end else $display("[ OK ] T7 心跳恢复退出安全态");

        repeat (20) @(posedge aclk);
        if (errors == 0) $display("TB_RESULT: PASS");
        else             $display("TB_RESULT: FAIL (%0d errors)", errors);
        $finish;
    end

endmodule
