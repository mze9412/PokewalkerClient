"""
Tests for Pokewalker Image Encoding
"""

import pytest
from pokewalker_client.images import (
    greyscale_to_2bit,
    encode_column,
    decode_column,
    encode_image,
    decode_image,
    calculate_image_size,
    SPRITE_SMALL_SIZE,
    SPRITE_SMALL_ANIM_SIZE,
    NAME_IMAGE_SIZE,
)


class TestGreyscaleConversion:
    """Tests for greyscale to 2-bit conversion."""
    
    def test_white(self):
        """White (255) should map to 0."""
        assert greyscale_to_2bit(255) == 0
        assert greyscale_to_2bit(250) == 0
        assert greyscale_to_2bit(192) == 0
    
    def test_light_grey(self):
        """Light grey should map to 1."""
        assert greyscale_to_2bit(191) == 1
        assert greyscale_to_2bit(170) == 1
        assert greyscale_to_2bit(128) == 1
    
    def test_dark_grey(self):
        """Dark grey should map to 2."""
        assert greyscale_to_2bit(127) == 2
        assert greyscale_to_2bit(85) == 2
        assert greyscale_to_2bit(64) == 2
    
    def test_black(self):
        """Black (0) should map to 3."""
        assert greyscale_to_2bit(63) == 3
        assert greyscale_to_2bit(0) == 3


class TestColumnEncoding:
    """Tests for 8-pixel column encoding/decoding."""
    
    def test_encode_all_white(self):
        """All white (0) pixels should produce [0x00, 0x00]."""
        pixels = [0, 0, 0, 0, 0, 0, 0, 0]
        result = encode_column(pixels)
        assert result == bytes([0x00, 0x00])
    
    def test_encode_all_black(self):
        """All black (3) pixels should produce [0xFF, 0xFF]."""
        pixels = [3, 3, 3, 3, 3, 3, 3, 3]
        result = encode_column(pixels)
        assert result == bytes([0xFF, 0xFF])
    
    def test_encode_alternating(self):
        """Test alternating pattern."""
        # Pattern: 0,1,2,3,0,1,2,3 (top to bottom)
        pixels = [0, 1, 2, 3, 0, 1, 2, 3]
        result = encode_column(pixels)
        
        # High plane: bits for pixels with value & 2
        # Positions 2,3,6,7 have high bit set: 0b11001100 = 0xCC
        # Low plane: bits for pixels with value & 1
        # Positions 1,3,5,7 have low bit set: 0b10101010 = 0xAA
        assert result == bytes([0xCC, 0xAA])
    
    def test_decode_roundtrip(self):
        """Test encode/decode roundtrip."""
        original = [0, 1, 2, 3, 3, 2, 1, 0]
        encoded = encode_column(original)
        decoded = decode_column(encoded)
        assert decoded == original
    
    def test_encode_invalid_length(self):
        """Test that wrong number of pixels raises error."""
        with pytest.raises(ValueError):
            encode_column([0, 1, 2])  # Too few
        
        with pytest.raises(ValueError):
            encode_column([0] * 10)  # Too many


class TestImageEncoding:
    """Tests for full image encoding/decoding."""
    
    def test_encode_8x8_white(self):
        """Test encoding 8x8 white image."""
        pixels = [[0] * 8 for _ in range(8)]
        result = encode_image(pixels, 8, 8)
        
        # 8 columns * 1 stripe * 2 bytes = 16 bytes
        assert len(result) == 16
        assert result == bytes([0x00] * 16)
    
    def test_encode_8x8_black(self):
        """Test encoding 8x8 black image."""
        pixels = [[3] * 8 for _ in range(8)]
        result = encode_image(pixels, 8, 8)
        
        assert len(result) == 16
        assert result == bytes([0xFF] * 16)
    
    def test_encode_16x16(self):
        """Test encoding 16x16 image."""
        pixels = [[0] * 16 for _ in range(16)]
        result = encode_image(pixels, 16, 16)
        
        # 16 columns * 2 stripes * 2 bytes = 64 bytes
        assert len(result) == 64
    
    def test_decode_roundtrip(self):
        """Test full image encode/decode roundtrip."""
        # Create test pattern
        pixels = []
        for y in range(8):
            row = []
            for x in range(8):
                row.append((x + y) % 4)
            pixels.append(row)
        
        encoded = encode_image(pixels, 8, 8)
        decoded = decode_image(encoded, 8, 8)
        
        assert decoded == pixels
    
    def test_encode_invalid_height(self):
        """Test that non-multiple-of-8 height raises error."""
        pixels = [[0] * 8 for _ in range(10)]  # 10 is not multiple of 8
        
        with pytest.raises(ValueError):
            encode_image(pixels, 8, 10)


class TestImageSizes:
    """Tests for image size calculations."""
    
    def test_calculate_8x8(self):
        """Test 8x8 image size."""
        assert calculate_image_size(8, 8) == 16
    
    def test_calculate_32x24(self):
        """Test 32x24 sprite size (small pokemon)."""
        size = calculate_image_size(32, 24)
        assert size == SPRITE_SMALL_SIZE
        assert size == 192  # 0xC0
    
    def test_sprite_anim_size(self):
        """Test animated sprite size (2 frames)."""
        assert SPRITE_SMALL_ANIM_SIZE == 384  # 0x180
    
    def test_name_image_size(self):
        """Test name image size (80x16)."""
        size = calculate_image_size(80, 16)
        assert size == NAME_IMAGE_SIZE
        assert size == 320  # 0x140
