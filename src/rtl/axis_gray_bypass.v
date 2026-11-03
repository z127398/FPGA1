`timescale 1ns / 1ps
// ============================================================================
//  axis_gray_bypass -- 摄像头视频流 "彩色直通 / 灰度" 二选一
// ----------------------------------------------------------------------------
//  上游 frontend 的 24bit RGB AXIS 流在这里复制成两路：
//    gp_axis_* : 送给 ov5640_rgb2gray_0/video_in（灰度 IP 的输入）
//    s_axis_*  : 原始数据直接进 mux 的旁通端
//  灰度 IP 的输出 gd_axis_* 进 mux 的处理端。
//
//    sel = 0 -> m_axis 输出旁通（彩色原始数据）
//    sel = 1 -> m_axis 输出灰度 IP 的结果
//
//  握手策略：两路输入始终接收（tready 都给），未被选中的一路数据被丢弃。
//  这样任何一路都不会反压上游，避免广播分支把整条流水线拖停。
//  代价：切换瞬间有 1 帧画面撕裂（两路存在固定延迟差），
//        PS 端切换后丢弃 1~2 帧即可。
//
//  aclk 本模块逻辑上不使用，但必须保留：让 4 个 AXIS 接口关联到同一个
//  100MHz 时钟域，否则 BD 会报 FREQ_HZ bus parameter missing。
// ============================================================================
module axis_gray_bypass (
    input  wire        aclk,
    input  wire        sel,            // 0 = 彩色直通, 1 = 灰度

    // 来自 frontend 的原始视频流
    input  wire [23:0] s_axis_tdata,
    input  wire [2:0]  s_axis_tkeep,
    input  wire        s_axis_tvalid,
    output wire        s_axis_tready,
    input  wire        s_axis_tlast,
    input  wire        s_axis_tuser,   // SOF

    // 送往 ov5640_rgb2gray_0/video_in
    output wire [23:0] gp_axis_tdata,
    output wire [2:0]  gp_axis_tkeep,
    output wire        gp_axis_tvalid,
    input  wire        gp_axis_tready,
    output wire        gp_axis_tlast,
    output wire        gp_axis_tuser,

    // 来自 ov5640_rgb2gray_0/video_out
    input  wire [23:0] gd_axis_tdata,
    input  wire [2:0]  gd_axis_tkeep,
    input  wire        gd_axis_tvalid,
    output wire        gd_axis_tready,
    input  wire        gd_axis_tlast,
    input  wire        gd_axis_tuser,

    // 送往下游 camera_in/out_stream -> axi_vdma/S_AXIS_S2MM
    output wire [23:0] m_axis_tdata,
    output wire [2:0]  m_axis_tkeep,
    output wire        m_axis_tvalid,
    input  wire        m_axis_tready,
    output wire        m_axis_tlast,
    output wire        m_axis_tuser
);

    // ---- 灰度 IP 输入侧：直接复制上游数据 ----
    assign gp_axis_tdata  = s_axis_tdata;
    assign gp_axis_tkeep  = s_axis_tkeep;
    assign gp_axis_tvalid = s_axis_tvalid;
    assign gp_axis_tlast  = s_axis_tlast;
    assign gp_axis_tuser  = s_axis_tuser;

    // ---- 上游 ready：输出通路与灰度通路都就绪才接收，保证两路同步 ----
    assign s_axis_tready = m_axis_tready & gp_axis_tready;

    // ---- 灰度 IP 输出始终被消费（未选中即丢弃），不反压上游 ----
    assign gd_axis_tready = m_axis_tready;

    // ---- 二选一 ----
    assign m_axis_tdata  = sel ? gd_axis_tdata  : s_axis_tdata;
    assign m_axis_tkeep  = sel ? gd_axis_tkeep  : s_axis_tkeep;
    assign m_axis_tvalid = sel ? gd_axis_tvalid : s_axis_tvalid;
    assign m_axis_tlast  = sel ? gd_axis_tlast  : s_axis_tlast;
    assign m_axis_tuser  = sel ? gd_axis_tuser  : s_axis_tuser;

endmodule
