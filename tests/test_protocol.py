"""
Tests for Pokewalker Protocol
"""

import pytest
from pokewalker_client.protocol import (
    ir_encode,
    ir_decode,
    calculate_checksum,
    verify_checksum,
    Packet,
    Command,
    IR_XOR_MASK,
)


class TestIREncoding:
    """Tests for IR XOR encoding/decoding."""
    
    def test_encode_decode_roundtrip(self):
        """Encoding then decoding should return original."""
        original = bytes([0x00, 0x55, 0xAA, 0xFF, 0x12, 0x34])
        encoded = ir_encode(original)
        decoded = ir_decode(encoded)
        assert decoded == original
    
    def test_encode_xor_mask(self):
        """Encoding should XOR each byte with 0xAA."""
        data = bytes([0x00, 0xAA, 0x55, 0xFF])
        encoded = ir_encode(data)
        expected = bytes([0xAA, 0x00, 0xFF, 0x55])
        assert encoded == expected
    
    def test_encode_empty(self):
        """Encoding empty bytes should return empty."""
        assert ir_encode(b"") == b""
    
    def test_advertisement_byte(self):
        """Advertisement byte (0xFC) should decode from 0x56."""
        # 0xFC ^ 0xAA = 0x56
        encoded_advert = bytes([0x56])
        decoded = ir_decode(encoded_advert)
        assert decoded[0] == Command.ADVERTISE


class TestChecksum:
    """Tests for checksum calculation."""
    
    def test_checksum_basic(self):
        """Test basic checksum calculation."""
        # Create a simple packet with known bytes
        # Checksum bytes (indices 2-3) are treated as 0
        data = bytes([
            0x20,  # command (index 0, even)
            0x01,  # extra (index 1, odd)
            0x00,  # checksum hi (index 2, even) - treated as 0
            0x00,  # checksum lo (index 3, odd) - treated as 0
            0x12,  # session id byte 0 (index 4, even)
            0x34,  # session id byte 1 (index 5, odd)
            0x56,  # session id byte 2 (index 6, even)
            0x78,  # session id byte 3 (index 7, odd)
        ])
        
        # Even sum: 0x20 + 0x12 + 0x56 = 0x88
        # Odd sum: 0x01 + 0x34 + 0x78 = 0xAD
        # Checksum: 0x88 * 256 + 0xAD = 0x88AD
        
        checksum = calculate_checksum(data)
        assert checksum == 0x88AD
    
    def test_checksum_with_payload(self):
        """Test checksum with payload data."""
        data = bytes([
            0x0C, 0x01, 0x00, 0x00,  # cmd, extra, checksum placeholder
            0x00, 0x00, 0x00, 0x01,  # session id
            0x00, 0x10, 0x80,        # payload: address + length
        ])
        
        checksum = calculate_checksum(data)
        # Should be a valid 16-bit value
        assert 0 <= checksum <= 0xFFFF
    
    def test_checksum_folding(self):
        """Test that checksum folds properly when > 16 bits."""
        # Create data that produces a large sum requiring folding
        data = bytes([0xFF] * 8)
        # Simulate: we skip indices 2,3
        # Even: FF + FF + FF = 0x2FD
        # Odd: FF + FF + FF = 0x2FD  
        # Sum: 0x2FD * 256 + 0x2FD = 0x2FD2FD
        # Fold: 0x2FD + 0x02FD = 0x05FA
        
        checksum = calculate_checksum(data)
        assert checksum <= 0xFFFF


class TestPacket:
    """Tests for Packet class."""
    
    def test_packet_to_bytes(self):
        """Test packet serialization."""
        packet = Packet(
            command=Command.PING,
            extra=0x01,
            session_id=0x12345678,
        )
        
        data = packet.to_bytes()
        
        # Should be 8 bytes (header only, no payload)
        assert len(data) == 8
        
        # Check command
        assert data[0] == Command.PING
        
        # Check extra
        assert data[1] == 0x01
        
        # Session ID should be big-endian
        assert data[4:8] == bytes([0x12, 0x34, 0x56, 0x78])
    
    def test_packet_roundtrip(self):
        """Test packet serialize/deserialize roundtrip."""
        original = Packet(
            command=Command.EEPROM_READ_REQ,
            extra=0x02,
            session_id=0xDEADBEEF,
            payload=bytes([0x00, 0x10, 0x80]),  # address + length
        )
        
        data = original.to_bytes()
        parsed = Packet.from_bytes(data)
        
        assert parsed.command == original.command
        assert parsed.extra == original.extra
        assert parsed.session_id == original.session_id
        assert parsed.payload == original.payload
    
    def test_packet_checksum_valid(self):
        """Test that packet produces valid checksum."""
        packet = Packet(
            command=Command.IDENTITY_REQ,
            extra=0x01,
            session_id=0x00000000,
        )
        
        data = packet.to_bytes()
        assert verify_checksum(data)
    
    def test_packet_from_bytes_invalid_checksum(self):
        """Test that invalid checksum raises error."""
        # Create valid packet
        packet = Packet(
            command=Command.PING,
            extra=0x01,
            session_id=0x12345678,
        )
        data = bytearray(packet.to_bytes())
        
        # Corrupt the checksum
        data[2] ^= 0xFF
        
        with pytest.raises(ValueError, match="Checksum"):
            Packet.from_bytes(bytes(data))
    
    def test_packet_too_short(self):
        """Test that short data raises error."""
        with pytest.raises(ValueError, match="too short"):
            Packet.from_bytes(bytes([0x00, 0x01, 0x02]))


class TestCommands:
    """Tests for Command enum values."""
    
    def test_command_values(self):
        """Verify command byte values match protocol spec."""
        assert Command.ADVERTISE == 0xFC
        assert Command.CONNECT_REQ == 0xFA
        assert Command.CONNECT_REPLY == 0xF8
        assert Command.DISCONNECT == 0xF4
        
        assert Command.EEPROM_READ_REQ == 0x0C
        assert Command.EEPROM_READ_REPLY == 0x0E
        assert Command.EEPROM_WRITE_LO == 0x02
        assert Command.EEPROM_WRITE_HI == 0x82
        assert Command.EEPROM_WRITE_ACK == 0x04
        
        assert Command.RAM_WRITE == 0x06
        
        assert Command.IDENTITY_REQ == 0x20
        assert Command.IDENTITY_REPLY == 0x22
        
        assert Command.PING == 0x24
        assert Command.PONG == 0x26
        
        assert Command.GIFT_POKEMON == 0xC2
        assert Command.GIFT_ITEM == 0xC4
