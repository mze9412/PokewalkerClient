"""
H8/300 Shellcode for Pokewalker Exploitation

Provides shellcode payloads for arbitrary code execution via CMD_06.
Based on dmitry.gr's research on the H8/38606R CPU.

Memory map:
- 0x0000-0xBFFF: ROM
- 0xF020-0xF0FF: MMIO
- 0xF780-0xFF7F: RAM
- 0xFF80-0xFFFF: MMIO

Key addresses:
- 0xF7E0: Main event loop function pointer (overwrite to hijack execution)
- 0xF8D6: IR packet payload buffer
- 0xF956-0xFF40: Safe area for shellcode upload
- 0x0772: sendPacket(r0l=len, r0h=cmd, r1l=extra)
- 0x08D6: IR app main loop (restore to return control)
- 0x1F3E: addWatts(r0l=amount_8bit)
- 0x1F40: addWatts entry for 16-bit amount in r0
- 0x259E: wdt_pet() - pet the watchdog
- 0x693A: setProcToCallByMainInLoop()

SCI3 (IR) registers:
- 0x9B: TDR3 (transmit data register)
- 0x9C: SSR3 (status register, bit 7 = TDRE = tx buffer empty)
"""

import struct
from typing import Optional
from dataclasses import dataclass


# Key memory addresses
class Address:
    """Important memory addresses in the Pokewalker."""
    # RAM
    EVENT_LOOP_PTR = 0xF7E0      # Pointer to current micro-app main loop
    PACKET_BUFFER = 0xF8D6      # IR packet payload buffer
    SHELLCODE_AREA = 0xF956     # Safe area for shellcode upload
    
    # ROM functions
    SEND_PACKET = 0x0772        # sendPacket(r0l=len, r0h=cmd, r1l=extra)
    IR_APP_MAIN = 0x08D6        # IR app main loop
    ADD_WATTS_8 = 0x1F3E        # addWatts with 8-bit parameter
    ADD_WATTS_16 = 0x1F40       # addWatts with 16-bit parameter in r0
    WDT_PET = 0x259E            # Pet the watchdog timer
    SET_PROC = 0x693A           # setProcToCallByMainInLoop(r0)
    COMMON_PROLOGUE = 0xBA42    # Function prologue
    COMMON_EPILOGUE = 0xBA62    # Function epilogue
    
    # MMIO
    SCI_TDR3 = 0x9B             # IR transmit data register
    SCI_SSR3 = 0x9C             # IR status register


@dataclass
class Shellcode:
    """Assembled shellcode with metadata."""
    code: bytes
    upload_address: int
    description: str


def assemble_add_watts(amount: int) -> Shellcode:
    """
    Generate shellcode to add watts.
    
    The ROM function at 0x1F40 takes a 16-bit watt amount in r0.
    Max useful value is 9999.
    
    Args:
        amount: Watts to add (0-65535, but practically 0-9999)
    
    Returns:
        Shellcode to upload and execute
    """
    if amount > 65535:
        raise ValueError("Amount must fit in 16 bits")
    
    # H8/300 assembly:
    # mov.w   #amount, r0    ; 79 00 HH LL
    # jsr     @0x1F40        ; 5E 00 1F 40
    # rts                    ; 54 70
    
    code = bytes([
        0x79, 0x00, (amount >> 8) & 0xFF, amount & 0xFF,  # mov.w #amount, r0
        0x5E, 0x00, 0x1F, 0x40,                           # jsr @0x1F40
        0x54, 0x70,                                        # rts
    ])
    
    return Shellcode(
        code=code,
        upload_address=Address.SHELLCODE_AREA,
        description=f"Add {amount} watts",
    )


