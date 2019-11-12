from litex.soc.integration.doc import AutoDoc, ModuleDoc
from litex.soc.interconnect.csr_eventmanager import *

from migen.genlib.cdc import MultiReg
from migen.genlib.cdc import PulseSynchronizer

class SpiMaster(Module, AutoCSR, AutoDoc):
    def __init__(self, pads):
        self.intro = ModuleDoc("""Simple soft SPI master module optimized for Betrusted applications

        Requires a clock domain 'spi', which runs at the speed of the SPI bus. 
        
        Simulation benchmarks 16.5us to transfer 16x16 bit words including setup overhead (sysclk=100MHz, spiclk=25MHz)
        which is about 15Mbps system-level performance, assuming the receiver can keep up.
        """)

        self.miso = pads.miso
        self.mosi = pads.mosi
        self.sclk = pads.sclk
        self.csn = pads.csn

        # self.comb += self.sclk.eq(~ClockSignal("spi"))  # TODO: add clock gating to save power; note receiver reqs for CS pre-clocks
        # generate a clock, this is Artix-specific
        # mirror the clock with zero delay, and 180 degrees out of phase
        self.specials += [
            Instance("ODDR2",
                     p_DDR_ALIGNMENT="NONE",
                     p_INIT="0",
                     p_SRTYPE="SYNC",

                     o_Q=self.sclk,
                     i_C0=ClockSignal("spi"),
                     i_C1=~ClockSignal("spi"),
                     i_D0=0,
                     i_D1=1,
                     i_R=ResetSignal("spi"),
                     i_S=0,
            ),
        ]

        self.tx = CSRStorage(16, name="tx", description="""Tx data, for MOSI""")
        self.rx = CSRStatus(16, name="rx", description="""Rx data, from MISO""")
        self.control = CSRStorage(fields=[
            CSRField("go", description="Initiate a SPI cycle by writing a `1`. Does not automatically clear."),
            CSRField("intena", description="Enable interrupt on transaction finished"),
        ])
        self.status = CSRStatus(fields=[
            CSRField("tip", description="Set when transaction is in progress"),
            CSRField("txfull", description="Set when Tx register is full"),
        ])

        self.submodules.ev = EventManager()
        self.ev.spi_int = EventSourceProcess()  # falling edge triggered
        self.ev.finalize()
        self.comb += self.ev.spi_int.trigger.eq(self.control.fields.intena & self.status.fields.tip)

        # Replica CSR into "spi" clock domain
        self.tx_r = Signal(16)
        self.rx_r = Signal(16)
        self.tip_r = Signal()
        self.txfull_r = Signal()
        self.go_r = Signal()
        self.tx_written = Signal()

        self.specials += MultiReg(self.tip_r, self.status.fields.tip)
        self.specials += MultiReg(self.txfull_r, self.status.fields.txfull)
        self.specials += MultiReg(self.control.fields.go, self.go_r, "spi")
        self.specials += MultiReg(self.tx.re, self.tx_written, "spi")
        # extract rising edge of go -- necessary in case of huge disparity in sysclk-to-spi clock domain
        self.go_d = Signal()
        self.go_edge = Signal()
        self.sync.spi += self.go_d.eq(self.go_r)
        self.comb += self.go_edge.eq(self.go_r & ~self.go_d)

        self.csn_r = Signal(reset=1)
        self.comb += self.csn.eq(self.csn_r)
        self.comb += self.rx.status.eq(self.rx_r) ## invalid while transaction is in progress
        fsm = FSM(reset_state="IDLE")
        fsm = ClockDomainsRenamer("spi")(fsm)
        self.submodules += fsm
        spicount = Signal(4)
        fsm.act("IDLE",
                If(self.go_edge,
                   NextState("RUN"),
                   NextValue(self.tx_r, Cat(0, self.tx.storage[:15])),
                   # stability guaranteed so no synchronizer necessary
                   NextValue(spicount, 15),
                   NextValue(self.txfull_r, 0),
                   NextValue(self.tip_r, 1),
                   NextValue(self.csn_r, 0),
                   NextValue(self.mosi, self.tx.storage[15]),
                   NextValue(self.rx_r, Cat(self.miso, self.rx_r[:15])),
                ).Else(
                    NextValue(self.tip_r, 0),
                    NextValue(self.csn_r, 1),
                    If(self.tx_written,
                       NextValue(self.txfull_r, 1),
                    ),
                )
        )
        fsm.act("RUN",
                If(spicount > 0,
                   NextValue(self.mosi, self.tx_r[15]),
                   NextValue(self.tx_r, Cat(0, self.tx_r[:15])),
                   NextValue(spicount, spicount - 1),
                   NextValue(self.rx_r, Cat(self.miso, self.rx_r[:15])),
                ).Else(
                    NextValue(self.csn_r, 1),
                    NextValue(self.tip_r, 0),
                    NextState("IDLE"),
                ),
        )


