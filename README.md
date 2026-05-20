# Pokewalker USB IR Client

A Python library, CLI tool, and TUI for communicating with Nintendo Pokewalker devices over USB-IrDA.

Based on the protocol reverse-engineered by [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker).

## Features

- **Read walker status**: Trainer info, steps, watts, current/caught pokemon, items
- **EEPROM backup/restore**: Full 64 KB dump and restore with progress bar
- **Add watts**: Inject watts via shellcode execution (max 9999)
- **Set pokemon**: Place any pokemon on the walker as the walking companion
- **Gift pokemon**: Send an event-style pokemon (shown with gift animation)
- **Gift item**: Send any item with an auto-rendered name image
- **Gift stamps**: Award Heart/Spade/Diamond/Club stamp cards
- **Clear items**: Zero out dowsed, gifted, and/or pending event item slots
- **Download pokemon data**: Save sprites, name image, and stats to files
- **Download/upload area image**: Backup and restore the route background image
- **Sprite support**: Auto-fetch sprites from Pokemon Showdown or load from file
- **Interactive TUI**: Textual-based terminal UI with autocomplete

## Hardware Requirements

### USB-IrDA Dongle

You need a USB adapter that exposes an **IrDA-SIR** interface at **115,200 baud** as a standard serial port (typically `/dev/ttyUSB0` on Linux).

**Confirmed working chipsets:**

| Chipset | Common product | Notes |
|---------|---------------|-------|
| MosChip MCS7780 | Generic USB-IrDA dongles | Best Linux support, plug-and-play |
| MosChip MCS7840 | Some multi-port adapters | Also supported by `mcs7840` driver |

**Not compatible:** USB-IrDA adapters that use the Linux `irda` subsystem and expose `/dev/ircomm*` — the walker requires raw serial access, not the IrDA stack.

### Checking Your Dongle

```bash
# After plugging in, check dmesg
dmesg | tail -20

# Good: "mcs7840" or "pl2303" driver loading, /dev/ttyUSB0 appears
# Bad: "irda" or "ircomm" in the output
```

### Linux Setup

```bash
# Add yourself to the dialout group (re-login required)
sudo usermod -a -G dialout $USER

# Or create a udev rule to set permissions on plug-in
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="9710", ATTRS{idProduct}=="7840", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-usbirda.rules
sudo udevadm control --reload-rules
```

Replace the `idVendor`/`idProduct` with values from `lsusb` for your specific dongle.

### Physical Alignment

Point the Pokewalker's IR window directly at the dongle, 5–20 cm apart. Press the center button on the walker to enter communication mode — the screen shows the spinning Pokeball animation.

## Software Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (dependency management)

## Installation

### Using Docker (Recommended)

```bash
docker build -t pokewalker .

# Run CLI with USB device passthrough
docker run --device=/dev/ttyUSB0 pokewalker -p /dev/ttyUSB0 info

# Or use docker-compose
docker compose run pokewalker -p /dev/ttyUSB0 info

# Run tests
docker compose run test
```

### From Source

```bash
git clone https://github.com/yourusername/pokewalker-client
cd pokewalker-client
uv sync
```

## CLI Usage

All commands accept `-p PORT` (default: `/dev/ttyUSB0`) and `-t SECONDS` (timeout, default: 60).

### Status

```bash
# Show trainer, steps, watts, pokemon, items
uv run pokewalker info

# List available serial ports
uv run pokewalker ports

# Ping test
uv run pokewalker ping
```

### EEPROM Backup & Restore

```bash
# Dump full EEPROM to file
uv run pokewalker dump backup.bin

# Restore from file (auto-creates a backup first)
uv run pokewalker restore backup.bin

# Restore without backup
uv run pokewalker restore backup.bin --force
```

### Watts

```bash
# Add watts (0–9999)
uv run pokewalker watts 9999
```

### Set Walking Pokemon

Places a pokemon on the walker as the active walking companion. Writes the pokemon data, sprites, and name image to EEPROM.

```bash
# Minimal — blank sprites
uv run pokewalker set-pokemon --species pikachu --level 10

# With auto-fetched sprite (requires Pillow + internet)
uv run pokewalker set-pokemon --species 25 --level 50 --fetch-sprites

# Full options
uv run pokewalker set-pokemon \
  --species pikachu \
  --level 50 \
  --shiny \
  --female \
  --held-item 234 \        # Leftovers
  --move 85 \              # Thunderbolt
  --move 57 \              # Surf
  --variant 0 \
  --name "SPARKY" \        # Custom name rendered as bitmap
  --fetch-sprites

# From local sprite files (32×48 PNG, two frames stacked)
uv run pokewalker set-pokemon --species 25 --level 5 \
  --small-sprite small.png --large-sprite large.png
```

**Variant** is used for Unown (0=A … 25=Z, 26=!, 27=?), Spinda spot patterns, Arceus type plates, and any other species with alternate forms.

### Gift Pokemon

Sends an event-style pokemon with a gift animation (shown in gift menu).

```bash
uv run pokewalker gift pokemon \
  --species mewtwo \
  --level 70 \
  --shiny \
  --ot-name "EVENT" \
  --fetch-sprites
```

### Gift Item

```bash
# By name (autocomplete-friendly)
uv run pokewalker gift item 50   # Rare Candy (by ID)

# See items.py for the full list of supported IDs and names
```

### Gift Stamps

```bash
# All four suits
uv run pokewalker gift-stamps --all

# Individual suits
uv run pokewalker gift-stamps --heart --spade
```

### Clear Items

