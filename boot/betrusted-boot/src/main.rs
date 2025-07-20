#![cfg_attr(target_os = "none", no_std)]
#![cfg_attr(target_os = "none", no_main)]

#![allow(unreachable_code)] // allow debugging of failures to jump out of the bootloader

const VERSION_STR: &'static str = "Vexii Bootloader Shim\n\r";
// v0.2.0 -- intial version
// v0.2.1 -- fix warmboot issue (SHA reset)
// v0.2.2 -- check version & length in header against signed area
// v0.2.3 -- lock out key ROM on signature check failure
// Shim - no security, not for production

const LOADER_DATA_OFFSET: u32 = 0x2050_1000;
const LOADER_SIG_OFFSET: u32 = 0x2050_0000;
// changing the bootloader stack is very tricky. here's some places where it needs to be updated:
// - here
// - inside asm.S for stack guard
// - loader - reserved pages (near bottom of file)
// - loader - a second place for reserved placed (around line 1407)
// - loader - clean suspend marker (around line 1318)
// - susres - clean suspend marker location (around line 144)
// - loader - backup args  (line 1250)
// - loader - backup args  (line 1280)
// should probably fix this to make it easier, except it's splattered across so many moving parts...
const STACK_LEN: u32 = 8192 - (7 * 4); // 7 words for backup kernel args
const STACK_TOP: u32 = 0x4100_0000 - STACK_LEN;

use utralib::generated::*;

mod debug;

/*
    Notes about printing:
      - the println! and write! macros are actually quite expensive in the context of a 32kiB ROM (~4k overhead??)
      - we are trying to get away with direct putc() and tiny_write_str() calls. looks weird for Rust, but it saves a few bytes
*/
#[repr(C)]
struct SignatureInFlash {
    pub version: u32,
    pub signed_len: u32,
    pub signature: [u8; 64],
}

mod panic_handler {
    use core::panic::PanicInfo;
    use crate::debug;
    #[panic_handler]
    fn handle_panic(arg: &PanicInfo) -> ! {
        //crate::println!("{}", _arg);
        let mut uart = debug::Uart {};
        if let Some(s) = arg.payload().downcast_ref::<&str>() {
            uart.tiny_write_str(s);
        } else {
            uart.tiny_write_str("unspecified panic!\n\r");
        }
        loop {}
    }
}

struct Point {
    x: i16,
    y: i16,
}
#[derive(PartialEq, Eq)]
enum Color {
    Light,
    Dark
}
const FB_WIDTH_WORDS: usize = 11;
const FB_WIDTH_PIXELS: usize = 336;
const FB_LINES: usize = 536;
const FB_SIZE: usize = FB_WIDTH_WORDS * FB_LINES; // 44 bytes by 536 lines
// this font is from the embedded graphics crate https://docs.rs/embedded-graphics/0.7.1/embedded_graphics/
const FONT_IMAGE: &'static [u8] = include_bytes!("font6x12_1bpp.raw");
const CHAR_HEIGHT: u32 = 12;
const CHAR_WIDTH: u32 = 6;
const FONT_IMAGE_WIDTH: u32 = 96;
const LEFT_MARGIN: i16 = 10;

