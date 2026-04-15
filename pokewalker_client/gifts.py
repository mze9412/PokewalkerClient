"""
Pokemon and Item Gifting

Functions to gift event pokemon and items to the Pokewalker.

Requires:
- Pokemon/item data written to appropriate EEPROM addresses
- Sprite images converted to walker format
- Name text rendered as images

EEPROM addresses for event pokemon:
- 0xBA44: PokemonSummary (0x10 bytes)
- 0xBA54: EventPokeExtraData (0x2C bytes)
- 0xBA80: Animated sprite (0x180 bytes, 32x24 x 2 frames)
- 0xBC00: Name image (0x140 bytes, 80x16)

EEPROM addresses for event item:
- 0xBD40: Item data (6 zeros + u16 item ID)
- 0xBD48: Name image (0x180 bytes, 96x16)
"""

import struct
from typing import Optional
from dataclasses import dataclass

from .commands import PokewalkerCommands
from .structures import PokemonSummary, EventPokeExtraData, EEPROMAddress
from .images import (
    calculate_image_size,
    SPRITE_SMALL_ANIM_SIZE,
    NAME_IMAGE_SIZE,
    NAME_IMAGE_WIDE_SIZE,
)

try:
    from .images import load_and_convert, image_to_walker_format, HAS_PIL
except ImportError:
    HAS_PIL = False


# Item IDs for common useful items
class Items:
    """Common item IDs from Pokemon HGSS."""
    # Healing
    POTION = 17
    SUPER_POTION = 26
    HYPER_POTION = 27
    MAX_POTION = 28
    FULL_RESTORE = 29
    REVIVE = 30
    MAX_REVIVE = 31
    
    # Pokeballs
    POKE_BALL = 4
    GREAT_BALL = 3
    ULTRA_BALL = 2
    MASTER_BALL = 1
    
    # Evolution stones
    FIRE_STONE = 82
    WATER_STONE = 84
    THUNDER_STONE = 83
    LEAF_STONE = 85
    MOON_STONE = 81
    SUN_STONE = 80
    
    # Held items
    ORAN_BERRY = 155
    SITRUS_BERRY = 158
    LUM_BERRY = 157
    LEFTOVERS = 234
    
    # Rare items
    RARE_CANDY = 50
    PP_UP = 51
    PP_MAX = 53
    NUGGET = 92
    BIG_NUGGET = 581  # Gen 5+ but might work
    STARF_BERRY = 207  # Given at 99999 steps


@dataclass
class GiftPokemon:
    """Configuration for gifting a pokemon."""
    species: int
    level: int
    nickname: str = ""
    held_item: int = 0
    moves: list[int] = None
    is_shiny: bool = False
    is_female: bool = False
    variant: int = 0  # For unown, spinda, etc.
    
    # Original trainer info
    ot_name: str = "WALKER"
    ot_tid: int = 12345
    ot_sid: int = 54321
    
    # Extra data
    ability: int = 0
    pokeball: int = Items.POKE_BALL
    location_met: int = 0  # Pokewalker location
    
    def __post_init__(self):
        if self.moves is None:
            self.moves = [0, 0, 0, 0]
    
    def to_summary(self) -> PokemonSummary:
        """Convert to PokemonSummary structure."""
        variant_flags = self.variant & 0x1F
        if self.is_female:
            variant_flags |= 0x20
        
        more_flags = 0
        if self.is_shiny:
            more_flags |= 0x02
        if self.variant != 0:
            more_flags |= 0x01  # Has form
        
        return PokemonSummary(
            species=self.species,
            held_item=self.held_item,
            moves=self.moves[:4] + [0] * (4 - len(self.moves)),
            level=self.level,
            variant_and_flags=variant_flags,
            more_flags=more_flags,
        )
    
    def to_extra_data(self) -> EventPokeExtraData:
        """Convert to EventPokeExtraData structure."""
        return EventPokeExtraData(
            ot_tid=self.ot_tid,
            ot_sid=self.ot_sid,
            location_met=self.location_met,
            ot_name=self.ot_name,
            ability=self.ability,
            pokeball_type=self.pokeball,
        )


