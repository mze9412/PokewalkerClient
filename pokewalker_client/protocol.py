"""
Pokewalker IR Protocol Implementation

Handles the low-level IR communication protocol:
- XOR 0xAA encoding/decoding
- Packet structure (8-byte header + payload)
- Checksum calculation
- Session management (advertisement, handshake)
"""

import logging
import struct
import random
from dataclasses import dataclass
from typing import Optional
from enum import IntEnum

logger = logging.getLogger(__name__)


class Command(IntEnum):
    """Pokewalker command codes."""
    # Connection
    ADVERTISE = 0xFC      # Walker advertisement byte
    CONNECT_REQ = 0xFA    # Master connection request
    CONNECT_REPLY = 0xF8  # Slave connection reply
    DISCONNECT = 0xF4     # Disconnect
    
    # EEPROM operations
    EEPROM_WRITE_LO = 0x02      # EEPROM write, low 128 bytes of 256-byte page
    EEPROM_WRITE_HI = 0x82      # EEPROM write, high 128 bytes of 256-byte page
    EEPROM_WRITE_ACK = 0x04     # EEPROM write acknowledgment
    EEPROM_READ_REQ = 0x0C      # EEPROM read request
    EEPROM_READ_REPLY = 0x0E    # EEPROM read reply
    EEPROM_WRITE_RANDOM = 0x0A  # EEPROM write at random address
    
    # Compressed EEPROM writes
    EEPROM_WRITE_COMP_LO = 0x00  # Compressed EEPROM write, low
    EEPROM_WRITE_COMP_HI = 0x80  # Compressed EEPROM write, high
    
    # RAM/MMIO direct write (arbitrary code execution)
    RAM_WRITE = 0x06  # Direct internal memory write
    
    # Identity
    IDENTITY_REQ = 0x20   # Request identity data
    IDENTITY_REPLY = 0x22 # Identity data reply
    
    # Ping
    PING = 0x24
    PONG = 0x26
    
    # Walk control
    WALK_START = 0x5A
    WALK_END = 0x4E
    WALK_END_REPLY = 0x50
    
    # Special events
    GIFT_POKEMON = 0xC2   # Gift event pokemon
    GIFT_ITEM = 0xC4      # Gift event item
    SPECIAL_MAP = 0xC0    # Gift special map
    SPECIAL_ROUTE = 0xC6  # Gift special route
    
    # Stamps
    STAMP_HEART = 0xB8
    STAMP_SPADE = 0xBA
    STAMP_DIAMOND = 0xBC
    STAMP_CLUB = 0xBE


# XOR mask for IR encoding
IR_XOR_MASK = 0xAA


def ir_encode(data: bytes) -> bytes:
    """Encode data for IR transmission by XORing with 0xAA."""
    return bytes(b ^ IR_XOR_MASK for b in data)


def ir_decode(data: bytes) -> bytes:
    """Decode IR-received data by XORing with 0xAA."""
    return bytes(b ^ IR_XOR_MASK for b in data)


def calculate_checksum(data: bytes) -> int:
    """
    Calculate Pokewalker packet checksum.

    Algorithm (from reverse-pokewalker documentation):
    1. Initialize accumulator to 0x0002
    2. For each byte (skipping checksum field at indices 2-3):
       - Even index: add (byte << 8); if overflow add carry 1
       - Odd index:  add byte directly (16-bit wrap)
    3. Byte-swap the 16-bit result
    """
    acc = 0x0002

    for i, byte in enumerate(data):
        if i == 2 or i == 3:
            continue
        if i % 2 == 0:
            new = acc + (byte << 8)
            acc = (new & 0xFFFF) + (1 if new > 0xFFFF else 0)
        else:
            acc = (acc + byte) & 0xFFFF

    return ((acc & 0xFF) << 8) | (acc >> 8)


def verify_checksum(packet: bytes) -> bool:
    """Verify packet checksum is correct."""
    if len(packet) < 8:
        return False
    
    received_checksum = struct.unpack(">H", packet[2:4])[0]
    calculated = calculate_checksum(packet)
    return received_checksum == calculated


@dataclass
class Packet:
    """
    Pokewalker protocol packet.
    
    Header (8 bytes):
    - command: 1 byte
    - extra: 1 byte (often address high byte or flags)
    - checksum: 2 bytes (big-endian)
    - session_id: 4 bytes
    
    Followed by optional payload.
    """
    command: int
    extra: int
    session_id: int
    payload: bytes = b""
    
    @classmethod
    def from_bytes(cls, data: bytes, strict_checksum: bool = True) -> "Packet":
        """Parse a packet from raw bytes (already decoded from IR)."""
        if len(data) < 8:
            raise ValueError(f"Packet too short: {len(data)} bytes")

        command = data[0]
        extra = data[1]
        checksum = struct.unpack(">H", data[2:4])[0]
        session_id = struct.unpack(">I", data[4:8])[0]
        payload = data[8:]

        if strict_checksum and not verify_checksum(data):
            raise ValueError(f"Checksum mismatch")

        return cls(
            command=command,
            extra=extra,
            session_id=session_id,
            payload=payload,
        )
    
    def to_bytes(self) -> bytes:
        """Serialize packet to bytes (before IR encoding)."""
        # Build packet without checksum
        header = struct.pack(
            ">BBHI",
            self.command,
            self.extra,
            0,  # Placeholder for checksum
            self.session_id,
        )
        packet = header + self.payload
        
        # Calculate and insert checksum
        checksum = calculate_checksum(packet)
        packet = packet[:2] + struct.pack(">H", checksum) + packet[4:]
        
        return packet