struct Gfx {
    csr: utralib::CSR<u32>,
    fb: &'static mut [u32],
}
impl<'a> Gfx {
    pub fn init(&mut self, clk_mhz: u32) {
        self.csr.wfo(utra::memlcd::PRESCALER_PRESCALER, (clk_mhz / 2_000_000) - 1);
    }
    pub fn update_all(&mut self) {
        self.csr.wfo(utra::memlcd::COMMAND_UPDATEALL, 1);
    }
    pub fn update_dirty(&mut self) {
        self.csr.wfo(utra::memlcd::COMMAND_UPDATEDIRTY, 1);
    }
    pub fn busy(&self) -> bool {
        if self.csr.rf(utra::memlcd::BUSY_BUSY) == 1 {
            true
        } else {
            false
        }
    }
    pub fn set_devboot(&mut self) {
        self.csr.wfo(utra::memlcd::DEVBOOT_DEVBOOT, 1);
    }

    fn char_offset(&self, c: char) -> u32 {
        let fallback = ' ' as u32 - ' ' as u32;
        if c < ' ' {
            return fallback;
        }
        if c <= '~' {
            return c as u32 - ' ' as u32;
        }
        fallback
    }
    fn put_digit(&mut self, d: u8, pos: &mut Point) {
        let mut buf: [u8; 4] = [0; 4]; // stack buffer for the character encoding
        let nyb = d & 0xF;
        if nyb < 10 {
            self.msg(((nyb + 0x30) as char).encode_utf8(&mut buf), pos);
        } else {
            self.msg(((nyb + 0x61 - 10) as char).encode_utf8(&mut buf), pos);
        }
    }
    fn put_hex(&mut self, c: u8, pos: &mut Point) {
        self.put_digit(c >> 4, pos);
        self.put_digit(c & 0xF, pos);
    }
    pub fn hex_word(&mut self, word: u32, pos: &mut Point) {
        for &byte in word.to_be_bytes().iter() {
            self.put_hex(byte, pos);
        }
    }
    pub fn msg(&mut self, text: &'a str, pos: &mut Point) {
        // this routine is adapted from the embedded graphics crate https://docs.rs/embedded-graphics/0.7.1/embedded_graphics/
        let char_per_row = FONT_IMAGE_WIDTH / CHAR_WIDTH;
        let mut idx = 0;
        let mut x_update: i16 = 0;
        for current_char in text.chars() {
            let mut char_walk_x = 0;
            let mut char_walk_y = 0;

            loop {
                // Char _code_ offset from first char, most often a space
                // E.g. first char = ' ' (32), target char = '!' (33), offset = 33 - 32 = 1
                let char_offset = self.char_offset(current_char);
                let row = char_offset / char_per_row;

                // Top left corner of character, in pixels
                let char_x = (char_offset - (row * char_per_row)) * CHAR_WIDTH;
                let char_y = row * CHAR_HEIGHT;

                // Bit index
                // = X pixel offset for char
                // + Character row offset (row 0 = 0, row 1 = (192 * 8) = 1536)
                // + X offset for the pixel block that comprises this char
                // + Y offset for pixel block
                let bitmap_bit_index = char_x
                    + (FONT_IMAGE_WIDTH * char_y)
                    + char_walk_x
                    + (char_walk_y * FONT_IMAGE_WIDTH);

                let bitmap_byte = bitmap_bit_index / 8;
                let bitmap_bit = 7 - (bitmap_bit_index % 8);

                let color = if FONT_IMAGE[bitmap_byte as usize] & (1 << bitmap_bit) != 0 {
                    Color::Light
                } else {
                    Color::Dark
                };

                let x = pos.x
                    + (CHAR_WIDTH * idx as u32) as i16
                    + char_walk_x as i16;
                let y = pos.y + char_walk_y as i16;

                // draw color at x, y
                if (current_char as u8 != 0xd) && (current_char as u8 != 0xa) { // don't draw CRLF specials
                    self.draw_pixel(Point{x, y}, color);
                }

                char_walk_x += 1;

                if char_walk_x >= CHAR_WIDTH {
                    char_walk_x = 0;
                    char_walk_y += 1;

                    // Done with this char, move on to the next one
                    if char_walk_y >= CHAR_HEIGHT {
                        if current_char as u8 == 0xd { // '\n'
                            pos.y += CHAR_HEIGHT as i16;
                        } else if current_char as u8 == 0xa { // '\r'
                            pos.x = LEFT_MARGIN as i16;
                            x_update = 0;
                        } else {
                            idx += 1;
                            x_update += CHAR_WIDTH as i16;
                        }

                        break;
                    }
                }
            }
        }
        pos.x += x_update;
        self.update_dirty();
        while self.busy() {}
    }
    pub fn draw_pixel(&mut self, pix: Point, color: Color) {
        let mut clip_y: usize = pix.y as usize;
        if clip_y >= FB_LINES {
            clip_y = FB_LINES - 1;
        }
        let clip_x: usize = pix.x as usize;
        if clip_x >= FB_WIDTH_PIXELS {
            clip_y = FB_WIDTH_PIXELS - 1;
        }
        if color == Color::Light {
            self.fb[(clip_x + clip_y * FB_WIDTH_WORDS * 32) / 32] |= 1 << (clip_x % 32)
        } else {
            self.fb[(clip_x + clip_y * FB_WIDTH_WORDS * 32) / 32] &= !(1 << (clip_x % 32))
        }
        // set the dirty bit on the line that contains the pixel
        self.fb[clip_y * FB_WIDTH_WORDS + (FB_WIDTH_WORDS - 1)] |= 0x1_0000;
    }
}