class GiftManager:
    """
    Manages gifting pokemon and items to the Pokewalker.
    """
    
    def __init__(self, commands: PokewalkerCommands):
        """
        Initialize gift manager.
        
        Args:
            commands: PokewalkerCommands instance
        """
        self.commands = commands
    
    def gift_pokemon(
        self,
        pokemon: GiftPokemon,
        sprite_path: Optional[str] = None,
        sprite_data: Optional[bytes] = None,
        name_image_path: Optional[str] = None,
        name_image_data: Optional[bytes] = None,
    ) -> bool:
        """
        Gift an event pokemon to the walker.
        
        You must provide either sprite_path or sprite_data for the sprite,
        and either name_image_path or name_image_data for the name.
        
        Args:
            pokemon: GiftPokemon configuration
            sprite_path: Path to sprite image (32x24 or 32x48 for 2 frames)
            sprite_data: Pre-encoded sprite data (0x180 bytes)
            name_image_path: Path to name text image (80x16)
            name_image_data: Pre-encoded name image data (0x140 bytes)
        
        Returns:
            True on success, False on failure
        """
        # Convert pokemon data
        summary = pokemon.to_summary()
        extra = pokemon.to_extra_data()
        
        # Write pokemon summary
        if not self.commands.write_eeprom(
            EEPROMAddress.EVENT_POKEMON,
            summary.to_bytes(),
        ):
            return False
        
        # Write extra data
        if not self.commands.write_eeprom(
            EEPROMAddress.EVENT_POKEMON_EXTRA,
            extra.to_bytes(),
        ):
            return False
        
        # Write sprite
        if sprite_data is None and sprite_path is not None:
            if not HAS_PIL:
                raise RuntimeError("PIL required for image conversion")
            sprite_data = load_and_convert(sprite_path, 32, 48)  # 2 frames
        
        if sprite_data is not None:
            if len(sprite_data) != SPRITE_SMALL_ANIM_SIZE:
                raise ValueError(f"Sprite must be {SPRITE_SMALL_ANIM_SIZE} bytes")
            
            # Write sprite in chunks (max 127 bytes per write)
            offset = 0
            while offset < len(sprite_data):
                chunk = sprite_data[offset:offset + 127]
                if not self.commands.write_eeprom(
                    EEPROMAddress.EVENT_POKEMON_SPRITE + offset,
                    chunk,
                ):
                    return False
                offset += len(chunk)
        
        # Write name image
        if name_image_data is None and name_image_path is not None:
            if not HAS_PIL:
                raise RuntimeError("PIL required for image conversion")
            name_image_data = load_and_convert(name_image_path, 80, 16)
        
        if name_image_data is not None:
            if len(name_image_data) != NAME_IMAGE_SIZE:
                raise ValueError(f"Name image must be {NAME_IMAGE_SIZE} bytes")
            
            offset = 0
            while offset < len(name_image_data):
                chunk = name_image_data[offset:offset + 127]
                if not self.commands.write_eeprom(
                    EEPROMAddress.EVENT_POKEMON_NAME + offset,
                    chunk,
                ):
                    return False
                offset += len(chunk)
        
        # Send gift command
        return self.commands.gift_event_pokemon()
    
    def gift_item(
        self,
        item_id: int,
        name_image_path: Optional[str] = None,
        name_image_data: Optional[bytes] = None,
    ) -> bool:
        """
        Gift an event item to the walker.
        
        Args:
            item_id: Item ID to gift
            name_image_path: Path to name text image (96x16)
            name_image_data: Pre-encoded name image data (0x180 bytes)
        
        Returns:
            True on success, False on failure
        """
        # Write item data (6 zeros + u16 item ID, little-endian)
        item_data = bytes(6) + struct.pack("<H", item_id)
        
        if not self.commands.write_eeprom(EEPROMAddress.EVENT_ITEM, item_data):
            return False
        
        # Write name image
        if name_image_data is None and name_image_path is not None:
            if not HAS_PIL:
                raise RuntimeError("PIL required for image conversion")
            name_image_data = load_and_convert(name_image_path, 96, 16)
        
        if name_image_data is not None:
            if len(name_image_data) != NAME_IMAGE_WIDE_SIZE:
                raise ValueError(f"Name image must be {NAME_IMAGE_WIDE_SIZE} bytes")
            
            offset = 0
            while offset < len(name_image_data):
                chunk = name_image_data[offset:offset + 127]
                if not self.commands.write_eeprom(
                    EEPROMAddress.EVENT_ITEM_NAME + offset,
                    chunk,
                ):
                    return False
                offset += len(chunk)
        
        # Send gift command
        return self.commands.gift_event_item()
    
    def gift_stamps(self, heart: bool = True, spade: bool = True,
                    diamond: bool = True, club: bool = True) -> bool:
        """
        Gift stamp cards to the walker.
        
        Args:
            heart: Gift heart stamp
            spade: Gift spade stamp
            diamond: Gift diamond stamp
            club: Gift club stamp
        
        Returns:
            True if all requested stamps gifted successfully
        """
        from .protocol import Command
        
        success = True
        
        if heart:
            reply = self.commands.protocol.send_command(Command.STAMP_HEART)
            success = success and (reply is not None)
        
        if spade:
            reply = self.commands.protocol.send_command(Command.STAMP_SPADE)
            success = success and (reply is not None)
        
        if diamond:
            reply = self.commands.protocol.send_command(Command.STAMP_DIAMOND)
            success = success and (reply is not None)
        
        if club:
            reply = self.commands.protocol.send_command(Command.STAMP_CLUB)
            success = success and (reply is not None)
        
        return success


def create_blank_sprite(width: int = 32, height: int = 48) -> bytes:
    """
    Create a blank (white) sprite in walker format.
    
    Args:
        width: Sprite width
        height: Sprite height
    
    Returns:
        Encoded blank sprite
    """
    # All zeros = all white in walker format
    size = calculate_image_size(width, height)
    return bytes(size)


def create_blank_name_image(width: int = 80, height: int = 16) -> bytes:
    """
    Create a blank (white) name image in walker format.
    
    Args:
        width: Image width
        height: Image height
    
    Returns:
        Encoded blank image
    """
    size = calculate_image_size(width, height)
    return bytes(size)