def assemble_send_ir_byte(byte_value: int) -> Shellcode:
    """
    Generate shellcode to send a single IR byte (for testing).
    
    Waits for TX buffer space, sends byte, loops forever.
    
    Args:
        byte_value: Byte to send continuously
    
    Returns:
        Shellcode to upload and execute
    """
    # H8/300 assembly (from dmitry.gr):
    # 1:
    #   mov.b   @SCI.SSR3, r0l    ; 28 9C - also sets flags
    #   bpl     1b                 ; 4A FC - loop if TDRE not set
    #   mov.b   #byte, r0l        ; F8 XX
    #   mov.b   r0l, @SCI.TDR3    ; 38 9B - write triggers transmission
    #   bra     1b                 ; 40 F6
    
    code = bytes([
        0x28, 0x9C,              # mov.b @0x9C, r0l
        0x4A, 0xFC,              # bpl -4 (loop if bit 7 clear)
        0xF8, byte_value,        # mov.b #byte, r0l
        0x38, 0x9B,              # mov.b r0l, @0x9B
        0x40, 0xF6,              # bra -10 (back to start)
    ])
    
    return Shellcode(
        code=code,
        upload_address=Address.SHELLCODE_AREA,
        description=f"Send IR byte 0x{byte_value:02X} continuously",
    )


def assemble_rom_dump(start_address: int = 0x0000) -> Shellcode:
    """
    Generate shellcode to dump ROM over IR.
    
    Sends bytes from start_address until watchdog reset (~22KB before reset).
    
    Args:
        start_address: ROM address to start dumping from
    
    Returns:
        Shellcode to upload and execute
    """
    # H8/300 assembly:
    # mov.w   #start, r1        ; 79 01 HH LL
    # 1:
    #   mov.b   @SCI.SSR3, r0l   ; 28 9C
    #   bpl     1b               ; 4A FC
    #   mov.b   @er1+, r0l       ; 6C 18 - read and increment
    #   mov.b   r0l, @SCI.TDR3   ; 38 9B
    #   bra     1b               ; 40 F6
    
    code = bytes([
        0x79, 0x01, (start_address >> 8) & 0xFF, start_address & 0xFF,
        0x28, 0x9C,              # mov.b @0x9C, r0l
        0x4A, 0xFC,              # bpl -4
        0x6C, 0x18,              # mov.b @er1+, r0l
        0x38, 0x9B,              # mov.b r0l, @0x9B
        0x40, 0xF6,              # bra -10
    ])
    
    return Shellcode(
        code=code,
        upload_address=Address.SHELLCODE_AREA,
        description=f"Dump ROM from 0x{start_address:04X}",
    )


def assemble_rom_dump_with_packets(start_address: int = 0x0000) -> Shellcode:
    """
    Generate shellcode to dump ROM using proper packets.
    
    This is the improved method that uses checksummed packets,
    allowing reliable ROM dump without re-syncing.
    
    Sends 384 128-byte packets containing the entire ROM.
    
    Args:
        start_address: ROM address to start dumping from
    
    Returns:
        Shellcode to upload and execute
    """
    # From dmitry.gr's PalmOS app:
    # static const uint8_t rom_dump_exploit_upload_to_0xF956[] = {
    #   0x56,                     // upload address low byte
    #   0x5E, 0x00, 0xBA, 0x42,   // jsr common_prologue
    #   0x19, 0x55,               // sub.w r5, r5
    # lbl_big_loop:
    #   0x79, 0x06, 0xf8, 0xd6,   // mov.w 0xf8d6, r6
    #   0xfc, 0x80,               // mov.b 0x80, r4l
    #   0x7b, 0x5c, 0x59, 0x8f,   // eemov.b
    #   0x79, 0x00, 0xaa, 0x80,   // mov.w #0xaa80, r0
    #   0x5e, 0x00, 0x07, 0x72,   // jsr sendPacket
    #   0x5E, 0x00, 0x25, 0x9E,   // jsr wdt_pet
    #   0x79, 0x25, 0xc0, 0x00,   // cmp.w r5, #0xc000
    #   0x46, 0xe4,               // bne $-0x1c (lbl_big_loop)
    #   0x79, 0x00, 0x08, 0xd6,   // mov.w #&irAppMainLoop, r0
    #   0x5e, 0x00, 0x69, 0x3a,   // jsr setProcToCallByMainInLoop
    #   0x5a, 0x00, 0xba, 0x62    // jmp common_epilogue
    # };
    
    code = bytes([
        0x5E, 0x00, 0xBA, 0x42,   # jsr common_prologue
        0x19, 0x55,               # sub.w r5, r5 (r5 = 0)
        # lbl_big_loop:
        0x79, 0x06, 0xF8, 0xD6,   # mov.w #0xF8D6, r6 (packet buffer)
        0xFC, 0x80,               # mov.b #0x80, r4l (128 bytes)
        0x7B, 0x5C, 0x59, 0x8F,   # eemov.b (copy r4l bytes from er5 to er6, incrementing both)
        0x79, 0x00, 0xAA, 0x80,   # mov.w #0xAA80, r0 (cmd=0xAA, extra=0x80, length calculated)
        0x5E, 0x00, 0x07, 0x72,   # jsr sendPacket
        0x5E, 0x00, 0x25, 0x9E,   # jsr wdt_pet
        0x79, 0x25, 0xC0, 0x00,   # cmp.w #0xC000, r5 (48KB = entire ROM)
        0x46, 0xE4,               # bne lbl_big_loop
        0x79, 0x00, 0x08, 0xD6,   # mov.w #0x08D6, r0 (IR app main loop)
        0x5E, 0x00, 0x69, 0x3A,   # jsr setProcToCallByMainInLoop
        0x5A, 0x00, 0xBA, 0x62,   # jmp common_epilogue
    ])
    
    return Shellcode(
        code=code,
        upload_address=Address.SHELLCODE_AREA,
        description="Dump ROM using checksummed packets",
    )


