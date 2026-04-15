"""
Image Encoding for Pokewalker Display

Converts images to the Pokewalker's 2-bit greyscale format.

Display format (SSD1854-based):
- 96x64 pixels, 2-bit greyscale (4 shades)
- Screen split into 8-pixel-tall horizontal stripes
- Each stripe scanned left-to-right
- Each column (8 pixels) encoded as 2 bytes (2 bitplanes)
- First byte: more significant bitplane
- Second byte: less significant bitplane
- LSB = top pixel, MSB = bottom pixel
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# PIL is optional - only needed for image file conversion
_has_pil = False
try:
    from PIL import Image
    _has_pil = True
except ImportError:
    pass

if TYPE_CHECKING:
    from PIL import Image


# Display dimensions
DISPLAY_WIDTH = 96
DISPLAY_HEIGHT = 64
BITS_PER_PIXEL = 2
STRIPE_HEIGHT = 8

# Common image sizes used by the walker
IMAGE_SIZES = {
    "sprite_small": (32, 24),      # Small pokemon sprite
    "sprite_large": (64, 48),      # Large pokemon sprite (home screen)
    "name_text": (80, 16),         # Pokemon/item name
    "name_text_wide": (96, 16),    # Wide text (messages)
    "area_image": (32, 24),        # Route area image
    "icon_16x16": (16, 16),        # Menu icons
    "icon_8x8": (8, 8),            # Small icons
}


def greyscale_to_2bit(value: int) -> int:
    """
    Convert 8-bit greyscale to 2-bit (0-3).
    
    0 = white (brightest)
    1 = light grey
    2 = dark grey
    3 = black (darkest)
    """
    # Invert so 0=white, 3=black (matches walker display)
    return 3 - (value >> 6)


def encode_column(pixels: list[int]) -> bytes:
    """
    Encode an 8-pixel vertical column to 2 bytes.
    
    Args:
        pixels: List of 8 2-bit pixel values (top to bottom)
    
    Returns:
        2 bytes: [high bitplane, low bitplane]
    """
    if len(pixels) != 8:
        raise ValueError("Column must have exactly 8 pixels")
    
    high_plane = 0
    low_plane = 0
    
    for i, pixel in enumerate(pixels):
        # LSB = top pixel, MSB = bottom pixel
        if pixel & 0x02:  # High bit
            high_plane |= (1 << i)
        if pixel & 0x01:  # Low bit
            low_plane |= (1 << i)
    
    return bytes([high_plane, low_plane])


def encode_image(pixels_2bit: list[list[int]], width: int, height: int) -> bytes:
    """
    Encode a 2-bit image to walker display format.
    
    Args:
        pixels_2bit: 2D array of 2-bit pixel values [y][x]
        width: Image width
        height: Image height (must be multiple of 8)
    
    Returns:
        Encoded image bytes
    """
    if height % STRIPE_HEIGHT != 0:
        raise ValueError(f"Height must be multiple of {STRIPE_HEIGHT}")
    
    result = bytearray()
    
    # Process each 8-pixel-tall stripe
    for stripe_y in range(0, height, STRIPE_HEIGHT):
        # Process each column in the stripe
        for x in range(width):
            # Get the 8 pixels in this column
            column: list[int] = []
            for y in range(stripe_y, stripe_y + STRIPE_HEIGHT):
                column.append(pixels_2bit[y][x])
            
            result.extend(encode_column(column))
    
    return bytes(result)


def decode_column(data: bytes) -> list[int]:
    """
    Decode 2 bytes to 8 2-bit pixel values.
    
    Args:
        data: 2 bytes [high bitplane, low bitplane]
    
    Returns:
        List of 8 2-bit pixel values (top to bottom)
    """
    high_plane = data[0]
    low_plane = data[1]
    
    pixels: list[int] = []
    for i in range(8):
        pixel = 0
        if high_plane & (1 << i):
            pixel |= 0x02
        if low_plane & (1 << i):
            pixel |= 0x01
        pixels.append(pixel)
    
    return pixels


def decode_image(data: bytes, width: int, height: int) -> list[list[int]]:
    """
    Decode walker display format to 2-bit pixel array.
    
    Args:
        data: Encoded image bytes
        width: Image width
        height: Image height
    
    Returns:
        2D array of 2-bit pixel values [y][x]
    """
    expected_size = (width * height * 2) // STRIPE_HEIGHT
    if len(data) < expected_size:
        raise ValueError(f"Data too short: expected {expected_size}, got {len(data)}")
    
    # Initialize pixel array
    pixels = [[0 for _ in range(width)] for _ in range(height)]
    
    idx = 0
    for stripe_y in range(0, height, STRIPE_HEIGHT):
        for x in range(width):
            column = decode_column(data[idx:idx + 2])
            idx += 2
            
            for i, pixel in enumerate(column):
                y = stripe_y + i
                if y < height:
                    pixels[y][x] = pixel
    
    return pixels


if _has_pil:
    def image_to_walker_format(
        image: "Image.Image",
        target_width: int,
        target_height: int,
        dither: bool = True,
    ) -> bytes:
        """
        Convert PIL Image to walker display format.
        
        Args:
            image: PIL Image (any mode)
            target_width: Target width
            target_height: Target height (must be multiple of 8)
            dither: Use dithering for better quality
        
        Returns:
            Encoded image bytes
        """
        from PIL import Image as PILImage  # Re-import for local use
        
        # Resize to target dimensions
        if image.size != (target_width, target_height):
            image = image.resize((target_width, target_height), PILImage.Resampling.LANCZOS)
        
        # Convert to greyscale
        if image.mode != "L":
            image = image.convert("L")
        
        # Quantize to 4 levels
        if dither:
            # Use Floyd-Steinberg dithering
            palette = PILImage.new("P", (1, 1))
            palette.putpalette([
                255, 255, 255,  # 0 = white
                170, 170, 170,  # 1 = light grey
                85, 85, 85,     # 2 = dark grey
                0, 0, 0,        # 3 = black
            ] + [0] * (256 - 4) * 3)
            image = image.quantize(colors=4, palette=palette, dither=PILImage.Dither.FLOYDSTEINBERG)
            image = image.convert("L")
        
        # Convert to 2-bit array
        pixels_2bit: list[list[int]] = []
        for y in range(target_height):
            row: list[int] = []
            for x in range(target_width):
                value = image.getpixel((x, y))
                row.append(greyscale_to_2bit(int(value)))  # type: ignore[arg-type]
            pixels_2bit.append(row)
        
        return encode_image(pixels_2bit, target_width, target_height)
    
    
    def walker_format_to_image(
        data: bytes,
        width: int,
        height: int,
    ) -> "Image.Image":
        """
        Convert walker display format to PIL Image.
        
        Args:
            data: Encoded image bytes
            width: Image width
            height: Image height
        
        Returns:
            PIL Image in greyscale mode
        """
        from PIL import Image as PILImage  # Re-import for local use
        
        pixels_2bit = decode_image(data, width, height)
        
        image = PILImage.new("L", (width, height))
        
        # Convert 2-bit values back to 8-bit greyscale
        for y in range(height):
            for x in range(width):
                # 0=white(255), 1=light(170), 2=dark(85), 3=black(0)
                value_2bit = pixels_2bit[y][x]
                value_8bit = 255 - (value_2bit * 85)
                image.putpixel((x, y), value_8bit)
        
        return image
    
    
    def load_and_convert(
        path: str,
        target_width: int,
        target_height: int,
    ) -> bytes:
        """
        Load image file and convert to walker format.
        
        Args:
            path: Path to image file
            target_width: Target width
            target_height: Target height
        
        Returns:
            Encoded image bytes
        """
        from PIL import Image as PILImage  # Re-import for local use
        
        image = PILImage.open(path)
        return image_to_walker_format(image, target_width, target_height)


def calculate_image_size(width: int, height: int) -> int:
    """
    Calculate encoded image size in bytes.
    
    Args:
        width: Image width
        height: Image height
    
    Returns:
        Size in bytes
    """
    stripes = height // STRIPE_HEIGHT
    return width * stripes * 2  # 2 bytes per column per stripe


def encode_animated_sprite(
    frame1_data: bytes,
    frame2_data: bytes,
    width: int,
    height: int,
) -> bytes:
    """
    Combine two animation frames into walker format.
    
    Walker animated sprites are stored as frame1 followed by frame2.
    
    Args:
        frame1_data: First frame (already encoded)
        frame2_data: Second frame (already encoded)
        width: Sprite width
        height: Sprite height
    
    Returns:
        Combined animation data
    """
    expected_size = calculate_image_size(width, height)
    
    if len(frame1_data) != expected_size:
        raise ValueError(f"Frame 1 size mismatch: expected {expected_size}, got {len(frame1_data)}")
    if len(frame2_data) != expected_size:
        raise ValueError(f"Frame 2 size mismatch: expected {expected_size}, got {len(frame2_data)}")
    
    return frame1_data + frame2_data


# Pre-calculated sizes for common walker images
SPRITE_SMALL_SIZE = calculate_image_size(32, 24)       # 0xC0 = 192 bytes
SPRITE_SMALL_ANIM_SIZE = SPRITE_SMALL_SIZE * 2         # 0x180 = 384 bytes
SPRITE_LARGE_SIZE = calculate_image_size(64, 48)       # 0x300 = 768 bytes
SPRITE_LARGE_ANIM_SIZE = SPRITE_LARGE_SIZE * 2         # 0x600 = 1536 bytes
NAME_IMAGE_SIZE = calculate_image_size(80, 16)         # 0x140 = 320 bytes
NAME_IMAGE_WIDE_SIZE = calculate_image_size(96, 16)    # 0x180 = 384 bytes
