// Lightning ID responder + edge capture (built from idcap.v).
// Answers the phone's 0x74 ID request with RESP on whichever ID line asked,
// then routes that side's L0 lanes to USB-C #2. Edges stream as in idcap.v.
//
// ID-line capture for the Lightning debug board.
//
// Streams every edge on the 4 ID lines and the 4 L1 lanes over FT2232H channel B
// (/dev/ttyUSB1) at 12 Mbaud 8N1 (one bit per 12 MHz clock), 83 ns resolution.
// Decode with gateware/idcap.py.
//
// Event = 4 bytes, first byte has bit 7 set, the others clear:
//   b0 = {1, s[7:1]}  b1 = {0, s[0], d[19:14]}  b2 = {0, d[13:7]}  b3 = {0, d[6:0]}
//   s = {a_id0, a_id1, b_id0, b_id1, l1a_p, l1a_n, l1b_p, l1b_n} after the edge,
//   d = 12 MHz ticks since the previous event (a heartbeat event repeats the
//   current state when d would overflow, about every 87 ms).
//
// Lightning power turns on 1 s after configuration (so the phone's first ID
// requests are captured) and is forced off while the button is held.
// Lane muxes stay disconnected.
module idresp #(
    // reply to 0x74: 7 bytes + CRC-8/Maxim (init 0xFF), first byte first
    parameter [63:0] RESP = 64'h75_10_0c_00_00_00_00_66
) (
    input  wire clk12,
    input  wire ft_txd, output wire ft_rxd, input wire ft_rts_n, output wire ft_cts_n,
    output wire flash_mosi, output wire flash_sck, output wire flash_cs_n, input wire flash_miso,
    output wire muxa_sel, output wire muxa_oe_n, output wire muxb_sel, output wire muxb_oe_n,
    output wire pwr_en, input wire pwr_flt_n,
    input  wire l0a_p, l0a_n, l0b_p, l0b_n, l1a_p, l1a_n, l1b_p, l1b_n,
    inout  wire a_id0, a_id1, b_id0, b_id1,
    input  wire btn_n, vbus2_det,
    output wire exp0, exp1, exp2, exp3, exp5, exp6,
    output wire led_r, led_g, led_b
);
    assign flash_cs_n = 1'b1;
    assign flash_sck  = 1'b0;
    assign flash_mosi = 1'b0;
    // ---------------- ID responders, one per ID line ----------------
    wire [3:0] id_in = {a_id0, a_id1, b_id0, b_id1};
    wire [3:0] id_drv, id_done;
    genvar g;
    generate for (g = 0; g < 4; g = g + 1) begin : resp
        sdq_resp #(.RESP(RESP)) r (.clk(clk12), .line(id_in[g]), .drive_low(id_drv[g]), .replied(id_done[g]));
    end endgenerate
    assign a_id0 = id_drv[3] ? 1'b0 : 1'bz;
    assign a_id1 = id_drv[2] ? 1'b0 : 1'bz;
    assign b_id0 = id_drv[1] ? 1'b0 : 1'bz;
    assign b_id1 = id_drv[0] ? 1'b0 : 1'bz;

    // route the side we answered on to USB-C #2 (only one side at a time)
    reg [1:0] side = 0;                  // 0 none, 1 A, 2 B
    always @(posedge clk12)
        if (|id_done[3:2]) side <= 1;
        else if (|id_done[1:0]) side <= 2;
    assign muxa_sel = 1'b1;  assign muxa_oe_n = (side != 1);
    assign muxb_sel = 1'b1;  assign muxb_oe_n = (side != 2);
    assign ft_cts_n = 1'b0;
    assign {exp0, exp1, exp2, exp3, exp5, exp6} = 6'b0;

    // ---------------- power-on delay ----------------
    reg [23:0] dly = 0;
    reg on = 0;
    always @(posedge clk12)
        if (!on) begin
            dly <= dly + 1;
            if (dly == 24'd11_999_999) on <= 1;
        end
    assign pwr_en = on & btn_n;

    // ---------------- sampling ----------------
    reg [7:0] s1 = 0, s2 = 0, prev = 0;
    always @(posedge clk12) begin
        s1 <= {a_id0, a_id1, b_id0, b_id1, l1a_p, l1a_n, l1b_p, l1b_n};
        s2 <= s1;
    end

    reg [19:0] delta = 0;
    wire change = (s2 != prev);
    wire hb = (delta == 20'hFFFFF);
    reg  wr = 0;
    reg  [27:0] wdata = 0;
    always @(posedge clk12) begin
        wr <= 0;
        if (change || hb) begin
            wr <= 1;
            wdata <= {s2, delta};
            prev <= s2;
            delta <= 1;
        end else
            delta <= delta + 1;
    end

    // ---------------- FIFO (inferred block RAM) ----------------
    reg [27:0] mem [0:1023];
    reg [9:0] wp = 0, rp = 0;
    reg ovf = 0;
    wire full  = (wp + 10'd1 == rp);
    wire empty = (wp == rp);
    always @(posedge clk12)
        if (wr) begin
            if (!full) begin mem[wp] <= wdata; wp <= wp + 1; end
            else ovf <= 1;
        end
    reg [27:0] rdata;
    always @(posedge clk12) rdata <= mem[rp];

    // ---------------- 12 Mbaud transmitter ----------------
    reg [9:0] sh = 10'h3ff;
    reg [3:0] bits = 0;
    reg [1:0] idx = 0;
    reg [27:0] ev;
    reg busy = 0, load = 0;
    assign ft_rxd = sh[0];
    function [7:0] evbyte(input [27:0] e, input [1:0] i);
        case (i)
            0: evbyte = {1'b1, e[27:21]};
            1: evbyte = {1'b0, e[20], e[19:14]};
            2: evbyte = {1'b0, e[13:7]};
            3: evbyte = {1'b0, e[6:0]};
        endcase
    endfunction
    always @(posedge clk12) begin
        load <= 0;
        if (bits != 0) begin
            sh <= {1'b1, sh[9:1]};
            bits <= bits - 1;
        end else if (busy) begin
            sh <= {1'b1, evbyte(ev, idx), 1'b0};
            bits <= 9;
            idx <= idx + 1;
            if (idx == 3) busy <= 0;
        end else if (load) begin
            ev <= rdata; busy <= 1; idx <= 0;
        end else if (!empty) begin
            rp <= rp + 1; load <= 1;     // rdata (mem[rp]) is valid next clock
        end
    end

    // ---------------- LED: green = power on, red = FIFO overflowed ----------------
    SB_RGBA_DRV #(.CURRENT_MODE("0b1"), .RGB0_CURRENT("0b000001"),
                  .RGB1_CURRENT("0b000001"), .RGB2_CURRENT("0b000001")) rgb (
        .CURREN(1'b1), .RGBLEDEN(1'b1),
        .RGB0PWM(ovf), .RGB1PWM(pwr_en), .RGB2PWM(side != 0),
        .RGB0(led_r), .RGB1(led_g), .RGB2(led_b));

    wire _unused = &{1'b0, ft_txd, ft_rts_n, flash_miso, pwr_flt_n, vbus2_det,
                     l0a_p, l0a_n, l0b_p, l0b_n};
endmodule

// One ID line: decode the phone's pulses, answer a 4-byte 0x74 request.
// Bit = low pulse on a 10.08 us period: 1 = 1.67 us low, 0 = 6.92 us low, LSB
// first, 15.67 us high after each byte; a low > 10.8 us is a break. After the
// request the phone sends a break; the reply starts 8 us after it ends.
module sdq_resp #(parameter [63:0] RESP = 0) (
    input wire clk, input wire line, output reg drive_low = 0, output reg replied = 0
);
    localparam T_PER = 121, T_ONE = 20, T_ZERO = 83, T_BYTEGAP = 150, T_BRK = 130,
               T_BIT = 48, T_WAIT = 96;
    reg [1:0] sy = 2'b11;
    always @(posedge clk) sy <= {sy[0], line};
    wire l = sy[1];
    reg lp = 1;
    reg [11:0] w = 0;            // low width
    reg [7:0] sh = 0;
    reg [2:0] nb = 0;            // bits in current byte
    reg [2:0] nB = 0;            // bytes since break
    reg req = 0, got = 0;
    // transmitter
    reg tx = 0, wait_ = 0;
    reg [11:0] t = 0;
    reg [5:0] bi = 0;            // bit index 0..63
    reg [63:0] rs = 0;
    // byte k (k = bi[5:3]) is rs[63-8k -: 8], sent first byte first; bits LSB first
    wire [5:0] bidx = 6'd56 - {bi[5:3], 3'b000} + {3'b000, bi[2:0]};
    wire bit_now = rs[bidx];
    always @(posedge clk) begin
        replied <= 0;
        lp <= l;
        if (tx) begin
            t <= t + 1;
            drive_low <= (t < (bit_now ? T_ONE : T_ZERO));
            if (t == ((bi[2:0] == 7) ? T_PER + T_BYTEGAP - 1 : T_PER - 1)) begin
                t <= 0;
                if (bi == 63) begin tx <= 0; drive_low <= 0; replied <= 1; end
                bi <= bi + 1;
            end
        end else if (wait_) begin
            t <= t + 1;
            if (t == T_WAIT) begin wait_ <= 0; tx <= 1; t <= 0; bi <= 0; rs <= RESP; end
        end else begin
            if (!l) w <= (w == 12'hfff) ? w : w + 1;
            if (lp && !l) w <= 1;                       // falling edge
            if (!lp && l) begin                         // rising edge: classify the low
                if (w > T_BRK) begin
                    if (got) begin wait_ <= 1; t <= 0; end
                    got <= 0; req <= 0; nb <= 0; nB <= 0;
                end else begin
                    sh <= {(w < T_BIT), sh[7:1]};
                    nb <= nb + 1;
                    if (nb == 7) begin
                        nB <= nB + 1;
                        if (nB == 0) req <= ({(w < T_BIT), sh[7:1]} == 8'h74);
                        if (nB == 3 && req) got <= 1;
                    end
                end
            end
        end
    end
endmodule
