"""
EEPROM Operations

Utilities for reading, writing, and dumping the Pokewalker's 64KB EEPROM.
"""

import os
from typing import Optional, Callable
from pathlib import Path

from .commands import PokewalkerCommands
from .structures import EEPROMAddress


# EEPROM size in bytes
EEPROM_SIZE = 64 * 1024  # 64KB


class EEPROMManager:
    """
    Manages EEPROM read/write operations with safety features.
    """
    
    def __init__(self, commands: PokewalkerCommands):
        """
        Initialize EEPROM manager.
        
        Args:
            commands: PokewalkerCommands instance
        """
        self.commands = commands
    
    def dump(
        self,
        output_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """
        Dump entire EEPROM to file.
        
        Args:
            output_path: Path to save dump
            progress_callback: Optional callback(bytes_read, total_bytes)
        
        Returns:
            True on success, False on failure
        """
        data = bytearray()
        chunk_size = 128  # Max read size
        
        for offset in range(0, EEPROM_SIZE, chunk_size):
            chunk = self.commands.read_eeprom(offset, chunk_size)
            if chunk is None:
                return False
            
            data.extend(chunk)
            
            if progress_callback:
                progress_callback(len(data), EEPROM_SIZE)
        
        # Write to file
        with open(output_path, "wb") as f:
            f.write(data)
        
        return True
    
    def restore(
        self,
        input_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        verify: bool = True,
    ) -> bool:
        """
        Restore EEPROM from dump file.
        
        WARNING: This will overwrite all walker data!
        
        Args:
            input_path: Path to dump file
            progress_callback: Optional callback(bytes_written, total_bytes)
            verify: If True, verify writes by reading back
        
        Returns:
            True on success, False on failure
        """
        with open(input_path, "rb") as f:
            data = f.read()
        
        if len(data) != EEPROM_SIZE:
            raise ValueError(f"Dump file must be {EEPROM_SIZE} bytes, got {len(data)}")
        
        chunk_size = 128
        bytes_written = 0
        
        for offset in range(0, EEPROM_SIZE, chunk_size):
            chunk = data[offset:offset + chunk_size]
            
            if not self.commands.write_eeprom_aligned(offset, chunk):
                return False
            
            if verify:
                readback = self.commands.read_eeprom(offset, chunk_size)
                if readback != chunk:
                    return False
            
            bytes_written += len(chunk)
            if progress_callback:
                progress_callback(bytes_written, EEPROM_SIZE)
        
        return True
    
    def read_range(self, start: int, length: int) -> Optional[bytes]:
        """
        Read arbitrary range from EEPROM.
        
        Handles chunking for reads larger than 128 bytes.
        
        Args:
            start: Start address
            length: Number of bytes to read
        
        Returns:
            Bytes read or None on failure
        """
        if start + length > EEPROM_SIZE:
            raise ValueError(f"Read extends past EEPROM end")
        
        data = bytearray()
        remaining = length
        offset = start
        
        while remaining > 0:
            chunk_size = min(128, remaining)
            chunk = self.commands.read_eeprom(offset, chunk_size)
            if chunk is None:
                return None
            
            data.extend(chunk)
            offset += chunk_size
            remaining -= chunk_size
        
        return bytes(data)
    
    def write_range(
        self,
        start: int,
        data: bytes,
        verify: bool = True,
    ) -> bool:
        """
        Write arbitrary range to EEPROM.
        
        Uses random-address write (CMD_0A) for flexibility.
        
        Args:
            start: Start address
            data: Data to write
            verify: If True, verify by reading back
        
        Returns:
            True on success, False on failure
        """
        if start + len(data) > EEPROM_SIZE:
            raise ValueError(f"Write extends past EEPROM end")
        
        # For small writes, use random-address write
        if len(data) <= 127:  # CMD_0A payload limit
            if not self.commands.write_eeprom(start, data):
                return False
            
            if verify:
                readback = self.commands.read_eeprom(start, len(data))
                if readback != data:
                    return False
            
            return True
        
        # For larger writes, chunk it
        remaining = len(data)
        offset = 0
        
        while remaining > 0:
            chunk_size = min(127, remaining)
            chunk = data[offset:offset + chunk_size]
            
            if not self.commands.write_eeprom(start + offset, chunk):
                return False
            
            if verify:
                readback = self.commands.read_eeprom(start + offset, chunk_size)
                if readback != chunk:
                    return False
            
            offset += chunk_size
            remaining -= chunk_size
        
        return True
    
    def backup_before_write(
        self,
        backup_dir: str = ".",
    ) -> str:
        """
        Create a backup of EEPROM before making changes.
        
        Args:
            backup_dir: Directory to save backup
        
        Returns:
            Path to backup file
        
        Raises:
            RuntimeError: If backup fails
        """
        import datetime
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = Path(backup_dir) / f"pokewalker_backup_{timestamp}.bin"
        
        if not self.dump(str(backup_path)):
            raise RuntimeError("Failed to create backup")
        
        return str(backup_path)
    
    def verify_integrity(self) -> dict:
        """
        Verify EEPROM integrity by checking known structures.
        
        Returns:
            Dict with verification results
        """
        results = {
            "magic_valid": False,
            "identity_readable": False,
            "health_readable": False,
        }
        
        # Check magic string
        results["magic_valid"] = self.commands.verify_magic()
        
        # Check identity data
        identity = self.commands.get_identity()
        results["identity_readable"] = identity is not None
        
        # Check health data
        health = self.commands.get_health_data()
        results["health_readable"] = health is not None
        
        return results


def compare_dumps(dump1_path: str, dump2_path: str) -> list[tuple[int, int, int]]:
    """
    Compare two EEPROM dumps and find differences.
    
    Args:
        dump1_path: Path to first dump
        dump2_path: Path to second dump
    
    Returns:
        List of (offset, byte1, byte2) tuples for differences
    """
    with open(dump1_path, "rb") as f1:
        data1 = f1.read()
    
    with open(dump2_path, "rb") as f2:
        data2 = f2.read()
    
    if len(data1) != len(data2):
        raise ValueError("Dumps must be same size")
    
    differences = []
    for i in range(len(data1)):
        if data1[i] != data2[i]:
            differences.append((i, data1[i], data2[i]))
    
    return differences