class SpiSlave(Module, AutoCSR, AutoDoc):
    def __init__(self, pads):
        self.intro = ModuleDoc("""Simple soft SPI slave module optimized for Betrusted-EC (UP5K arch) use

        Assumes a free-running sclk and csn performs the function of framing bits
        Thus csn must go high between each frame, you cannot hold csn low for burst transfers
        """)

        self.miso = pads.miso
        self.mosi = pads.mosi
        self.sclk = pads.sclk
        self.csn = pads.csn

        ### FIXME: stand-in for SPI clock input
        self.clock_domains.cd_spislave = ClockDomain()
        self.comb += self.cd_spislave.clk.eq(self.sclk)

        self.tx = CSRStorage(16, name="tx", description="""Tx data, to MISO""")
        self.rx = CSRStatus(16, name="rx", description="""Rx data, from MOSI""")
        self.control = CSRStorage(fields=[
            CSRField("intena", description="Enable interrupt on transaction finished"),
            CSRField("clrerr", description="Clear Rx overrun error", pulse=True),
        ])
        self.status = CSRStatus(fields=[
            CSRField("tip", description="Set when transaction is in progress"),
            CSRField("rxfull", description="Set when Rx register has new, valid contents to read"),
            CSRField("rxover", description="Set if Rx register was not read before another transaction was started")
        ])

        self.submodules.ev = EventManager()
        self.ev.spi_int = EventSourceProcess()  # falling edge triggered
        self.ev.finalize()
        self.comb += self.ev.spi_int.trigger.eq(self.control.fields.intena & self.status.fields.tip)

        # Replica CSR into "spi" clock domain
        self.txrx = Signal(16)
        self.tip_r = Signal()
        self.rxfull_r = Signal()
        self.rxover_r = Signal()
        self.csn_r = Signal()

        self.specials += MultiReg(self.tip_r, self.status.fields.tip)
        self.comb += self.tip_r.eq(~self.csn)
        tip_d = Signal()
        donepulse = Signal()
        self.sync += tip_d.eq(self.tip_r)
        self.comb += donepulse.eq(~self.tip_r & tip_d)  # done pulse goes high when tip drops

        self.comb += self.status.fields.rxfull.eq(self.rxfull_r)
        self.comb += self.status.fields.rxover.eq(self.rxover_r)

        self.sync += [
            If(self.rx.we,
               self.rxfull_r.eq(0),
            ).Else(
                If(donepulse,
                   self.rxfull_r.eq(1)
                ).Else(
                    self.rxfull_r.eq(self.rxfull_r),
                ),

                If(self.tip_r & self.rxfull_r,
                   self.rxover_r.eq(1)
                ).Elif(self.control.fields.clrerr,
                   self.rxover_r.eq(0)
                ).Else(
                    self.rxover_r.eq(self.rxover_r)
                ),
            )
        ]

        self.comb += self.miso.eq(self.txrx[15])
        csn_d = Signal()
        self.sync.spislave += [
            csn_d.eq(self.csn),
            # "Sloppy" clock boundary crossing allowed because "rxfull" is synchronized and CPU should grab data based on that
            If(self.csn == 0,
               self.txrx.eq(Cat(self.mosi, self.txrx[0:15])),
               self.rx.status.eq(self.rx.status),
            ).Else(
               If(self.csn & ~csn_d,
                 self.rx.status.eq(self.txrx),
               ).Else(
                   self.rx.status.eq(self.rx.status)
               ),
               self.txrx.eq(self.tx.storage)
            )
        ]
