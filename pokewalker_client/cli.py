"""
Pokewalker CLI

Command-line interface for interacting with Pokewalker devices.

Usage:
    pokewalker info               - Display walker status
    pokewalker dump <file>        - Dump EEPROM to file
    pokewalker restore <file>     - Restore EEPROM from file
    pokewalker watts <amount>     - Add watts (requires shellcode)
    pokewalker gift pokemon       - Gift a pokemon
    pokewalker gift item <id>     - Gift an item
    pokewalker rom-dump <file>    - Dump internal ROM
"""

import argparse
import sys
import logging
from typing import Optional

import serial.serialutil

from .serial_port import SerialPort, list_ports
from .protocol import PokewalkerProtocol
from .commands import PokewalkerCommands
from .structures import IdentityData, HealthData
from .eeprom import EEPROMManager
from .shellcode import ShellcodeExecutor, assemble_add_watts


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


def connect(port: str, timeout: float = 60.0) -> Optional[tuple]:
    """
    Connect to Pokewalker.
    
    Returns:
        Tuple of (SerialPort, PokewalkerProtocol, PokewalkerCommands) or None
    """
    serial_port = SerialPort(port)
    
    try:
        serial_port.open()
    except serial.serialutil.SerialException as e:
        if "No such file or directory" in str(e) or "FileNotFoundError" in str(e):
            print(f"ERROR: Serial port '{port}' not found.")
            print()
            print("Available ports:")
            ports = list_ports()
            if ports:
                for p in ports:
                    print(f"  - {p}")
            else:
                print("  (no serial ports detected)")
            print()
            print("Make sure your USB-IrDA dongle is connected.")
            print("Use 'pokewalker ports' to list available ports.")
        elif "Permission denied" in str(e):
            print(f"ERROR: Permission denied for '{port}'.")
            print()
            print("Try one of the following:")
            print(f"  - Run with sudo: sudo pokewalker -p {port} <command>")
            print(f"  - Add yourself to the dialout group: sudo usermod -a -G dialout $USER")
            print("    (then log out and back in)")
        else:
            print(f"ERROR: Could not open serial port '{port}': {e}")
        return None
    
    protocol = PokewalkerProtocol(serial_port)
    
    print(f"Waiting for Pokewalker on {port}...")
    print("Press the center button on your Pokewalker to enter communication mode.")
    
    if not protocol.connect(timeout=timeout):
        print("Failed to connect. Make sure your Pokewalker is in communication mode.")
        serial_port.close()
        return None
    
    print("Connected!")
    
    commands = PokewalkerCommands(protocol)
    return serial_port, protocol, commands


def cmd_info(args) -> int:
    """Display walker information."""
    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1
    
    serial, protocol, commands = result
    
    try:
        # CMD_20 must be first after handshake per protocol spec
        identity = commands.get_identity()
        if identity is None:
            print("Failed to read identity data.")
            return 1

        # Verify EEPROM magic
        if not commands.verify_magic():
            print("Warning: EEPROM magic not found. Walker may be uninitialized.")
        
        print("\n=== Walker Information ===")
        print(f"Trainer: {identity.trainer_name}")
        print(f"TID: {identity.trainer_tid}")
        print(f"SID: {identity.trainer_sid}")
        print(f"Paired: {identity.is_paired}")
        print(f"Has Pokemon: {identity.has_pokemon}")
        print(f"Pokemon on Walk: {identity.pokemon_on_walk}")
        
        # Get health data
        health = commands.get_health_data()
        if health:
            print(f"\n=== Stats ===")
            print(f"Current Watts: {health.current_watts}")
            print(f"Total Steps: {health.total_steps}")
            print(f"Steps Since Sync: {health.steps_since_sync}")
            print(f"Total Days: {health.total_days}")
        
        # Get caught pokemon
        caught = commands.get_caught_pokemon()
        if caught:
            print(f"\n=== Caught Pokemon ({len(caught)}) ===")
            for poke in caught:
                shiny = " (SHINY)" if poke.is_shiny else ""
                print(f"  Species #{poke.species} Lv.{poke.level}{shiny}")
        
        # Get items
        dowsed = commands.get_dowsed_items()
        if dowsed:
            print(f"\n=== Dowsed Items ({len(dowsed)}) ===")
            for item_id in dowsed:
                print(f"  Item #{item_id}")
        
        gifted = commands.get_gifted_items()
        if gifted:
            print(f"\n=== Gifted Items ({len(gifted)}) ===")
            for item_id in gifted:
                print(f"  Item #{item_id}")
        
        return 0
    
    finally:
        protocol.disconnect()
        serial.close()


