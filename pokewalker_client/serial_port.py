"""
Serial Port Wrapper for USB-IrDA Communication

Provides a simple interface for serial communication with
USB-IrDA dongles at the required settings for Pokewalker:
- 115,200 baud
- 8 data bits
- No parity
- 1 stop bit
"""

import serial
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# Pokewalker IR settings
BAUD_RATE = 115200
BYTE_SIZE = serial.EIGHTBITS
PARITY = serial.PARITY_NONE
STOP_BITS = serial.STOPBITS_ONE


class SerialPort:
    """
    Serial port wrapper for USB-IrDA communication.
    
    Usage:
        with SerialPort("/dev/ttyUSB0") as port:
            port.write(data)
            response = port.read(128)
    """
    
    def __init__(self, port: str, timeout: float = 1.0):
        """
        Initialize serial port.
        
        Args:
            port: Serial port path (e.g., "/dev/ttyUSB0", "COM3")
            timeout: Default read timeout in seconds
        """
        self.port_path = port
        self.timeout = timeout
        self._serial: Optional[serial.Serial] = None
    
    def open(self) -> None:
        """Open the serial port with Pokewalker settings."""
        if self._serial is not None and self._serial.is_open:
            return
        
        logger.debug(f"Opening serial port {self.port_path}")
        self._serial = serial.Serial(
            port=self.port_path,
            baudrate=BAUD_RATE,
            bytesize=BYTE_SIZE,
            parity=PARITY,
            stopbits=STOP_BITS,
            timeout=self.timeout,
        )
        
        # Flush any stale data
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()
    
    def close(self) -> None:
        """Close the serial port."""
        if self._serial is not None and self._serial.is_open:
            logger.debug(f"Closing serial port {self.port_path}")
            self._serial.close()
        self._serial = None
    
    def write(self, data: bytes) -> int:
        """
        Write data to serial port.
        
        Args:
            data: Bytes to write
        
        Returns:
            Number of bytes written
        """
        if self._serial is None or not self._serial.is_open:
            raise RuntimeError("Serial port not open")
        
        logger.debug(f"TX: {data.hex()}")
        return self._serial.write(data)
    
    def read(self, size: int, timeout: Optional[float] = None) -> bytes:
        """
        Read data from serial port.
        
        Args:
            size: Maximum number of bytes to read
            timeout: Read timeout (uses default if None)
        
        Returns:
            Bytes read (may be fewer than size)
        """
        if self._serial is None or not self._serial.is_open:
            raise RuntimeError("Serial port not open")
        
        if timeout is not None:
            old_timeout = self._serial.timeout
            self._serial.timeout = timeout
        
        try:
            data = self._serial.read(size)
            if data:
                logger.debug(f"RX: {data.hex()}")
            return data
        finally:
            if timeout is not None:
                self._serial.timeout = old_timeout
    
    def read_until(self, expected: bytes, timeout: Optional[float] = None) -> bytes:
        """
        Read until expected bytes found or timeout.
        
        Args:
            expected: Byte sequence to look for
            timeout: Read timeout
        
        Returns:
            All bytes read including expected sequence
        """
        if self._serial is None or not self._serial.is_open:
            raise RuntimeError("Serial port not open")
        
        if timeout is not None:
            old_timeout = self._serial.timeout
            self._serial.timeout = timeout
        
        try:
            data = self._serial.read_until(expected)
            if data:
                logger.debug(f"RX: {data.hex()}")
            return data
        finally:
            if timeout is not None:
                self._serial.timeout = old_timeout
    
    def flush(self) -> None:
        """Flush input and output buffers."""
        if self._serial is not None and self._serial.is_open:
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
    
    @property
    def is_open(self) -> bool:
        """Check if port is open."""
        return self._serial is not None and self._serial.is_open
    
    def __enter__(self) -> "SerialPort":
        """Context manager entry."""
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


def list_ports() -> list[str]:
    """
    List available serial ports.
    
    Returns:
        List of port paths
    """
    import serial.tools.list_ports
    return [port.device for port in serial.tools.list_ports.comports()]
