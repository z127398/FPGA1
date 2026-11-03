module top(
    input  wire sys_clk,
    input  wire sys_rst_n,
    output wire led
);

    reg [25:0] cnt;

    always @(posedge sys_clk or negedge sys_rst_n) begin
        if (!sys_rst_n)
            cnt <= 26'd0;
        else
            cnt <= cnt + 1'b1;
    end

    assign led = cnt[25];

endmodule
