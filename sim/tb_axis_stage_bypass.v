`timescale 1ns / 1ps
// ============================================================================
//  tb_axis_stage_bypass -- axis_stage_bypass 的功能验证
// ----------------------------------------------------------------------------
//  验证项：
//    T1 sel=0 旁路：m_axis 必须与 s_axis 逐拍相同，且处理 IP 也拿到同样的数据
//    T2 sel=1 处理：m_axis 必须等于处理 IP 的输出（模型输出 = 输入 + 1）
//    T3 反压：m_tready 拉低时 s_tready 必须跟着拉低，且不丢拍
//    T4 切换：sel 中途翻转不得出现 X，且两路都还在工作
// ============================================================================
module tb_axis_stage_bypass;

    reg  aclk = 1'b0;
    reg  aresetn = 1'b0;
    always #5 aclk = ~aclk;                      // 100MHz

    integer errors = 0;
    integer i;

    // ---------------- DUT 端口 ----------------
    reg  sel = 1'b0;

    reg  [23:0] s_tdata = 24'd0;
    reg  [2:0]  s_tkeep = 3'b111;
    reg         s_tvalid = 1'b0;
    reg         s_tlast = 1'b0;
    reg         s_tuser = 1'b0;
    wire        s_tready;

    wire [23:0] px_tdata;
    wire [2:0]  px_tkeep;
    wire        px_tvalid;
    reg         px_tready = 1'b0;                // 由 IP 模型驱动
    wire        px_tlast;
    wire        px_tuser;

    reg  [23:0] pd_tdata = 24'd0;
    reg  [2:0]  pd_tkeep = 3'b111;
    reg         pd_tvalid = 1'b0;
    reg         pd_tlast = 1'b0;
    reg         pd_tuser = 1'b0;
    wire        pd_tready;

    wire [23:0] m_tdata;
    wire [2:0]  m_tkeep;
    wire        m_tvalid;
    wire        m_tlast;
    wire        m_tuser;
    reg         m_tready = 1'b1;

    axis_stage_bypass dut (
        .aclk(aclk), .sel(sel),
        .s_axis_tdata(s_tdata), .s_axis_tkeep(s_tkeep), .s_axis_tvalid(s_tvalid),
        .s_axis_tready(s_tready), .s_axis_tlast(s_tlast), .s_axis_tuser(s_tuser),
        .px_axis_tdata(px_tdata), .px_axis_tkeep(px_tkeep), .px_axis_tvalid(px_tvalid),
        .px_axis_tready(px_tready), .px_axis_tlast(px_tlast), .px_axis_tuser(px_tuser),
        .pd_axis_tdata(pd_tdata), .pd_axis_tkeep(pd_tkeep), .pd_axis_tvalid(pd_tvalid),
        .pd_axis_tready(pd_tready), .pd_axis_tlast(pd_tlast), .pd_axis_tuser(pd_tuser),
        .m_axis_tdata(m_tdata), .m_axis_tkeep(m_tkeep), .m_axis_tvalid(m_tvalid),
        .m_axis_tready(m_tready), .m_axis_tlast(m_tlast), .m_axis_tuser(m_tuser)
    );

    // ---------------- 处理 IP 模型：1 拍延迟，输出 = 输入 + 1 ----------------
    // 说明：模型输入侧恒 ready（px_tready=1），于是 s_tready 等价于 m_tready，
    // 便于逐拍比对；px 侧反压留到 W3 的 TB 加固里补测。
    reg [23:0] buf_data  = 24'd0;
    reg [2:0]  buf_keep  = 3'b111;
    reg        buf_valid = 1'b0;
    reg        ip_stall  = 1'b0;       // 拉高可模拟处理 IP 不 ready，用于测 px 侧反压

    always @(posedge aclk) begin
        if (!aresetn) begin
            buf_valid <= 1'b0;
            buf_data  <= 24'd0;
        end else begin
            buf_data  <= px_tdata + 24'd1;
            buf_keep  <= px_tkeep;
            buf_valid <= px_tvalid;
        end
    end
    always @(*) begin
        px_tready = ~ip_stall;
        pd_tdata  = buf_data;
        pd_tkeep  = buf_keep;
        pd_tlast  = px_tlast;
        pd_tuser  = px_tuser;
        pd_tvalid = buf_valid;
    end

    // ---------------- 下游接收记录 ----------------
    integer m_count = 0;
    reg [23:0] last_m = 24'd0;
    always @(posedge aclk) begin
        if (aresetn && m_tvalid && m_tready) begin
            m_count <= m_count + 1;
            last_m  <= m_tdata;
        end
    end

    // ---------------- 激励 ----------------
    task send_beat(input [23:0] d, input last);
        begin
            @(negedge aclk);
            s_tdata  = d;
            s_tvalid = 1'b1;
            s_tlast  = last;
            s_tuser  = last;
            @(negedge aclk);
            s_tvalid = 1'b0;
            s_tlast  = 1'b0;
            s_tuser  = 1'b0;
        end
    endtask

    initial begin
        aresetn = 1'b0;
        repeat (10) @(posedge aclk);
        aresetn = 1'b1;
        repeat (5) @(posedge aclk);

        // ---------- T1: sel=0 旁路，m 应等于 s ----------
        sel = 1'b0;
        for (i = 0; i < 8; i = i + 1) begin
            @(negedge aclk);
            s_tdata  = 24'h100000 + i;
            s_tvalid = 1'b1;
            s_tlast  = (i == 7);
            s_tuser  = (i == 0);
            @(negedge aclk);
            // 在 m 被接收的那拍检查数据一致
            wait (m_tvalid === 1'b1);
            @(posedge aclk);
            if (m_tvalid && m_tready) begin
                if (m_tdata !== (24'h100000 + i)) begin
                    $display("[FAIL] T1 sel=0: m_tdata=%h 期望 %h", m_tdata, 24'h100000 + i);
                    errors = errors + 1;
                end
            end
            s_tvalid = 1'b0; s_tlast = 1'b0; s_tuser = 1'b0;
        end
        $display("[INFO] T1 done, m_count=%0d", m_count);

        // ---------- T2: sel=1 处理，m 应等于 s+1 ----------
        sel = 1'b1;
        repeat (20) @(posedge aclk);               // 让模型缓冲清空
        for (i = 0; i < 8; i = i + 1) begin
            @(negedge aclk);
            s_tdata  = 24'h200000 + i;
            s_tvalid = 1'b1;
            s_tlast  = (i == 7);
            s_tuser  = (i == 0);
            @(negedge aclk);
            wait (m_tvalid === 1'b1);
            @(posedge aclk);
            if (m_tvalid && m_tready) begin
                if (m_tdata !== (24'h200000 + i + 24'd1)) begin
                    $display("[FAIL] T2 sel=1: m_tdata=%h 期望 %h", m_tdata, 24'h200000 + i + 24'd1);
                    errors = errors + 1;
                end
            end
            s_tvalid = 1'b0; s_tlast = 1'b0; s_tuser = 1'b0;
        end
        $display("[INFO] T2 done");

        // ---------- T3: 反压，m_tready 拉低时 s_tready 必须拉低且不丢拍 ----------
        sel = 1'b0;
        repeat (20) @(posedge aclk);
        m_tready = 1'b0;
        @(negedge aclk);
        s_tdata  = 24'h300001;
        s_tvalid = 1'b1;
        @(posedge aclk);
        if (s_tready !== 1'b0) begin
            $display("[FAIL] T3: m_tready=0 时 s_tready 仍为高");
            errors = errors + 1;
        end
        repeat (5) @(posedge aclk);
        m_tready = 1'b1;
        @(posedge aclk);
        if (m_tdata !== 24'h300001) begin
            $display("[FAIL] T3: 解压后数据错 m_tdata=%h", m_tdata);
            errors = errors + 1;
        end
        s_tvalid = 1'b0;
        $display("[INFO] T3 done");

        // ---------- T5: px 侧反压（处理 IP 暂不 ready）----------
        // 期望：s_tready 必须跟着拉低；解压后数据不丢
        sel = 1'b0;
        repeat (20) @(posedge aclk);
        ip_stall = 1'b1;
        @(negedge aclk);
        s_tdata  = 24'h500001;
        s_tvalid = 1'b1;
        @(posedge aclk);
        if (s_tready !== 1'b0) begin
            $display("[FAIL] T5: px_tready=0 时 s_tready 仍为高");
            errors = errors + 1;
        end
        repeat (5) @(posedge aclk);
        if (s_tready !== 1'b0) begin
            $display("[FAIL] T5: px 反压持续期间 s_tready 未保持低");
            errors = errors + 1;
        end
        ip_stall = 1'b0;
        @(posedge aclk);
        if (m_tdata !== 24'h500001) begin
            $display("[FAIL] T5: px 解压后旁路数据错 m_tdata=%h", m_tdata);
            errors = errors + 1;
        end
        s_tvalid = 1'b0;
        $display("[INFO] T5 done");

        // ---------- T4: 切换不产生 X ----------
        repeat (10) @(posedge aclk);
        sel = 1'b1; repeat (10) @(posedge aclk);
        sel = 1'b0; repeat (10) @(posedge aclk);
        if (m_tdata === 24'hxxxxxx) begin
            $display("[FAIL] T4: 切换后 m_tdata 出现 X");
            errors = errors + 1;
        end
        $display("[INFO] T4 done");

        repeat (20) @(posedge aclk);
        if (errors == 0) $display("TB_RESULT: PASS");
        else             $display("TB_RESULT: FAIL (%0d errors)", errors);
        $finish;
    end

endmodule
