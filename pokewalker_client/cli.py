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


def connect(port: str, timeout: float = 5.0) -> Optional[tuple]:
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
    result = connect(args.port)
    if result is None:
        return 1
    
    serial, protocol, commands = result
    
    try:
        # Verify connection
        if not commands.verify_magic():
            print("Warning: EEPROM magic not found. Walker may be uninitialized.")
        
        # Get identity
        identity = commands.get_identity()
        if identity is None:
            print("Failed to read identity data.")
            return 1
        
        print("\n=== Walker Information ===")
        print(f"Trainer: {identity.trainer_name}")
        print(f"TID: {identity.trainer_tid}")
        print(f"SID: {identity.trainer_sid}")
        print(f"Steps: {identity.step_count}")
        print(f"Paired: {identity.is_paired}")
        print(f"Has Pokemon: {identity.has_pokemon}")
        print(f"Pokemon on Walk: {identity.pokemon_on_walk}")
        
        # Get health data
        health = commands.get_health_data()
        if health:
            print(f"\n=== Stats ===")
            print(f"Current Watts: {health.current_watts}")
            print(f"Today's Steps: {health.today_steps}")
            print(f"Lifetime Steps: {health.lifetime_total_steps}")
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
    result = connect(args.port)
    if result is None:
        return 1
    
    serial, protocol, commands = result
    
    try:
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
    result = connect(args.port)
    if result is None:
        return 1
    
    serial, protocol, commands = result
    
    try:
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
    
    result = connect(args.port)
    if result is None:
        return 1
    
    serial, protocol, commands = result
    
    try:
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


def cmd_gift_item(args) -> int:
    """Gift an item."""
    from .gifts import GiftManager, create_blank_name_image
    
    result = connect(args.port)
    if result is None:
        return 1
    
    serial, protocol, commands = result
    
    try:
        gift_mgr = GiftManager(commands)
        
        # Use blank image if none provided
        name_image = create_blank_name_image(96, 16)
        
        if args.image:
            try:
                from .images import load_and_convert
                name_image = load_and_convert(args.image, 96, 16)
            except ImportError:
                print("Warning: PIL not available, using blank image.")
        
        print(f"Gifting item #{args.item_id}...")
        
        if gift_mgr.gift_item(args.item_id, name_image_data=name_image):
            print("Item gifted successfully!")
            return 0
        else:
            print("Failed to gift item!")
            return 1
    
    finally:
        protocol.disconnect()
        serial.close()


def cmd_ping(args) -> int:
    """Ping the walker."""
    result = connect(args.port)
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
    
    # gift item
    gift_item_parser = gift_subparsers.add_parser("item", help="Gift an item")
    gift_item_parser.add_argument("item_id", type=int, help="Item ID")
    gift_item_parser.add_argument("--image", help="Item name image file")
    gift_item_parser.set_defaults(func=cmd_gift_item)
    
    # ping
    ping_parser = subparsers.add_parser("ping", help="Ping the walker")
    ping_parser.set_defaults(func=cmd_ping)
    
    # ports
    ports_parser = subparsers.add_parser("ports", help="List serial ports")
    ports_parser.set_defaults(func=cmd_list_ports)
    
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