class PokewalkerProtocol:
    """
    Manages Pokewalker IR protocol communication.
    
    Handles:
    - Connection establishment (advertisement detection, handshake)
    - Packet encoding/decoding
    - Session ID management
    """
    
    def __init__(self, serial_port):
        """
        Initialize protocol handler.
        
        Args:
            serial_port: SerialPort instance for IR communication
        """
        self.serial = serial_port
        self.session_id: Optional[int] = None
        self.connected = False
    
    def wait_for_advertisement(self, timeout: float = 5.0) -> bool:
        """
        Wait for walker advertisement byte (0xFC).
        
        The walker sends 0xFC every few hundred milliseconds when
        in communication mode.
        
        Returns:
            True if advertisement received, False on timeout
        """
        import time
        start = time.time()
        
        while time.time() - start < timeout:
            data = self.serial.read(1, timeout=0.5)
            if data:
                decoded = ir_decode(data)
                if decoded[0] == Command.ADVERTISE:
                    logger.debug(f"Walker advertisement received (raw=0x{data[0]:02X} decoded=0x{decoded[0]:02X})")
                    return True
        
        return False
    
    def connect(self, timeout: float = 5.0) -> bool:
        """
        Establish connection with walker.

        Protocol:
        1. Wait for 0xFC advertisement
        2. Send 0xFA with random session ID
        3. Receive 0xF8 with walker's session ID
        4. XOR both IDs for final session ID

        Returns:
            True if connection established, False otherwise
        """
        import time

        if not self.wait_for_advertisement(timeout):
            return False

        our_session_id = random.randint(0, 0xFFFFFFFF)

        connect_packet = Packet(
            command=Command.CONNECT_REQ,
            extra=0x01,
            session_id=our_session_id,
        )

        # The walker broadcasts ~every 100 ms then listens briefly.
        # Read byte-by-byte so we can resend CONNECT_REQ the instant we see
        # another advertisement, rather than waiting a full second between
        # attempts and missing most of the listen windows.
        start = time.time()
        buffer = b""

        self.serial.flush()
        self._send_packet(connect_packet)

        while time.time() - start < timeout:
            data = self.serial.read(1, timeout=0.1)
            if not data:
                continue

            decoded = ir_decode(data)[0]

            if decoded == Command.ADVERTISE:
                # Walker re-advertised; resend immediately to catch listen window
                buffer = b""
                self.serial.flush()
                self._send_packet(connect_packet)
                continue

            buffer += bytes([decoded])

            # Slide window: try to parse CONNECT_REPLY from accumulated bytes
            while len(buffer) >= 8:
                try:
                    pkt = Packet.from_bytes(buffer)
                    if pkt.command == Command.CONNECT_REPLY:
                        self.session_id = our_session_id ^ pkt.session_id
                        self.connected = True
                        return True
                    buffer = b""
                    break
                except ValueError:
                    buffer = buffer[1:]

        return False
    
    def disconnect(self) -> None:
        """Send disconnect command and close session."""
        if self.connected and self.session_id is not None:
            packet = Packet(
                command=Command.DISCONNECT,
                extra=0x01,
                session_id=self.session_id,
            )
            self._send_packet(packet)
        
        self.connected = False
        self.session_id = None
    
    def send_command(
        self,
        command: int,
        payload: bytes = b"",
        extra: int = 0x01,
        reply_payload_size: Optional[int] = None,
        expected_reply_command: Optional[int] = None,
        timeout: float = 2.0,
    ) -> Optional[Packet]:
        """
        Send a command and wait for response.

        Args:
            command: Command byte
            payload: Optional payload data
            extra: Extra byte (default 0x01 for master)
            reply_payload_size: Expected payload byte count in reply; if given,
                _receive_packet waits until enough bytes are buffered before
                trying to parse, avoiding false checksum matches on short slices.
            expected_reply_command: Command byte we expect in the reply. Used as
                a fallback identifier when checksum fails and session_id is also
                corrupted by IR noise.

        Returns:
            Response packet or None on failure
        """
        if not self.connected or self.session_id is None:
            raise RuntimeError("Not connected")

        packet = Packet(
            command=command,
            extra=extra,
            session_id=self.session_id,
            payload=payload,
        )
        self._send_packet(packet)

        return self._receive_packet(
            timeout=timeout,
            expected_payload_size=reply_payload_size,
            expected_command=expected_reply_command,
        )
    
    def _send_packet(self, packet: Packet) -> None:
        """Encode and send a packet."""
        raw = packet.to_bytes()
        encoded = ir_encode(raw)
        self.serial.write(encoded)
    
    def _receive_packet(
        self,
        timeout: float = 2.0,
        expected_payload_size: Optional[int] = None,
        expected_command: Optional[int] = None,
    ) -> Optional[Packet]:
        """
        Receive and decode a packet.

        If expected_payload_size is given, waits until the buffer holds at least
        8 + expected_payload_size decoded bytes before attempting to parse.  This
        avoids false checksum matches on short prefix slices and ensures we don't
        return a packet with a truncated payload.

        Without expected_payload_size, falls back to the O(n²) sliding-window
        scan (handles leading advertisement noise but may return early on a
        coincidental checksum match).
        """
        import time
        start = time.time()
        buffer = b""
        target = (8 + expected_payload_size) if expected_payload_size is not None else None

        stall_count = 0
        while time.time() - start < timeout:
            data = self.serial.read(256, timeout=0.05)
            if data:
                buffer += ir_decode(data)
                stall_count = 0
                logger.debug(f"_receive_packet: read {len(data)} bytes, buffer now {len(buffer)}, target={target}")

                if target is not None and len(buffer) >= target - 4:
                    # Try the standard scan immediately while we have the data.
                    if len(buffer) >= target:
                        for i in range(len(buffer) - target + 1):
                            for j in range(i + target, len(buffer) + 1):
                                try:
                                    pkt = Packet.from_bytes(buffer[i:j])
                                    logger.debug(f"_receive_packet: immediate scan i={i} j={j} cmd=0x{pkt.command:02X}")
                                    return pkt
                                except ValueError:
                                    continue
                    # Scan failed or not enough bytes: stop accumulating now and
                    # let the post-loop fallback (session_id / command byte) handle it.
                    logger.debug("_receive_packet: near target, breaking for post-loop fallback")
                    break
            else:
                stall_count += 1
                logger.debug(f"_receive_packet: read timeout, buffer={len(buffer)}, target={target}, elapsed={time.time()-start:.2f}s")
                if target is not None and len(buffer) >= target - 4 and stall_count >= 1:
                    logger.debug("_receive_packet: buffer stalled near target, breaking early")
                    break

            if target is not None:
                if len(buffer) < target:
                    continue
                # Variable-size scan starting at `target` bytes: waits for
                # enough data to avoid false positives on short prefixes, and
                # handles walkers that send one extra trailing byte.
                for i in range(len(buffer) - target + 1):
                    for j in range(i + target, len(buffer) + 1):
                        try:
                            pkt = Packet.from_bytes(buffer[i:j])
                            logger.debug(f"_receive_packet: found at i={i} j={j} cmd=0x{pkt.command:02X} payload={len(pkt.payload)}")
                            return pkt
                        except ValueError:
                            continue
                logger.debug(f"_receive_packet: scan exhausted {len(buffer)} bytes, no valid packet found")
                continue

            # Unknown payload length: try every (i, j) pair.
            for i in range(len(buffer)):
                for j in range(i + 8, len(buffer) + 1):
                    try:
                        pkt = Packet.from_bytes(buffer[i:j])
                        logger.debug(f"_receive_packet: found at i={i} j={j} cmd=0x{pkt.command:02X} payload={len(pkt.payload)}")
                        return pkt
                    except ValueError:
                        continue

        logger.debug(f"_receive_packet: timed out, buffer={len(buffer)}, target={target}")

        # Fallback for IR-corrupted packets: accept a near-target-sized slice when
        # we can verify identity by session_id or, if session_id is also corrupted,
        # by expected command byte.  IR drops 1-4 bytes per packet fairly regularly,
        # so allow up to 4 missing bytes (tail is least critical field).
        if target is not None and len(buffer) >= max(4, target - 4):
            session_bytes = (
                struct.pack(">I", self.session_id) if self.session_id is not None else None
            )
            chunk_size = min(target, len(buffer))
            max_offset = len(buffer) - chunk_size

            # Pass 1: exact session_id match (strongest signal)
            for i in range(max_offset + 1):
                candidate = buffer[i : i + chunk_size]
                if session_bytes and candidate[4:8] == session_bytes:
                    logger.warning(
                        f"Checksum failed; accepting offset={i} by session_id match "
                        f"cmd=0x{candidate[0]:02X} payload={len(candidate)-8}B (IR noise)"
                    )
                    return Packet.from_bytes(candidate, strict_checksum=False)

            # Pass 2: command-byte match at offset 0 (weaker, but reliable when we
            # know exactly which reply we're waiting for and the session_id was corrupted).
            # IR noise can also truncate the packet by 1-2 bytes; pad with zeros so
            # Packet.from_bytes has the minimum 8-byte header it requires.
            if expected_command is not None:
                candidate = buffer[:chunk_size]
                if candidate[0] == expected_command:
                    if len(candidate) < 8:
                        candidate = candidate + bytes(8 - len(candidate))
                    logger.warning(
                        f"Checksum + session_id failed; accepting offset=0 by command match "
                        f"cmd=0x{candidate[0]:02X} payload={len(candidate)-8}B (IR noise)"
                    )
                    return Packet.from_bytes(candidate, strict_checksum=False)

        return None
