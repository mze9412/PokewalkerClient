"""
Pokewalker High-Level Commands

Wraps the low-level protocol into convenient command functions:
- Read/write EEPROM
- Get walker identity and health data
- Disconnect gracefully
"""

from typing import Optional
import struct

from .protocol import PokewalkerProtocol, Command, Packet
from .structures import IdentityData, HealthData, PokemonSummary, EEPROMAddress


class PokewalkerCommands:
    """
    High-level command interface for Pokewalker communication.
    
    Usage:
        with SerialPort("/dev/ttyUSB0") as port:
            protocol = PokewalkerProtocol(port)
            if protocol.connect():
                cmd = PokewalkerCommands(protocol)
                identity = cmd.get_identity()
                print(f"Trainer: {identity.trainer_name}")
                protocol.disconnect()
    """
    
    def __init__(self, protocol: PokewalkerProtocol):
        """
        Initialize command interface.
        
        Args:
            protocol: Connected PokewalkerProtocol instance
        """
        self.protocol = protocol
    
    def ping(self) -> bool:
        """
        Send ping and wait for pong.
        
        Returns:
            True if pong received, False otherwise
        """
        reply = self.protocol.send_command(Command.PING)
        return reply is not None and reply.command == Command.PONG
    
    def get_identity(self) -> Optional[IdentityData]:
        """
        Request walker identity data.
        
        Returns:
            IdentityData or None on failure
        """
        reply = self.protocol.send_command(Command.IDENTITY_REQ)
        if reply is None or reply.command != Command.IDENTITY_REPLY:
            return None
        
        if len(reply.payload) < 0x68:
            return None
        
        return IdentityData.from_bytes(reply.payload)
    
    def read_eeprom(self, address: int, length: int) -> Optional[bytes]:
        """
        Read data from EEPROM.
        
        Args:
            address: 16-bit EEPROM address
            length: Number of bytes to read (max 128)
        
        Returns:
            Bytes read or None on failure
        """
        if length > 128:
            raise ValueError("Cannot read more than 128 bytes at once")
        
        # Payload: 2-byte address (big-endian) + 1-byte length
        payload = struct.pack(">HB", address, length)
        
        reply = self.protocol.send_command(Command.EEPROM_READ_REQ, payload)
        if reply is None or reply.command != Command.EEPROM_READ_REPLY:
            return None
        
        return reply.payload
    
    def write_eeprom_aligned(self, address: int, data: bytes) -> bool:
        """
        Write 128 bytes to EEPROM at 128-byte aligned address.
        
        Uses CMD_02 (low half) or CMD_82 (high half) depending on address.
        
        Args:
            address: Must be 128-byte aligned (0x0000, 0x0080, 0x0100, etc.)
            data: Exactly 128 bytes
        
        Returns:
            True on success, False on failure
        """
        if len(data) != 128:
            raise ValueError("Data must be exactly 128 bytes")
        if address & 0x7F != 0:
            raise ValueError("Address must be 128-byte aligned")
        
        # Determine command based on address alignment
        # CMD_02 for low 128 bytes of 256-byte page (address & 0x80 == 0)
        # CMD_82 for high 128 bytes of 256-byte page (address & 0x80 == 0x80)
        if address & 0x80:
            cmd = Command.EEPROM_WRITE_HI
        else:
            cmd = Command.EEPROM_WRITE_LO
        
        # Extra byte is high byte of address
        extra = (address >> 8) & 0xFF
        
        reply = self.protocol.send_command(cmd, data, extra=extra)
        return reply is not None and reply.command == Command.EEPROM_WRITE_ACK
    
    def write_eeprom(self, address: int, data: bytes) -> bool:
        """
        Write arbitrary data to EEPROM at any address.
        
        Uses CMD_0A for random-address writes.
        
        Args:
            address: 16-bit EEPROM address
            data: Data to write (any length, but be careful!)
        
        Returns:
            True on success, False on failure
        """
        # Payload: 1-byte low address + data
        # Extra byte is high byte of address
        extra = (address >> 8) & 0xFF
        payload = bytes([address & 0xFF]) + data
        
        reply = self.protocol.send_command(Command.EEPROM_WRITE_RANDOM, payload, extra=extra)
        return reply is not None and reply.command == Command.EEPROM_WRITE_ACK
    
    def write_ram(self, address: int, data: bytes) -> bool:
        """
        Write directly to internal memory (RAM/MMIO).
        
        WARNING: This can be used for arbitrary code execution!
        Use with extreme caution.
        
        Args:
            address: 16-bit internal address (RAM: 0xF780-0xFF7F)
            data: Data to write
        
        Returns:
            True on success, False on failure
        """
        # Extra byte is high byte of address
        # First byte of payload is low byte of address
        extra = (address >> 8) & 0xFF
        payload = bytes([address & 0xFF]) + data
        
        reply = self.protocol.send_command(Command.RAM_WRITE, payload, extra=extra)
        return reply is not None and reply.command == Command.RAM_WRITE
    
    def get_health_data(self) -> Optional[HealthData]:
        """
        Read health data from EEPROM.
        
        Returns:
            HealthData or None on failure
        """
        data = self.read_eeprom(EEPROMAddress.HEALTH, 0x19)
        if data is None:
            return None
        
        return HealthData.from_bytes(data)
    
    def get_current_pokemon(self) -> Optional[PokemonSummary]:
        """
        Read current walking pokemon data.
        
        Returns:
            PokemonSummary or None if no pokemon or failure
        """
        # First check identity to see if we have a pokemon
        identity = self.get_identity()
        if identity is None or not identity.has_pokemon:
            return None
        
        # Pokemon summary is in RouteInfo at 0x8F00
        data = self.read_eeprom(EEPROMAddress.ROUTE_INFO, 0x10)
        if data is None:
            return None
        
        return PokemonSummary.from_bytes(data)
    
    def gift_event_pokemon(self) -> bool:
        """
        Trigger event pokemon gift animation.
        
        Requires event pokemon data to be written to EEPROM first:
        - PokemonSummary at 0xBA44
        - EventPokeExtraData at 0xBA54
        - Sprite at 0xBA80 (0x180 bytes)
        - Name image at 0xBC00 (0x140 bytes)
        
        Returns:
            True on success, False on failure
        """
        reply = self.protocol.send_command(Command.GIFT_POKEMON)
        return reply is not None and reply.command == Command.GIFT_POKEMON
    
    def gift_event_item(self) -> bool:
        """
        Trigger event item gift animation.
        
        Requires item data to be written to EEPROM first:
        - Item data at 0xBD40 (6 zeros + u16 item number)
        - Name image at 0xBD48 (0x180 bytes)
        
        Returns:
            True on success, False on failure
        """
        reply = self.protocol.send_command(Command.GIFT_ITEM)
        return reply is not None and reply.command == Command.GIFT_ITEM
    
    def verify_magic(self) -> bool:
        """
        Verify walker has valid EEPROM magic string.
        
        Returns:
            True if "nintendo" found at EEPROM:0x0000
        """
        data = self.read_eeprom(EEPROMAddress.MAGIC, 8)
        if data is None:
            return False
        
        # Check for "nintendo" string
        return data == b"nintendo"
    
    def get_caught_pokemon(self) -> list[PokemonSummary]:
        """
        Get list of pokemon caught during current walk.
        
        Returns:
            List of up to 3 PokemonSummary objects
        """
        result = []
        data = self.read_eeprom(EEPROMAddress.CAUGHT_POKEMON, 0x30)
        if data is None:
            return result
        
        for i in range(3):
            offset = i * 0x10
            pokemon = PokemonSummary.from_bytes(data[offset:offset + 0x10])
            if pokemon.species != 0:
                result.append(pokemon)
        
        return result
    
    def get_dowsed_items(self) -> list[int]:
        """
        Get list of items dowsed during current walk.
        
        Returns:
            List of up to 3 item IDs
        """
        result = []
        data = self.read_eeprom(EEPROMAddress.DOWSED_ITEMS, 12)
        if data is None:
            return result
        
        for i in range(3):
            offset = i * 4
            item_id = struct.unpack("<H", data[offset:offset + 2])[0]
            if item_id != 0:
                result.append(item_id)
        
        return result
    
    def get_gifted_items(self) -> list[int]:
        """
        Get list of items received from peer play.
        
        Returns:
            List of up to 10 item IDs
        """
        result = []
        data = self.read_eeprom(EEPROMAddress.GIFTED_ITEMS, 40)
        if data is None:
            return result
        
        for i in range(10):
            offset = i * 4
            item_id = struct.unpack("<H", data[offset:offset + 2])[0]
            if item_id != 0:
                result.append(item_id)
        
        return result