Zeros out item slots so they appear empty on next sync.

```bash
# Clear dowsed and gifted items (common use)
uv run pokewalker clear-items --dowsed --gifted

# Clear pending event item slot too
uv run pokewalker clear-items --all
```

### Download Pokemon Data

Saves sprites, name image, and a JSON stats file. Useful for backups before changing the walking pokemon.

```bash
uv run pokewalker download-pokemon --output-dir ./pokemon_backup
# Saves: small_sprite.png, large_sprite.png, name.png, area.png, pokemon.json
```

### Download / Upload Area Image

The route background (32×24 pixels) can be backed up and restored independently.

```bash
# Download to PNG
uv run pokewalker download-area --output area.png

# Upload from PNG (resized/converted automatically)
uv run pokewalker upload-area custom_background.png
```

### Debug

```bash
# Print raw IR bytes received from the walker (decode + command name)
uv run pokewalker listen
```

## TUI Usage

```bash
uv run pokewalker-tui
```

The TUI provides the same functionality as the CLI in an interactive terminal interface:

- **Left panel**: Command list — click or use arrow keys to select
- **Connection bar**: Port field with `↺` scan button, and timeout setting
- **Form area**: Parameters for the selected command with autocomplete for species and items
- **Run / Cancel**: Execute the command; retry automatically up to 5 times on IR errors
- **Output log**: Scrollable log of results and warnings

Sprites are fetched / loaded before the IR session opens to prevent timeout during the write.

## Python API

```python
from pokewalker_client.serial_port import SerialPort
from pokewalker_client.protocol import PokewalkerProtocol
from pokewalker_client.commands import PokewalkerCommands

with SerialPort("/dev/ttyUSB0") as port:
    protocol = PokewalkerProtocol(port)
    if protocol.connect():
        commands = PokewalkerCommands(protocol)
        identity = commands.get_identity()
        print(f"Trainer: {identity.trainer_name}")
        health = commands.get_health_data()
        print(f"Watts: {health.current_watts}")
        protocol.disconnect()
```

### Gifting

```python
from pokewalker_client.gifts import GiftManager, WalkingPokemon, GiftPokemon
from pokewalker_client.images import generate_name_image

gift_mgr = GiftManager(commands)

# Set walking pokemon (with pre-fetched sprite)
from pokewalker_client.sprites import fetch_sprite
small, large = fetch_sprite(25, shiny=False)  # Pikachu
name_img = generate_name_image("SPARKY")

pokemon = WalkingPokemon(species=25, level=10)
gift_mgr.set_walking_pokemon(pokemon,
    small_sprite_data=small,
    large_sprite_data=large,
    name_image_data=name_img,
)

# Gift an item
gift_mgr.gift_item(50)  # Rare Candy
```

## Protocol Overview

The Pokewalker uses IrDA-SIR at **115,200 baud, 8N1**.

### Encoding

All bytes are XOR'd with `0xAA` before transmission.

### Packet Format

```
+-------+-------+----------+-----------+---------+
| Cmd   | Extra | Checksum | SessionID | Payload |
| 1byte | 1byte | 2bytes   | 4bytes    | 0-128B  |
+-------+-------+----------+-----------+---------+
```

### Connection Handshake

1. Walker broadcasts `0xFC` advertisement byte periodically
2. Master sends `0xFA` with a random 4-byte session ID
3. Walker replies `0xF8` with its own random session ID
4. Final session ID = XOR of both IDs

### Key Commands

| Cmd | Direction | Purpose |
|-----|-----------|---------|
| 0xFC | w→\* | Advertisement |
| 0xFA | m→w | Connect request |
| 0xF8 | w→m | Connect reply |
| 0x20 | m→w | Get identity (must be first after connect) |
| 0x0C | m→w | EEPROM read (max 128 bytes) |
| 0x0A | m→w | EEPROM write random address |
| 0x02 | m→w | EEPROM write aligned (low half of page) |
| 0x82 | m→w | EEPROM write aligned (high half of page) |
| 0x06 | m→w | RAM write (enables shellcode execution) |
| 0xC2 | m→w | Gift pokemon trigger |
| 0xC4 | m→w | Gift item trigger |

## Project Structure

```
pokewalker_client/
├── __init__.py        # Package exports
├── protocol.py        # IR encoding, packets, checksum
├── serial_port.py     # USB serial wrapper
├── commands.py        # High-level commands
├── structures.py      # Data structures (IdentityData, HealthData, etc.)
├── eeprom.py          # EEPROM dump/restore manager
├── shellcode.py       # H8/300 shellcode for watts injection
├── images.py          # 2-bit greyscale image encoding/decoding
├── sprites.py         # Sprite fetching from Pokemon Showdown CDN
├── gifts.py           # Pokemon/item gifting logic
├── species.py         # Gen 4 species ID lookup table
├── items.py           # Gen 4 item ID lookup table
├── cli.py             # Command-line interface
└── tui.py             # Textual TUI
```

## Safety Notes

> **Always create an EEPROM backup before any modifications.**
> `uv run pokewalker dump backup.bin`

Risks:
- Corrupting save data (restored via `uv run pokewalker restore backup.bin`)
- Potentially bricking the device with sufficiently destructive EEPROM writes

## Credits

- [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker) for the incredible reverse engineering work
- The Pokemon hacking community for structure documentation

## License

MIT License — see LICENSE file for details.

## Disclaimer

Not affiliated with Nintendo, The Pokemon Company, or Game Freak. Pokemon and Pokewalker are trademarks of Nintendo. Use at your own risk.