#[export_name = "rust_entry"]
pub unsafe extern "C" fn rust_entry(_unused1: *const usize, _unused2: u32) -> ! {
    // reset the SHA block, in case we're coming out of a warm reset
    let mut sha = CSR::new(utra::sha512::HW_SHA512_BASE as *mut u32);
    sha.wfo(utra::sha512::POWER_ON, 1);
    sha.wfo(utra::sha512::CONFIG_RESET, 1); // this reset takes ~32 CPU cycles but we do plenty of other stuff
    ///////// end hardware resets

    let mut cursor = Point {x: LEFT_MARGIN, y: 10};

    // initial banner
    let mut uart = debug::Uart {};
    uart.tiny_write_str("  ");

    // clear screen to all black
    let mut gfx = Gfx {
        csr: CSR::new(utra::memlcd::HW_MEMLCD_BASE as *mut u32),
        fb: core::slice::from_raw_parts_mut(utralib::HW_MEMLCD_MEM as *mut u32, FB_SIZE), // unsafe but inside an unsafe already
    };
    gfx.init(100_000_000);

    for word in gfx.fb.iter_mut() {
        *word = 0x0; // set to all black
    }
    gfx.update_all();
    while gfx.busy() { }

    // now characters should actually be able to print
    uart.tiny_write_str(VERSION_STR);
    gfx.msg(VERSION_STR, &mut cursor);

    // always devboot mode because no sign verification in this bootloader
    gfx.set_devboot();

    // check the stack usage
    let stack: &[u32] = core::slice::from_raw_parts(STACK_TOP as *const u32, (STACK_LEN as usize / core::mem::size_of::<u32>()) as usize);
    let mut unused_stack_words = 0;
    for &word in stack.iter() {
        if word != 0xDEAD_C0DE {
            break;
        }
        unused_stack_words += 1;
    }
    uart.tiny_write_str("Free stack: 0x");
    uart.print_hex_word(unused_stack_words * 4);
    gfx.msg("Free stack: 0x", &mut cursor);
    gfx.hex_word(unused_stack_words * 4, &mut cursor);
    uart.newline();

    let wait_kbhit = false;
    if wait_kbhit {
        let mut last_char: u8 = 0;
        loop {
            if let Some(c) = uart.getc() {
                uart.putc(c);
                if c == 0xd { // add an LF to a CR
                    uart.putc(0xa);
                }
                if c == 0xd && last_char == 0x21 { // '!'
                    break;
                }
                last_char = c;
            }
        }
    }
    gfx.msg("\n\r\n\rJumping to loader...\n\r", &mut cursor);
    uart.tiny_write_str("\n\r\n\rJumping to loader...\n\r");

    let mut sha_csr = CSR::new(utra::sha512::HW_SHA512_BASE as *mut u32);
    sha_csr.wfo(utra::sha512::POWER_ON, 0); // cut power to the SHA block; this is the expected default state after the bootloader is done.

    // now jump to the loader once everything checks out.
    start_loader(
        0x2098_0000,  // start of kernel arguments
        0x0,           // this is unused
        0x2050_1000,  // jump address of the loader itself
    );
    uart.tiny_write_str("Should have jumped to loader!");
    uart.newline();
    loop {
    }
}

fn die() {
    let ticktimer = CSR::new(utra::ticktimer::HW_TICKTIMER_BASE as *mut u32);
    let mut power = CSR::new(utra::power::HW_POWER_BASE as *mut u32);
    let mut com = CSR::new(utra::com::HW_COM_BASE as *mut u32);
    let mut start = ticktimer.rf(utra::ticktimer::TIME0_TIME);
    loop {
        // every 15 seconds, attempt to send a power down command
        // any attempt to re-flash the system must halt the CPU before we time-out to this point!
        if ticktimer.rf(utra::ticktimer::TIME0_TIME) - start > 15_000 {
            power.rmwf(utra::power::POWER_STATE, 0);
            power.rmwf(utra::power::POWER_SELF, 0);

            // ship mode is the safest mode -- suitable for long-term storage (~years)
            com.wfo(utra::com::TX_TX, com_rs::ComState::POWER_SHIPMODE.verb as u32);
            while com.rf(utra::com::STATUS_TIP) == 1 {}
            let _ = com.rf(utra::com::RX_RX); // discard the RX result

            start = ticktimer.rf(utra::ticktimer::TIME0_TIME);
        }
    }
}

extern "C" {
    fn start_loader(
        arg_buffer: usize,
        signature: usize,
        loader_addr: usize,
    ) -> !;
}
