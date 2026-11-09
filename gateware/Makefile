# Build the self-test bitstream:  make        (needs yosys, nextpnr-ice40, icepack)
# Flash it over USB-C #1:          make prog   (needs iceprog)
# The YoWASP builds work too:      make YOSYS=yowasp-yosys NEXTPNR=yowasp-nextpnr-ice40 ICEPACK=yowasp-icepack
TOP     ?= selftest
YOSYS   ?= yosys
NEXTPNR ?= nextpnr-ice40
ICEPACK ?= icepack
ICEPROG ?= iceprog

all: $(TOP).bin

$(TOP).json: $(TOP).v
	$(YOSYS) -q -p "synth_ice40 -top $(TOP) -json $@" $<

$(TOP).asc: $(TOP).json lightning_debug.pcf
	$(NEXTPNR) -q --up5k --package sg48 --freq 12 --pcf lightning_debug.pcf --json $< --asc $@ --report $(TOP).report.json

$(TOP).bin: $(TOP).asc
	$(ICEPACK) $< $@

prog: $(TOP).bin
	$(ICEPROG) $<

clean:
	rm -f $(TOP).json $(TOP).asc $(TOP).bin $(TOP).report.json

.PHONY: all prog clean
