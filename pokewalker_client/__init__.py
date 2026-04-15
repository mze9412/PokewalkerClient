"""
Pokewalker USB IR Client

A Python library for communicating with Nintendo Pokewalker devices
over infrared using a USB-IrDA dongle.

Based on the protocol reverse-engineered by dmitry.gr:
https://dmitry.gr/?r=05.Projects&proj=28.%20pokewalker
"""

__version__ = "0.1.0"

from .protocol import PokewalkerProtocol
from .commands import PokewalkerCommands
from .structures import IdentityData, HealthData, PokemonSummary

__all__ = [
    "PokewalkerProtocol",
    "PokewalkerCommands",
    "IdentityData",
    "HealthData",
    "PokemonSummary",
]