def create_event_loop_hijack(target_address: int) -> bytes:
    """
    Create payload to hijack the event loop.
    
    Writes target address to 0xF7E0, causing the main loop to call
    our code on next iteration.
    
    Args:
        target_address: Address of shellcode to execute
    
    Returns:
        Payload for CMD_06 (excluding the address byte)
    """
    # The event loop pointer at 0xF7E0 is 16-bit, big-endian
    return struct.pack(">H", target_address)


def restore_event_loop() -> bytes:
    """
    Create payload to restore normal event loop.
    
    Returns:
        Payload for CMD_06 to restore IR app main loop
    """
    return struct.pack(">H", Address.IR_APP_MAIN)


class ShellcodeExecutor:
    """
    Helper class to upload and execute shellcode.
    """
    
    def __init__(self, commands):
        """
        Initialize executor.
        
        Args:
            commands: PokewalkerCommands instance
        """
        self.commands = commands
    
    def upload_shellcode(self, shellcode: Shellcode) -> bool:
        """
        Upload shellcode to RAM.
        
        Args:
            shellcode: Shellcode to upload
        
        Returns:
            True on success, False on failure
        """
        return self.commands.write_ram(shellcode.upload_address, shellcode.code)
    
    def trigger_execution(self, shellcode: Shellcode) -> bool:
        """
        Trigger shellcode execution by hijacking event loop.
        
        Args:
            shellcode: Previously uploaded shellcode
        
        Returns:
            True on success, False on failure
        """
        hijack_payload = create_event_loop_hijack(shellcode.upload_address)
        return self.commands.write_ram(Address.EVENT_LOOP_PTR, hijack_payload)
    
    def restore_normal_operation(self) -> bool:
        """
        Restore normal walker operation.
        
        Returns:
            True on success, False on failure
        """
        restore_payload = restore_event_loop()
        return self.commands.write_ram(Address.EVENT_LOOP_PTR, restore_payload)
    
    def execute(self, shellcode: Shellcode) -> bool:
        """
        Upload and execute shellcode.
        
        Args:
            shellcode: Shellcode to execute
        
        Returns:
            True if upload and trigger succeeded
        """
        if not self.upload_shellcode(shellcode):
            return False
        
        return self.trigger_execution(shellcode)
    
    def add_watts(self, amount: int) -> bool:
        """
        Add watts to the walker.
        
        Args:
            amount: Watts to add (0-9999 recommended)
        
        Returns:
            True on success
        """
        shellcode = assemble_add_watts(amount)
        return self.execute(shellcode)
