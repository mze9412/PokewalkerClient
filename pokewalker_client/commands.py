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
from .structures import IdentityData, HealthData, PokemonSummary, EEPROMAddress, IdentityFlags
from .images import SPRITE_SMALL_ANIM_SIZE, SPRITE_LARGE_ANIM_SIZE, NAME_IMAGE_SIZE, SPRITE_SMALL_SIZE


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
        reply = self.protocol.send_command(
            Command.PING, reply_payload_size=0, expected_reply_command=Command.PONG
        )
        return reply is not None and reply.command == Command.PONG
    
    def get_identity(self) -> Optional[IdentityData]:
        """
        Request walker identity data.

        Returns:
            IdentityData or None on failure
        """
        reply = self.protocol.send_command(
            Command.IDENTITY_REQ,
            reply_payload_size=0x68,
            expected_reply_command=Command.IDENTITY_REPLY,
        )
        if reply is None or reply.command != Command.IDENTITY_REPLY:
            return None

        payload = reply.payload
        # IR noise can drop a few tail bytes; the most critical fields (trainer name,
        # TID/SID, flags) are in the first 0x5C bytes.  Refuse only truly short replies.
        if len(payload) < 0x5C:
            return None
        if len(payload) < 0x68:
            payload = payload + bytes(0x68 - len(payload))

        identity = IdentityData.from_bytes(payload)

        # The flags byte at payload[0x5B] is frequently zeroed by IR noise.
        # Override it from the reliable EEPROM copy (0x00ED + 0x5B = 0x0148).
        eeprom_flags = self.read_eeprom(EEPROMAddress.IDENTITY + 0x5B, 1)
        if eeprom_flags:
            identity.flags = eeprom_flags[0]

        return identity

    def read_eeprom_chunked(self, address: int, length: int) -> Optional[bytes]:
        """Read more than 128 bytes by issuing multiple EEPROM_READ_REQ commands."""
        result = b""
        offset = 0
        while offset < length:
            chunk_size = min(128, length - offset)
            chunk = self.read_eeprom(address + offset, chunk_size)
            if chunk is None:
                return None
            result += chunk
            offset += chunk_size
        return result

    def download_pokemon_data(self) -> Optional[dict]:
        """
        Read all walking-pokemon data from the walker.
        Returns dict with keys: summary_bytes, small_sprite, large_sprite, name_image, area_image
        Returns None if any critical read fails.
        """
        summary_bytes = self.read_eeprom_chunked(EEPROMAddress.ROUTE_INFO, 0x10)
        if summary_bytes is None:
            return None
        small_sprite = self.read_eeprom_chunked(EEPROMAddress.POKEMON_SMALL_ANIM, 0x180)
        if small_sprite is None:
            return None
        large_sprite = self.read_eeprom_chunked(EEPROMAddress.POKEMON_LARGE_ANIM, 0x600)
        if large_sprite is None:
            return None
        name_image = self.read_eeprom_chunked(EEPROMAddress.POKEMON_NAME, 0x140)
        if name_image is None:
            return None
        area_image = self.read_eeprom_chunked(EEPROMAddress.AREA_IMAGE, 0xC0)
        # area_image is optional — don't fail if missing
        return {
            "summary_bytes": summary_bytes,
            "small_sprite": small_sprite,
            "large_sprite": large_sprite,
            "name_image": name_image,
            "area_image": area_image,
        }

    def download_area_image(self) -> Optional[bytes]:
        """Read the route background image (0xC0 bytes) from EEPROM."""
        return self.read_eeprom_chunked(EEPROMAddress.AREA_IMAGE, 0xC0)

    def upload_area_image(self, data: bytes) -> bool:
        """
        Write a route background image (must be exactly 0xC0 bytes) to EEPROM.
        Use images.load_and_convert(path, 32, 24) to prepare the data from a file.
        """
        if len(data) != 0xC0:
            raise ValueError(f"Area image must be 0xC0 bytes, got {len(data)}")
        offset = 0
        while offset < len(data):
            chunk_size = min(127, len(data) - offset)
            if not self.write_eeprom(EEPROMAddress.AREA_IMAGE + offset, data[offset:offset + chunk_size]):
                return False
            offset += chunk_size
        return True

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

        payload = bytes([(address >> 8) & 0xFF, address & 0xFF, length])

        reply = self.protocol.send_command(
            Command.EEPROM_READ_REQ, payload, extra=0x01,
            reply_payload_size=length,
            expected_reply_command=Command.EEPROM_READ_REPLY,
        )
        if reply is None or reply.command != Command.EEPROM_READ_REPLY:
            return None

        data = reply.payload
        if len(data) < length:
            # IR noise truncated the reply — pad up to 4 missing tail bytes,
            # fail outright for anything shorter so callers can retry cleanly.
            if len(data) < length - 4:
                return None
            data = data + bytes(length - len(data))
        return data
    
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
        
        reply = self.protocol.send_command(
            cmd, data, extra=extra, reply_payload_size=0,
            expected_reply_command=Command.EEPROM_WRITE_ACK,
        )
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
        
        reply = self.protocol.send_command(
            Command.EEPROM_WRITE_RANDOM, payload, extra=extra, reply_payload_size=0,
            expected_reply_command=Command.EEPROM_WRITE_ACK,
        )
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
        data = self.read_eeprom(EEPROMAddress.HEALTH, 0x18)
        if data is None:
            return None
        
        return HealthData.from_bytes(data)
    
    def get_current_pokemon(self, identity: Optional["IdentityData"] = None) -> Optional[PokemonSummary]:
        """
        Read current walking pokemon data.

        Args:
            identity: Pre-fetched identity (avoids a second CMD_20 if already obtained)

        Returns:
            PokemonSummary or None if no pokemon or failure
        """
        if identity is None:
            identity = self.get_identity()
        if identity is None or not identity.has_pokemon:
            return None

        data = self.read_eeprom(EEPROMAddress.ROUTE_INFO, 0x10)
        if data is None:
            return None

        return PokemonSummary.from_bytes(data)

    def set_current_pokemon(
        self,
        pokemon: PokemonSummary,
        identity: Optional["IdentityData"] = None,
    ) -> bool:
        """
        Set the Pokemon currently walking with the trainer.

        Writes PokemonSummary to ROUTE_INFO and updates identity flags in both
        primary (0x00ED) and backup (0x01ED) copies.

        Args:
            pokemon: Pokemon to set as the walking Pokemon
            identity: Pre-fetched identity (avoids a second CMD_20 if already obtained)

        Returns:
            True on success, False on failure
        """
        if not self.write_eeprom(EEPROMAddress.ROUTE_INFO, pokemon.to_bytes()):
            return False

        if identity is None:
            identity = self.get_identity()
        if identity is None:
            return False

        identity.flags |= IdentityFlags.HAS_POKEMON | IdentityFlags.POKEMON_ON_WALK
        identity_bytes = identity.to_bytes()

        if not self.write_eeprom(EEPROMAddress.IDENTITY, identity_bytes):
            return False
        # Write backup copy at 0x01ED (reliable dual-write pattern)
        if not self.write_eeprom(0x01ED, identity_bytes):
            return False

        return True

    def set_walking_pokemon_sprites(
        self,
        small_anim: bytes,
        large_anim: bytes,
        name_image: bytes,
        area_image: Optional[bytes] = None,
    ) -> bool:
        """
        Write walking Pokemon sprites and name image to EEPROM.

        Args:
            small_anim:  0x180 bytes — 32x24 x 2 frames (walking animation)
            large_anim:  0x600 bytes — 64x48 x 2 frames (home screen)
            name_image:  0x140 bytes — 80x16 name text image
            area_image:  0x0C0 bytes — 32x24 route background (optional)

        Returns:
            True on success, False on failure
        """
        slots = [
            (EEPROMAddress.POKEMON_SMALL_ANIM, small_anim, SPRITE_SMALL_ANIM_SIZE),
            (EEPROMAddress.POKEMON_LARGE_ANIM, large_anim, SPRITE_LARGE_ANIM_SIZE),
            (EEPROMAddress.POKEMON_NAME,        name_image, NAME_IMAGE_SIZE),
        ]
        if area_image is not None:
            slots.append((EEPROMAddress.AREA_IMAGE, area_image, SPRITE_SMALL_SIZE))

        for address, data, expected_size in slots:
            if len(data) != expected_size:
                raise ValueError(
                    f"Data for 0x{address:04X} must be {expected_size} bytes, got {len(data)}"
                )
            offset = 0
            while offset < len(data):
                chunk = data[offset:offset + 127]
                if not self.write_eeprom(address + offset, chunk):
                    return False
                offset += len(chunk)

        return True

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

    def clear_items(
        self,
        dowsed: bool = True,
        gifted: bool = True,
        event: bool = True,
    ) -> dict[str, bool]:
        """
        Zero out item slots in EEPROM.

        Args:
            dowsed: Clear 3 dowsed-item slots (0xCEBC, 12 bytes)
            gifted: Clear 10 gifted-item slots (0xCEC8, 40 bytes)
            event:  Clear pending event-item slot and its name image
                    (0xBD40, 8 bytes + 0xBD48, 0x180 bytes)

        Returns:
            Dict mapping area name to success bool.
        """
        results: dict[str, bool] = {}
        if dowsed:
            results["dowsed"] = self.write_eeprom(EEPROMAddress.DOWSED_ITEMS, bytes(12))
        if gifted:
            results["gifted"] = self.write_eeprom(EEPROMAddress.GIFTED_ITEMS, bytes(40))
        if event:
            ok = self.write_eeprom(EEPROMAddress.EVENT_ITEM, bytes(8))
            offset = 0
            while ok and offset < 0x180:
                chunk_size = min(127, 0x180 - offset)
                ok = self.write_eeprom(EEPROMAddress.EVENT_ITEM_NAME + offset, bytes(chunk_size))
                offset += chunk_size
            results["event"] = ok
        return results
