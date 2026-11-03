`timescale 1ns / 1ps
// ============================================================================
//  axis_stage_bypass -- 通用的"处理级旁路"2:1 AXIS 选择器
// ----------------------------------------------------------------------------
//  用途：把任意一个 24bit AXIS 图像处理 IP 挂进视频流水线，并允许逐级旁路，
//        从而用一条流水线分时复用出多种处理模式（资源受限器件的常用手法）。
//
//      s_axis ──┬──────────────────────────────────────────────┐
//               │                                              │
//               └─► px_axis ─► [ 处理 IP ] ─► pd_axis ────┐    │
//                                                         ├─► m_axis
//                                  sel=0 直通 ─────────────┘
//
//    sel = 0 : m_axis 输出 s_axis 原样（旁路该级）
//    sel = 1 : m_axis 输出处理 IP 的结果
//
//  握手策略：两路输入始终接收（tready 都给），未被选中的一路数据被丢弃，
//  因此任何一路都不会反压上游、不会把整条流水线拖停。
//  代价：切换瞬间有 1 帧撕裂（两路存在固定延迟差），PS 端丢 1~2 帧即可。
//
//  aclk 在本模块逻辑上不使用，但必须保留：让四个 AXIS 接口关联到同一个时钟域，
//  否则 BD 会报 FREQ_HZ bus parameter missing。
// ============================================================================
module axis_stage_bypass (
    input  wire        aclk,
    input  wire        sel,             // 0 = 旁路直通, 1 = 走处理 IP

    // 来自上游的原始视频流
    input  wire [23:0] s_axis_tdata,
    input  wire [2:0]  s_axis_tkeep,
    input  wire        s_axis_tvalid,
    output wire        s_axis_tready,
    input  wire        s_axis_tlast,
    input  wire        s_axis_tuser,    // SOF

    // 送给处理 IP 的输入（与 s_axis 同源）
    output wire [23:0] px_axis_tdata,
    output wire [2:0]  px_axis_tkeep,
    output wire        px_axis_tvalid,
    input  wire        px_axis_tready,
    output wire        px_axis_tlast,
    output wire        px_axis_tuser,

    // 来自处理 IP 的输出
    input  wire [23:0] pd_axis_tdata,
    input  wire [2:0]  pd_axis_tkeep,
    input  wire        pd_axis_tvalid,
    output wire        pd_axis_tready,
    input  wire        pd_axis_tlast,
    input  wire        pd_axis_tuser,

    // 送往下一级 / 最终的 out_stream
    output wire [23:0] m_axis_tdata,
    output wire [2:0]  m_axis_tkeep,
    output wire        m_axis_tvalid,
    input  wire        m_axis_tready,
    output wire        m_axis_tlast,
    output wire        m_axis_tuser
);

    // ---- 处理 IP 输入侧：直接复制上游数据 ----
    assign px_axis_tdata  = s_axis_tdata;
    assign px_axis_tkeep  = s_axis_tkeep;
    assign px_axis_tvalid = s_axis_tvalid;
    assign px_axis_tlast  = s_axis_tlast;
    assign px_axis_tuser  = s_axis_tuser;

    // ---- 上游 ready：输出通路与处理通路都就绪才接收，保证两路同步 ----
    assign s_axis_tready = m_axis_tready & px_axis_tready;

    // ---- 处理 IP 输出始终被消费（未被选中即丢弃），不反压上游 ----
    assign pd_axis_tready = m_axis_tready;

    // ---- 二选一 ----
    assign m_axis_tdata  = sel ? pd_axis_tdata  : s_axis_tdata;
    assign m_axis_tkeep  = sel ? pd_axis_tkeep  : s_axis_tkeep;
    assign m_axis_tvalid = sel ? pd_axis_tvalid : s_axis_tvalid;
    assign m_axis_tlast  = sel ? pd_axis_tlast  : s_axis_tlast;
    assign m_axis_tuser  = sel ? pd_axis_tuser  : s_axis_tuser;

endmodule
