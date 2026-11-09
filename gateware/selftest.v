// Bring-up / self-test gateware for the Lightning debug board.
//
// Uses every pin in lightning_debug.pcf, so a clean nextpnr run proves the pin
// file matches the iCE40UP5K-SG48 (banks, globals, RGB pins).
//
// On hardware:
//   - RGB LED cycles R -> G -> B (one second each) through SB_RGBA_DRV.
//   - FT2232H channel B (/dev/ttyUSB1) is a 115200 8N1 console:
//       s   print a status line
//       p   toggle Lightning power (TPS2065C EN)
//       a   cycle lane mux A: off -> FPGA -> USB-C #2 -> off
//       b   same for mux B
//     Status line (one character per signal, 0/1):
//       ID a0 a1 b0 b1  L1 ap an bp bn  L0 ap an bp bn  btn vbus2 flt  pwr ma mb
//     ma/mb are 0 = off, 1 = FPGA, 2 = USB.
//   - J5 EXP pins output a slow binary count (EXP0 ~ 2.8 Hz, each next pin half
//     that), so each header pin can be checked with a meter or LED.
//   - The user button forces Lightning power off while held.
module selftest (
    input  wire clk12,
    // FT2232H channel B
    input  wire ft_txd, output wire ft_rxd, input wire ft_rts_n, output wire ft_cts_n,
    // config flash, parked after configuration
    output wire flash_mosi, output wire flash_sck, output wire flash_cs_n, input wire flash_miso,
    // lane muxes
    output wire muxa_sel, output wire muxa_oe_n, output wire muxb_sel, output wire muxb_oe_n,
    // Lightning power
    output wire pwr_en, input wire pwr_flt_n,
    // lanes
    input  wire l0a_p, l0a_n, l0b_p, l0b_n, l1a_p, l1a_n, l1b_p, l1b_n,
    // ID lines
    input  wire a_id0, a_id1, b_id0, b_id1,
    // misc
    input  wire btn_n, vbus2_det,
    // spare header
    output wire exp0, exp1, exp2, exp3, exp5, exp6,
    // RGB LED sinks
    output wire led_r, led_g, led_b
);
    // ---------------- free-running counter ----------------
    reg [27:0] cnt = 0;
    always @(posedge clk12) cnt <= cnt + 1;
    assign {exp6, exp5, exp3, exp2, exp1, exp0} = cnt[27:22];

    // ---------------- flash parked ----------------
    assign flash_cs_n = 1'b1;
    assign flash_sck  = 1'b0;
    assign flash_mosi = 1'b0;

    // ---------------- control state ----------------
    reg pwr = 0;
    reg [1:0] ma = 0, mb = 0;            // 0 off, 1 FPGA, 2 USB
    assign pwr_en    = pwr & btn_n;
    assign muxa_oe_n = (ma == 0);
    assign muxa_sel  = (ma == 2);
    assign muxb_oe_n = (mb == 0);
    assign muxb_sel  = (mb == 2);
    assign ft_cts_n  = 1'b0;             // always ready

    // ---------------- RGB LED ----------------
    reg [1:0] col = 0;
    reg [23:0] sec = 0;
    always @(posedge clk12)
        if (sec == 24'd11_999_999) begin
            sec <= 0;
            col <= (col == 2) ? 2'd0 : col + 1;
        end else
            sec <= sec + 1;

    SB_RGBA_DRV #(
        .CURRENT_MODE("0b1"),            // half current
        .RGB0_CURRENT("0b000001"),       // 2 mA
        .RGB1_CURRENT("0b000001"),
        .RGB2_CURRENT("0b000001")
    ) rgb (
        .CURREN(1'b1), .RGBLEDEN(1'b1),
        .RGB0PWM(col == 0), .RGB1PWM(col == 1), .RGB2PWM(col == 2),
        .RGB0(led_r), .RGB1(led_g), .RGB2(led_b)
    );

    // ---------------- UART 115200 @ 12 MHz ----------------
    localparam DIV = 104;

    // receiver (FT -> FPGA)
    reg [1:0] rx_s = 2'b11;
    always @(posedge clk12) rx_s <= {rx_s[0], ft_txd};
    wire rx = rx_s[1];
    reg [6:0] rx_div = 0;
    reg [3:0] rx_bit = 0;
    reg [7:0] rx_sh = 0;
    reg rx_busy = 0, rx_stb = 0;
    reg [7:0] rx_byte = 0;
    always @(posedge clk12) begin
        rx_stb <= 0;
        if (!rx_busy) begin
            if (!rx) begin rx_busy <= 1; rx_div <= DIV / 2; rx_bit <= 0; end
        end else if (rx_div != 0) rx_div <= rx_div - 1;
        else begin
            rx_div <= DIV - 1;
            rx_bit <= rx_bit + 1;
            if (rx_bit == 0 && rx) rx_busy <= 0;            // false start
            else if (rx_bit >= 1 && rx_bit <= 8) rx_sh <= {rx, rx_sh[7:1]};
            else if (rx_bit == 9) begin
                rx_busy <= 0;
                if (rx) begin rx_byte <= rx_sh; rx_stb <= 1; end
            end
        end
    end

    // transmitter (FPGA -> FT)
    reg [9:0] tx_sh = 10'h3ff;
    reg [6:0] tx_div = 0;
    reg [3:0] tx_left = 0;
    wire tx_idle = (tx_left == 0);
    assign ft_rxd = tx_sh[0];
    reg tx_go = 0;
    reg [7:0] tx_byte = 0;
    always @(posedge clk12)
        if (tx_go && tx_idle) begin
            tx_sh <= {1'b1, tx_byte, 1'b0};
            tx_left <= 10; tx_div <= DIV - 1;
        end else if (!tx_idle) begin
            if (tx_div != 0) tx_div <= tx_div - 1;
            else begin
                tx_div <= DIV - 1;
                tx_sh <= {1'b1, tx_sh[9:1]};
                tx_left <= tx_left - 1;
            end
        end

    // ---------------- status line ----------------
    // 22 data characters plus spaces, then CR LF.
    wire [1:0] ma_c = ma, mb_c = mb;
    function [7:0] b2c(input v); b2c = v ? "1" : "0"; endfunction
    reg [5:0] pos = 0;
    reg printing = 0;
    reg [7:0] ch;
    always @(*) begin
        case (pos)
            0: ch = b2c(a_id0);  1: ch = b2c(a_id1);  2: ch = b2c(b_id0);  3: ch = b2c(b_id1);
            4: ch = " ";
            5: ch = b2c(l1a_p);  6: ch = b2c(l1a_n);  7: ch = b2c(l1b_p);  8: ch = b2c(l1b_n);
            9: ch = " ";
            10: ch = b2c(l0a_p); 11: ch = b2c(l0a_n); 12: ch = b2c(l0b_p); 13: ch = b2c(l0b_n);
            14: ch = " ";
            15: ch = b2c(btn_n); 16: ch = b2c(vbus2_det); 17: ch = b2c(pwr_flt_n);
            18: ch = " ";
            19: ch = b2c(pwr);   20: ch = "0" + ma_c; 21: ch = "0" + mb_c;
            22: ch = 8'h0d;      23: ch = 8'h0a;
            default: ch = 8'h0a;
        endcase
    end

    always @(posedge clk12) begin
        tx_go <= 0;
        if (rx_stb) case (rx_byte)
            "p": pwr <= ~pwr;
            "a": ma  <= (ma == 2) ? 2'd0 : ma + 1;
            "b": mb  <= (mb == 2) ? 2'd0 : mb + 1;
            default: ;
        endcase
        if (rx_stb && !printing) begin printing <= 1; pos <= 0; end
        else if (printing && tx_idle && !tx_go) begin
            tx_byte <= ch; tx_go <= 1;
            if (pos == 23) printing <= 0; else pos <= pos + 1;
        end
    end

    // unused inputs
    wire _unused = &{1'b0, ft_rts_n, flash_miso};
endmodule
