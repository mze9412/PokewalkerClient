# Pokewalker USB IR Client

A Python library and CLI tool for communicating with Nintendo Pokewalker devices over USB-IrDA.

Based on the protocol reverse-engineered by [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker).

## Features

- **Read walker status**: View trainer info, steps, watts, caught pokemon, and items
- **EEPROM backup/restore**: Full 64KB dump and restore
- **Add watts**: Inject watts via shellcode execution
- **Gift items**: Send custom items to the walker
- **Gift pokemon**: Send custom pokemon (including shiny!)
- **ROM dump**: Dump the internal ROM via exploit

## Requirements

### Hardware

- **USB-IrDA dongle**: Any USB infrared adapter that supports IrDA-SIR mode at 115,200 baud
  - Examples: USB-IrDA adapters based on MosChip MCS7780/7840
  - Or: USB-serial adapter + IR transceiver circuit (TSOP receiver + IR LED)
- **Pokewalker**: A working Nintendo Pokewalker device

### Software

- Python 3.10+
- pyserial
- Pillow (optional, for image conversion)

## Installation

### Using Docker (Recommended)

```bash
# Build the image
docker build -t pokewalker .

# Run with USB device passthrough
docker run --device=/dev/ttyUSB0 pokewalker -p /dev/ttyUSB0 info

# Or use docker-compose
docker compose run pokewalker -p /dev/ttyUSB0 info

# Run tests
docker compose run test
```

### From Source

```bash
# From source
git clone https://github.com/yourusername/pokewalker-client
cd pokewalker-client
pip install -e ".[all]"

# Or just the core package
pip install -e .
```

## Usage

### Basic Commands

```bash
# List available serial ports
pokewalker ports

# Display walker information
pokewalker -p /dev/ttyUSB0 info

# Dump EEPROM to file
pokewalker -p /dev/ttyUSB0 dump backup.bin

# Restore EEPROM from file
pokewalker -p /dev/ttyUSB0 restore backup.bin

# Add watts (max 9999)
pokewalker -p /dev/ttyUSB0 watts 9999

# Gift an item
pokewalker -p /dev/ttyUSB0 gift item 50  # Rare Candy

# Ping test
pokewalker -p /dev/ttyUSB0 ping
```

### Python API

```python
from pokewalker_client import PokewalkerProtocol, PokewalkerCommands
from pokewalker_client.serial_port import SerialPort

# Connect
with SerialPort("/dev/ttyUSB0") as port:
    protocol = PokewalkerProtocol(port)
    
    print("Put your Pokewalker in communication mode...")
    if protocol.connect():
        commands = PokewalkerCommands(protocol)
        
        # Get walker info
        identity = commands.get_identity()
        print(f"Trainer: {identity.trainer_name}")
        print(f"Steps: {identity.step_count}")
        
        # Get health data
        health = commands.get_health_data()
        print(f"Watts: {health.current_watts}")
        
        protocol.disconnect()
```

### Adding Watts

```python
from pokewalker_client.shellcode import ShellcodeExecutor

# After connecting...
executor = ShellcodeExecutor(commands)
executor.add_watts(9999)
```

### Gifting Items

```python
from pokewalker_client.gifts import GiftManager, Items

gift_mgr = GiftManager(commands)

# Gift a Rare Candy
gift_mgr.gift_item(Items.RARE_CANDY)
```

## Protocol Overview

The Pokewalker uses IrDA-SIR (Serial Infrared) at 115,200 baud, 8N1.

### Encoding

All data is XORed with 0xAA before transmission.

### Packet Format

```
+-------+-------+----------+-----------+---------+
| Cmd   | Extra | Checksum | SessionID | Payload |
| 1byte | 1byte | 2bytes   | 4bytes    | 0-128B  |
+-------+-------+----------+-----------+---------+
```

### Connection Handshake

1. Walker sends 0xFC advertisement byte periodically
2. Master sends 0xFA with random session ID
3. Walker replies 0xF8 with its random session ID
4. Final session ID = XOR of both IDs

### Key Commands

| Cmd | Direction | Purpose |
|-----|-----------|---------|
| 0xFC | w→* | Advertisement |
| 0xFA | m→w | Connect request |
| 0xF8 | w→m | Connect reply |
| 0x0C | m→w | EEPROM read |
| 0x02/0x82 | m→w | EEPROM write (aligned) |
| 0x06 | m→w | RAM write (code exec!) |
| 0x20 | m→w | Get identity |
| 0xC2 | m→w | Gift pokemon |
| 0xC4 | m→w | Gift item |

## Project Structure

```
pokewalker_client/
├── __init__.py        # Package exports
├── protocol.py        # IR encoding, packets, checksum
├── serial_port.py     # USB serial wrapper
├── commands.py        # High-level commands
├── structures.py      # Data structures (IdentityData, etc.)
├── eeprom.py          # EEPROM operations
├── shellcode.py       # H8/300 shellcode for code exec
├── images.py          # 2bpp image encoding
├── gifts.py           # Pokemon/item gifting
└── cli.py             # Command-line interface
```

## Safety Notes

⚠️ **WARNING**: This tool can modify your Pokewalker's EEPROM and execute arbitrary code on the device. While the operations are based on well-documented research, there is always a risk of:

- Corrupting save data
- Bricking the device (recoverable by re-pairing with a game)
- Creating invalid pokemon that may cause issues in the game

**Always create a backup before making any modifications!**

## Credits

- [dmitry.gr](https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker) for the incredible reverse engineering work
- The Pokemon hacking community for structure documentation

## License

MIT License - see LICENSE file for details.

## Disclaimer

This project is not affiliated with Nintendo, The Pokémon Company, or Game Freak. Pokémon and Pokewalker are trademarks of Nintendo. Use at your own risk.
