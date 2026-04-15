"""
Pokewalker IR Protocol Implementation

Handles the low-level IR communication protocol:
- XOR 0xAA encoding/decoding
- Packet structure (8-byte header + payload)
- Checksum calculation
- Session management (advertisement, handshake)
"""

import struct
import random
from dataclasses import dataclass
from typing import Optional
from enum import IntEnum


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
    
    Algorithm:
    1. Sum all even-indexed bytes
    2. Sum all odd-indexed bytes  
    3. Result = even_sum * 256 + odd_sum
    4. Fold: while top 16 bits set, add top 16 to bottom 16
    
    The checksum bytes (indices 2-3) are treated as 0 during calculation.
    """
    even_sum = 0
    odd_sum = 0
    
    for i, byte in enumerate(data):
        # Skip checksum bytes (indices 2 and 3)
        if i == 2 or i == 3:
            continue
        if i % 2 == 0:
            even_sum += byte
        else:
            odd_sum += byte
    
    checksum = (even_sum << 8) + odd_sum
    
    # Fold until no bits in top 16
    while checksum > 0xFFFF:
        checksum = (checksum & 0xFFFF) + (checksum >> 16)
    
    return checksum


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
    def from_bytes(cls, data: bytes) -> "Packet":
        """Parse a packet from raw bytes (already decoded from IR)."""
        if len(data) < 8:
            raise ValueError(f"Packet too short: {len(data)} bytes")
        
        command = data[0]
        extra = data[1]
        checksum = struct.unpack(">H", data[2:4])[0]
        session_id = struct.unpack(">I", data[4:8])[0]
        payload = data[8:]
        
        # Verify checksum
        if not verify_checksum(data):
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
        # Wait for advertisement
        if not self.wait_for_advertisement(timeout):
            return False
        
        # Generate our session ID
        our_session_id = random.randint(0, 0xFFFFFFFF)
        
        # Send connection request
        connect_packet = Packet(
            command=Command.CONNECT_REQ,
            extra=0x01,  # Master sends with extra=1
            session_id=our_session_id,
        )
        self._send_packet(connect_packet)
        
        # Wait for reply
        reply = self._receive_packet(timeout=2.0)
        if reply is None or reply.command != Command.CONNECT_REPLY:
            return False
        
        # Calculate final session ID (XOR of both)
        their_session_id = reply.session_id
        self.session_id = our_session_id ^ their_session_id
        self.connected = True
        
        return True
    
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
    ) -> Optional[Packet]:
        """
        Send a command and wait for response.
        
        Args:
            command: Command byte
            payload: Optional payload data
            extra: Extra byte (default 0x01 for master)
        
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
        
        return self._receive_packet(timeout=2.0)
    
    def _send_packet(self, packet: Packet) -> None:
        """Encode and send a packet."""
        raw = packet.to_bytes()
        encoded = ir_encode(raw)
        self.serial.write(encoded)
    
    def _receive_packet(self, timeout: float = 2.0) -> Optional[Packet]:
        """
        Receive and decode a packet.
        
        Reads bytes until a complete valid packet is received or timeout.
        """
        import time
        start = time.time()
        buffer = b""
        
        while time.time() - start < timeout:
            # Read available data
            data = self.serial.read(256, timeout=0.1)
            if not data:
                continue
            
            buffer += ir_decode(data)
            
            # Need at least 8 bytes for header
            if len(buffer) < 8:
                continue
            
            # Try to parse packet
            try:
                packet = Packet.from_bytes(buffer)
                return packet
            except ValueError:
                # Incomplete or invalid, keep reading
                continue
        
        return None
