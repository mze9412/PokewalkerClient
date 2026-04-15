"""
Tests for Pokewalker Data Structures
"""

import pytest
from pokewalker_client.structures import (
    IdentityData,
    HealthData,
    PokemonSummary,
    EventPokeExtraData,
    UniqueIdentityData,
    IdentityFlags,
    decode_pokemon_string,
    encode_pokemon_string,
)


class TestPokemonString:
    """Tests for Pokemon string encoding/decoding."""
    
    def test_decode_simple(self):
        """Test decoding simple ASCII text."""
        # "ASH" in 16-bit encoding (simplified)
        data = bytes([0x41, 0x00, 0x53, 0x00, 0x48, 0x00, 0xFF, 0xFF])
        result = decode_pokemon_string(data, 4)
        assert result == "ASH"
    
    def test_decode_with_terminator(self):
        """Test decoding stops at 0xFFFF."""
        data = bytes([0x41, 0x00, 0xFF, 0xFF, 0x42, 0x00])
        result = decode_pokemon_string(data, 3)
        assert result == "A"
    
    def test_encode_simple(self):
        """Test encoding simple ASCII text."""
        result = encode_pokemon_string("HI", 4)
        # Should be 8 bytes (4 chars * 2 bytes)
        assert len(result) == 8
        # "H" = 0x48, "I" = 0x49, then 0xFFFF padding
        assert result[0:2] == bytes([0x48, 0x00])
        assert result[2:4] == bytes([0x49, 0x00])
    
    def test_encode_decode_roundtrip(self):
        """Test encode/decode roundtrip."""
        original = "PIKACHU"
        encoded = encode_pokemon_string(original, 11)
        decoded = decode_pokemon_string(encoded, 11)
        assert decoded == original


class TestIdentityData:
    """Tests for IdentityData structure."""
    
    def test_identity_size(self):
        """Test that IdentityData serializes to correct size."""
        identity = IdentityData()
        data = identity.to_bytes()
        assert len(data) == 0x68
    
    def test_identity_roundtrip(self):
        """Test serialize/deserialize roundtrip."""
        original = IdentityData(
            trainer_tid=12345,
            trainer_sid=54321,
            trainer_name="TRAINER",
            flags=IdentityFlags.WALKER_PAIRED | IdentityFlags.HAS_POKEMON,
            step_count=9999,
            proto_ver=0x02,
        )
        
        data = original.to_bytes()
        parsed = IdentityData.from_bytes(data)
        
        assert parsed.trainer_tid == original.trainer_tid
        assert parsed.trainer_sid == original.trainer_sid
        assert parsed.trainer_name == original.trainer_name
        assert parsed.step_count == original.step_count
        assert parsed.proto_ver == original.proto_ver
    
    def test_identity_flags(self):
        """Test identity flag properties."""
        identity = IdentityData(flags=0x07)
        
        assert identity.is_paired
        assert identity.has_pokemon
        assert identity.pokemon_on_walk
        
        identity2 = IdentityData(flags=0x00)
        assert not identity2.is_paired
        assert not identity2.has_pokemon


class TestHealthData:
    """Tests for HealthData structure."""
    
    def test_health_size(self):
        """Test that HealthData serializes to correct size."""
        health = HealthData()
        data = health.to_bytes()
        assert len(data) == 0x19
    
    def test_health_roundtrip(self):
        """Test serialize/deserialize roundtrip."""
        original = HealthData(
            lifetime_total_steps=100000,
            today_steps=5000,
            current_watts=500,
            total_days=30,
        )
        
        data = original.to_bytes()
        parsed = HealthData.from_bytes(data)
        
        assert parsed.lifetime_total_steps == original.lifetime_total_steps
        assert parsed.today_steps == original.today_steps
        assert parsed.current_watts == original.current_watts
        assert parsed.total_days == original.total_days
    
    def test_health_settings(self):
        """Test settings parsing."""
        # settings bits: [0]=special route, [1..2]=volume, [3..6]=contrast
        health = HealthData(settings=0b01011010)
        
        assert not health.on_special_route  # bit 0 = 0
        assert health.volume == 0b01  # bits 1-2
        assert health.contrast == 0b1011  # bits 3-6


class TestPokemonSummary:
    """Tests for PokemonSummary structure."""
    
    def test_summary_size(self):
        """Test that PokemonSummary serializes to correct size."""
        summary = PokemonSummary()
        data = summary.to_bytes()
        assert len(data) == 0x10
    
    def test_summary_roundtrip(self):
        """Test serialize/deserialize roundtrip."""
        original = PokemonSummary(
            species=25,  # Pikachu
            level=50,
            held_item=234,  # Leftovers
            moves=[85, 86, 87, 88],  # Thunderbolt, Thunder Wave, etc
        )
        
        data = original.to_bytes()
        parsed = PokemonSummary.from_bytes(data)
        
        assert parsed.species == original.species
        assert parsed.level == original.level
        assert parsed.held_item == original.held_item
        assert parsed.moves == original.moves
    
    def test_summary_flags(self):
        """Test summary flag parsing."""
        summary = PokemonSummary(
            variant_and_flags=0x25,  # variant=5, female=True
            more_flags=0x03,  # shiny=True, has_form=True
        )
        
        assert summary.variant == 5
        assert summary.is_female
        assert summary.is_shiny
        assert summary.has_form


class TestEventPokeExtraData:
    """Tests for EventPokeExtraData structure."""
    
    def test_extra_size(self):
        """Test that EventPokeExtraData serializes to correct size."""
        extra = EventPokeExtraData()
        data = extra.to_bytes()
        assert len(data) == 0x2C
    
    def test_extra_roundtrip(self):
        """Test serialize/deserialize roundtrip."""
        original = EventPokeExtraData(
            ot_tid=12345,
            ot_sid=54321,
            ot_name="DMITRY",
            ability=1,
            pokeball_type=4,  # Poke Ball
            location_met=100,
        )
        
        data = original.to_bytes()
        parsed = EventPokeExtraData.from_bytes(data)
        
        assert parsed.ot_tid == original.ot_tid
        assert parsed.ot_sid == original.ot_sid
        assert parsed.ot_name == original.ot_name
        assert parsed.ability == original.ability
        assert parsed.pokeball_type == original.pokeball_type