def cmd_dump(args) -> int:
    """Dump EEPROM to file."""
    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1
    
    serial, protocol, commands = result
    
    try:
        # CMD_20 must be first after handshake per protocol spec
        if commands.get_identity() is None:
            print("Failed to initialize session with walker.")
            return 1

        eeprom = EEPROMManager(commands)

        def progress(current, total):
            percent = (current * 100) // total
            bar = "=" * (percent // 2) + " " * (50 - percent // 2)
            print(f"\rDumping: [{bar}] {percent}%", end="", flush=True)

        print(f"Dumping EEPROM to {args.output}...")
        
        if eeprom.dump(args.output, progress_callback=progress):
            print(f"\nDump complete: {args.output}")
            return 0
        else:
            print("\nDump failed!")
            return 1
    
    finally:
        protocol.disconnect()
        serial.close()


def cmd_restore(args) -> int:
    """Restore EEPROM from file."""
    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1
    
    serial, protocol, commands = result
    
    try:
        # CMD_20 must be first after handshake per protocol spec
        if commands.get_identity() is None:
            print("Failed to initialize session with walker.")
            return 1

        eeprom = EEPROMManager(commands)

        if not args.force:
            print("WARNING: This will overwrite all walker data!")
            print("Creating backup first...")
            
            try:
                backup_path = eeprom.backup_before_write()
                print(f"Backup saved to: {backup_path}")
            except Exception as e:
                print(f"Backup failed: {e}")
                print("Use --force to skip backup.")
                return 1
        
        def progress(current, total):
            percent = (current * 100) // total
            bar = "=" * (percent // 2) + " " * (50 - percent // 2)
            print(f"\rRestoring: [{bar}] {percent}%", end="", flush=True)
        
        print(f"Restoring EEPROM from {args.input}...")
        
        if eeprom.restore(args.input, progress_callback=progress):
            print("\nRestore complete!")
            return 0
        else:
            print("\nRestore failed!")
            return 1
    
    finally:
        protocol.disconnect()
        serial.close()


def cmd_watts(args) -> int:
    """Add watts to walker."""
    amount = args.amount
    if amount > 9999:
        print("Warning: Capping watts at 9999 (max displayable).")
        amount = 9999
    
    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1
    
    serial, protocol, commands = result
    
    try:
        # CMD_20 must be first after handshake per protocol spec
        if commands.get_identity() is None:
            print("Failed to initialize session with walker.")
            return 1

        print(f"Adding {amount} watts...")

        executor = ShellcodeExecutor(commands)
        
        if executor.add_watts(amount):
            print("Watts added successfully!")
            
            # Verify
            health = commands.get_health_data()
            if health:
                print(f"Current watts: {health.current_watts}")
            
            return 0
        else:
            print("Failed to add watts!")
            return 1
    
    finally:
        protocol.disconnect()
        serial.close()


def cmd_gift_pokemon(args) -> int:
    """Gift an event Pokemon to the walker."""
    from .gifts import GiftManager, GiftPokemon

    moves = (args.move or [])[:4]
    pokemon = GiftPokemon(
        species=args.species,
        level=args.level,
        held_item=args.held_item or 0,
        moves=moves,
        is_shiny=args.shiny,
        is_female=args.female,
        ot_name=args.ot_name or "WALKER",
    )

    from .species import SPECIES
    display_name = SPECIES.get(pokemon.species, f"#{pokemon.species}")
    shiny_str = " (SHINY)" if pokemon.is_shiny else ""
    print(f"Gifting Pokemon: {display_name} Lv.{pokemon.level}{shiny_str}")

    # Pre-fetch sprite before connecting — network latency would stall the IR
    # session long enough for the walker to time out mid-write.
    sprite_data = None
    if args.fetch_sprites and args.sprite is None:
        from .sprites import fetch_sprite
        print("Fetching sprite from Pokemon Showdown...")
        try:
            sprite_data, _ = fetch_sprite(pokemon.species, shiny=pokemon.is_shiny)
            print("Sprite fetched.")
        except RuntimeError as e:
            print(f"Warning: {e}")
            print("Continuing without sprite.")

    # Pre-render custom name image before connecting.
    name_image_data = None
    if args.name and args.name_image is None:
        from .images import generate_name_image, HAS_PIL
        if HAS_PIL:
            name_image_data = generate_name_image(args.name)
        else:
            print("Warning: Pillow not available, cannot render custom name.")

    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1

    serial, protocol, commands = result

    try:
        if commands.get_identity() is None:
            print("Failed to initialize session with walker.")
            return 1

        gift_mgr = GiftManager(commands)

        ok = gift_mgr.gift_pokemon(
            pokemon,
            sprite_path=args.sprite,
            sprite_data=sprite_data,
            name_image_path=args.name_image,
            name_image_data=name_image_data,
        )

        if ok:
            print("Pokemon gifted successfully!")
            return 0
        else:
            print("Failed to gift Pokemon.")
            return 1

    finally:
        protocol.disconnect()
        serial.close()


def cmd_gift_item(args) -> int:
    """Gift an item."""
    from .gifts import GiftManager, create_blank_name_image
    from .items import ITEMS

    item_name = ITEMS.get(args.item_id, f"Item #{args.item_id}")

    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1

    serial, protocol, commands = result

    try:
        # CMD_20 must be first after handshake per protocol spec
        if commands.get_identity() is None:
            print("Failed to initialize session with walker.")
            return 1

        gift_mgr = GiftManager(commands)

        # Auto-generate name image from item name, fall back to blank if PIL unavailable
        name_image = None
        if args.image:
            try:
                from .images import load_and_convert
                name_image = load_and_convert(args.image, 96, 16)
            except ImportError:
                print("Warning: PIL not available, using blank image.")
        if name_image is None:
            try:
                from .images import generate_name_image, HAS_PIL
                if HAS_PIL:
                    name_image = generate_name_image(item_name, width=96)
            except Exception:
                pass
        if name_image is None:
            name_image = create_blank_name_image(96, 16)

        print(f"Gifting item: {item_name} (#{args.item_id})...")
        
        if gift_mgr.gift_item(args.item_id, name_image_data=name_image):
            print("Item gifted successfully!")
            return 0
        else:
            print("Failed to gift item!")
            return 1
    
    finally:
        protocol.disconnect()
        serial.close()


def cmd_clear_items(args) -> int:
    """Clear item slots on the walker."""
    dowsed = args.dowsed or args.all
    gifted = args.gifted or args.all
    event = args.event or args.all

    if not any([dowsed, gifted, event]):
        print("Specify at least one area: --dowsed, --gifted, --event, or --all")
        return 1

    areas = []
    if dowsed:
        areas.append("dowsed items")
    if gifted:
        areas.append("gifted items")
    if event:
        areas.append("event item")
    print(f"Clearing: {', '.join(areas)}")

    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1

    serial, protocol, commands = result
    try:
        if commands.get_identity() is None:
            print("Failed to initialize session with walker.")
            return 1

        results = commands.clear_items(dowsed=dowsed, gifted=gifted, event=event)
        failed = [k for k, v in results.items() if not v]
        if failed:
            print(f"Failed to clear: {', '.join(failed)}")
            return 1
        print("Done.")
        return 0
    finally:
        protocol.disconnect()
        serial.close()


def cmd_download_pokemon(args) -> int:
    """Download walking Pokemon data (sprites, name image, stats) to files."""
    import os
    import json

    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1

    serial, protocol, commands = result

    try:
        if commands.get_identity() is None:
            print("Failed to initialize session with walker.")
            return 1

        print(f"Downloading Pokemon data...")
        data = commands.download_pokemon_data()
        if data is None:
            print("Failed to read Pokemon data from walker.")
            return 1

        output_dir = args.output_dir
        os.makedirs(output_dir, exist_ok=True)
        saved = []

        try:
            from .images import walker_format_to_image, HAS_PIL
            from .structures import PokemonSummary
            if HAS_PIL:
                walker_format_to_image(data["small_sprite"], 32, 48).save(
                    os.path.join(output_dir, "small_sprite.png"))
                saved.append("small_sprite.png")
                walker_format_to_image(data["large_sprite"], 64, 96).save(
                    os.path.join(output_dir, "large_sprite.png"))
                saved.append("large_sprite.png")
                walker_format_to_image(data["name_image"], 80, 16).save(
                    os.path.join(output_dir, "name.png"))
                saved.append("name.png")
                if data["area_image"]:
                    walker_format_to_image(data["area_image"], 32, 24).save(
                        os.path.join(output_dir, "area.png"))
                    saved.append("area.png")
            summary = PokemonSummary.from_bytes(data["summary_bytes"])
            from .species import SPECIES
            info = {
                "species": summary.species,
                "species_name": SPECIES.get(summary.species, f"#{summary.species}"),
                "level": summary.level,
                "held_item": summary.held_item,
                "moves": summary.moves,
                "is_shiny": summary.is_shiny,
                "is_female": summary.is_female,
            }
            info_path = os.path.join(output_dir, "pokemon.json")
            with open(info_path, "w") as f:
                json.dump(info, f, indent=2)
            saved.append("pokemon.json")
        except Exception as e:
            print(f"Failed to save files: {e}")
            return 1

        print(f"Saved to {output_dir}: {', '.join(saved)}")
        return 0

    finally:
        protocol.disconnect()
        serial.close()


def cmd_download_area(args) -> int:
    """Download route background image to a file."""
    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1

    serial, protocol, commands = result

    try:
        if commands.get_identity() is None:
            print("Failed to initialize session with walker.")
            return 1

        print("Downloading area image...")
        data = commands.download_area_image()
        if data is None:
            print("Failed to read area image from walker.")
            return 1

        output_path = args.output
        try:
            from .images import walker_format_to_image, HAS_PIL
            if HAS_PIL:
                walker_format_to_image(data, 32, 24).save(output_path)
            else:
                bin_path = output_path.rsplit(".", 1)[0] + ".bin"
                with open(bin_path, "wb") as f:
                    f.write(data)
                output_path = bin_path
        except Exception as e:
            print(f"Failed to save area image: {e}")
            return 1

        print(f"Area image saved: {output_path}")
        return 0

    finally:
        protocol.disconnect()
        serial.close()


def cmd_upload_area(args) -> int:
    """Upload a route background image to the walker."""
    try:
        from .images import load_and_convert, HAS_PIL
        if not HAS_PIL:
            print("Pillow is required to load image files.")
            return 1
        area_data = load_and_convert(args.image_path, 32, 24)
    except Exception as e:
        print(f"Failed to load image: {e}")
        return 1

    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1

    serial, protocol, commands = result

    try:
        if commands.get_identity() is None:
            print("Failed to initialize session with walker.")
            return 1

        print(f"Uploading area image from {args.image_path}...")
        if not commands.upload_area_image(area_data):
            print("Failed to write area image to walker.")
            return 1

        print("Area image uploaded.")
        return 0

    finally:
        protocol.disconnect()
        serial.close()


def cmd_gift_stamps(args) -> int:
    """Gift stamp cards to the walker."""
    from .gifts import GiftManager
    heart = args.heart or args.all
    spade = args.spade or args.all
    diamond = args.diamond or args.all
    club = args.club or args.all
    if not any([heart, spade, diamond, club]):
        print("Specify at least one stamp: --heart, --spade, --diamond, --club, or --all")
        return 1
    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1
    serial, protocol, commands = result
    try:
        if commands.get_identity() is None:
            print("Failed to initialize session.")
            return 1
        gift_mgr = GiftManager(commands)
        if not gift_mgr.gift_stamps(heart=heart, spade=spade, diamond=diamond, club=club):
            print("Failed to gift stamps.")
            return 1
        print("Stamps gifted.")
        return 0
    finally:
        protocol.disconnect()
        serial.close()


def _parse_species(value: str) -> int:
    """Accept a species ID integer or a species name string."""
    try:
        return int(value)
    except ValueError:
        from .species import SPECIES_BY_NAME
        result = SPECIES_BY_NAME.get(value.lower())
        if result is None:
            import argparse
            raise argparse.ArgumentTypeError(f"Unknown species: {value!r}")
        return result


def cmd_set_pokemon(args) -> int:
    """Set the Pokemon currently walking with the trainer."""
    from .gifts import GiftManager, WalkingPokemon

    moves = (args.move or [])[:4]

    pokemon = WalkingPokemon(
        species=args.species,
        level=args.level,
        held_item=args.held_item or 0,
        moves=moves,
        is_shiny=args.shiny,
        is_female=args.female,
        variant=args.variant or 0,
    )

    from .species import SPECIES
    name = SPECIES.get(pokemon.species, f"#{pokemon.species}")
    shiny_str = " (SHINY)" if pokemon.is_shiny else ""
    female_str = " (F)" if pokemon.is_female else ""
    print(f"Setting walking Pokemon: {name} Lv.{pokemon.level}{shiny_str}{female_str}")

    # Fetch sprite before connecting — network latency would stall the IR
    # session long enough for the walker to time out mid-write.
    small_sprite_data = None
    large_sprite_data = None
    if args.fetch_sprites and args.small_sprite is None and args.large_sprite is None:
        from .sprites import fetch_sprite
        print("Fetching sprite from Pokemon Showdown...")
        try:
            small_sprite_data, large_sprite_data = fetch_sprite(
                pokemon.species, shiny=pokemon.is_shiny
            )
            print("Sprite fetched.")
        except RuntimeError as e:
            print(f"Warning: {e}")
            print("Continuing with blank sprites.")

    # Pre-render custom name image before connecting (same reason: PIL work must
    # not happen inside the IR session window).
    name_image_data = None
    if args.name and args.name_image is None:
        from .images import generate_name_image, HAS_PIL
        if HAS_PIL:
            name_image_data = generate_name_image(args.name)
        else:
            print("Warning: Pillow not available, cannot render custom name.")

    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1

    serial, protocol, commands = result

    try:
        # CMD_20 must be first after handshake per protocol spec
        identity = commands.get_identity()
        if identity is None:
            print("Failed to initialize session with walker.")
            return 1

        gift_mgr = GiftManager(commands)

        ok = gift_mgr.set_walking_pokemon(
            pokemon,
            small_sprite_path=args.small_sprite,
            small_sprite_data=small_sprite_data,
            large_sprite_path=args.large_sprite,
            large_sprite_data=large_sprite_data,
            name_image_path=args.name_image,
            name_image_data=name_image_data,
            area_image_path=args.area_image,
            identity=identity,
        )

        if ok:
            print("Walking Pokemon set successfully!")
            return 0
        else:
            print("Failed to set walking Pokemon.")
            return 1

    finally:
        protocol.disconnect()
        serial.close()


def cmd_ping(args) -> int:
    """Ping the walker."""
    result = connect(args.port, timeout=args.timeout)
    if result is None:
        return 1
    
    serial, protocol, commands = result
    
    try:
        if commands.ping():
            print("Pong!")
            return 0
        else:
            print("No response.")
            return 1
    
    finally:
        protocol.disconnect()
        serial.close()


def cmd_list_ports(args) -> int:
    """List available serial ports."""
    ports = list_ports()

    if not ports:
        print("No serial ports found.")
        return 1

    print("Available serial ports:")
    for port in ports:
        print(f"  {port}")

    return 0



def cmd_listen(args) -> int:
    """Print raw bytes from the serial port, decoded from IR XOR encoding."""
    from .protocol import ir_decode, Command

    known = {c.value: c.name for c in Command}
    baud = args.baud

    print(f"Listening on {args.port} at {baud} bps — press walker button now (Ctrl-C to stop)...")
    print(f"{'RAW':>6}  {'DECODED':>8}  MEANING")
    print("-" * 32)

    try:
        with serial.Serial(args.port, baudrate=baud, timeout=0.5) as s:
            while True:
                byte = s.read(1)
                if not byte:
                    continue
                raw = byte[0]
                decoded = ir_decode(byte)[0]
                meaning = known.get(decoded, "")
                print(f"  0x{raw:02X}  ->  0x{decoded:02X}   {meaning}")
    except serial.serialutil.SerialException as e:
        print(f"ERROR: {e}")
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")

    return 0



def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="pokewalker",
        description="Pokewalker USB IR Client",
    )
    parser.add_argument(
        "-p", "--port",
        default="/dev/ttyUSB0",
        help="Serial port (default: /dev/ttyUSB0)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "-t", "--timeout",
        type=float,
        default=60.0,
        metavar="SECONDS",
        help="Seconds to wait for walker advertisement (default: 60)",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # info
    info_parser = subparsers.add_parser("info", help="Display walker information")
    info_parser.set_defaults(func=cmd_info)
    
    # dump
    dump_parser = subparsers.add_parser("dump", help="Dump EEPROM to file")
    dump_parser.add_argument("output", help="Output file path")
    dump_parser.set_defaults(func=cmd_dump)
    
    # restore
    restore_parser = subparsers.add_parser("restore", help="Restore EEPROM from file")
    restore_parser.add_argument("input", help="Input file path")
    restore_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip backup before restore",
    )
    restore_parser.set_defaults(func=cmd_restore)
    
    # watts
    watts_parser = subparsers.add_parser("watts", help="Add watts")
    watts_parser.add_argument("amount", type=int, help="Watts to add (max 9999)")
    watts_parser.set_defaults(func=cmd_watts)
    
    # gift (subcommand group)
    gift_parser = subparsers.add_parser("gift", help="Gift pokemon or item")
    gift_subparsers = gift_parser.add_subparsers(dest="gift_type")
    
    # gift pokemon
    gift_poke_parser = gift_subparsers.add_parser("pokemon", help="Gift an event Pokemon")
    gift_poke_parser.add_argument(
        "--species", type=_parse_species, required=True, metavar="ID_OR_NAME",
        help="Species ID (e.g. 25) or name (e.g. pikachu)",
    )
    gift_poke_parser.add_argument(
        "--level", type=int, required=True, metavar="N",
        help="Pokemon level (1-100)",
    )
    gift_poke_parser.add_argument(
        "--move", type=int, action="append", metavar="ID",
        help="Move ID (may be specified up to 4 times)",
    )
    gift_poke_parser.add_argument(
        "--held-item", type=int, default=0, metavar="ID",
        help="Held item ID (default: none)",
    )
    gift_poke_parser.add_argument("--shiny", action="store_true", help="Mark as shiny")
    gift_poke_parser.add_argument("--female", action="store_true", help="Mark as female")
    gift_poke_parser.add_argument(
        "--ot-name", metavar="TEXT",
        help="Original trainer name (default: WALKER)",
    )
    gift_poke_parser.add_argument(
        "--sprite", metavar="PATH",
        help="Path to sprite image (32x48, 2 frames stacked; optional)",
    )
    gift_poke_parser.add_argument(
        "--name-image", metavar="PATH",
        help="Path to name image (80x16); auto-generated from species name if omitted",
    )
    gift_poke_parser.add_argument(
        "--fetch-sprites", action="store_true",
        help="Fetch sprite from Pokemon Showdown CDN (requires internet + Pillow)",
    )
    gift_poke_parser.add_argument(
        "--name", metavar="TEXT",
        help="Custom display name rendered as the name image (overrides species name)",
    )
    gift_poke_parser.set_defaults(func=cmd_gift_pokemon)

    # gift item
    gift_item_parser = gift_subparsers.add_parser("item", help="Gift an item")
    gift_item_parser.add_argument("item_id", type=int, help="Item ID")
    gift_item_parser.add_argument("--image", help="Item name image file")
    gift_item_parser.set_defaults(func=cmd_gift_item)
    
    # set-pokemon
    set_poke_parser = subparsers.add_parser(
        "set-pokemon",
        help="Set the Pokemon currently walking with the trainer",
    )
    set_poke_parser.add_argument(
        "--species", type=_parse_species, required=True, metavar="ID_OR_NAME",
        help="Species ID (e.g. 25) or name (e.g. pikachu)",
    )
    set_poke_parser.add_argument(
        "--level", type=int, required=True, metavar="N",
        help="Pokemon level (1-100)",
    )
    set_poke_parser.add_argument(
        "--move", type=int, action="append", metavar="ID",
        help="Move ID (may be specified up to 4 times)",
    )
    set_poke_parser.add_argument(
        "--held-item", type=int, default=0, metavar="ID",
        help="Held item ID (default: none)",
    )
    set_poke_parser.add_argument(
        "--shiny", action="store_true",
        help="Mark Pokemon as shiny",
    )
    set_poke_parser.add_argument(
        "--female", action="store_true",
        help="Mark Pokemon as female",
    )
    set_poke_parser.add_argument(
        "--variant", type=int, default=0, metavar="N",
        help="Form/variant index for Unown, Spinda, Arceus, etc.",
    )
    set_poke_parser.add_argument(
        "--small-sprite", metavar="PATH",
        help="Path to small walking animation image (32x48, 2 frames stacked)",
    )
    set_poke_parser.add_argument(
        "--large-sprite", metavar="PATH",
        help="Path to large home screen animation image (64x96, 2 frames stacked)",
    )
    set_poke_parser.add_argument(
        "--name-image", metavar="PATH",
        help="Path to name image (80x16); auto-generated from species name if omitted",
    )
    set_poke_parser.add_argument(
        "--area-image", metavar="PATH",
        help="Path to route background image (32x24, optional)",
    )
    set_poke_parser.add_argument(
        "--fetch-sprites", action="store_true",
        help="Fetch sprite from Pokemon Showdown CDN (requires internet + Pillow)",
    )
    set_poke_parser.add_argument(
        "--name", metavar="TEXT",
        help="Custom display name rendered as the Pokemon name image (overrides species name)",
    )
    set_poke_parser.set_defaults(func=cmd_set_pokemon)

    # download-pokemon
    dl_poke_parser = subparsers.add_parser("download-pokemon", help="Download walking Pokemon data to files")
    dl_poke_parser.add_argument("--output-dir", required=True, metavar="DIR", help="Directory to save files")
    dl_poke_parser.set_defaults(func=cmd_download_pokemon)

    # download-area
    dl_area_parser = subparsers.add_parser("download-area", help="Download route background image")
    dl_area_parser.add_argument("--output", required=True, metavar="PATH", help="Output file path")
    dl_area_parser.set_defaults(func=cmd_download_area)

    # upload-area
    ul_area_parser = subparsers.add_parser("upload-area", help="Upload route background image")
    ul_area_parser.add_argument("image_path", help="Path to image file (PNG, 32x24)")
    ul_area_parser.set_defaults(func=cmd_upload_area)

    # gift-stamps
    stamps_parser = subparsers.add_parser("gift-stamps", help="Gift stamp cards")
    stamps_parser.add_argument("--heart", action="store_true")
    stamps_parser.add_argument("--spade", action="store_true")
    stamps_parser.add_argument("--diamond", action="store_true")
    stamps_parser.add_argument("--club", action="store_true")
    stamps_parser.add_argument("--all", action="store_true", help="Gift all stamps")
    stamps_parser.set_defaults(func=cmd_gift_stamps)

    # clear-items
    clear_parser = subparsers.add_parser("clear-items", help="Clear item slots on the walker")
    clear_parser.add_argument("--dowsed", action="store_true", help="Clear dowsed items (found while walking)")
    clear_parser.add_argument("--gifted", action="store_true", help="Clear gifted items (received from peer play)")
    clear_parser.add_argument("--event", action="store_true", help="Clear pending event item slot")
    clear_parser.add_argument("--all", action="store_true", help="Clear all item areas")
    clear_parser.set_defaults(func=cmd_clear_items)

    # ping
    ping_parser = subparsers.add_parser("ping", help="Ping the walker")
    ping_parser.set_defaults(func=cmd_ping)
    
    # ports
    ports_parser = subparsers.add_parser("ports", help="List serial ports")
    ports_parser.set_defaults(func=cmd_list_ports)

    # listen
    listen_parser = subparsers.add_parser(
        "listen",
        help="Print raw bytes received from the walker (IR decode + command name)",
    )
    listen_parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        choices=[9600, 19200, 38400, 57600, 115200],
        help="Baud rate to listen at (default: 115200)",
    )
    listen_parser.set_defaults(func=cmd_listen)

    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    if args.command is None:
        parser.print_help()
        return 1
    
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as e:
        logging.exception("Error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
