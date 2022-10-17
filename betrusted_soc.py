#!/usr/bin/env python3

# This variable defines all the external programs that this module
# relies on.  lxbuildenv reads this variable in order to ensure
# the build will finish without exiting due to missing third-party
# programs.

LX_DEPENDENCIES = ["riscv", "vivado"]

# Import lxbuildenv to integrate the deps/ directory
from re import S
import lxbuildenv
import litex.soc.doc as lxsocdoc
from pathlib import Path
import subprocess
import sys

from random import SystemRandom
import argparse

from migen import *
from migen.genlib.cdc import MultiReg, BlindTransfer, BusSynchronizer
from migen.genlib.resetsync import AsyncResetSynchronizer

from litex.build.generic_platform import *
from litex.build.xilinx import XilinxPlatform, VivadoProgrammer

from litex.soc.interconnect.csr import *
from litex.soc.interconnect.csr_eventmanager import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.integration.doc import AutoDoc, ModuleDoc
from litex.soc.cores.clock import S7MMCM, S7IDELAYCTRL
from litex.soc.cores.i2s import S7I2S
from litex.soc.cores.spi_opi import S7SPIOPI
from litex.soc.integration.soc import SoCRegion

from litex.soc.interconnect import wishbone
from litex.soc.integration.soc import SoCRegion
from gateware.rom_block import BlockRom

from gateware import info
from gateware import sram_32_cached
from gateware import memlcd
from gateware import spi_7series as spi
from gateware import messible
from gateware import i2c
from gateware import ticktimer
from gateware.wdt import WDT
from gateware import spinor
from gateware import keyboard
from gateware import jtag_phy

from gateware.trng.ring_osc_v2 import TrngRingOscV2
from gateware import aes_opentitan as aes
from gateware import sha2_opentitan as sha2
from gateware import sha512_opentitan as sha512
from gateware.curve25519.engine import Engine
from gateware.timer_alwayson import TimerAlwaysOn
from gateware.keyrom import KeyRom
from gateware import perfcounter

from valentyusb.usbcore.cpu.eptri import TriEndpointInterface
from valentyusb.usbcore.io import IoBuf

# IOs ----------------------------------------------------------------------------------------------

_io_pvt = [   # PVT-generation I/Os
    ("clk12", 0, Pins("R3"), IOStandard("LVCMOS18")),

    ("jtag", 0,
         Subsignal("tck", Pins("U11"), IOStandard("LVCMOS18")),  # DVT
         Subsignal("tms", Pins("P6"), IOStandard("LVCMOS18")),   # DVT
         Subsignal("tdi", Pins("P7"), IOStandard("LVCMOS18")),   # DVT
         Subsignal("tdo", Pins("R6"), IOStandard("LVCMOS18")),   # DVT
    ),

    ("usb", 0,
         Subsignal("d_p", Pins("C1"), IOStandard("LVCMOS33"), Misc("DRIVE=12")),      # DVT
         Subsignal("d_n", Pins("B1"), IOStandard("LVCMOS33"), Misc("DRIVE=12")),      # DVT
         Subsignal("pullup_p", Pins("D1"), IOStandard("LVCMOS33"), Misc("DRIVE=4")),  # DVT
         Misc("SLEW=SLOW"),
     ),

    # USB PU/PD options are also available, but not wired up
    # ("usb_alt", 0,
    # Subsignal("pulldn_p", Pins("C2"), IOStandard("LVCMOS33")),  # DVT
    # Subsignal("pullup_n", Pins("B2"), IOStandard("LVCMOS33")),  # DVT
    # Subsignal("pulldn_n", Pins("A4"), IOStandard("LVCMOS33")),  # DVT
    # Misc("DRIVE=4"), Misc("SLEW=SLOW"),
    # ),

    ("lpclk", 0, Pins("N15"), IOStandard("LVCMOS18")),  # wifi_lpclk

    # Audio interface
    ("i2s", 0,
       Subsignal("clk", Pins("D12")),
       Subsignal("tx", Pins("E13")), # au_sdi1
       Subsignal("rx", Pins("C13")), # au_sdo1
       Subsignal("sync", Pins("D14")),
       IOStandard("LVCMOS33"),
       Misc("SLEW=SLOW"), Misc("DRIVE=4"),
     ),
    ("au_mclk", 0, Pins("E12"), IOStandard("LVCMOS33"), Misc("SLEW=SLOW"), Misc("DRIVE=8")),

    # I2C1 bus -- to RTC and audio CODEC
    ("i2c", 0,
        Subsignal("scl", Pins("G2"), IOStandard("LVCMOS33")), # DVT
        Subsignal("sda", Pins("F2"), IOStandard("LVCMOS33")), # DVT
        Misc("SLEW=SLOW"), Misc("DRIVE=4"),
    ),

    # RTC interrupt
    ("rtc_irq", 0, Pins("N5"), IOStandard("LVCMOS18")),

    # COM interface to UP5K
    ("com", 0,
        Subsignal("csn",  Pins("T15"), IOStandard("LVCMOS18"), Misc("SLEW=SLOW"), Misc("DRIVE=4")),
        Subsignal("cipo", Pins("P16"), IOStandard("LVCMOS18")),
        Subsignal("copi", Pins("N18"), IOStandard("LVCMOS18"), Misc("SLEW=SLOW"), Misc("DRIVE=4")),
        Subsignal("sclk", Pins("R16"), IOStandard("LVCMOS18"), Misc("SLEW=SLOW"), Misc("DRIVE=4")),
        Subsignal("hold", Pins("L13"), IOStandard("LVCMOS18")), # New function in PVT from DVT, but same physical wiring
     ),
    ("com_irq", 0, Pins("M16"), IOStandard("LVCMOS18")),

    # Keyboard scan matrix
    ("kbd", 0,
        # "key" 0-8 are rows, 9-18 are columns
        # column scan with 1's, so PD to default 0
        Subsignal("row", Pins("A15 A17 A16 A14 C17 B16 B17 C14 B15"), Misc("PULLDOWN True")), # DVT
        Subsignal("col", Pins("B13 C18 E14 D15 B18 D16 D17 F13 E15 A13")),                    # DVT
        IOStandard("LVCMOS33"),
        Misc("SLEW=SLOW"),
        Misc("DRIVE=4"),
     ),

    # LCD interface
    ("lcd", 0,
        Subsignal("sclk", Pins("H17")), # DVT
        Subsignal("scs",  Pins("G17")), # DVT
        Subsignal("si",   Pins("H18")), # DVT
        IOStandard("LVCMOS33"),
        Misc("SLEW=SLOW"),
        Misc("DRIVE=4"),
     ),

    # SPI Flash
    ("spiflash_1x", 0, # clock needs to be accessed through STARTUPE2
        Subsignal("cs_n", Pins("M13")),
        Subsignal("copi", Pins("K17")),
        Subsignal("cipo", Pins("K18")),
        Subsignal("wp",   Pins("L14")), # provisional
        Subsignal("hold", Pins("M15")), # provisional
        IOStandard("LVCMOS18")
    ),
    ("spiflash_8x", 0, # clock needs a separate override to meet timing
        Subsignal("cs_n", Pins("M13")),
        Subsignal("dq",   Pins("K17 K18 L14 M15 L17 L18 M14 N14")),
        Subsignal("dqs",  Pins("R14")),
        Subsignal("ecs_n", Pins("L16")),
        Subsignal("sclk", Pins("C12")),  # DVT
        IOStandard("LVCMOS18"),
        Misc("SLEW=SLOW"),
     ),

    # SRAM
    ("sram", 0,
        Subsignal("adr", Pins(
            "V12 M5 P5 N4  V14 M3 R17 U15",
            "M4  L6 K3 R18 U16 K1 R5  T2",
            "U1  N1 L5 K2  M18 T6"),
            IOStandard("LVCMOS18"),
            Misc("SLEW=SLOW"),
        ),
        Subsignal("ce_n", Pins("V5"),  IOStandard("LVCMOS18"), Misc("PULLUP True")),
        Subsignal("oe_n", Pins("U12"), IOStandard("LVCMOS18"), Misc("PULLUP True")),
        Subsignal("we_n", Pins("K4"),  IOStandard("LVCMOS18"), Misc("PULLUP True")),
        Subsignal("zz_n", Pins("V17"), IOStandard("LVCMOS18"), Misc("PULLUP True"), Misc("SLEW=SLOW")),
        Subsignal("d", Pins(
            "M2  R4  P2  L4  L1  M1  R1  P1",
            "U3  V2  V4  U2  N2  T1  K6  J6",
            "V16 V15 U17 U18 P17 T18 P18 M17",
            "N3  T4  V13 P15 T14 R15 T3  R7"),
            IOStandard("LVCMOS18"),
            Misc("SLEW=SLOW"),
        ),
        Subsignal("dm_n", Pins("V3 R2 T5 T13"), IOStandard("LVCMOS18")),
    ),
]

