"""
Sprite fetching from Pokemon Showdown CDN.

Downloads sprites and encodes them for the walker's display format.

Animation strategy (two frames required by walker firmware):
  Primary  — fetch animated APNG from Showdown `ani/` folder; extract frames 0
             and 1 so each frame is a distinct pose from the actual game animation.
  Fallback — fetch static Gen 4 sprite; use it as frame 1 and a 2 px upward-
             shifted copy as frame 2 (synthetic bounce effect).
"""

import io
import urllib.error
import urllib.request
from typing import Optional, TYPE_CHECKING

from .images import image_to_walker_format

if TYPE_CHECKING:
    from PIL import Image as PILImage

SHOWDOWN_BASE = "https://play.pokemonshowdown.com/sprites"


def species_to_slug(name: str) -> str:
    """Convert a species name to a Showdown CDN URL slug."""
    slug = name.lower()
    slug = slug.replace("'", "")       # farfetch'd → farfetchd
    slug = slug.replace(". ", "-")     # mr. mime → mr-mime
    slug = slug.replace(".", "")       # mime jr. → mime-jr (trailing dot)
    slug = slug.replace(" ", "-")      # remaining spaces → hyphens
    return slug


def _fetch_url(url: str) -> Optional[bytes]:
    """Fetch URL bytes, returning None on HTTP error instead of raising."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except urllib.error.HTTPError:
        return None


def _process_grey(src_rgba: "PILImage.Image") -> "PILImage.Image":
    """
    Convert an RGBA frame to a gamma-corrected greyscale image ready for
    resizing and encoding.  Pipeline: crop transparent border → flatten alpha
    onto white → autocontrast → gamma 1.4.
    """
    from PIL import Image, ImageOps

    alpha = src_rgba.split()[3]
    bbox = alpha.getbbox()
    if bbox:
        src_rgba = src_rgba.crop(bbox)

    bg = Image.new("RGB", src_rgba.size, (255, 255, 255))
    bg.paste(src_rgba, mask=src_rgba.split()[3])
    grey = bg.convert("L")

    grey = ImageOps.autocontrast(grey, cutoff=2)
    grey = grey.point(lambda v: int((v / 255.0) ** 1.4 * 255))
    return grey


def _shift_up(img: "PILImage.Image", px: int) -> "PILImage.Image":
    """Return a copy of *img* shifted upward by *px* pixels (white fill)."""
    from PIL import Image
    shifted = Image.new("L", img.size, 255)
    shifted.paste(img, (0, -px))
    return shifted


def _try_fetch_apng(
    slug: str,
    shiny: bool,
) -> Optional[tuple["PILImage.Image", "PILImage.Image"]]:
    """
    Try to fetch an animated APNG from Showdown's ani/ folder.

    Returns (frame0_rgba, frame1_rgba) if the sprite has ≥ 2 frames,
    or None if the fetch fails or the image has fewer than 2 frames.
    """
    from PIL import Image, ImageSequence

    folder = "ani-shiny" if shiny else "ani"
    url = f"{SHOWDOWN_BASE}/{folder}/{slug}.png"
    data = _fetch_url(url)
    if data is None:
        return None

    try:
        img = Image.open(io.BytesIO(data))
        n_frames = getattr(img, "n_frames", 1)
        if n_frames < 2:
            return None
        frames = list(ImageSequence.Iterator(img))
        # Each frame from ImageSequence may be in palette ("P") mode; convert.
        f0 = frames[0].convert("RGBA")
        f1 = frames[1].convert("RGBA")
        return f0, f1
    except Exception:
        return None


def _encode_two_frames(
    grey1: "PILImage.Image",
    grey2: "PILImage.Image",
    frame_w: int,
    frame_h: int,
) -> bytes:
    """
    Resize and stack two greyscale frames into the walker animation format.

    Returns (frame_w × frame_h×2) encoded bytes.
    """
    from PIL import Image

    r1 = grey1.resize((frame_w, frame_h), Image.Resampling.LANCZOS)
    r2 = grey2.resize((frame_w, frame_h), Image.Resampling.LANCZOS)
    combined = Image.new("L", (frame_w, frame_h * 2), 255)
    combined.paste(r1, (0, 0))
    combined.paste(r2, (0, frame_h))
    return image_to_walker_format(combined, frame_w, frame_h * 2, dither=False)


def fetch_sprite(
    species: "int | str",
    shiny: bool = False,
) -> tuple[bytes, bytes]:
    """
    Fetch a front sprite from Pokemon Showdown and encode it for both
    walker animation slots.

    Animation strategy:
      - Tries the animated APNG from Showdown's `ani/` (or `ani-shiny/`)
        folder first.  If the sprite has ≥ 2 frames, frames 0 and 1 are used
        as the two walker animation frames (distinct game-authentic poses).
      - Falls back to the static Gen 4 sprite if the animated APNG is
        unavailable or has only 1 frame.  Frame 2 is then a 2 px upward
        shift of frame 1 to create a synthetic bounce effect.

    Requires Pillow (PIL).

    Args:
        species: Species ID (int) or name string (case-insensitive)
        shiny:   Fetch shiny colour variant if True

    Returns:
        (small_anim, large_anim) where:
          small_anim  0x180 bytes  32x24 x 2 frames  walking animation slot
          large_anim  0x600 bytes  64x48 x 2 frames  home screen slot
    """
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Pillow is required for sprite fetching (pip install Pillow)")

    from .species import SPECIES, SPECIES_BY_NAME

    # Resolve species to a display name for the slug
    if isinstance(species, int):
        name = SPECIES.get(species, str(species))
    else:
        resolved_id = SPECIES_BY_NAME.get(species.lower())
        name = SPECIES.get(resolved_id, species) if resolved_id is not None else species

    slug = species_to_slug(name)

    # --- Try animated APNG first ---
    apng_frames = _try_fetch_apng(slug, shiny)

    if apng_frames is not None:
        grey1 = _process_grey(apng_frames[0])
        grey2 = _process_grey(apng_frames[1])
        print(f"  Using animated APNG ({slug}): {2} distinct frames")
    else:
        # Fall back to static Gen 4 sprite
        folder = "gen4-shiny" if shiny else "gen4"
        url = f"{SHOWDOWN_BASE}/{folder}/{slug}.png"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                img_bytes = resp.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Sprite not found for {name!r}: HTTP {e.code}\n  URL: {url}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error fetching sprite for {name!r}: {e.reason}")

        src = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        grey1 = _process_grey(src)
        grey2 = _shift_up(grey1, px=2)
        print(f"  Using Gen 4 static sprite ({slug}) with synthetic bounce fallback")

    small_anim = _encode_two_frames(grey1, grey2, 32, 24)   # → 32x48 → 0x180 bytes
    large_anim = _encode_two_frames(grey1, grey2, 64, 48)   # → 64x96 → 0x600 bytes

    return small_anim, large_anim
