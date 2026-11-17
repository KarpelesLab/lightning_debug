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
module idcap (
    input  wire clk12,
    input  wire ft_txd, output wire ft_rxd, input wire ft_rts_n, output wire ft_cts_n,
    output wire flash_mosi, output wire flash_sck, output wire flash_cs_n, input wire flash_miso,
    output wire muxa_sel, output wire muxa_oe_n, output wire muxb_sel, output wire muxb_oe_n,
    output wire pwr_en, input wire pwr_flt_n,
    input  wire l0a_p, l0a_n, l0b_p, l0b_n, l1a_p, l1a_n, l1b_p, l1b_n,
    input  wire a_id0, a_id1, b_id0, b_id1,
    input  wire btn_n, vbus2_det,
    output wire exp0, exp1, exp2, exp3, exp5, exp6,
    output wire led_r, led_g, led_b
);
    assign flash_cs_n = 1'b1;
    assign flash_sck  = 1'b0;
    assign flash_mosi = 1'b0;
    assign {muxa_sel, muxb_sel} = 2'b00;
    assign {muxa_oe_n, muxb_oe_n} = 2'b11;
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
        .RGB0PWM(ovf), .RGB1PWM(pwr_en), .RGB2PWM(1'b0),
        .RGB0(led_r), .RGB1(led_g), .RGB2(led_b));

    wire _unused = &{1'b0, ft_txd, ft_rts_n, flash_miso, pwr_flt_n, vbus2_det,
                     l0a_p, l0a_n, l0b_p, l0b_n};
endmodule