_io_xous = [
    ("analog", 0,
     Subsignal("usbdet_p", Pins("C3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("usbdet_n", Pins("A3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("vbus_div", Pins("C4"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise0", Pins("C5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise1", Pins("A8"), IOStandard("LVCMOS33")),  # DVT
     # diff grounds
     Subsignal("usbdet_p_n", Pins("B3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("usbdet_n_n", Pins("A2"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("vbus_div_n", Pins("B4"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise0_n", Pins("B5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise1_n", Pins("A7"), IOStandard("LVCMOS33")),  # DVT
     # dedicated pins (no I/O standard applicable)
     Subsignal("ana_vn", Pins("K9")),
     Subsignal("ana_vp", Pins("J10")),
     ),

    ("noise", 0,
     Subsignal("noisebias_on", Pins("E17"), IOStandard("LVCMOS33")),  # DVT
     # Noise generator
     Subsignal("noise_on", Pins("P14 R13"), IOStandard("LVCMOS18")),
     ),
    # Power control signals
    ("power", 0,
     Subsignal("audio_on", Pins("B7"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("fpga_sys_on", Pins("A5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("allow_up5k_n", Pins("B14"), IOStandard("LVCMOS33")),
     Subsignal("pwr_s0", Pins("U6"), IOStandard("LVCMOS18")),
     # Subsignal("pwr_s1",       Pins("L13"), IOStandard("LVCMOS18")),  # DVT # PVT convert to "com hold"
     # vibe motor
     Subsignal("vibe_on", Pins("G13"), IOStandard("LVCMOS33")),  # PVT
     # reset EC
     Subsignal("reset_ec", Pins("M6"), IOStandard("LVCMOS18")),
     # PVT -- allow FPGA to recover crashed EC (invert polarity)
     # USB_CC DFP attach
     Subsignal("cc_id", Pins("D18"), IOStandard("LVCMOS33")),  # DVT
     # turn on the UP5K in case we are woken up by RTC
     Subsignal("up5k_on", Pins("G18"), IOStandard("LVCMOS33")),  # DVT -- T_TO_U_ON
     Subsignal("boostmode", Pins("H16"), IOStandard("LVCMOS33"), Misc("PULLDOWN True"), Misc("DRIVE=4")),  # PVT - for sourcing power in USB host mode
     Subsignal("selfdestruct", Pins("J14"), IOStandard("LVCMOS33"), Misc("PULLDOWN True"), Misc("DRIVE=16"),),
     # PVT - cut power to BBRAM key and unit in an annoying-to-reset fashion
     Misc("SLEW=SLOW"),
     Misc("DRIVE=4"),
     ),

    # Top-side internal FPC header
     ("gpio", 0, Pins("F14 F15 E16 G15 H15 G16 F18 E18"), IOStandard("LVCMOS33"), Misc("SLEW=SLOW")),  # PVT
]

_io_xous_pvt2 = [
    ("analog", 0,
     Subsignal("usbdet_p", Pins("C3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("usbdet_n", Pins("A3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("vbus_div", Pins("C4"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise0", Pins("C5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise1", Pins("A8"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("gpio2", Pins("E16"), IOStandard("LVCMOS33")), # PVT2
     Subsignal("gpio5", Pins("D7"), IOStandard("LVCMOS33")),  # PVT2
     # diff grounds
     Subsignal("usbdet_p_n", Pins("B3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("usbdet_n_n", Pins("A2"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("vbus_div_n", Pins("B4"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise0_n", Pins("B5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise1_n", Pins("A7"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("gpio2_n", Pins("E17"), IOStandard("LVCMOS33")), # PVT2
     Subsignal("gpio5_n", Pins("C7"), IOStandard("LVCMOS33")),  # PVT2
     # dedicated pins (no I/O standard applicable)
     Subsignal("ana_vn", Pins("K9")),
     Subsignal("ana_vp", Pins("J10")),
     ),

    ("noise", 0,
     Subsignal("noisebias_on", Pins("H14"), IOStandard("LVCMOS33")),  # PVT2
     # Noise generator
     Subsignal("noise_on", Pins("P14 R13"), IOStandard("LVCMOS18")),
     ),
    # Power control signals
    ("power", 0,
     Subsignal("audio_on", Pins("B7"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("fpga_sys_on", Pins("A5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("allow_up5k_n", Pins("B14"), IOStandard("LVCMOS33")),
     Subsignal("pwr_s0", Pins("U6"), IOStandard("LVCMOS18")),
     Subsignal("pwr_s0_replica", Pins("U7"), IOStandard("LVCMOS18")), # PVT2
     # Subsignal("pwr_s1",       Pins("L13"), IOStandard("LVCMOS18")),  # DVT # PVT convert to "com hold"
     # vibe motor
     Subsignal("vibe_on", Pins("G13"), IOStandard("LVCMOS33")),  # PVT
     # reset EC
     Subsignal("reset_ec", Pins("M6"), IOStandard("LVCMOS18")),
     # PVT -- allow FPGA to recover crashed EC (invert polarity)
     # USB_CC DFP attach
     Subsignal("cc_id", Pins("D18"), IOStandard("LVCMOS33")),  # DVT
     # turn on the UP5K in case we are woken up by RTC
     Subsignal("up5k_on", Pins("G18"), IOStandard("LVCMOS33")),  # DVT -- T_TO_U_ON
     Subsignal("boostmode", Pins("H16"), IOStandard("LVCMOS33"), Misc("PULLDOWN True"), Misc("DRIVE=4")),  # PVT - for sourcing power in USB host mode
     Subsignal("selfdestruct", Pins("J14"), IOStandard("LVCMOS33"), Misc("PULLDOWN True"), Misc("DRIVE=16"),),
     # PVT - cut power to BBRAM key and unit in an annoying-to-reset fashion
     Misc("SLEW=SLOW"),
     Misc("DRIVE=4"),
     ),

    # mixed digital/analog: gpio2 and gpio5 are mapped to bogus, non-connected pins (E6/D6)
    ("gpio", 0, Pins("F14 F15 E6 G15 H15 D6 F18 E18"), IOStandard("LVCMOS33"), Misc("SLEW=SLOW")),  # PVT2
]
_io_gpio_digital_only = [ # todo - add a command line config option + mod the analog_pads record to accommodate digital-only mode
    # Top-side internal FPC header
    # digital-only pinout for GPIOs
    ("gpio", 0, Pins("F14 F15 E16 G15 H15 D7 F18 E18"), IOStandard("LVCMOS33"), Misc("SLEW=SLOW")),  # PVT2
]

_io_fw = [
    ("analog", 0,
     Subsignal("usbdet_p", Pins("C3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("usbdet_n", Pins("A3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("vbus_div", Pins("C4"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise0", Pins("C5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise1", Pins("A8"), IOStandard("LVCMOS33")),  # DVT
     # diff grounds
     Subsignal("usbdet_p_n", Pins("B3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("usbdet_n_n", Pins("A2"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("vbus_div_n", Pins("B4"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise0_n", Pins("B5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise1_n", Pins("A7"), IOStandard("LVCMOS33")),  # DVT
     # dedicated pins (no I/O standard applicable)
     Subsignal("ana_vn", Pins("K9")),
     Subsignal("ana_vp", Pins("J10")),
     ),

    # Power control signals
    ("power", 0,
     Subsignal("noisebias_on", Pins("E17"), IOStandard("LVCMOS33")),  # DVT
     # Noise generator
     Subsignal("noise_on", Pins("P14 R13"), IOStandard("LVCMOS18")),

     Subsignal("audio_on", Pins("B7"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("fpga_sys_on", Pins("A5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("allow_up5k_n", Pins("B14"), IOStandard("LVCMOS33")),
     Subsignal("pwr_s0", Pins("U6"), IOStandard("LVCMOS18")),
     # Subsignal("pwr_s1",       Pins("L13"), IOStandard("LVCMOS18")),  # DVT # PVT convert to "com hold"
     # vibe motor
     Subsignal("vibe_on", Pins("G13"), IOStandard("LVCMOS33")),  # PVT
     # reset EC
     Subsignal("reset_ec", Pins("M6"), IOStandard("LVCMOS18")),
     # PVT -- allow FPGA to recover crashed EC (invert polarity)
     # USB_CC DFP attach
     Subsignal("cc_id", Pins("D18"), IOStandard("LVCMOS33")),  # DVT
     # turn on the UP5K in case we are woken up by RTC
     Subsignal("up5k_on", Pins("G18"), IOStandard("LVCMOS33")),  # DVT -- T_TO_U_ON
     Subsignal("boostmode", Pins("H16"), IOStandard("LVCMOS33")),  # PVT - for sourcing power in USB host mode
     Subsignal("selfdestruct", Pins("J14"), IOStandard("LVCMOS33"), Misc("PULLDOWN True")),
     # PVT - cut power to BBRAM key and unit in an annoying-to-reset fashion
     Misc("SLEW=SLOW"),
     Misc("DRIVE=4"),
     ),

    # Top-side internal FPC header
    ("gpio", 0, Pins("F14 F15 E16 G15 H15 G16 F18 E18"), IOStandard("LVCMOS33"), Misc("SLEW=SLOW")),  # PVT
]

_io_dvt = [
    ("analog", 0,
     Subsignal("usbdet_p", Pins("C3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("usbdet_n", Pins("A3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("vbus_div", Pins("C4"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise0", Pins("C5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise1", Pins("A8"), IOStandard("LVCMOS33")),  # DVT
     # diff grounds
     Subsignal("usbdet_p_n", Pins("B3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("usbdet_n_n", Pins("A2"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("vbus_div_n", Pins("B4"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise0_n", Pins("B5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("noise1_n", Pins("A7"), IOStandard("LVCMOS33")),  # DVT
     # dedicated pins (no I/O standard applicable)
     Subsignal("ana_vn", Pins("K9")),
     Subsignal("ana_vp", Pins("J10")),
     ),

    ("noise", 0,
     Subsignal("noisebias_on", Pins("E17"), IOStandard("LVCMOS33")),  # DVT
     # Noise generator
     Subsignal("noise_on", Pins("P14 R13"), IOStandard("LVCMOS18")),
    ),

    # Power control signals
    ("power", 0,
     Subsignal("audio_on", Pins("B7"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("fpga_sys_on", Pins("A5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("allow_up5k_n", Pins("B14"), IOStandard("LVCMOS33")),
     Subsignal("pwr_s0", Pins("U6"), IOStandard("LVCMOS18")),
     # Subsignal("pwr_s1",       Pins("L13"), IOStandard("LVCMOS18")),  # DVT # PVT convert to "com hold"
     # vibe motor
     Subsignal("vibe_on", Pins("H15"), IOStandard("LVCMOS33")),  # PVT
     # reset EC
     Subsignal("reset_ec", Pins("M6"), IOStandard("LVCMOS18")),
     # PVT -- allow FPGA to recover crashed EC (invert polarity)
     # USB_CC DFP attach
     Subsignal("cc_id", Pins("D18"), IOStandard("LVCMOS33")),  # DVT
     # turn on the UP5K in case we are woken up by RTC
     Subsignal("up5k_on", Pins("E18"), IOStandard("LVCMOS33")),  # DVT -- T_TO_U_ON
     Misc("SLEW=SLOW"),
     Misc("DRIVE=4"),
     ),

    # Top-side internal FPC header
    ("gpio", 0, Pins("F14 F15 E16 G15 G16 G13 F18 G18"), IOStandard("LVCMOS33"), Misc("SLEW=SLOW")),  # DVT + dummies to make width the same
]

_io_xous_modnoise = [
    ("analog", 0,
     Subsignal("usbdet_p", Pins("C3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("usbdet_n", Pins("A3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("vbus_div", Pins("C4"), IOStandard("LVCMOS33")),  # DVT
     #Subsignal("noise0", Pins("C5"), IOStandard("LVCMOS33")),  # DVT
     #Subsignal("noise1", Pins("A8"), IOStandard("LVCMOS33")),  # DVT
     # diff grounds
     Subsignal("usbdet_p_n", Pins("B3"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("usbdet_n_n", Pins("A2"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("vbus_div_n", Pins("B4"), IOStandard("LVCMOS33")),  # DVT
     #Subsignal("noise0_n", Pins("B5"), IOStandard("LVCMOS33")),  # DVT
     #Subsignal("noise1_n", Pins("A7"), IOStandard("LVCMOS33")),  # DVT
     # dedicated pins (no I/O standard applicable)
     Subsignal("ana_vn", Pins("K9")),
     Subsignal("ana_vp", Pins("J10")),
     ),

    # Modular noise generator
    ("noise", 0,
     Subsignal("noise_on", Pins("R13"), IOStandard("LVCMOS18"), Misc("SLEW=SLOW"), Misc("DRIVE=12")),
     Subsignal("noise_in", Pins("P14"), IOStandard("LVCMOS18")),
     Subsignal("phase0", Pins("C5"), IOStandard("LVCMOS33"), Misc("SLEW=SLOW")),
     Subsignal("phase1", Pins("A8"), IOStandard("LVCMOS33"), Misc("SLEW=SLOW")),
     ),

    # Power control signals
    ("power", 0,
     Subsignal("audio_on", Pins("B7"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("fpga_sys_on", Pins("A5"), IOStandard("LVCMOS33")),  # DVT
     Subsignal("allow_up5k_n", Pins("B14"), IOStandard("LVCMOS33")),
     Subsignal("pwr_s0", Pins("U6"), IOStandard("LVCMOS18")),
     # Subsignal("pwr_s1",       Pins("L13"), IOStandard("LVCMOS18")),  # DVT # PVT convert to "com hold"
     # vibe motor
     Subsignal("vibe_on", Pins("G13"), IOStandard("LVCMOS33")),  # PVT
     # reset EC
     Subsignal("reset_ec", Pins("M6"), IOStandard("LVCMOS18")),
     # PVT -- allow FPGA to recover crashed EC (invert polarity)
     # USB_CC DFP attach
     Subsignal("cc_id", Pins("D18"), IOStandard("LVCMOS33")),  # DVT
     # turn on the UP5K in case we are woken up by RTC
     Subsignal("up5k_on", Pins("G18"), IOStandard("LVCMOS33")),  # DVT -- T_TO_U_ON
     Subsignal("boostmode", Pins("H16"), IOStandard("LVCMOS33")),  # PVT - for sourcing power in USB host mode
     Subsignal("selfdestruct", Pins("J14"), IOStandard("LVCMOS33"), Misc("PULLDOWN True")),
     # PVT - cut power to BBRAM key and unit in an annoying-to-reset fashion
     Misc("SLEW=SLOW"),
     Misc("DRIVE=4"),
     ),

    # Top-side internal FPC header
    ("gpio", 0, Pins("F14 F15 E16 G15 H15 G16 F18 E18"), IOStandard("LVCMOS33"), Misc("SLEW=SLOW")),  # PVT
]

# use this config to wire the debug bridge UART to the Rpi
_io_uart_debug = [
    ("debug", 0,  # wired to the Rpi
        Subsignal("tx", Pins("V6")),
        Subsignal("rx", Pins("V7"), Misc("PULLUP True")),
        IOStandard("LVCMOS18"),
        Misc("SLEW=SLOW"),
    ),

    ("serial", 0, # wired to the internal flex
        Subsignal("tx", Pins("B18")), # debug0 breakout
        Subsignal("rx", Pins("D15"), Misc("PULLUP True")), # debug1
        IOStandard("LVCMOS33"),
        Misc("SLEW=SLOW"),
     ),
]

# use this config to wire the console UART to the Rpi, and debug bridge to GPIOs
_io_uart_debug_swapped = [
    ("serial", 0, # wired to the RPi
     Subsignal("tx", Pins("V6")),
     Subsignal("rx", Pins("V7"), Misc("PULLUP True")),
     IOStandard("LVCMOS18"),
     Misc("SLEW=SLOW"),
     ),

    ("debug", 0, # wired to the internal flex
     Subsignal("tx", Pins("B18")), # debug0 breakout
     Subsignal("rx", Pins("D15"), Misc("PULLUP True")), # debug1
     IOStandard("LVCMOS33"),
     Misc("SLEW=SLOW"),
     ),
]

# Platform -----------------------------------------------------------------------------------------

class Platform(XilinxPlatform):
    def __init__(self, io, toolchain="vivado", programmer="vivado", part="50", encrypt=False, make_mod=False, bbram=False, strategy='default'):
        part = "xc7s" + part + "-csga324-1il"
        XilinxPlatform.__init__(self, part, io, toolchain=toolchain)

        if strategy != 'default':
            self.toolchain.vivado_route_directive = strategy
            self.toolchain.vivado_post_route_phys_opt_directive = "Explore"  # always explore if we're in a non-default strategy

        # NOTE: to do quad-SPI mode, the QE bit has to be set in the SPINOR status register. OpenOCD
        # won't do this natively, have to find a work-around (like using iMPACT to set it once)
        self.add_platform_command(
            "set_property CONFIG_VOLTAGE 1.8 [current_design]")
        self.add_platform_command(
            "set_property CFGBVS GND [current_design]")
        self.add_platform_command(
            "set_property BITSTREAM.CONFIG.CONFIGRATE 66 [current_design]")
        self.add_platform_command(
            "set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 1 [current_design]")
        self.toolchain.bitstream_commands = [
            "set_property CONFIG_VOLTAGE 1.8 [current_design]",
            "set_property CFGBVS GND [current_design]",
            "set_property BITSTREAM.CONFIG.CONFIGRATE 66 [current_design]",
            "set_property BITSTREAM.CONFIG.SPI_BUSWIDTH 1 [current_design]",
        ]
        if encrypt:
            type = 'eFUSE'
            if bbram:
                type = 'BBRAM'
            self.toolchain.bitstream_commands += [
                "set_property BITSTREAM.ENCRYPTION.ENCRYPT YES [current_design]",
                "set_property BITSTREAM.ENCRYPTION.ENCRYPTKEYSELECT {} [current_design]".format(type),
                "set_property BITSTREAM.ENCRYPTION.KEYFILE ../../dummy.nky [current_design]"
            ]

        self.toolchain.additional_commands += \
            ["write_cfgmem -verbose -force -format bin -interface spix1 -size 64 "
             "-loadbit \"up 0x0 {build_name}.bit\" -file {build_name}.bin"]
        self.programmer = programmer

        self.toolchain.additional_commands += [
            "report_timing -delay_type min_max -max_paths 100 -slack_less_than 0 -sort_by group -input_pins -routable_nets -name failures -file timing-failures.txt"
        ]
        # this routine retained in case we have to re-explore the bitstream to find the location of the ROM LUTs
        if make_mod:
            # build a version of the bitstream with a different INIT value for the ROM lut, so the offset frame can
            # be discovered by diffing
            for bit in range(0, 32):
                for lut in range(4):
                    if lut == 0:
                        lutname = 'A'
                    elif lut == 1:
                        lutname = 'B'
                    elif lut == 2:
                        lutname = 'C'
                    else:
                        lutname = 'D'

                    self.toolchain.additional_commands += ["set_property INIT 64'hA6C355555555A6C3 [get_cells KEYROM" + str(bit) + lutname + "]"]

            self.toolchain.additional_commands += ["write_bitstream -bin_file -force top-mod.bit"]

    def create_programmer(self):
        if self.programmer == "vivado":
            return VivadoProgrammer(flash_part="n25q128-1.8v-spi-x1_x2_x4")
        else:
            raise ValueError("{} programmer is not supported".format(self.programmer))

    def do_finalize(self, fragment):
        XilinxPlatform.do_finalize(self, fragment)

# CRG ----------------------------------------------------------------------------------------------

class CRG(Module, AutoCSR):
    def __init__(self, platform, sys_clk_freq, spinor_edge_delay_ns=2.5):
        self.warm_reset = Signal()
        self.power_down = Signal()
        self.crypto_on = Signal()

        self.clock_domains.cd_sys   = ClockDomain()
        self.clock_domains.cd_spi   = ClockDomain()
        self.clock_domains.cd_lpclk = ClockDomain()
        self.clock_domains.cd_spinor = ClockDomain()
        self.clock_domains.cd_clk200 = ClockDomain()
        self.clock_domains.cd_clk50 = ClockDomain()
        self.clock_domains.cd_usb_48 = ClockDomain()
        self.clock_domains.cd_usb_12 = ClockDomain()
        self.clock_domains.cd_raw_12 = ClockDomain()

        self.clock_domains.cd_clk200_crypto = ClockDomain()
        self.clock_domains.cd_sys_crypto = ClockDomain()
        self.clock_domains.cd_sys_always_on = ClockDomain()
        self.clock_domains.cd_clk50_always_on = ClockDomain()

        # # #

        sysclk_ns = 1e9 / sys_clk_freq
        # convert delay request in ns to degrees, where 360 degrees is one whole clock period
        phase_f = (spinor_edge_delay_ns / sysclk_ns) * 360
        # round phase to the nearest multiple of 7.5 (needs to be a multiple of 45 / CLKOUT2_DIVIDE = 45 / 6 = 7.5
        # note that CLKOUT2_DIVIDE is automatically calculated by mmcm.create_clkout() below
        phase = round(phase_f / 7.5) * 7.5

        clk32khz = platform.request("lpclk")
        self.specials += Instance("BUFG", i_I=clk32khz, o_O=self.cd_lpclk.clk)
        platform.add_platform_command("create_clock -name lpclk -period {:0.3f} [get_nets lpclk]".format(1e9 / 32.768e3))

        clk12 = platform.request("clk12")
        # Note: below feature cannot be used because Litex appends this *after* platform commands! This causes the generated
        # clock derived constraints immediately below to fail, because .xdc file is parsed in-order, and the main clock needs
        # to be created before the derived clocks. Instead, we use the line afterwards.
        # platform.add_period_constraint(clk12, 1e9 / 12e6)
        platform.add_platform_command("create_clock -name clk12 -period {:0.3f} [get_nets clk12]".format(1e9 / 12e6))
        # The above constraint must strictly proceed the below create_generated_clock constraints in the .XDC file

        # This allows PLLs/MMCMEs to be placed anywhere and reference the input clock
        self.clk12_bufg = Signal()
        self.specials += Instance("BUFG", i_I=clk12, o_O=self.clk12_bufg)
        self.comb += self.cd_raw_12.clk.eq(self.clk12_bufg)

        self.submodules.mmcm = mmcm = S7MMCM(speedgrade=-1)
        mmcm.register_clkin(self.clk12_bufg, 12e6)
        # we count on clocks being assigned to the MMCME2_ADV in order. If we make more MMCME2 or shift ordering, these constraints must change.
        mmcm.create_clkout(self.cd_usb_48, 48e6, with_reset=False, buf="bufgce", ce=mmcm.locked) # 48 MHz for USB; always-on
        platform.add_platform_command("create_generated_clock -name usb_48 [get_pins MMCME2_ADV/CLKOUT0]")

        mmcm.create_clkout(self.cd_spi, 20e6, with_reset=False, buf="bufgce", ce=mmcm.locked & ~self.power_down)
        platform.add_platform_command("create_generated_clock -name spi_clk [get_pins MMCME2_ADV/CLKOUT1]")

        mmcm.create_clkout(self.cd_spinor, sys_clk_freq, phase=phase, with_reset=False, buf="bufgce", ce=mmcm.locked & ~self.power_down)  # delayed version for SPINOR cclk (different from COM SPI above)
        platform.add_platform_command("create_generated_clock -name spinor [get_pins MMCME2_ADV/CLKOUT2]")

        # clk200 does not gate off because we want to keep the IDELAYCTRL block "warm"
        mmcm.create_clkout(self.cd_clk200, 200e6, with_reset=False, buf="bufg",
            gated_replicas={self.cd_clk200_crypto : (mmcm.locked & (~self.power_down | self.crypto_on))}) # 200MHz always-on required for IDELAYCTL
        platform.add_platform_command("create_generated_clock -name clk200 [get_pins MMCME2_ADV/CLKOUT3]")

        # clk50 is explicitly for the crypto unit, so it doesn't have the _crypto suffix, consfusingly...
        mmcm.create_clkout(self.cd_clk50, 50e6, with_reset=False, buf="bufgce", ce=(mmcm.locked & (~self.power_down | self.crypto_on)),
            gated_replicas={self.cd_clk50_always_on: mmcm.locked}) # 50MHz for ChaCha conditioner, attached to the always-on TRNG
        platform.add_platform_command("create_generated_clock -name clk50 [get_pins MMCME2_ADV/CLKOUT4]")

        mmcm.create_clkout(self.cd_usb_12, 12e6, with_reset=False, buf="bufgce", ce=mmcm.locked) # 12 MHz for USB; always-on
        platform.add_platform_command("create_generated_clock -name usb_12 [get_pins MMCME2_ADV/CLKOUT5]")

        # needs to be exactly 100MHz hence margin=0
        mmcm.create_clkout(self.cd_sys, sys_clk_freq, margin=0, with_reset=False, buf="bufgce", ce=(~self.power_down & mmcm.locked),
            gated_replicas={self.cd_sys_crypto : (mmcm.locked & (~self.power_down | self.crypto_on)), self.cd_sys_always_on : mmcm.locked})
        platform.add_platform_command("create_generated_clock -name sys_clk [get_pins MMCME2_ADV/CLKOUT6]")

        mmcm.expose_drp()

        # timing to the "S" pins is not sensitive because we don't care if there is an extra clock pulse relative
        # to the gating. Glitch-free operation is guaranteed regardless!
        platform.add_platform_command('set_false_path -through [get_pins BUFGCTRL*/S*]')
        platform.add_platform_command('set_false_path -through [get_nets vns_rst_meta*]') # fixes for a later version of vivado

        self.ignore_locked = Signal()
        reset_combo = Signal()
        self.comb += reset_combo.eq(self.warm_reset | (~mmcm.locked & ~self.ignore_locked))
        # See https://forums.xilinx.com/t5/Other-FPGA-Architecture/MMCM-Behavior-After-Its-PWRDWN-Port-Is-Asserted-and-Then/td-p/792324
        # "The DRP functional logic itself does not behave differently for PWRDWN or RST.
        # The "registers" programmed previously through the DRP (or any other once) are not affected either
        # way because they are configuration cells and are only overwritten if you re-program the part or
        # by another DRP operation. Typically, from an application perspective, PWRDWN and RST are identical.
        # The difference is obviously that in the PWRDWN case the MMCM completely shuts down for an extended period
        # of time even if asserted only briefly. Takes a while to bring back the regulators vs simply reset.
        # In addition, since power is turned of, it takes longer to reacquire LOCK vs RST because the VCO starts from scratch."
        #self.comb += mmcm.reset.eq(self.power_down)
        #self.comb += mmcm.power_down.eq(self.power_down)
        self.specials += [
            AsyncResetSynchronizer(self.cd_usb_48, reset_combo),
            AsyncResetSynchronizer(self.cd_spi, reset_combo),
            AsyncResetSynchronizer(self.cd_spinor, reset_combo),
            AsyncResetSynchronizer(self.cd_clk200, reset_combo),
            AsyncResetSynchronizer(self.cd_clk50, reset_combo),
            AsyncResetSynchronizer(self.cd_usb_12, reset_combo),
            AsyncResetSynchronizer(self.cd_sys, reset_combo),

            AsyncResetSynchronizer(self.cd_clk200_crypto, reset_combo),
            AsyncResetSynchronizer(self.cd_sys_crypto, reset_combo),

            AsyncResetSynchronizer(self.cd_sys_always_on, reset_combo),
            AsyncResetSynchronizer(self.cd_clk50_always_on, reset_combo),
        ]

        # Add an IDELAYCTRL primitive for the SpiOpi block
        self.submodules += S7IDELAYCTRL(self.cd_clk200, reset_cycles=32) # 155ns @ 200MHz, min 59.28ns

# WarmBoot -----------------------------------------------------------------------------------------

class WarmBoot(Module, AutoCSR):
    def __init__(self, parent, reset_vector=0):
        self.soc_reset = CSRStorage(size=8, description="Writing 0xAC to this register will do a full SoC reset, including CRGs and peripherals")
        self.addr = CSRStorage(size=32, reset=reset_vector, description="The address written here will be used as the next reset vector")
        self.cpu_reset = CSRStorage(size=1, description="Writing anything to this register resets the CPU, and the CPU only; does not affect CRG or peripherals")
        self.do_reset = Signal()
        # "Reset Key" is 0xac (0b101011xx)
        self.comb += self.do_reset.eq((self.soc_reset.storage & 0xfc) == 0xac)

# BtEvents -----------------------------------------------------------------------------------------

class BtEvents(Module, AutoCSR, AutoDoc):
    def __init__(self, com, rtc):
        self.submodules.ev = EventManager()
        self.ev.com_int    = EventSourceProcess(edge="rising")   # rising edge triggered
        self.ev.rtc_int    = EventSourceProcess()                # falling edge triggered
        self.ev.finalize()

        com_int = Signal()
        rtc_int = Signal()
        self.specials += MultiReg(com, com_int)
        self.specials += MultiReg(rtc, rtc_int)
        self.comb += self.ev.com_int.trigger.eq(com_int)
        self.comb += self.ev.rtc_int.trigger.eq(rtc_int)
        self.com_pad = Signal()
        self.rtc_pad = Signal()
        self.comb += [
            self.com_pad.eq(com),
            self.rtc_pad.eq(rtc),
        ]

# BtPower ------------------------------------------------------------------------------------------

class BtPower(Module, AutoCSR, AutoDoc):
    def __init__(self, pads, revision='pvt', xous=True):
        self.intro = ModuleDoc("""BtPower - power control pins
        """)

        if xous == True:
            self.power = CSRStorage(fields=[
                CSRField("audio", size=1, description="Write `1` to power on the audio subsystem"),
                CSRField("self", size=1, description="Writing `1` forces self power-on (overrides the EC's ability to power me down)", reset=1),
                CSRField("ec_snoop", size=1, description="Writing `1` allows the insecure EC to snoop a couple keyboard pads for wakeup key sequence recognition"),
                CSRField("state", size=2, description="Current SoC power state. 0x=off or not ready, 10=on and safe to shutdown, 11=on and not safe to shut down, resets to 01 to allow extSRAM access immediately during init", reset=1),
                CSRField("reset_ec", size=1, description="Writing a `1` forces EC into reset. Requires write of `0` to release reset."),
                CSRField("up5k_on", size=1, description="Writing a `1` pulses the UP5K domain to turn on", pulse=True),
                CSRField("boostmode", size=1, description="Writing a `1` causes the USB port to source 5V. To be active only when playing the host role."),
                CSRField("selfdestruct", size=1, description="Set this bit to clear BBRAM AES key (if used) and cut power in an annoying-to-reset fashion"),
                CSRField("crypto_on", size=1, description="Writing a `1` to this bit turns the clock on to the crypto accelerators. Configured to currently override power to `on` at boot to ease system setup.", reset=1),
                CSRField("ignore_locked", size=1, description="Writing a `1` to this bit causes the reset to ignore the PLL lock status"),
                CSRField("disable_wfi", size=1, description="Writing a `1` to this bit causes WFI throttling to be disabled")
            ])
        else:
            self.power = CSRStorage(8, fields=[
                CSRField("audio",     size=1, description="Write `1` to power on the audio subsystem"),
                CSRField("self",      size=1, description="Writing `1` forces self power-on (overrides the EC's ability to power me down)", reset=1),
                CSRField("ec_snoop",  size=1, description="Writing `1` allows the insecure EC to snoop a couple keyboard pads for wakeup key sequence recognition"),
                CSRField("state",     size=2, description="Current SoC power state. 0=off or not ready, 1=on, resets to 1 to allow extSRAM access immediately during init", reset=1),
                CSRField("noisebias", size=1, description="Writing `1` enables the primary bias supply for the noise generator"),
                CSRField("noise",     size=2, description="Controls which of two noise channels are active; all combos valid. noisebias must be on first."),
                CSRField("reset_ec",  size=1, description="Writing a `1` forces EC into reset. Requires write of `0` to release reset."),
                CSRField("up5k_on",   size=1, description="Writing a `1` pulses the UP5K domain to turn on", pulse=True),
                CSRField("boostmode", size=1, description="Writing a `1` causes the USB port to source 5V. To be active only when playing the host role."),
                CSRField("selfdestruct", size=1, description="Set this bit to clear BBRAM AES key (if used) and cut power in an annoying-to-reset fashion")
            ])

        self.clk_status = CSRStatus(fields=[
            CSRField("crypto_on", size=1, description="The actual crypto clock power on signal, after OR'ing between three separate sources (power, sha512, and engine25519)"),
            CSRField("sha_on", size=1, description="Readback of SHA block power setting"),
            CSRField("engine_on", size=1, description="Readback of Engine25519 block power setting"),
            CSRField("btpower_on", size=1, description="Readback of this block's override-on power setting"),
        ])
        self.wakeup_source = CSRStorage(size=8, fields=[
            CSRField("kbd", size=1, reset=1, description="Use the keyboard as wakeup source"),
            CSRField("ticktimer", size=1, reset=1, description="Use the ticktimer as wakeup source"),
            CSRField("timer0", size=1, reset=1, description="Use timer0 (os timer) as wakeup source"),
            CSRField("usb", size=1, reset=1, description="Use USB k-transition as wakeup source"),
            CSRField("audio", size=1, reset=1, description="Use audio FIFO empty as wakeup source"),
            CSRField("com", size=1, reset=1, description="Use COM hold falling edge plus COM irq rising edge as wakeup source"),
            CSRField("rtc", size=1, reset=1, description="Use RTC external interrupt as wakeup source"),
            CSRField("console", size=1, reset=1, description="Use the console UART RX line dropping as wakeup source"),
        ])
        self.kbd_wakeup = Signal()
        self.ticktimer_wakeup = Signal()
        self.timer0_wakeup = Signal()
        self.usb_wakeup = Signal()
        self.audio_wakeup = Signal()
        self.com_wakeup = Signal()
        self.rtc_wakeup = Signal()
        self.console_wakeup = Signal()
        self.specials += MultiReg(self.wakeup_source.fields.kbd, self.kbd_wakeup, "raw_12")
        self.specials += MultiReg(self.wakeup_source.fields.ticktimer, self.ticktimer_wakeup, "raw_12")
        self.specials += MultiReg(self.wakeup_source.fields.timer0, self.timer0_wakeup, "raw_12")
        self.specials += MultiReg(self.wakeup_source.fields.usb, self.usb_wakeup, "raw_12")
        self.specials += MultiReg(self.wakeup_source.fields.audio, self.audio_wakeup, "raw_12")
        self.specials += MultiReg(self.wakeup_source.fields.com, self.com_wakeup, "raw_12")
        self.specials += MultiReg(self.wakeup_source.fields.rtc, self.rtc_wakeup, "raw_12")
        self.specials += MultiReg(self.wakeup_source.fields.console, self.console_wakeup, "raw_12")

        count_bits=31
        count=Signal(count_bits)
        active=Signal(count_bits)
        self.power_down = Signal()
        self.activity_rate = CSRStatus(fields=[
            CSRField("counts_awake", size=count_bits, description="number of counts in the last sample interval that we were active")
        ])
        self.sampling_period = CSRStorage(fields=[
            CSRField("sample_period", size=count_bits, description="Sampling period for counts awake, in 12MHz cycles"),
            CSRField("kill_sampler", size=1, description="When set, permanently disable reporting (in case you don't want the high-resolutionn timing sidechannel)")
        ])
        self.submodules.period_sync = BusSynchronizer(count_bits, "sys", "raw_12")
        self.submodules.period_update = BlindTransfer("sys", "raw_12")
        self.submodules.activity_update_sys = BlindTransfer("raw_12", "sys")
        self.submodules.activity_sync = BusSynchronizer(count_bits, "raw_12", "sys")
        sampler_killed=Signal(reset=0)
        self.sync += [ # one-way door for kill_sampler
            If(self.sampling_period.fields.kill_sampler,
                sampler_killed.eq(1)
            ).Else(
                sampler_killed.eq(sampler_killed)
            )
        ]
        self.comb += [
            If(~sampler_killed,
                self.activity_rate.fields.counts_awake.eq(self.activity_sync.o)
            ).Else(
                self.activity_rate.fields.counts_awake.eq(0xdead)
            )
        ]
        activity_update = Signal()
        self.comb += [
            self.period_sync.i.eq(self.sampling_period.fields.sample_period),
            self.period_update.i.eq(self.sampling_period.re),
            activity_update.eq(self.activity_update_sys.o),
        ]
        self.sync.raw_12 += [
            If((count == 0) | self.period_update.o,
                count.eq(self.period_sync.o),
            ).Else(
                count.eq(count - 1)
            ),
            If(count == 0,
                self.activity_sync.i.eq(active),
                self.activity_update_sys.i.eq(1),
                active.eq(0),
            ).Else(
                self.activity_update_sys.i.eq(0),
                self.activity_sync.i.eq(self.activity_sync.i),
                If(~self.power_down,
                    active.eq(active + 1)
                ).Else(
                    active.eq(active)
                )
            )
        ]
        # future-proofing this: we might want to add e.g. PWM levels and so forth, so give it its own register
        self.vibe = CSRStorage(1, description="Vibration motor configuration register", fields=[
            CSRField("vibe", size=1, description="Turn on vibration motor"),
        ])
        self.comb += [
            pads.audio_on.eq(self.power.fields.audio),
            # This signal automatically enables snoop when SoC is powered down
            pads.allow_up5k_n.eq(~self.power.fields.ec_snoop),
        ]

        if (revision != 'modnoise') and (xous == False):
            self.comb += pads.noise_on.eq(self.power.fields.noise),

        if xous == False:
            self.comb += pads.noisebias_on.eq(self.power.fields.noisebias)
        self.comb += [
            pads.vibe_on.eq(self.vibe.fields.vibe),
            pads.reset_ec.eq(self.power.fields.reset_ec),
        ]
        self.submodules.ev = EventManager()
        self.ev.usb_attach = EventSourcePulse(description="USB attach event")
        self.ev.activity_update = EventSourcePulse(description="update available to activity register")
        self.ev.finalize()
        self.comb += self.ev.activity_update.trigger.eq(activity_update) # this is actually about 9 cycles wide, not strictly a single-cycle pulse, but interrupt latency should be >>9 cycles
        usb_attach = Signal()
        usb_attach_r = Signal()
        self.specials += MultiReg(pads.cc_id, usb_attach)
        self.sync += [
            usb_attach_r.eq(usb_attach),
            self.ev.usb_attach.trigger.eq(~usb_attach & usb_attach_r),  # falling edge trigger
        ]
        up5k_on_pulse = 0.20  # pulse up5k for 200ms to turn it on and have it keep itself on
        up5k_on_count = Signal(26, reset=int(up5k_on_pulse * 100e6))
        self.sync += [
            If(up5k_on_count > 0,
                pads.up5k_on.eq(1),
            ).Else(
                pads.up5k_on.eq(0)
            ),
            If(self.power.fields.up5k_on,
                up5k_on_count.eq(int(up5k_on_pulse * 100e6))
            ).Elif( up5k_on_count > 0,
                up5k_on_count.eq(up5k_on_count - 1),
            ).Else(
                up5k_on_count.eq(0)
            )
        ]

        # 4 cycles (40ns) delay between power-down, and CE & ZZ tri-state. This is to ensure that
        # the CE & ZZ pins are definitely off before allowing the power to drop, or else we'll have RAM corruption
        self.powerdown_override = Signal()
        self.l2_idle = Signal()
        pdo_delay = Signal(4, reset=0)
        self.sync.sys_always_on += [
            pdo_delay[3].eq(self.powerdown_override & self.l2_idle),
            pdo_delay[2].eq(pdo_delay[3]),
            pdo_delay[1].eq(pdo_delay[2]),
            pdo_delay[0].eq(pdo_delay[1]),
        ]
        # Hi-Z driver is less glitchy during power transients
        self.sys_on_ts = TSTriple(1)
        self.specials += self.sys_on_ts.get_tristate(pads.fpga_sys_on)
        self.comb += [
            self.sys_on_ts.oe.eq(self.power.fields.self & ~pdo_delay[0]),
            self.sys_on_ts.o.eq(self.power.fields.self & ~pdo_delay[1]),
        ]

        # Ensure SRAM isolation during reset (CE & ZZ = 1 by pull-ups). Use Hi-Z driver for less glitches.
        s0 = Signal()
        self.pwr_s0_ts = TSTriple(1)
        self.specials += self.pwr_s0_ts.get_tristate(pads.pwr_s0)
        self.comb += [
            s0.eq(self.power.fields.state[0] & ~ResetSignal()),
            self.pwr_s0_ts.oe.eq(s0 & ~pdo_delay[0]),
            self.pwr_s0_ts.o.eq(s0 & ~self.powerdown_override)
        ]
        if (revision == 'pvt2'):
            # replica version to firewall off u-domain manipulation of SRAM CE lines
            self.comb += pads.pwr_s0_replica.eq(s0 & ~self.powerdown_override)

        # Hi-Z driver is less glitchy, prevents boost mode power from re-glitching the power on during power off transitions
        if revision != 'dvt':
            self.boost_ts = TSTriple(1)
            self.specials += self.boost_ts.get_tristate(pads.boostmode)
            self.comb += [
                self.boost_ts.oe.eq(self.power.fields.boostmode),
                self.boost_ts.o.eq(self.power.fields.boostmode)
            ]

            # Hi-Z driver is less glitchy and less likely to trigger the self destruct mechanism on power glitches
            self.sd_ts = TSTriple(1)
            self.specials += self.sd_ts.get_tristate(pads.selfdestruct)
            self.comb += [
                self.sd_ts.oe.eq(self.power.fields.selfdestruct),
                self.sd_ts.o.eq(self.power.fields.selfdestruct),
            ]

# BtGpio -------------------------------------------------------------------------------------------

class BtGpio(Module, AutoDoc, AutoCSR):
    def __init__(self, pads, usb_type="debug"):
        self.intro = ModuleDoc("""BtGpio - GPIO interface for betrusted""")

        gpio_in  = Signal(pads.nbits)
        gpio_out = Signal(pads.nbits)
        gpio_oe  = Signal(pads.nbits)

        for g in range(0, pads.nbits):
            gpio_ts = TSTriple(1)
            self.specials += gpio_ts.get_tristate(pads[g])
            self.comb += [
                gpio_ts.oe.eq(gpio_oe[g]),
                gpio_ts.o.eq(gpio_out[g]),
                gpio_in[g].eq(gpio_ts.i),
            ]

        self.output = CSRStorage(pads.nbits, name="output", description="Values to appear on GPIO when respective `drive` bit is asserted")
        self.input  = CSRStatus(pads.nbits,  name="input",  description="Value measured on the respective GPIO pin")
        self.drive  = CSRStorage(pads.nbits, name="drive",  description="When a bit is set to `1`, the respective pad drives its value out")
        self.intena = CSRStatus(pads.nbits,  name="intena", description="Enable interrupts when a respective bit is set")
        self.intpol = CSRStatus(pads.nbits,  name="intpol", description="When a bit is `1`, falling-edges cause interrupts. Otherwise, rising edges cause interrupts.")

        self.uartsel = CSRStorage(2, name="uartsel", description="Used to select which UART is routed to physical pins, 00 = kernel debug, 01 = console, others reserved based on build")
        self.debug = CSRStorage(description="Various debugging configurations", fields = [
            CSRField(name="wfi", size=1,
                description="Whet set, patches CRG powerdown into GPIO0 instead of the usual data line. Must configure as output for the value to appear on the pin"),
            CSRField(name="wakeup", size=1,
                description="Whet set, patches wakeup signal into GPIO1 instead of the usual data line. Must configure as output for the value to appear on the pin"),
        ])
        if usb_type != 'spinal':
            self.usbdisable = CSRStorage(1, name="usbdisable", description="When set to ``1``, USB debug is limited by remapping all wishbone request addresses to 0x8000_0000")

        self.debug_wakeup = Signal()
        self.debug_wfi = Signal()
        self.specials += MultiReg(gpio_in, self.input.status)
        self.comb += [
            gpio_out[2:].eq(self.output.storage[2:]),
            gpio_oe.eq(self.drive.storage),
            If(self.debug.fields.wfi,
                gpio_out[0].eq(self.debug_wfi)
            ).Else(
                gpio_out[0].eq(self.output.storage[0])
            ),
            If(self.debug.fields.wakeup,
                gpio_out[1].eq(self.debug_wakeup)
            ).Else(
                gpio_out[1].eq(self.output.storage[1])
            )
        ]

        self.submodules.ev = EventManager()

        for i in range(0, pads.nbits):
            setattr(self.ev, "gpioint" + str(i), EventSourcePulse() ) # pulse => rising edge

        self.ev.finalize()

        for i in range(0, pads.nbits):
            # pull from input.status because it's after the MultiReg synchronizer
            self.comb += getattr(self.ev, "gpioint" + str(i)).trigger.eq(self.input.status[i] ^ self.intpol.status[i])
            # note that if you change the polarity on the interrupt it could trigger an interrupt

# BtSeed -------------------------------------------------------------------------------------------

class BtSeed(Module, AutoDoc, AutoCSR):
    def __init__(self, reproduceable=False):
        self.intro = ModuleDoc("""Place and route seed. Set to a fixed number for reproduceable builds.
        Use a random number or your own number if you are paranoid about hardware implants that target
        fixed locations within the FPGA.""")

        if reproduceable:
          seed_reset = int(4) # chosen by fair dice roll. guaranteed to be random.
        else:
          rng        = SystemRandom()
          seed_reset = rng.getrandbits(64)
        self.seed = CSRStatus(64, name="seed", description="Seed used for the build", reset=seed_reset)

# Keyboard Injector -------------------------------------------------------------------------------

class KeyInject(Module, AutoDoc, AutoCSR):
    def __init__(self):
        self.intro = ModuleDoc("""Used by developers to pass a key from the UART to the keyboard block.
        This is necessary because memory space partitioning plus Rust dependency architecture does
        not allow the logger block to access either the keyboard memory space or any of the facilities
        that would normally allow a message to be passed to the keyboard interface. In particular,
        every package depends upon the logger block; in order for the logger block to talk to the
        keyboard interface, it would need to add the keyboard to its dependencies, which in turn
        depends upon the logger, which creates a circular, unresolvable dependency in Rust. This block
        allows us to break this dependency by creating a separate memory page for a CSR that we can
        map into the logger's memory space, which is capable of raising an interrupt in the Keyboard's
        memory space.""")

        # this is used to permanently disable this backdoor, should a user desire to
        disable = Signal(reset=0)
        self.uart_char = CSRStorage(8, fields = [
            CSRField("char", size=8, description="character value to inject. Automatically raises an interrupt upon write. There is no interlock or FIFO buffering on this, so you can lose characters if you inject too fast."),
        ])
        self.disable = CSRStorage(1, fields = [
            CSRField("disable", size=1, description="writing a 1 permanently disables the block, until the next cold boot", reset=0),
        ])
        self.char = Signal(8)
        self.stb = Signal()
        self.sync += [
            If(self.disable.fields.disable,
                disable.eq(1)
            ).Else(
                disable.eq(disable)
            ),
            If(disable == 0,
                self.stb.eq(self.uart_char.re),
                self.char.eq(self.uart_char.fields.char),
            ).Else(
                self.stb.eq(0),
                self.char.eq(0),
            ),
        ]

# Suspend/Resume ---------------------------------------------------------------------------------

class SusRes(Module, AutoDoc, AutoCSR):
    def __init__(self, bits=64):
        self.intro = ModuleDoc("""Suspend/Resume Helper
        This module is a utility module that assists with suspend and
        resume functions. It has the ability to 'reach into' the Ticktimer space to help coordinate
        a clean, monatomic shut down from a suspend/resume manager that exists in a different,
        isolated process space from the TickTimer.

        It also contains a register which tracks the current resume state. The bootloader controls
        the kernel's behavior by setting this bit prior to resuming operation.
        """)

        self.control = CSRStorage(2, fields=[
            CSRField("pause", description="Write a `1` to this field to request a pause to counting, 0 for free-run. Count pauses on the next tick quanta."),
            CSRField("load", description="If paused, write a `1` to this bit to load a resume value to the timer. If not paused, this bit is ignored.", pulse=True),
        ])
        self.resume_time = CSRStorage(bits, name="resume_time", description="Elapsed time to load. Loaded upon writing `1` to the load bit in the control register. This will immediately affect the msleep extension.")
        self.time = CSRStatus(bits, name="time", description="""Cycle-accurate mirror copy of time in systicks, from the TickTimer""")
        self.status = CSRStatus(1, fields=[
            CSRField("paused", description="When set, indicates that the counter has been paused")
        ])
        self.state = CSRStorage(2, fields=[
            CSRField("resume", description="Used to transfer the resume state information from the loader to Xous. If set, indicates we are on the resume half of a suspend/resume."),
            CSRField("was_forced", description="Used by the bootloader to indicate to the kernel if the current resume was from a forced suspend (e.g. a timeout happened and a server may be unclean."),
        ])
        self.resume = Signal()
        self.comb += self.resume.eq(self.state.fields.resume)
        self.powerdown = CSRStorage(1, fields=[
            CSRField("powerdown", description="Write a `1` to force an immediate powerdown. Use with care.", reset=0)
        ])
        self.powerdown_override = Signal()
        self.comb += self.powerdown_override.eq(self.powerdown.fields.powerdown)

        self.wfi = CSRStorage(1, fields=[
            CSRField("override", description="Write a `1` to this register to disable WFI (used to make sure the suspend/resume is not interrupted by a CPU sleep cal)")
        ])
        self.wfi_override = Signal()
        self.comb += self.wfi_override.eq(self.wfi.fields.override)

        self.interrupt = CSRStorage(1, fields=[
            CSRField("interrupt", size = 1, pulse=True,
                description="Writing this causes an interrupt to fire. Used by Xous to initiate suspend/resume from an interrupt context."
            )
        ])
        self.submodules.ev = EventManager()
        self.ev.soft_int = EventSourceProcess()
        self.kernel_resume_interrupt = Signal()
        self.comb += self.ev.soft_int.trigger.eq(self.interrupt.fields.interrupt | self.kernel_resume_interrupt)

# Deterministic timeout ---------------------------------------------------------------------------

class D11cTime(Module, AutoDoc, AutoCSR):
    def __init__(self, count=1638):
        self.intro = ModuleDoc("""Deterministic Timeout
        This module creates a heartbeat that is deterministic. If used correctly, it can help reduce
        timing side channels on secure processes by giving them an independent, coarse source of
        time. The idea is that a secure process may handle a request, and then wait for a heartbeat
        from the D11cTime module to change polarity, which occurs at a regular interval,
        before returning the result.

        There is a trade-off on how frequent the heartbeat is versus information leakage versus
        overall throughput of the secure module's responses. If the heartbeat is faster than the
        maximum time to complete a computation, then information leakage will occur; if it is much
        slower than the maximum time to complete a computation, then performance is reduced. Deterministic
        timeout is not the end-all solution; adding noise and computational confounders are also
        countermeasures to be considered, but this is one of the simpler approaches, and it is relatively
        hardware-efficient.

        This block has been configured to default to {}ms timeout, assuming LPCLK is 32768Hz.
        """.format( (count / 32768.0) * 1000.0 ))

        self.control = CSRStorage(15, fields = [
            CSRField("count", size=15, description="Number of 1/32768 second ticks before creating a heart beat", reset=count),
        ])
        self.heartbeat = CSRStatus(1, fields = [
            CSRField("beat", description="Set to `1` at the next `count` interval rollover since `clear` was set."),
        ])

        slowcnt = Signal(15, reset=count)
        self.submodules.cnt_sync = BusSynchronizer(15, "sys", "lpclk")
        self.comb += [
            self.cnt_sync.i.eq(self.control.fields.count),
            slowcnt.eq(self.cnt_sync.o),
        ]
        counter = Signal(15, reset=count)
        heartbeat = Signal(reset=0)
        self.sync.lpclk += [
            If(counter == 0,
                counter.eq(slowcnt),
                heartbeat.eq(~heartbeat),
            ).Else(
                counter.eq(counter - 1),
            )
        ]
        self.specials += MultiReg(heartbeat, self.heartbeat.fields.beat)

# WFI ---------------------------------------------------------------------------------------------

class Wfi(Module, AutoDoc, AutoCSR):
    def __init__(self):
        self.intro = ModuleDoc("""WFI: wait for interrupt
        Registers to allow the kernel to tell the hardware to throttle clocks until an event happens.
        """)

        self.wfi = CSRStorage(fields=[
            CSRField("wfi", description="Writing a `1` triggers an attempt to sleep clocks until an event happens", pulse=True)
        ])
        self.ignore_locked = CSRStorage(fields = [
            CSRField("ignore_locked", description="Writing a `1` causes the reset condition for the SoC to ignore the locked state of the PLL")
        ])

# SPINOR soft int ----------------------------------------------------------------------------------

class SpinorSoftInt(Module, AutoCSR, AutoDoc):
    def __init__(self):
        self.submodules.ev = EventManager()
        self.ev.spinor_int = EventSourceProcess(description="Used by software to trigger an interrupt context switch for SPINOR handlers.")
        self.ev.finalize()

        self.softint = CSRStorage(fields=[
            CSRField("softint", description="Writing a `1` here triggers a software interrupt for the SPINOR server.", pulse=True)
        ])
        self.comb += self.ev.spinor_int.trigger.eq(self.softint.fields.softint)


# System constants ---------------------------------------------------------------------------------

boot_offset    = 0x500000 # enough space to hold 2x FPGA bitstreams before the firmware start
bios_size      = 0x10000
SPI_FLASH_SIZE = 128 * 1024 * 1024
SRAM_EXT_SIZE  = 0x1000000
prefix = ""  # sometimes 'soc_', sometimes '' prefix Litex is attaching to net names
# changes randomly depending on how the build system feels (currently problems with Chisel doing weird things to net names when CPU core is regenerated)

# BetrustedSoC -------------------------------------------------------------------------------------

class BetrustedSoC(SoCCore):
    # I/O range: 0x80000000-0xfffffffff (not cacheable)
    SoCCore.mem_map = {
        "rom":             0x80000000, # uncached
        "spiflash":        0x20000000,
        "sram_ext":        0x40000000,
        "memlcd":          0xb0000000,
        "audio":           0xe0000000,
        "sha2":            0xe0001000,
        "sha512":          0xe0002000,
        "engine":          0xe0020000,
        "usbdev":          0xe0040000,
        "vexriscv_debug":  0xefff0000, # this doesn't "stick", LiteX overrides it, so if you use it, you will have to hard code it. Also, search & replace for changes.
        "csr":             0xf0000000,
    }

    def __init__(self, platform, revision, sys_clk_freq=int(100e6), legacy_spi=False,
                 xous=False, usb_type='debug', uart_name="crossover", bios_path='boot/boot.bin',
                 puppet=False, use_perfcounter=False,
                 **kwargs):
        assert sys_clk_freq in [int(12e6), int(100e6)]
        global bios_size

        # CPU cluster
        ## For dev work, we're booting from SPI directly. However, for enhanced security
        ## we will eventually want to move to a bitstream-ROM based bootloader that does
        ## a signature verification of the external SPI code before running it. The theory is that
        ## a user will burn a random AES key into their FPGA and encrypt their bitstream to their
        ## unique AES key, creating a root of trust that offers a defense against trivial patch attacks.

        if xous == False:  # raw firmware boots from SPINOR directly; xous boots from default Litex internal ROM
            reset_address = self.mem_map["spiflash"]+boot_offset
            bios_size = 0
        else:
            reset_address = self.mem_map["rom"]

        # SoCCore ----------------------------------------------------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq, csr_data_width=32,
            integrated_rom_size  = 0,    # don't use default ROM
            integrated_rom_init  = None, # bios_path,
            integrated_sram_size = 0,    # Use external SRAM for boot code
            ident                = "Precursor SoC " + revision,
            cpu_type             = "vexriscv",
            csr_paging           = 4096,  # increase paging to 1 page size
            csr_address_width    = 16,    # increase to accommodate larger page size
            with_uart            = False, # implemented manually to allow for UART mux
            uart_name            = uart_name,
            cpu_reset_address    = reset_address,
            with_ctrl            = False,
            with_timer           = False, # override default timer with a timer that operates in a low-power clock domain
            **kwargs)
        # Litex will always try to move the ROM back to 0.
        # Move ROM and RAM to uncached regions - we only use these at boot, and they are already quite fast
        # this helps remove their contribution from the cache tag critical path
        if self.mem_map["rom"] == 0:
            self.mem_map["rom"] += 0x80000000

        # CPU --------------------------------------------------------------------------------------
        self.cpu.use_external_variant("deps/pythondata-cpu-vexriscv/pythondata_cpu_vexriscv/verilog/VexRiscv_BetrustedSoC_Debug.v")
        self.cpu.add_debug()
        self.submodules.reboot = WarmBoot(self, reset_address)
        self.add_csr("reboot")
        warm_reset = Signal()
        wdt_reset = Signal()
        self.comb += warm_reset.eq(self.reboot.do_reset | wdt_reset) # this is patched into the GSR via the SPINOR block (because that's where the STARTUPE2 block lives)
        self.cpu.cpu_params.update(i_externalResetVector=self.reboot.addr.storage)
        # override the default CPU reset so there's more margin on the signal
        # we do *not* patch this into the system reset because it also kicks the Wishbone USB debug bridge, which complicates firmware updates!
        reset_cycles = 32
        cpu_res_ctr = Signal(log2_int(reset_cycles), reset=reset_cycles - 1)
        cpu_reset = Signal(reset=1)
        self.sync += [
            If(self.reboot.cpu_reset.re,
                cpu_reset.eq(1),
                cpu_res_ctr.eq(reset_cycles - 1),
            ).Elif(cpu_res_ctr != 0,
                cpu_res_ctr.eq(cpu_res_ctr - 1)
            ).Else(
                cpu_reset.eq(0)
            ),
        ]
        if puppet:
            self.comb += self.cpu.reset.eq(1)
        else:
            self.comb += self.cpu.reset.eq(cpu_reset)
        # make a custom version of the timer0 core that's in the "always on" domain
        self.submodules.timer0 = ClockDomainsRenamer(cd_remapping={"always_on":"raw_12"})(TimerAlwaysOn())
        self.add_csr("timer0")
        self.add_interrupt("timer0")

        # Uncached boot ROM ---------------------------------------------------------------------
        # this ROM prefers compact size over performance
        rom_bus = wishbone.Interface(data_width=self.bus.data_width)
        rom     = BlockRom(bus=rom_bus, init=bios_path)
        self.bus.add_slave("rom", rom.bus, SoCRegion(origin=self.mem_map["rom"], size=bios_size, mode="r", cached=False))
        self.check_if_exists("rom")
        self.logger.info("Block ROM {} {} {}.".format(
            "rom",
            "added",
            self.bus.regions["rom"]))
        setattr(self.submodules, "rom", rom)

        # Debug cluster ----------------------------------------------------------------------------
        if usb_type == 'device':  # wire up the debug UART automatically if we don't have USB debugging capability
           from litex.soc.cores.uart import UARTWishboneBridge
           self.submodules.uart_bridge = UARTWishboneBridge(platform.request("debug"), sys_clk_freq, baudrate=115200)
           self.add_wb_master(self.uart_bridge.wishbone)
        if puppet == False:
            # the origin is hard-coded because LiteX overrides the mapping at some point.
            self.bus.add_slave("vexriscv_debug", self.cpu.debug_bus, SoCRegion(origin=0xefff0000, size=0x100, cached=False))
            #self.register_mem("vexriscv_debug", 0xefff0000, self.cpu.debug_bus, 0x100)

        # Clockgen cluster -------------------------------------------------------------------------
        self.submodules.crg = CRG(platform, sys_clk_freq, spinor_edge_delay_ns=2.5)
        self.add_csr("crg")
        self.comb += self.crg.warm_reset.eq(warm_reset) # mirror signal here to hit the Async reset injectors
        # lpclk/sys paths are async
        self.platform.add_platform_command('set_clock_groups -asynchronous -group [get_clocks sys_clk] -group [get_clocks lpclk]')
        # 12 always-on/sys paths are async
        self.platform.add_platform_command('set_clock_groups -asynchronous -group [get_clocks sys_clk] -group [get_clocks clk12]')

        # GPIO module ------------------------------------------------------------------------------
        self.submodules.gpio = BtGpio(platform.request("gpio"), usb_type=usb_type)
        self.add_csr("gpio")
        self.add_interrupt("gpio")

        # UART mux ---------------------------------------------------------------------------------
        from litex.soc.cores import uart
        uart_pins = platform.request("serial")
        if uart_name == "crossover": # note -- crossover UART is *much* slower than a physical UART.
            self.submodules.uart = uart.UARTCrossover()
            self.csr.add("uart_phy", use_loc_if_exists=True)
            self.csr.add("uart", use_loc_if_exists=True)
            self.add_interrupt("uart", use_loc_if_exists=True)

            self.submodules.console = uart.UARTCrossover(tx_fifo_depth=16, rx_fifo_depth=16)
            self.csr.add("console")
            self.add_interrupt("console")

        elif uart_name == "serial":
            serial_layout = [("tx", 1), ("rx", 1)]
            kernel_pads = Record(serial_layout)
            console_pads = Record(serial_layout)
            app_uart_pads = Record(serial_layout)
            self.comb += [
                If(self.gpio.uartsel.storage == 0,
                    uart_pins.tx.eq(kernel_pads.tx),
                    kernel_pads.rx.eq(uart_pins.rx),
                ).Elif(self.gpio.uartsel.storage == 1,
                    uart_pins.tx.eq(console_pads.tx),
                    console_pads.rx.eq(uart_pins.rx),
                ).Else(
                    uart_pins.tx.eq(app_uart_pads.tx),
                    app_uart_pads.rx.eq(uart_pins.rx),
                )
            ]
            self.submodules.uart_phy = ClockDomainsRenamer({"sys":"sys_always_on"})(uart.UARTPHY(
                pads=kernel_pads,
                clk_freq=sys_clk_freq,
                baudrate=115200))
            self.submodules.uart = ResetInserter()(
                ClockDomainsRenamer({"sys":"sys_always_on"})(uart.UART(self.uart_phy,
                    tx_fifo_depth=16, rx_fifo_depth=16)
                ))

            self.add_csr("uart_phy")
            self.add_csr("uart")
            self.add_interrupt("uart")

            self.submodules.console_phy = ClockDomainsRenamer({"sys":"sys_always_on"})(uart.UARTPHY(
                pads=console_pads,
                clk_freq=sys_clk_freq,
                baudrate=115200))
            self.submodules.console = ResetInserter()(
                ClockDomainsRenamer({"sys":"sys_always_on"})(uart.UART(self.console_phy,
                    tx_fifo_depth=16, rx_fifo_depth=16)
                ))

            self.add_csr("console_phy")
            self.add_csr("console")
            self.add_interrupt("console")

            # extra PHY for "application" uses -- mainly things like the FCC testing agent
            self.submodules.app_uart_phy = uart.UARTPHY(
                pads=app_uart_pads,
                clk_freq=sys_clk_freq,
                baudrate=115200)
            self.submodules.app_uart = ResetInserter()(
                ClockDomainsRenamer({"sys":"sys_always_on"})(uart.UART(self.app_uart_phy,
                    tx_fifo_depth=16, rx_fifo_depth=16)
                ))

            self.add_csr("app_uart_phy")
            self.add_csr("app_uart")
            self.add_interrupt("app_uart")


        # XADC analog interface---------------------------------------------------------------------

        from litex.soc.cores.xadc import analog_layout
        analog_pads = Record(analog_layout)
        analog = platform.request("analog")
        self.comb += [
            analog_pads.vp.eq(analog.ana_vp),
            analog_pads.vn.eq(analog.ana_vn),
        ]
        # use explicit dummies to tie the analog inputs, otherwise the name space during finalization changes
        # (e.g. FHDL adds 'betrustedsoc_' to the beginning of every netlist name to give a prefix to unnamed signals)
        # notet that the added prefix messes up the .XDC constraints
        dummy4 = Signal(4, reset=0)
        dummy5 = Signal(5, reset=0)
        dummy1 = Signal(1, reset=0)
        if (revision == 'dvt') or (revision == 'pvt'):
            self.comb += analog_pads.vauxp.eq(Cat(dummy4,          # 0,1,2,3
                                             analog.noise1,        # 4
                                             dummy1,               # 5
                                             analog.vbus_div,      # 6
                                             dummy5,               # 7,8,9,10,11
                                             analog.noise0,        # 12
                                             dummy1,               # 13
                                             analog.usbdet_p,      # 14
                                             analog.usbdet_n,      # 15
                                        )),
            self.comb += analog_pads.vauxn.eq(Cat(dummy4,          # 0,1,2,3
                                             analog.noise1_n,      # 4
                                             dummy1,               # 5
                                             analog.vbus_div_n,    # 6
                                             dummy5,               # 7,8,9,10,11
                                             analog.noise0_n,      # 12
                                             dummy1,               # 13
                                             analog.usbdet_p_n,    # 14
                                             analog.usbdet_n_n,    # 15
                                        )),
        elif revision == 'modnoise':
            self.comb += analog_pads.vauxp.eq(Cat(dummy4,          # 0,1,2,3
                                             dummy1,               # 4  was noise1
                                             dummy1,               # 5
                                             analog.vbus_div,      # 6
                                             dummy5,               # 7,8,9,10,11
                                             dummy1,               # 12 was noise0
                                             dummy1,               # 13
                                             analog.usbdet_p,      # 14
                                             analog.usbdet_n,      # 15
                                        )),
            self.comb += analog_pads.vauxn.eq(Cat(dummy4,          # 0,1,2,3
                                             dummy1,               # 4  was noise1_n
                                             dummy1,               # 5
                                             analog.vbus_div_n,    # 6
                                             dummy5,               # 7,8,9,10,11
                                             dummy1,               # 12  was noise0_n
                                             dummy1,               # 13
                                             analog.usbdet_p_n,    # 14
                                             analog.usbdet_n_n,    # 15
                                        )),
        elif revision == 'pvt2':
            self.comb += analog_pads.vauxp.eq(Cat(dummy4,          # 0,1,2,3
                                             analog.noise1,        # 4
                                             analog.gpio5,         # 5
                                             analog.vbus_div,      # 6
                                             dummy4,               # 7,8,9,10
                                             analog.gpio2,         # 11
                                             analog.noise0,        # 12
                                             dummy1,               # 13
                                             analog.usbdet_p,      # 14
                                             analog.usbdet_n,      # 15
                                        )),
            self.comb += analog_pads.vauxn.eq(Cat(dummy4,          # 0,1,2,3
                                             analog.noise1_n,      # 4
                                             analog.gpio5_n,       # 5
                                             analog.vbus_div_n,    # 6
                                             dummy4,               # 7,8,9,10
                                             analog.gpio2_n,       # 11
                                             analog.noise0_n,      # 12
                                             dummy1,               # 13
                                             analog.usbdet_p_n,    # 14
                                             analog.usbdet_n_n,    # 15
                                        )),
        else:
            print("Revision not supported, can't place analog pins")

        if xous == True:
            self.submodules.info = info.Info(platform, self.__class__.__name__, use_xadc=False) # xadc is managed by TRNG
        else:
            self.submodules.info = info.Info(platform, self.__class__.__name__, use_xadc=True, analog_pads=analog_pads)
        self.add_csr("info")
        self.platform.add_platform_command('create_generated_clock -name dna_cnt -source [get_pins {net}_reg[0]/Q] -divide_by 2 [get_pins DNA_PORT/CLK]', net=self.info.dna.count)

        # reset ignore - we should not be relying on any _rst signals to clear state in a single cycle!
        self.platform.add_platform_command('set_false_path -through [get_nets *_rst]')

        # all multiregs are false paths by definition. Make it explicit.
        self.platform.add_platform_command('set_false_path -through [get_nets *xilinxmultiregimpl*0]') # covers sys-to-other
        self.platform.add_platform_command('set_false_path -through [get_pins *xilinxmultiregimpl*0_reg/D]') # covers other-to-sys
        self.platform.add_platform_command('set_false_path -through [get_pins *xilinxmultiregimpl*0_reg[*]/D]') # covers other-to-sys

        # External SRAM ----------------------------------------------------------------------------
        # Cache fill time is ~320ns for 8 words.
        if usb_type == 'spinal':
            # smaller cache to reduce resource utilization
            self.submodules.sram_ext = sram_32_cached.SRAM32(platform.request("sram"), rd_timing=7, wr_timing=7, page_rd_timing=3, l2_cache_size=0x1_0000)
        else:
            self.submodules.sram_ext = sram_32_cached.SRAM32(platform.request("sram"), rd_timing=7, wr_timing=7, page_rd_timing=3, l2_cache_size=0x2_0000)
        self.add_csr("sram_ext")
        self.register_mem("sram_ext", self.mem_map["sram_ext"], self.sram_ext.bus, size=SRAM_EXT_SIZE)
        # A bit of a bodge -- the path is actually async, so what we are doing is trying to constrain intra-channel skew by pushing them up against clock limits (PS I'm not even sure this works...)
        self.platform.add_platform_command("set_input_delay -clock [get_clocks sys_clk] -min -add_delay 4.0 [get_ports {{sram_d[*]}}]")
        self.platform.add_platform_command("set_input_delay -clock [get_clocks sys_clk] -max -add_delay 9.0 [get_ports {{sram_d[*]}}]")
        self.platform.add_platform_command("set_output_delay -clock [get_clocks sys_clk] -min -add_delay 0.0 [get_ports {{sram_adr[*] sram_d[*] sram_ce_n sram_oe_n sram_we_n sram_zz_n sram_dm_n[*]}}]")
        self.platform.add_platform_command("set_output_delay -clock [get_clocks sys_clk] -max -add_delay 3.0 [get_ports {{sram_adr[*] sram_d[*] sram_ce_n sram_oe_n sram_we_n sram_zz_n sram_dm_n[*]}}]")
        # ODDR falling edge ignore
        self.platform.add_platform_command("set_false_path -fall_from [get_clocks sys_clk] -through [get_ports {{sram_d[*] sram_adr[*] sram_ce_n sram_oe_n sram_we_n sram_zz_n sram_dm_n[*]}}]")
        self.platform.add_platform_command("set_false_path -fall_to [get_clocks sys_clk] -through [get_ports {{sram_d[*]}}]")
        #self.platform.add_platform_command("set_false_path -fall_from [get_clocks sys_clk] -through [get_nets {net}]", net=self.sram_ext.load)
        #self.platform.add_platform_command("set_false_path -fall_to [get_clocks sys_clk] -through [get_nets {net}]", net=self.sram_ext.load)
        self.platform.add_platform_command("set_false_path -rise_from [get_clocks sys_clk] -fall_to [get_clocks sys_clk]")  # sort of a big hammer but should be OK

        # relax OE driver constraint (setup time of data to write enable edge is 23ns only, 70ns total cycle time given)
        self.platform.add_platform_command("set_multicycle_path 2 -setup -through [get_pins {net}_reg/Q]", net=self.sram_ext.sync_oe_n)
        self.platform.add_platform_command("set_multicycle_path 1 -hold -through [get_pins {net}_reg/Q]", net=self.sram_ext.sync_oe_n)

        # LCD interface ----------------------------------------------------------------------------
        cached_lcd = False  # not caching LCD memory may lead to net improvement as stack & code are not displaced by use-once LCD entries in iterator routines
        self.submodules.memlcd = ClockDomainsRenamer({"sys":"sys_always_on"})(memlcd.MemLCD(platform.request("lcd")))
        self.add_csr("memlcd")
        if cached_lcd:
            self.register_mem("memlcd", self.mem_map["memlcd"], self.memlcd.bus, size=self.memlcd.fb_depth*4)
        else:
            self.bus.add_slave("memlcd", self.memlcd.bus, SoCRegion(origin=self.mem_map["memlcd"], size=self.memlcd.fb_depth*4, mode="rw", cached=False))

        # COM SPI interface ------------------------------------------------------------------------
        if puppet:
           from litex.soc.cores.uart import UARTWishboneBridge
           com_pads = platform.request("com")
           serial_layout = [("tx", 1), ("rx", 1)]
           puppet_pads = Record(serial_layout)
           self.comb += [
               com_pads.copi.eq(puppet_pads.tx),
               puppet_pads.rx.eq(com_pads.cipo)
           ]
           self.submodules.puppet_bridge = ClockDomainsRenamer({"sys":"sys_always_on"})(
               UARTWishboneBridge(pads=puppet_pads, clk_freq=sys_clk_freq, baudrate=115200)
           )
           self.add_wb_master(self.puppet_bridge.wishbone)
        else:
            self.submodules.com = spi.SPIController(platform.request("com"), pipeline_cipo=True)
            self.add_csr("com")
            self.add_interrupt("com")
            # slow down clock period of SPI to 20MHz, this gives us about a 4ns margin for setup for PVT variation
            #   datasheet claims 10.0ns Tc-q max input delay
            #   measurement shows 14.1ns Tc-q using SB_IO primitive on UP5K. Set to 15ns for some safety margin.
            #   measurement shows 21.8ns Tc-q using fabric SB_DFFS to pad on UP5K. This may not be robust at 20MHz.
            # min-delay is minimum Tck-q of EC: how fast can data change relative to spi_clk edge inside FPGA
            self.platform.add_platform_command("set_input_delay -clock [get_clocks spi_clk] -min -add_delay 14.1 [get_ports {{com_cipo}}]")
            # max-delay is maximum Tck-q of EC: what's the longest it can take for data to settle relative to sp_clk edge inside FPGA
            self.platform.add_platform_command("set_input_delay -clock [get_clocks spi_clk] -max -add_delay 21.8 [get_ports {{com_cipo}}]")
            self.platform.add_platform_command("set_output_delay -clock [get_clocks spi_clk] -min -add_delay 5.55 [get_ports {{com_copi com_csn}}]") # UP5K input hold = 5.55
            self.platform.add_platform_command("set_output_delay -clock [get_clocks spi_clk] -max -add_delay 10.0 [get_ports {{com_copi com_csn}}]") # UP5K input setup = -0.5; so could set to -0.5, but we can hit 10...
            # cross domain clocking is handled with explicit software barrires, or with multiregs
            self.platform.add_false_path_constraints(self.crg.cd_sys.clk, self.crg.cd_spi.clk)
            self.platform.add_false_path_constraints(self.crg.cd_spi.clk, self.crg.cd_sys.clk)

        # I2C interface ----------------------------------------------------------------------------
        self.submodules.i2c = i2c.RTLI2C(platform, platform.request("i2c", 0))
        self.add_csr("i2c")
        self.add_interrupt("i2c")

        # Event generation for I2C and COM ---------------------------------------------------------
        self.submodules.btevents = BtEvents(platform.request("com_irq", 0), platform.request("rtc_irq", 0))
        self.add_csr("btevents")
        self.add_interrupt("btevents")

        # Messible for debug -----------------------------------------------------------------------
        self.submodules.messible = messible.Messible()
        self.add_csr("messible")
        self.submodules.messible2 = messible.Messible()
        self.add_csr("messible2")

        # Tick timer -------------------------------------------------------------------------------
        self.submodules.ticktimer = ClockDomainsRenamer(cd_remapping={"always_on":"raw_12"})(ticktimer.TickTimer(1000, 12e6, bits=64))
        self.add_csr("ticktimer")
        self.add_interrupt("ticktimer")

        # Suspend/resume ---------------------------------------------------------------------------
        self.submodules.susres = SusRes(bits=64)
        self.add_csr("susres")
        self.add_interrupt("susres")
        # wire up signals that cross from the ticktimer's CSR space to the susres CSR space. Allows for virtual memory process isolation
        # between the ticktimer and the suspend resume server, while allowing for cycle-accurate timing on suspend and resume.
        self.comb += [
            self.susres.time.status.eq(self.ticktimer.timer),
            self.susres.status.fields.paused.eq(self.ticktimer.paused),
            self.ticktimer.resume_time.eq(self.susres.resume_time.storage),
            self.ticktimer.pause.eq(self.susres.control.fields.pause),
            self.ticktimer.load.eq(self.susres.control.fields.load),
        ]
        # We seem to be able to do suspend/resume without the Resume Kicker, so comment it out as a historical note; delete once the susres path is really well tested.
        # the ResumeKicker is a port that the kernel can map and exclusively own in early boot to coordinate the Resume process
        # it provides a single bit that determines if a Resume should be done, and a signal that's passed to the interrupt
        # that is OR'd with the software interrupt in the SusRes block, allowing the system to re-enter the interrupt context
        # which actually coordinates all the resume activity in userspace.
        #self.submodules.resumekicker = ResumeKicker()
        #self.add_csr("resumekicker")
        #self.comb += [
        #    self.susres.kernel_resume_interrupt.eq(self.resumekicker.kick),
        #    self.resumekicker.resume.eq(self.susres.resume),
        #]

        # Power control pins -----------------------------------------------------------------------
        self.submodules.power = BtPower(platform.request("power"), revision, xous)
        self.add_csr("power")
        self.add_interrupt("power")
        self.comb += self.power.powerdown_override.eq(self.susres.powerdown_override)
        self.comb += self.power.l2_idle.eq(self.sram_ext.cache_idle)

        # SPI flash controller ---------------------------------------------------------------------
        if legacy_spi:
            self.submodules.spinor = spinor.SPINOR(platform, platform.request("spiflash_1x"), size=SPI_FLASH_SIZE)
        else:
            sclk_instance_name="SCLK_ODDR"
            iddr_instance_name="SPI_IDDR"
            cipo_instance_name="CIPO_FDRE"
            spiread=False
            spipads = platform.request("spiflash_8x")
            self.submodules.spinor = S7SPIOPI(spipads,
                    sclk_name=sclk_instance_name, iddr_name=iddr_instance_name, cipo_name=cipo_instance_name, spiread=spiread)
            self.spinor.add_timing_constraints(platform, "spiflash_8x")
            self.specials += MultiReg(warm_reset, self.spinor.gsr)
            self.comb += self.spinor.keyclearb.eq(~self.power.power.fields.selfdestruct),
            # a CSR block for sourcing software interrupts in the spinor server. It's disintegrated because it's a bit
            # painful to insert stuff into the S7SPIOPI block in the LiteX repo.
            self.submodules.spinor_soft_int = SpinorSoftInt()
            self.add_csr("spinor_soft_int")
            self.add_interrupt("spinor_soft_int")

        self.register_mem("spiflash", self.mem_map["spiflash"], self.spinor.bus, size=SPI_FLASH_SIZE)
        self.add_csr("spinor")
        self.add_interrupt("spinor")

        # Keyboard module --------------------------------------------------------------------------
        self.submodules.keyboard = ClockDomainsRenamer(cd_remapping={"kbd":"lpclk", "sys":"sys_always_on"})(keyboard.KeyScan(platform.request("kbd")))
        self.add_csr("keyboard")
        self.add_interrupt("keyboard")
        self.submodules.keyinject = ClockDomainsRenamer({"sys":"sys_always_on"})(KeyInject())
        self.add_csr("keyinject")
        self.comb += [
            self.keyboard.uart_inject.eq(self.keyinject.char),
            self.keyboard.inject_strobe.eq(self.keyinject.stb),
        ]
        # don't worry about timing path of LPCLK to sysclk because the values are explicitly synchronized out of band
        self.platform.add_platform_command('set_false_path -rise_from [get_clocks lpclk] -rise_to [get_clocks sys_clk] -through [get_pins *keyscan*_reg*/D]')

        # Build seed -------------------------------------------------------------------------------
        self.submodules.seed = BtSeed(reproduceable=False)
        self.add_csr("seed")

        # ROM test ---------------------------------------------------------------------------------
        self.submodules.keyrom = KeyRom(platform)
        self.add_csr("keyrom")

        # Audio interfaces -------------------------------------------------------------------------
        from litex.soc.cores.i2s import I2S_FORMAT
        if (revision == 'pvt') or (revision == 'modnoise') or (revision == 'pvt2'):
            self.submodules.audio = ClockDomainsRenamer({"sys":"sys_always_on"})(S7I2S(platform.request("i2s", 0), controller=False,
                frame_format=I2S_FORMAT.I2S_STANDARD, document_interrupts=True))
        else:
            self.submodules.audio = S7I2S(platform.request("i2s", 0), controller=False, document_interrupts=True)
        self.bus.add_slave("audio", self.audio.bus, SoCRegion(origin=self.mem_map["audio"], size=0x4, cached=False))
        self.add_csr("audio")
        self.add_interrupt("audio")

        self.comb += platform.request("au_mclk", 0).eq(self.crg.clk12_bufg)

        if xous == True:
            # Managed TRNG Interface -------------------------------------------------------------------
            from gateware.trng.trng_managed import TrngManaged, TrngManagedKernel, TrngManagedServer
            self.submodules.trng_kernel = ClockDomainsRenamer({"sys":"sys_always_on"})(TrngManagedKernel())
            self.add_csr("trng_kernel")
            self.add_interrupt("trng_kernel")
            self.submodules.trng_server = ClockDomainsRenamer({"sys":"sys_always_on"})(TrngManagedServer(ro_cores=4))
            self.add_csr("trng_server")
            self.add_interrupt("trng_server")
            # put the TRNG proper into an always on domain. It has its own power manager and health tests.
            # The TRNG adds about an 8.5mW power burden when it is in standby mode but clocks on
            if revision == 'dvt':
                patchrev = 'pvt2' # use the PVT2 setup, 'should be fine'
            else:
                patchrev = revision
            self.submodules.trng = ClockDomainsRenamer({"sys":"sys_always_on", "clk50":"clk50_always_on"})(
                TrngManaged(platform, analog_pads, platform.request("noise"), server=self.trng_server, kernel=self.trng_kernel, revision=patchrev, ro_cores=4))
            self.add_csr("trng")

        else:
            # Ring Oscillator TRNG ---------------------------------------------------------------------
            self.submodules.trng_osc = TrngRingOscV2(platform)
            self.add_csr("trng_osc")
            # MEMO: diagnostic option, need to turn off GPIO
            # gpio_pads = platform.request("gpio")
            #### self.comb += gpio_pads[0].eq(self.trng_osc.trng_fast)  # this one rarely needs probing
            # self.comb += gpio_pads[1].eq(self.trng_osc.trng_slow)
            # self.comb += gpio_pads[2].eq(self.trng_osc.trng_raw)

        # AES block --------------------------------------------------------------------------------
        # Note: AES instructions have been inserted into the VexriscV CPU, this is more logic-efficient
        # AES block + regular Vex => 21461 Slice LUTs (65.83%) overall; VexRiscv     has 4936 LUTs, 2327 FFs
        # AES block + AES Vex     => 22626 Slice LUTs (69.40%) overall; VexRiscv+AES has 5164 LUTs, 2398 FFs + 3.57% area
        # no AES block + AES Vex  => 16091 Slice LUTs (49.36%) overall; VexRiscv+AES has 4774 LUTs, 2398 FFs -20.04% area
        # seems moving AES into the CPU is a net 17% area savings. Note that the increased size of the Vex
        # "core" with the AES block is due to the large number of CSRs it requires, which expands the amount of logic
        # in the core as well.
        # AES inside the CPU core should also run faster; iirc the instructions run one round per clock,
        # and the CPU is clocked at 100MHz; the AES core only runs at 50MHz, and also runs one round per clock.
        # Not sure about key scheduling overheads, that could potentially be worse for the in-Vex core.
        # There could also be downsides in terms of sidechannels and correctness; the OpenTitan core is supposedly
        # heavily audited, but so far the AES plugin for Vexriscv has only been lightly tested.
        #
        # Thus, we remind ourselves of the availability of this core option with this comment.
        if xous == False:
            self.submodules.aes = aes.Aes(platform)
            self.add_csr("aes")

        # SHA-256 block ----------------------------------------------------------------------------
        #self.submodules.sha2 = sha2.Hmac(platform)
        #self.add_csr("sha2")
        #self.add_interrupt("sha2")
        #self.bus.add_slave("sha2", self.sha2.bus, SoCRegion(origin=self.mem_map["sha2"], size=0x4, cached=False))

        # SHA-512 block ----------------------------------------------------------------------------
        self.submodules.sha512 = sha512.Hmac(platform) # clk50 is only for crypto, so even though it doesn't have the _crypto suffix, it is gated with the _crypto clocks
        self.add_csr("sha512")
        self.add_interrupt("sha512")
        self.bus.add_slave("sha512", self.sha512.bus, SoCRegion(origin=self.mem_map["sha512"], size=0x4, cached=False))

        # Curve25519 engine ------------------------------------------------------------------------
        self.submodules.engine = ClockDomainsRenamer({"eng_clk":"clk50", "rf_clk":"clk200_crypto", "mul_clk":"sys_crypto"})(Engine(platform, self.mem_map["engine"], build_prefix=prefix))
        self.add_csr("engine")
        self.add_interrupt("engine")
        self.bus.add_slave("engine", self.engine.bus, SoCRegion(origin=self.mem_map["engine"], size=0x2_0000, cached=False))

        # JTAG self-provisioning block -------------------------------------------------------------
        self.submodules.jtag = jtag_phy.BtJtag(platform.request("jtag"))
        self.add_csr("jtag")

        # Watchdog Timer ---------------------------------------------------------------------------
        self.submodules.wdt = WDT(platform)
        self.add_csr("wdt")
        self.comb += [
            # the STARTUPE2 block is in the SPINOR module, have to reach in and monkey patch these signals...
            wdt_reset.eq(self.wdt.gsr),
            self.wdt.cfgmclk.eq(self.spinor.cfgmclk),
        ]

        # USB FS block (located near end because it depends on most other blocks above) ------------
        if usb_type == 'device':
            usb_pads = platform.request("usb")
            usb_iobuf = IoBuf(usb_pads.d_p, usb_pads.d_n, usb_pads.pullup_p)
            self.submodules.usb = TriEndpointInterface(usb_iobuf, cdc=True)
            self.add_csr("usb")
            self.add_interrupt("usb")
            self.platform.add_platform_command("set_false_path -through [get_nets {}usb_usb_core_rx_o_reset]".format(prefix))
            # all multiregs are false paths!
            self.platform.add_platform_command('set_false_path -through [get_pins -filter {{NAME =~ "*D*"}} -of_objects [get_cells xilinxmultireg*]]')
            self.platform.add_platform_command('set_false_path -through [get_pins -filter {{NAME =~ "*Q*"}} -of_objects [get_cells xilinxmultireg*]]')
            # async fifos should be async fifos
            self.platform.add_platform_command('set_false_path -rise_from [get_clocks usb_48] -rise_to [get_clocks usb_12] -through [get_cells -filter {{NAME =~ "storage_3*"}}]')
            self.platform.add_platform_command('set_false_path -rise_from [get_clocks usb_48] -rise_to [get_clocks usb_12] -through [get_cells -filter {{NAME =~ "storage_4*"}}]')
            self.platform.add_platform_command('set_false_path -rise_from [get_clocks usb_12] -rise_to [get_clocks sys_clk] -through [get_cells -filter {{NAME =~ "storage_5*"}}]')
            self.platform.add_platform_command('set_false_path -rise_from [get_clocks usb_12] -rise_to [get_clocks sys_clk] -through [get_cells -filter {{NAME =~ "storage_7*"}}]')
            self.platform.add_platform_command('set_false_path -rise_from [get_clocks sys_clk] -rise_to [get_clocks usb_12] -through [get_cells -filter {{NAME =~ "storage_6*"}}]')
        elif usb_type=='debug':
            from valentyusb.usbcore import io as usbio
            from valentyusb.usbcore.cpu import dummyusb
            usb_pads = platform.request("usb")
            usb_iobuf = usbio.IoBuf(usb_pads.d_p, usb_pads.d_n, usb_pads.pullup_p)
            self.submodules.usb = dummyusb.DummyUsb(usb_iobuf, debug=True, burst=True, cdc=True, relax_timing=True, product="Precursor " + revision)
            self.comb += self.usb.debug_bridge.disable_wb.eq(self.gpio.usbdisable.storage) # wire up the USB disable bit
            self.add_wb_master(self.usb.debug_bridge.wishbone)
            # self.platform.add_platform_command(
            #    'set_false_path -rise_from [get_clocks usb_12] -rise_to [get_clocks sys_clk] -through [get_pins {net}_reg*/D]',
            #     net=self.usb.debug_bridge.write_fifo.dout)
            # self.platform.add_platform_command(
            #     'set_false_path -rise_from [get_clocks sys_clk] -rise_to [get_clocks usb_12] -through [get_pins {net}_reg*/D]',
            #     net=self.usb.debug_bridge.read_fifo.dout)
            # The latest LiteX version rubs out the logical net names and replaces them with generic "storage_##" motifs. Let's pray this is consistent from compile-to-compile...
            self.platform.add_platform_command(
               'set_false_path -rise_from [get_clocks usb_12] -rise_to [get_clocks sys_clk] -through [get_pins storage_12_dat1_reg*/D]')
            self.platform.add_platform_command(
                'set_false_path -rise_from [get_clocks sys_clk] -rise_to [get_clocks usb_12] -through [get_pins storage_13_dat1_reg*/D]')
        elif usb_type == 'spinal':
            from gateware.usb import usb_device
            usb_ios = Record([
                ("dp_i",  1), ("dp_o",  1), ("dp_oe", 1),
                ("dm_i",  1), ("dm_o",  1), ("dm_oe", 1),
            ])
            # usb mux
            # valenty wants a `usb_iobuf` structure with self.usb_[p,n]_[tx,rx] pairs, a self.usb_tx_en, and pull-up pin
            # spinal wants a structure passed to it that defines a usb_ios record and it does the wiring based on that structure
            usb_pads = platform.request("usb")
            select_device=Signal()
            force_reset=Signal()
            self.submodules.usbiobuf = usb_iobuf = usb_device.IoBuf(
                usb_pads.d_p, usb_pads.d_n,
                usb_pullup_pin=usb_pads.pullup_p,
                select_device=select_device,
                force_reset=force_reset,
                alt_ios=usb_ios)

            # spinal core
            self.submodules.usbdev = usb_device.USBDevice(platform, usb_ios)
            self.bus.add_slave("usbdev", self.usbdev.wb_ctrl, SoCRegion(origin=self.mem_map["usbdev"], size=65536, mode="rw", cached=False))
            # all 48/sys paths are async (thanks to charles papon for suggesting this syntax)
            self.platform.add_platform_command('set_clock_groups -asynchronous -group [get_clocks sys_clk] -group [get_clocks usb_48]')
            self.add_csr("usbdev")
            self.add_interrupt("usbdev")

            # wishbone debug core
            from valentyusb.usbcore.cpu import dummyusb
            # this is the list of address ranges that the USB is allowed to access
            filters=[
                (self.mem_map['csr'] + (self.csr.locs['spinor'] * 0x1000), self.mem_map['csr'] + (self.csr.locs['spinor'] + 1) * 0x1000),
                (self.mem_map['csr'] + (self.csr.locs['wdt'] * 0x1000), self.mem_map['csr'] + (self.csr.locs['wdt'] + 1) * 0x1000),
                (self.mem_map['csr'] + (self.csr.locs['reboot'] * 0x1000), self.mem_map['csr'] + (self.csr.locs['reboot'] + 1) * 0x1000),
                # for resetting/halting the CPU ONLY; block other addresses so JTAG debug doesn't work.
                # these addresses are hard-coded because...somewhere in the code above...something...side-effects the address of the debug block
                # and really wants to set it to 0xf00f0000, which is wrong. It's probably one of those things that LiteX has a hard-coded setting for
                # because virtually nobody ever wants to remap it. However, we had to remap it on our system because our CSR space overflows
                # directly into this location, because we set 4k pages between each CSR (and nobody else does this in the LiteX ecosystem,
                # so it's a corner case that nobody else hits).
                # what it should be but is wrong --> (self.mem_map['vexriscv_debug'], self.mem_map['vexriscv_debug'] + 0x4), # for resetting/halting the CPU ONLY; block other addresses so JTAG debug doesn't work.
                (0xefff0000, 0xefff0000 + 0x4), # what we actually have
                (self.mem_map['spiflash'] + 0x27_7000, self.mem_map['spiflash'] + 0x28_0000), # readout of the CSR spec in the gateware region
                (self.mem_map['spiflash'] + 0x50_0000, self.mem_map['spiflash'] + 0x800_0000), # loader through rest of FLASH - should be encrypted/secured by gateware and/or not confidential
            ]
            if use_perfcounter:
                filters += [
                    # allow USB full access to RAM, so that we can readout the contents of the perfcounter. This is very insecure, but
                    # high-resolution performance profiling is also insecure as it facilitates timing attacks. In other words: don't use
                    # this in production!
                    (self.mem_map['sram_ext'], self.mem_map['sram_ext'] + SRAM_EXT_SIZE)
                ]
            self.submodules.usb = dummyusb.DummyUsb(
                usb_iobuf, debug=True, burst=True, cdc=True,
                relax_timing=True, product="Precursor " + revision,
                filters=filters
            )
            self.comb += [
                select_device.eq(self.usbdev.usbselect.fields.select_device),
                force_reset.eq(self.usbdev.usbselect.fields.force_reset),
                self.usb.debug_bridge.disable_wb.eq(self.usbdev.usbdisable.storage)
            ]
            self.add_wb_master(self.usb.debug_bridge.wishbone)
            # 12/sys paths are also async
            self.platform.add_platform_command('set_clock_groups -asynchronous -group [get_clocks sys_clk] -group [get_clocks usb_12]')

        # Lock down both ICAPE2 blocks -------------------------------------------------------------
        # this attempts to make it harder to partially reconfigure a bitstream that attempts to use
        # the ICAP block. An ICAP block can read out everything inside the FPGA, including key ROM,
        # even when the encryption fuses are set for the configuration stream.
        platform.toolchain.attr_translate["icap0"] = ("LOC", "ICAP_X0Y0")
        platform.toolchain.attr_translate["icap1"] = ("LOC", "ICAP_X0Y1")
        self.specials += [
            Instance("ICAPE2", i_I=0, i_CLK=0, i_CSIB=1, i_RDWRB=1,
                     attr={"KEEP", "DONT_TOUCH", "icap0"}
                     ),
            Instance("ICAPE2", i_I=0, i_CLK=0, i_CSIB=1, i_RDWRB=1,
                     attr={"KEEP", "DONT_TOUCH", "icap1"}
                     ),
        ]

        # Deterministic timeout helper ---------------------------------------------------------------
        self.submodules.d11ctime = D11cTime(count=1638)
        self.add_csr("d11ctime")

        # Global, cross-domain power management signals go at the bottom -----------------------------
        self.comb += [
            # if any crypto block wants its power to be on, it gets it. for it to be off, all blocks have to agree to turn it off
            self.crg.crypto_on.eq(self.power.power.fields.crypto_on | self.sha512.power.fields.on | self.engine.power.fields.on),
            # these status field helps debug which blocks are wedging power on
            self.power.clk_status.fields.crypto_on.eq(self.crg.crypto_on),
            self.power.clk_status.fields.sha_on.eq(self.sha512.power.fields.on),
            self.power.clk_status.fields.engine_on.eq(self.engine.power.fields.on),
            self.power.clk_status.fields.btpower_on.eq(self.power.power.fields.crypto_on),
        ]
        # the WFI module takes a WFI cue from the kernel and turns it into a pulse that can trigger
        # a clock gating event
        self.submodules.wfi = Wfi()
        self.add_csr("wfi")
        wfi_always_on = Signal()
        self.submodules.wfi_sync = BlindTransfer("sys", "raw_12")
        self.comb += self.wfi_sync.i.eq(self.wfi.wfi.fields.wfi) # wfi.fields.wfi is a pulsed=True CSR
        self.comb += wfi_always_on.eq(self.wfi_sync.o)
        wfi_always_on_r = Signal()
        wfi_falling_pulse = Signal()
        self.sync.raw_12 += [
            wfi_always_on_r.eq(wfi_always_on),
            wfi_falling_pulse.eq(~wfi_always_on & wfi_always_on_r)
        ]
        # external wakeup interrupts: COM (hold+irq), console uart, keyboard, power, ticktimer, timer0. not wired up (yet?): i2c, gpio, other UARTs
        kbd_wakeup = Signal()
        self.specials += MultiReg(self.keyboard.kbd_wakeup, kbd_wakeup, "raw_12")
        ticktimer_wakeup = Signal()
        self.comb += ticktimer_wakeup.eq(self.ticktimer.alarm_always_on)
        timer0_wakeup = Signal()
        self.comb += timer0_wakeup.eq(self.timer0.trigger_always_on)
        usb_k = Signal()
        self.specials += MultiReg(~usb_pads.d_p & usb_pads.d_n, usb_k, "raw_12")
        usb_extender = Signal(32)
        usb_wakeup = Signal()
        self.sync.raw_12 += [
            If(usb_k,
                usb_extender.eq( int(12e6) ) # set extender to 1s; should be much more than necessary.
            ).Else(
                If(usb_extender > 0,
                    usb_extender.eq(usb_extender - 1)
                ).Else(
                    usb_extender.eq(usb_extender)
                )
            ),
            usb_wakeup.eq(usb_extender != 0)  # stretch any USB "K" signals out to 1s so that firmware updates can work
        ]
        any_wakeup = Signal()
        audio_wakeup = Signal()
        self.specials += MultiReg(self.audio.ev.rx_ready.trigger, audio_wakeup, "raw_12")
        com_irq = Signal()
        self.specials += MultiReg(self.btevents.com_pad, com_irq, "raw_12") # com_irq is rising edge triggered
        com_irq_r = Signal()
        com_irq_wakeup = Signal()
        self.sync.raw_12 += com_irq_r.eq(com_irq)
        self.comb += com_irq_wakeup.eq(~com_irq_r & com_irq) # rising edge trigger
        rtc_wakeup = Signal()
        self.specials += MultiReg(~self.btevents.rtc_pad, rtc_wakeup, "raw_12") # rtc interrupt is active low
        com_hold = Signal()
        com_hold_r = Signal()
        com_hold_wakeup = Signal()
        if puppet == False:
            self.specials += MultiReg(self.com.hold, com_hold, "raw_12")
        self.sync.raw_12 += com_hold_r.eq(com_hold)
        self.comb += com_hold_wakeup.eq(com_hold_r & ~com_hold) # falling edge of hold, wakeup system

        console_wakeup = Signal()
        uart_trigger = Signal()
        self.specials += MultiReg(~uart_pins.rx, uart_trigger, "raw_12")
        # need to stretch out the wakeup signal from the UART: a UART frame is ~1041 12MHz clock cycles long
        # which is long enough for the CPU to go back to sleep again. So keep the UART awake for 2047 cycles
        # after getting a character, to ensure the interrupt handler fires.
        uart_oneshot = Signal(11)
        self.sync.raw_12 += [
            If(uart_trigger,
                uart_oneshot.eq( (2**uart_oneshot.nbits) - 1 )
            ).Elif(uart_oneshot > 0,
                uart_oneshot.eq(uart_oneshot - 1)
            ),
            console_wakeup.eq(uart_oneshot != 0)
        ]

        self.comb += any_wakeup.eq(
            kbd_wakeup & self.power.kbd_wakeup |
            ticktimer_wakeup & self.power.ticktimer_wakeup |
            timer0_wakeup  & self.power.timer0_wakeup |
            usb_wakeup  & self.power.usb_wakeup |
            audio_wakeup  & self.power.audio_wakeup |
            com_hold_wakeup  & self.power.com_wakeup |
            com_irq_wakeup & self.power.com_wakeup |
            rtc_wakeup  & self.power.rtc_wakeup |
            console_wakeup  & self.power.console_wakeup
        )
        allow_wfi = Signal()
        self.specials += MultiReg(~self.power.power.fields.disable_wfi, allow_wfi, "raw_12")
        suspend_pending = Signal()
        self.specials += MultiReg(self.susres.wfi_override, suspend_pending, "raw_12")
        # other sources: COM, and give the screen its own free-running clock so it can update while cpu sleeps
        wfi_engaged = Signal()
        if puppet:
            # disable power management in puppet mode
            self.sync.raw_12 += [
                self.crg.power_down.eq(0),
                wfi_engaged.eq(0),
            ]
        else:
            self.sync.raw_12 += [
                self.crg.power_down.eq(wfi_engaged & allow_wfi & ~suspend_pending),
                # compute the WFI state
                If(any_wakeup, # any wakeup source will bring us out of WFI
                    wfi_engaged.eq(0)
                ).Elif(wfi_falling_pulse & self.crg.mmcm.locked, # if the WFI pulse was seen, or we lose MMCM lock, stop the clocks
                    wfi_engaged.eq(1)
                ).Else(
                    wfi_engaged.eq(wfi_engaged)
                )
            ]
        self.comb += self.power.power_down.eq(self.crg.power_down)
        # when set, this tells the CRG to ignore the "locked" output when computing a reset state from the PLL
        self.comb += self.crg.ignore_locked.eq(self.power.power.fields.ignore_locked | self.wfi.ignore_locked.fields.ignore_locked)

        self.comb += [
            self.gpio.debug_wfi.eq(self.crg.power_down),
            self.gpio.debug_wakeup.eq(any_wakeup),
        ]

        # Performance counter ------------------------------------------------------------------------
        if use_perfcounter:
            self.submodules.perfcounter = perfcounter.PerfCounter(self)
            self.add_csr("perfcounter")

# Build --------------------------------------------------------------------------------------------

def main():
    global _io

    if os.environ['PYTHONHASHSEED'] != "1":
        print( "PYTHONHASHEED must be set to 1 for consistent validation results. Failing to set this results in non-deterministic compilation results")
        return 1
    # used to be -e blank.nky -u debug -x -s NoTimingRelaxation -r pvt2 -p
    # now is -e blank.nky
    parser = argparse.ArgumentParser(description="Build the Betrusted SoC")
    parser.add_argument(
        "-D", "--document-only", default=False, action="store_true", help="Build docs only"
    )
    parser.add_argument(
        "-e", "--encrypt", help="Format output for encryption using the specified dummy key. Image is re-encrypted at sealing time with a secure key.", type=str
    )
    parser.add_argument(
        "-x", "--xous", help="Build for the Xous runtime environment. Defaults to true. Setting the flag disables this.", default=True, action="store_false"
    )
    parser.add_argument(
        "-r", "--revision", choices=['modnoise', 'pvt', 'pvt2', 'dvt'], help="Build for a particular revision. Defaults to 'pvt2'", default='pvt2', type=str,
    )
    parser.add_argument(
        "-u", "--usb-type", choices=['debug', 'device', 'spinal'], help="Select the USB core. Defaults to 'spinal'", default='spinal', type=str,
    )
    parser.add_argument(
        "--puppet", help="Builds a 'puppet' that can be controlled by the UP5K via a Wishbone UART. Replaces COM with the UART.", default=False, action="store_true",
    )
    parser.add_argument(
        "-b", "--bbram", help="encrypt to bbram, not efuse. Defaults to efuse. Only meaningful in -e is also specified.", default=False, action="store_true"
    )
    parser.add_argument(
        "-p", "--physical-uart", help="Disable physical UART. Enables console UART tunelling over wishbone-tool, deactivatces physical pins.", default=True, action="store_false"
    )
    parser.add_argument(
        "-s", "--strategy", choices=['Explore', 'default', 'NoTimingRelaxation'], help="Pick the routing strategy. Defaults to NoTimingRelaxation.", default='NoTimingRelaxation', type=str
    )
    parser.add_argument(
        "-c", "--perfcounter", default=False, help="Build with the performance counter module.", action="store_true",
    )
    parser.add_argument(
        "--simple-boot", help="Fall back to the simple, unsigned bootloader", default=False, action="store_true",
    )

    ##### extract user arguments
    args = parser.parse_args()
    compile_gateware = True
    compile_software = True

    if args.document_only:
        compile_gateware = False
        compile_software = False

    bbram = False
    if args.encrypt == None:
        encrypt = False
    else:
        encrypt = True
        if args.bbram:
            bbram = True

    if (args.revision == 'pvt') or (args.revision == 'modnoise') or (args.revision == 'pvt2') or (args.revision == 'dvt'):
        io = _io_pvt # turns out this core can work on DVT too
    else:
        print("Invalid hardware revision specified: {}; aborting.".format(args.revision))
        sys.exit(1)

    if args.xous and (args.revision == 'pvt'):
        io += _io_xous
    elif args.xous and (args.revision == 'pvt2'):
        io += _io_xous_pvt2
    elif args.xous and (args.revision == 'modnoise'):
        io += _io_xous_modnoise
    elif args.revision == 'dvt':
        io += _io_dvt
    else:
        io += _io_fw

    if args.physical_uart:
        uart_name="serial"
    else:
        uart_name="crossover"

    ##### build the "bios"
    if compile_software:
        if args.simple_boot:
            os.system("riscv64-unknown-elf-as -fpic loader{}loader.S -o loader{}loader.elf".format(os.path.sep, os.path.sep))
            os.system("riscv64-unknown-elf-objcopy -O binary loader{}loader.elf loader{}bios.bin".format(os.path.sep, os.path.sep))
            print("**** WARNING: using 'simple boot' method -- no signature verification checks are done on boot! ****")
            bios_path = 'loader{}bios.bin'.format(os.path.sep)
        else:
            # do a first-pass to create the soc.svd file
            platform = Platform(io, encrypt=encrypt, bbram=bbram, strategy=args.strategy)
            platform.add_extension(_io_uart_debug_swapped)
            soc = BetrustedSoC(platform, args.revision, xous=args.xous, usb_type=args.usb_type, uart_name=uart_name, bios_path=None)
            builder = Builder(soc, output_dir="build", csr_csv="build/csr.csv", csr_svd="build/software/soc.svd",
                compile_software=False, compile_gateware=False)
            builder.software_packages=[] # necessary to bypass Meson dependency checks required by Litex libc
            vns = builder.build(run=False)

            os.system("cd boot && cargo xtask boot-image")
            bios_path = 'boot{}boot.bin'.format(os.path.sep)
    else:
        bios_path=None

    ##### second pass to build the actual chip. Note any changes below need to be reflected into the first pass...might be a good idea to modularize that
    ##### setup platform
    platform = Platform(io, encrypt=encrypt, bbram=bbram, strategy=args.strategy)
    # _io_uart_debug wires debug bridge to Rpi; _io_uart_debug_swapped wires console to Rpi
    platform.add_extension(_io_uart_debug_swapped)

    ##### define the soc
    soc = BetrustedSoC(
        platform,
        args.revision,
        xous=args.xous,
        usb_type=args.usb_type,
        uart_name=uart_name,
        bios_path=bios_path,
        puppet=args.puppet,
        use_perfcounter=args.perfcounter,
    )

    ##### setup the builder and run it
    builder = Builder(soc, output_dir="build",
        csr_csv="build/csr.csv", csr_svd="build/software/soc.svd",
        compile_software=False, compile_gateware=compile_gateware)
    builder.software_packages=[] # necessary to bypass Meson dependency checks required by Litex libc

    vns = builder.build()

    ##### post-build routines
    soc.do_exit(vns)
    lxsocdoc.generate_docs(soc, "build/documentation", note_pulses=True, sphinx_extensions=['sphinx_math_dollar', 'sphinx.ext.mathjax'],
            sphinx_extra_config=r"""
mathjax_config = {
   'tex2jax': {
       'inlineMath': [ ["\\(","\\)"] ],
       'displayMath': [["\\[","\\]"] ],
   },
}""")

    # generate the rom-inject library code
    if ~args.document_only:
        if not os.path.exists('fw/rom-inject/src'): # make rom-inject/src if it doesn't exist, e.g. on clean checkout
            os.mkdir('fw/rom-inject/src')
        with open('fw/rom-inject/src/lib.rs', 'w+') as libfile:
            subprocess.call([sys.executable, './key2bits.py', '-c', '-kkeystore.bin', '-rrom.db'], stdout=libfile)

    # now re-encrypt the binary if needed
    if encrypt and not args.document_only:
        # check if we need to re-encrypt to a set key
        # my.nky -- indicates the fuses have been burned on the target device, and needs re-encryption
        # keystore.bin -- indicates we want to initialize the on-chip key ROM with a set of known values
        if Path(args.encrypt).is_file():
            print('Found {}, re-encrypting binary to the specified fuse settings.'.format(args.encrypt))
            #if not Path('keystore.bin').is_file():  # i think we always want to regenerate this file from source...
            subprocess.call([sys.executable, './gen_keyrom.py', '--efuse-key', args.encrypt, '--dev-pubkey', './devkey/dev-x509.crt', '--output', 'keystore.bin'])

            print('Found keystore.bin, patching bitstream to contain specified keystore values.')
            with open('keystore.patch', 'w') as patchfile:
                subprocess.call([sys.executable, './key2bits.py', '-kkeystore.bin', '-rrom.db'], stdout=patchfile)
                keystore_args = '-pkeystore.patch'
                if bbram:
                    enc = [sys.executable, 'deps/encrypt-bitstream-python/encrypt-bitstream.py', '--bbram','-fbuild/gateware/betrusted_soc.bin', '-idummy.nky', '-k' + args.encrypt, '-obuild/gateware/encrypted'] + [keystore_args]
                else:
                    enc = [sys.executable, 'deps/encrypt-bitstream-python/encrypt-bitstream.py', '-fbuild/gateware/betrusted_soc.bin', '-idummy.nky', '-k' + args.encrypt, '-obuild/gateware/encrypted'] + [keystore_args]

            subprocess.call(enc)

            pad = [sys.executable, './append_csr.py', '-bbuild/gateware/encrypted.bin', '-cbuild/csr.csv', '-obuild/gateware/soc_csr.bin']
            subprocess.call(pad)
        else:
            print('Specified key file {} does not exist'.format(args.encrypt))
            return 1

    return 0

if __name__ == "__main__":
    from datetime import datetime
    start = datetime.now()
    ret = main()
    print("Run completed in {}".format(datetime.now()-start))

    sys.exit(ret)
