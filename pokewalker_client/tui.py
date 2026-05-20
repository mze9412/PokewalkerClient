"""
Pokewalker Terminal UI

Interactive Textual-based TUI for communicating with Pokewalker devices.
Run with: pokewalker-tui
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

import serial.serialutil

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.suggester import SuggestFromList
from textual.validation import Number
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    ContentSwitcher,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    RichLog,
    Select,
    Static,
)
from textual.worker import Worker

from .serial_port import SerialPort, list_ports
from .protocol import PokewalkerProtocol
from .commands import PokewalkerCommands
from .eeprom import EEPROMManager
from .shellcode import ShellcodeExecutor
from .species import SPECIES, SPECIES_BY_NAME
from .items import ITEMS, ITEMS_BY_NAME


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CommandError(Exception):
    """Raised by _execute_command_sync on any IR/protocol failure."""


class FormError(Exception):
    """Raised by collect_params() when form values are invalid."""


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

COMMANDS: list[tuple[str, str]] = [
    ("info", "Info"),
    ("ping", "Ping"),
    ("dump", "Dump EEPROM"),
    ("restore", "Restore EEPROM"),
    ("watts", "Add Watts"),
    ("set-pokemon", "Set Pokemon"),
    ("gift-pokemon", "Gift Pokemon"),
    ("gift-item", "Gift Item"),
    ("gift-stamps", "Gift Stamps"),
    ("clear-items", "Clear Items"),
    ("download-pokemon", "Download Pokemon"),
    ("download-area", "Download Area"),
    ("upload-area", "Upload Area"),
]


# ---------------------------------------------------------------------------
# Helpers (mirrored from cli.py)
# ---------------------------------------------------------------------------

def _parse_species(value: str) -> int:
    if not value.strip():
        raise FormError("Species is required.")
    try:
        return int(value)
    except ValueError:
        result = SPECIES_BY_NAME.get(value.strip().lower())
        if result is None:
            raise FormError(f"Unknown species: {value!r}. Use a name (e.g. pikachu) or ID (e.g. 25).")
        return result


def _parse_item(value: str) -> int:
    s = value.strip()
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        result = ITEMS_BY_NAME.get(s.lower())
        if result is None:
            raise FormError(f"Unknown item: {s!r}. Use a name (e.g. Potion) or ID (e.g. 17).")
        return result


def _parse_int(value: str, name: str, default: int = 0) -> int:
    s = value.strip()
    if not s:
        return default
    try:
        return int(s)
    except ValueError:
        raise FormError(f"{name} must be an integer.")


# ---------------------------------------------------------------------------
# Form widget classes
# ---------------------------------------------------------------------------

class InfoForm(Widget):
    def compose(self) -> ComposeResult:
        yield Static("No parameters required.\n\nReads identity, health, pokemon and items from the walker.")

    def collect_params(self) -> dict:
        return {}


class PingForm(Widget):
    def compose(self) -> ComposeResult:
        yield Static("No parameters required.\n\nSends a ping packet and waits for a pong response.")

    def collect_params(self) -> dict:
        return {}


class DumpForm(Widget):
    def compose(self) -> ComposeResult:
        yield Label("Output file path", classes="field-label")
        yield Input(
            placeholder="/tmp/walker.bin",
            id="dump-path",
        )

    def collect_params(self) -> dict:
        path = self.query_one("#dump-path", Input).value.strip()
        if not path:
            raise FormError("Output file path is required.")
        return {"path": path}


class RestoreForm(Widget):
    def compose(self) -> ComposeResult:
        yield Label("Input file path", classes="field-label")
        yield Input(
            placeholder="/tmp/walker.bin",
            id="restore-path",
        )
        yield Checkbox("Verify writes (recommended)", value=True, id="restore-verify")

    def collect_params(self) -> dict:
        path = self.query_one("#restore-path", Input).value.strip()
        if not path:
            raise FormError("Input file path is required.")
        verify = self.query_one("#restore-verify", Checkbox).value
        return {"path": path, "verify": verify}


class WattsForm(Widget):
    def compose(self) -> ComposeResult:
        yield Label("Amount (0 – 9999)", classes="field-label")
        yield Input(
            placeholder="100",
            id="watts-amount",
            validators=[Number(minimum=0, maximum=9999)],
        )

    def collect_params(self) -> dict:
        raw = self.query_one("#watts-amount", Input).value.strip()
        amount = _parse_int(raw, "Amount")
        if not (0 <= amount <= 9999):
            raise FormError("Amount must be between 0 and 9999.")
        return {"amount": amount}


class BasePokemonForm(Widget):
    """Shared fields for Set Pokemon and Gift Pokemon."""

    _EXTRA_FIELDS: bool = False  # subclass sets True to show ot_name

    def compose(self) -> ComposeResult:
        species_names = sorted(SPECIES_BY_NAME.keys())
        yield Label("Species (name or ID)", classes="field-label")
        yield Input(
            placeholder="pikachu",
            id="species",
            suggester=SuggestFromList(species_names, case_sensitive=False),
        )
        yield Label("Level (1 – 100)", classes="field-label")
        yield Input(
            placeholder="5",
            id="level",
            validators=[Number(minimum=1, maximum=100)],
        )
        yield Label("Variant (0 = default, Unown A=0…Z=25)", classes="field-label")
        yield Input(placeholder="0", id="variant", validators=[Number(minimum=0, maximum=27)])
        yield Label("Moves (up to 4 IDs, 0 = none)", classes="field-label")
        yield Horizontal(
            Input(placeholder="0", id="move1", classes="move-input"),
            Input(placeholder="0", id="move2", classes="move-input"),
            Input(placeholder="0", id="move3", classes="move-input"),
            Input(placeholder="0", id="move4", classes="move-input"),
            classes="move-row",
        )
        item_names = sorted(ITEMS_BY_NAME.keys())
        yield Label("Held item (name or ID, 0 = none)", classes="field-label")
        yield Input(
            placeholder="none",
            id="held-item",
            suggester=SuggestFromList(item_names, case_sensitive=False),
        )
        yield Label("Display name (blank = species name)", classes="field-label")
        yield Input(placeholder="Pikachu", id="display-name", max_length=12)
        yield Label("Sprite file (blank = fetch if checked, else blank)", classes="field-label")
        yield Input(placeholder="/path/to/sprite.png", id="sprite-path")
        if self._EXTRA_FIELDS:
            yield Label("OT Name (max 8 chars)", classes="field-label")
            yield Input(placeholder="WALKER", id="ot-name", max_length=8)
        yield Horizontal(
            Checkbox("Shiny", id="shiny"),
            Checkbox("Female", id="female"),
            Checkbox("Fetch sprites (internet)", value=True, id="fetch-sprites"),
            classes="flag-row",
        )

    def collect_params(self) -> dict:
        species = _parse_species(self.query_one("#species", Input).value)
        level_raw = self.query_one("#level", Input).value.strip()
        level = _parse_int(level_raw, "Level", default=1)
        if not (1 <= level <= 100):
            raise FormError("Level must be between 1 and 100.")
        variant = _parse_int(self.query_one("#variant", Input).value, "Variant", default=0)

        moves = []
        for mid in ("move1", "move2", "move3", "move4"):
            v = self.query_one(f"#{mid}", Input).value.strip()
            moves.append(_parse_int(v, f"Move {mid[-1]}"))

        held_item = _parse_item(self.query_one("#held-item", Input).value)
        is_shiny = self.query_one("#shiny", Checkbox).value
        is_female = self.query_one("#female", Checkbox).value
        fetch_sprites = self.query_one("#fetch-sprites", Checkbox).value
        display_name = self.query_one("#display-name", Input).value.strip()
        sprite_path = self.query_one("#sprite-path", Input).value.strip()

        params: dict[str, Any] = {
            "species": species,
            "level": level,
            "variant": variant,
            "moves": moves,
            "held_item": held_item,
            "is_shiny": is_shiny,
            "is_female": is_female,
            "fetch_sprites": fetch_sprites,
            "display_name": display_name,
            "sprite_path": sprite_path,
        }

        if self._EXTRA_FIELDS:
            ot_name = self.query_one("#ot-name", Input).value.strip() or "WALKER"
            params["ot_name"] = ot_name

        return params


class SetPokemonForm(BasePokemonForm):
    _EXTRA_FIELDS = False


class GiftPokemonForm(BasePokemonForm):
    _EXTRA_FIELDS = True


class GiftItemForm(Widget):
    def compose(self) -> ComposeResult:
        item_names = sorted(ITEMS_BY_NAME.keys())
        yield Label("Item (name or ID)", classes="field-label")
        yield Input(
            placeholder="potion",
            id="item-id",
            suggester=SuggestFromList(item_names, case_sensitive=False),
        )

    def collect_params(self) -> dict:
        raw = self.query_one("#item-id", Input).value.strip()
        if not raw:
            raise FormError("Item is required.")
        item_id = _parse_item(raw)
        return {"item_id": item_id}


class ClearItemsForm(Widget):
    def compose(self) -> ComposeResult:
        yield Static(
            "Zero out item slots on the walker.\n"
            "Cleared slots will appear empty when synced back to the game.",
        )
        yield Checkbox("Dowsed items (found while walking, up to 3)", value=True, id="clear-dowsed")
        yield Checkbox("Gifted items (received from peer play, up to 10)", value=True, id="clear-gifted")
        yield Checkbox("Event item (pending gift item)", value=False, id="clear-event")

    def collect_params(self) -> dict:
        dowsed = self.query_one("#clear-dowsed", Checkbox).value
        gifted = self.query_one("#clear-gifted", Checkbox).value
        event = self.query_one("#clear-event", Checkbox).value
        if not any([dowsed, gifted, event]):
            raise FormError("Select at least one area to clear.")
        return {"dowsed": dowsed, "gifted": gifted, "event": event}


class GiftStampsForm(Widget):
    def compose(self) -> ComposeResult:
        yield Static("Gift stamp cards to the walker.\nStamps are shown as collected on the walker screen.")
        yield Checkbox("Heart ♥", value=True, id="stamp-heart")
        yield Checkbox("Spade ♠", value=True, id="stamp-spade")
        yield Checkbox("Diamond ♦", value=True, id="stamp-diamond")
        yield Checkbox("Club ♣", value=True, id="stamp-club")

    def collect_params(self) -> dict:
        heart = self.query_one("#stamp-heart", Checkbox).value
        spade = self.query_one("#stamp-spade", Checkbox).value
        diamond = self.query_one("#stamp-diamond", Checkbox).value
        club = self.query_one("#stamp-club", Checkbox).value
        if not any([heart, spade, diamond, club]):
            raise FormError("Select at least one stamp.")
        return {"heart": heart, "spade": spade, "diamond": diamond, "club": club}


class DownloadPokemonForm(Widget):
    def compose(self) -> ComposeResult:
        yield Static("Download walking Pokémon data (sprites, name image, stats) to PNG files.")
        yield Label("Output directory", classes="field-label")
        yield Input(placeholder="/tmp/pokemon_dump", id="dl-pokemon-dir")

    def collect_params(self) -> dict:
        path = self.query_one("#dl-pokemon-dir", Input).value.strip()
        if not path:
            raise FormError("Output directory is required.")
        return {"output_dir": path}


class DownloadAreaForm(Widget):
    def compose(self) -> ComposeResult:
        yield Static("Download route background image to a PNG file.")
        yield Label("Output file path", classes="field-label")
        yield Input(placeholder="/tmp/area.png", id="dl-area-path")

    def collect_params(self) -> dict:
        path = self.query_one("#dl-area-path", Input).value.strip()
        if not path:
            raise FormError("Output file path is required.")
        return {"output_path": path}


class UploadAreaForm(Widget):
    def compose(self) -> ComposeResult:
        yield Static("Upload a route background image (PNG or walker binary, 32×24 pixels).")
        yield Label("Image file path", classes="field-label")
        yield Input(placeholder="/tmp/area.png", id="ul-area-path")

    def collect_params(self) -> dict:
        path = self.query_one("#ul-area-path", Input).value.strip()
        if not path:
            raise FormError("Image file path is required.")
        return {"image_path": path}


# ---------------------------------------------------------------------------
# Synchronous command execution (runs in thread pool)
# ---------------------------------------------------------------------------

def _prepare_sprites(params: dict) -> tuple[Optional[bytes], Optional[bytes], Optional[bytes], list[str]]:
    """
    Fetch/load/render sprite and name image data before the IR session opens.
    Returns (small_sprite_data, large_sprite_data, name_image_data, warnings).
    All heavy work (network, PIL) must happen here, not inside the IR session.
    """
    species = params["species"]
    is_shiny = params.get("is_shiny", False)
    warnings: list[str] = []

    small_sprite_data: Optional[bytes] = None
    large_sprite_data: Optional[bytes] = None

    # 1. Load from local file if provided
    sprite_path = params.get("sprite_path", "").strip()
    if sprite_path:
        try:
            from .images import load_and_convert, HAS_PIL
            if not HAS_PIL:
                raise RuntimeError("Pillow not installed — cannot load sprite file")
            small_sprite_data = load_and_convert(sprite_path, 32, 48)
            warnings.append(f"Sprite loaded from {sprite_path}")
        except Exception as e:
            warnings.append(f"Sprite file load failed: {e}")

    # 2. Fetch from internet if checkbox set and no local file succeeded
    if small_sprite_data is None and params.get("fetch_sprites"):
        try:
            from .sprites import fetch_sprite
            small_sprite_data, large_sprite_data = fetch_sprite(species, shiny=is_shiny)
            warnings.append("Sprite fetched from internet")
        except Exception as e:
            warnings.append(f"Sprite fetch failed: {e}")

    if small_sprite_data is None:
        warnings.append("No sprite — blank sprite will be written")

    # 3. Render name image
    name_image_data: Optional[bytes] = None
    display_name = params.get("display_name", "").strip()
    if display_name:
        try:
            from .images import generate_name_image
            name_image_data = generate_name_image(display_name)
        except Exception as e:
            warnings.append(f"Name image render failed: {e}")

    return small_sprite_data, large_sprite_data, name_image_data, warnings


def _execute_command_sync(
    command_id: str,
    params: dict,
    port: str,
    timeout: float,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """
    Blocking IR operation. Must be called via asyncio.to_thread.
    Raises CommandError on any failure.
    """
    # Prepare sprites/images before opening the serial port — network and PIL
    # work must not happen inside the IR session or the walker will time out.
    sprite_assets: tuple = (None, None, None, [])
    if command_id in ("set-pokemon", "gift-pokemon"):
        sprite_assets = _prepare_sprites(params)

    serial_port = SerialPort(port)
    try:
        serial_port.open()
    except serial.serialutil.SerialException as e:
        raise CommandError(f"Cannot open {port}: {e}")

    protocol = PokewalkerProtocol(serial_port)
    try:
        if not protocol.connect(timeout=timeout):
            raise CommandError("Failed to connect — make sure the walker is in communication mode.")

        commands = PokewalkerCommands(protocol)

        # CMD_20 must always be first after handshake
        identity = commands.get_identity()
        if identity is None:
            raise CommandError("Failed to read identity (CMD_20). Walker may be busy.")

        if command_id == "ping":
            if not commands.ping():
                raise CommandError("Ping failed — no pong received.")
            return {"pong": True}

        elif command_id == "info":
            health = commands.get_health_data()
            current_pokemon = commands.get_current_pokemon(identity)
            caught = commands.get_caught_pokemon()
            dowsed = commands.get_dowsed_items()
            gifted = commands.get_gifted_items()
            magic_ok = commands.verify_magic()
            return {
                "identity": identity,
                "health": health,
                "current_pokemon": current_pokemon,
                "caught": caught,
                "dowsed": dowsed,
                "gifted": gifted,
                "magic_ok": magic_ok,
            }

        elif command_id == "dump":
            eeprom = EEPROMManager(commands)
            if not eeprom.dump(params["path"], progress_callback=progress_cb):
                raise CommandError("EEPROM dump failed.")
            return {"path": params["path"]}

        elif command_id == "restore":
            eeprom = EEPROMManager(commands)
            if not eeprom.restore(params["path"], progress_callback=progress_cb, verify=params.get("verify", True)):
                raise CommandError("EEPROM restore failed.")
            return {"path": params["path"]}

        elif command_id == "watts":
            executor = ShellcodeExecutor(commands)
            amount = params["amount"]
            if not executor.add_watts(amount):
                raise CommandError("add_watts shellcode failed.")
            health = commands.get_health_data()
            return {"amount": amount, "current_watts": health.current_watts if health else None}

        elif command_id in ("set-pokemon", "gift-pokemon"):
            from .gifts import GiftManager, GiftPokemon, WalkingPokemon

            species = params["species"]
            is_shiny = params["is_shiny"]
            small_sprite_data, large_sprite_data, name_image_data, sprite_warnings = sprite_assets

            gift_mgr = GiftManager(commands)

            if command_id == "set-pokemon":
                pokemon = WalkingPokemon(
                    species=species,
                    level=params["level"],
                    held_item=params["held_item"],
                    moves=params["moves"],
                    is_shiny=is_shiny,
                    is_female=params["is_female"],
                    variant=params.get("variant", 0),
                )
                ok = gift_mgr.set_walking_pokemon(
                    pokemon,
                    small_sprite_data=small_sprite_data,
                    large_sprite_data=large_sprite_data,
                    name_image_data=name_image_data,
                    identity=identity,
                )
                if not ok:
                    raise CommandError("Failed to set walking Pokemon.")
            else:
                pokemon = GiftPokemon(
                    species=species,
                    level=params["level"],
                    held_item=params["held_item"],
                    moves=params["moves"],
                    is_shiny=is_shiny,
                    is_female=params["is_female"],
                    variant=params.get("variant", 0),
                    ot_name=params.get("ot_name", "WALKER"),
                )
                ok = gift_mgr.gift_pokemon(pokemon, sprite_data=small_sprite_data, name_image_data=name_image_data)
                if not ok:
                    raise CommandError("Failed to gift Pokemon.")

            name = SPECIES.get(species, f"#{species}")
            return {"species_name": name, "level": params["level"], "sprite_warnings": sprite_warnings}

        elif command_id == "gift-item":
            from .gifts import GiftManager, create_blank_name_image

            item_id = params["item_id"]
            item_name = ITEMS.get(item_id, f"Item #{item_id}")

            name_image_data = None
            try:
                from .images import generate_name_image, HAS_PIL
                if HAS_PIL:
                    name_image_data = generate_name_image(item_name, width=96)
            except Exception:
                pass
            if name_image_data is None:
                name_image_data = create_blank_name_image(96, 16)

            gift_mgr = GiftManager(commands)
            if not gift_mgr.gift_item(item_id, name_image_data=name_image_data):
                raise CommandError("Failed to gift item.")
            return {"item_id": item_id, "item_name": item_name}

        elif command_id == "clear-items":
            results = commands.clear_items(
                dowsed=params.get("dowsed", False),
                gifted=params.get("gifted", False),
                event=params.get("event", False),
            )
            if not all(results.values()):
                failed = [k for k, v in results.items() if not v]
                raise CommandError(f"Failed to clear: {', '.join(failed)}")
            return {"cleared": results}

        elif command_id == "gift-stamps":
            from .gifts import GiftManager
            gift_mgr = GiftManager(commands)
            ok = gift_mgr.gift_stamps(
                heart=params.get("heart", False),
                spade=params.get("spade", False),
                diamond=params.get("diamond", False),
                club=params.get("club", False),
            )
            if not ok:
                raise CommandError("Failed to gift stamps.")
            given = [k for k in ("heart", "spade", "diamond", "club") if params.get(k)]
            return {"stamps": given}

        elif command_id == "download-pokemon":
            import os, json
            output_dir = params["output_dir"]
            os.makedirs(output_dir, exist_ok=True)
            data = commands.download_pokemon_data()
            if data is None:
                raise CommandError("Failed to read Pokémon data from walker.")
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
                # Always save raw binary for summary
                summary = PokemonSummary.from_bytes(data["summary_bytes"])
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
                raise CommandError(f"Failed to save files: {e}")
            return {"output_dir": output_dir, "saved": saved}

        elif command_id == "download-area":
            import os
            output_path = params["output_path"]
            data = commands.download_area_image()
            if data is None:
                raise CommandError("Failed to read area image from walker.")
            try:
                from .images import walker_format_to_image, HAS_PIL
                if HAS_PIL:
                    walker_format_to_image(data, 32, 24).save(output_path)
                else:
                    # Save as raw binary with .bin extension if PIL unavailable
                    bin_path = output_path.rsplit(".", 1)[0] + ".bin"
                    with open(bin_path, "wb") as f:
                        f.write(data)
                    output_path = bin_path
            except Exception as e:
                raise CommandError(f"Failed to save area image: {e}")
            return {"output_path": output_path}

        elif command_id == "upload-area":
            image_path = params["image_path"]
            try:
                from .images import load_and_convert, HAS_PIL
                if not HAS_PIL:
                    raise CommandError("Pillow is required to load image files.")
                area_data = load_and_convert(image_path, 32, 24)
            except CommandError:
                raise
            except Exception as e:
                raise CommandError(f"Failed to load image: {e}")
            if not commands.upload_area_image(area_data):
                raise CommandError("Failed to write area image to walker.")
            return {"image_path": image_path}

        else:
            raise CommandError(f"Unknown command: {command_id}")

    finally:
        try:
            protocol.disconnect()
        except Exception:
            pass
        try:
            serial_port.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class PokewalkerTUI(App):
    TITLE = "Pokewalker TUI"
    BINDINGS = [("q", "quit", "Quit"), ("ctrl+c", "quit", "Quit")]

    CSS = """
    Screen {
        background: $surface;
    }

    #connection-bar {
        height: 5;
        padding: 0 1;
        background: $panel;
        border-bottom: solid $accent;
        layout: horizontal;
        align: left middle;
    }

    #connection-bar Label {
        margin-right: 1;
        color: $text-muted;
    }

    #port-select {
        width: 26;
        margin-right: 0;
    }

    #scan-ports-btn {
        width: 3;
        min-width: 3;
        margin-right: 2;
    }

    #timeout-input {
        width: 8;
    }

    #main-layout {
        height: 1fr;
    }

    #sidebar {
        width: 22;
        border-right: solid $accent;
        background: $panel;
    }

    #sidebar ListView {
        background: $panel;
    }

    #right-panel {
        width: 1fr;
        padding: 1 2;
    }

    #form-area {
        height: 38;
        overflow-y: auto;
        border: solid $accent;
        padding: 1;
        margin-bottom: 1;
    }

    #form-area > * {
        height: auto;
    }

    .field-label {
        color: $text-muted;
    }

    .move-row {
        height: 3;
    }

    .move-input {
        width: 1fr;
        margin-right: 1;
    }

    .flag-row {
        height: 3;
    }

    #progress-bar {
        display: none;
        margin-bottom: 1;
    }

    #button-row {
        height: 3;
        margin-bottom: 1;
        align: left middle;
    }

    #cancel-btn {
        display: none;
        margin-left: 2;
    }

    #retry-status {
        display: none;
        color: $warning;
        margin-bottom: 1;
    }

    #output-log {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._active_worker: Optional[Worker] = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Label("Port:", id="port-label"),
            Select(
                options=[("/dev/ttyUSB0", "/dev/ttyUSB0")],
                value="/dev/ttyUSB0",
                id="port-select",
                allow_blank=False,
            ),
            Button("↺", id="scan-ports-btn", variant="default"),
            Label("Timeout (s):", id="timeout-label"),
            Input(value="60", id="timeout-input", validators=[Number(minimum=1)]),
            id="connection-bar",
        )
        yield Horizontal(
            Vertical(
                ListView(
                    *[ListItem(Label(label), id=f"cmd-{cid}") for cid, label in COMMANDS],
                    id="command-list",
                ),
                id="sidebar",
            ),
            Vertical(
                ContentSwitcher(
                    InfoForm(id="form-info"),
                    PingForm(id="form-ping"),
                    DumpForm(id="form-dump"),
                    RestoreForm(id="form-restore"),
                    WattsForm(id="form-watts"),
                    SetPokemonForm(id="form-set-pokemon"),
                    GiftPokemonForm(id="form-gift-pokemon"),
                    GiftItemForm(id="form-gift-item"),
                    GiftStampsForm(id="form-gift-stamps"),
                    ClearItemsForm(id="form-clear-items"),
                    DownloadPokemonForm(id="form-download-pokemon"),
                    DownloadAreaForm(id="form-download-area"),
                    UploadAreaForm(id="form-upload-area"),
                    initial="form-info",
                    id="form-area",
                ),
                ProgressBar(total=65536, show_eta=False, id="progress-bar"),
                Horizontal(
                    Button("Run", variant="primary", id="run-btn"),
                    Button("Cancel", variant="error", id="cancel-btn"),
                    id="button-row",
                ),
                Label("", id="retry-status"),
                RichLog(markup=True, highlight=True, max_lines=500, id="output-log"),
                id="right-panel",
            ),
            id="main-layout",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._current_command = "info"
        self.query_one("#command-list", ListView).index = 0
        self._refresh_ports()

    def _refresh_ports(self) -> None:
        try:
            ports = list_ports()
        except Exception:
            ports = []
        if not ports:
            ports = ["/dev/ttyUSB0"]
        options = [(p, p) for p in ports]
        select = self.query_one("#port-select", Select)
        select.set_options(options)
        preferred = "/dev/ttyUSB0"
        select.value = preferred if preferred in ports else ports[0]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id and event.item.id.startswith("cmd-"):
            self._current_command = event.item.id[4:]
            self.query_one("#form-area", ContentSwitcher).current = f"form-{self._current_command}"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-btn":
            self._dispatch_run()
        elif event.button.id == "cancel-btn":
            if self._active_worker is not None:
                self._active_worker.cancel()
                self._log("[yellow]Cancelled.[/]")
                self._set_ui_state("idle")
        elif event.button.id == "scan-ports-btn":
            self._refresh_ports()

    def _dispatch_run(self) -> None:
        form_id = f"form-{self._current_command}"
        form = self.query_one(f"#{form_id}")
        try:
            params = form.collect_params()
        except FormError as e:
            self._log(f"[red]Validation error: {e}[/]")
            return

        port_val = self.query_one("#port-select", Select).value
        port = str(port_val) if port_val and port_val is not Select.BLANK else "/dev/ttyUSB0"
        timeout_raw = self.query_one("#timeout-input", Input).value.strip()
        try:
            timeout = float(timeout_raw) if timeout_raw else 60.0
        except ValueError:
            timeout = 60.0

        show_progress = self._current_command in ("dump", "restore")
        if show_progress:
            bar = self.query_one("#progress-bar", ProgressBar)
            bar.update(progress=0, total=65536)
            bar.styles.display = "block"
        else:
            self.query_one("#progress-bar", ProgressBar).styles.display = "none"

        self._set_ui_state("running")
        self._active_worker = self._run_command_worker(
            self._current_command, params, port, timeout, show_progress
        )

    @work(exclusive=True, thread=False)
    async def _run_command_worker(
        self,
        command_id: str,
        params: dict,
        port: str,
        timeout: float,
        show_progress: bool,
    ) -> None:
        MAX_RETRIES = 5
        progress_cb = self._make_progress_cb() if show_progress else None

        for attempt in range(1, MAX_RETRIES + 1):
            self._set_retry_label(attempt, MAX_RETRIES)
            try:
                result = await asyncio.to_thread(
                    _execute_command_sync,
                    command_id,
                    params,
                    port,
                    timeout,
                    progress_cb,
                )
                self._display_result(command_id, result)
                self._set_ui_state("idle")
                return
            except asyncio.CancelledError:
                return
            except CommandError as e:
                self._log(f"[red]Attempt {attempt}/{MAX_RETRIES} failed:[/] {e}")
                if attempt < MAX_RETRIES:
                    self._log("[yellow]Press the button on your Pokewalker, then try again…[/]")
            except Exception as e:
                self._log(f"[red]Unexpected error:[/] {e}")
                break

        self._log("[red bold]All attempts failed.[/] Check port and walker state.")
        self._set_ui_state("idle")

    def _make_progress_cb(self) -> Callable[[int, int], None]:
        bar = self.query_one("#progress-bar", ProgressBar)
        def cb(current: int, total: int) -> None:
            self.call_from_thread(bar.update, progress=current, total=total)
        return cb

    def _set_ui_state(self, state: str, attempt: int = 0, max_retries: int = 5) -> None:
        run_btn = self.query_one("#run-btn", Button)
        cancel_btn = self.query_one("#cancel-btn", Button)
        retry_label = self.query_one("#retry-status", Label)

        if state == "idle":
            run_btn.disabled = False
            cancel_btn.styles.display = "none"
            retry_label.styles.display = "none"
            self.query_one("#progress-bar", ProgressBar).styles.display = "none"
            self._active_worker = None
        else:
            run_btn.disabled = True
            cancel_btn.styles.display = "block"
            retry_label.styles.display = "block"

    def _set_retry_label(self, attempt: int, max_retries: int) -> None:
        label = self.query_one("#retry-status", Label)
        label.styles.display = "block"
        if attempt == 1:
            label.update("Connecting…")
        else:
            label.update(f"Attempt {attempt}/{max_retries} — press walker button…")

    def _display_result(self, command_id: str, result: dict) -> None:
        if command_id == "ping":
            self._log("[green bold]Pong![/] Walker responded.")

        elif command_id == "info":
            identity = result["identity"]
            health = result["health"]
            self._log(f"\n[bold cyan]═══ Walker Info ═══[/]")
            self._log(f"Trainer:   [bold]{identity.trainer_name}[/]  TID: {identity.trainer_tid}")
            self._log(f"Paired: {identity.is_paired}  Has Pokemon: {identity.has_pokemon}  On Walk: {identity.pokemon_on_walk}")
            if health:
                self._log(f"\n[bold cyan]═══ Stats ═══[/]")
                self._log(f"Steps:      {health.total_steps:,}  (since sync: {health.steps_since_sync:,})")
                self._log(f"Watts:      [yellow]{health.current_watts}[/]")
                self._log(f"Total days: {health.total_days}")
            if result.get("current_pokemon"):
                p = result["current_pokemon"]
                name = SPECIES.get(p.species, f"#{p.species}")
                shiny = " [yellow]★SHINY[/]" if p.is_shiny else ""
                self._log(f"\n[bold cyan]═══ Walking Pokemon ═══[/]")
                self._log(f"{name} Lv.{p.level}{shiny}")
            caught = result.get("caught") or []
            if caught:
                self._log(f"\n[bold cyan]═══ Caught ({len(caught)}) ═══[/]")
                for p in caught:
                    name = SPECIES.get(p.species, f"#{p.species}")
                    shiny = " ★" if p.is_shiny else ""
                    self._log(f"  {name} Lv.{p.level}{shiny}")
            if not result.get("magic_ok"):
                self._log("[yellow]Warning: EEPROM magic not found. Walker may be uninitialized.[/]")

        elif command_id == "dump":
            self._log(f"[green bold]Dump complete:[/] {result['path']}")

        elif command_id == "restore":
            self._log(f"[green bold]Restore complete:[/] {result['path']}")

        elif command_id == "watts":
            w = result.get("current_watts")
            self._log(f"[green bold]Added {result['amount']} watts.[/]" + (f" Current: [yellow]{w}[/]" if w is not None else ""))

        elif command_id in ("set-pokemon", "gift-pokemon"):
            action = "Set" if command_id == "set-pokemon" else "Gifted"
            self._log(f"[green bold]{action}:[/] {result['species_name']} Lv.{result['level']}")
            for w in result.get("sprite_warnings", []):
                color = "yellow" if "failed" in w or "blank" in w else "cyan"
                self._log(f"[{color}]Sprite:[/] {w}")

        elif command_id == "gift-item":
            self._log(f"[green bold]Item gifted:[/] {result['item_name']} (ID {result['item_id']})")

        elif command_id == "clear-items":
            labels = {"dowsed": "Dowsed items", "gifted": "Gifted items", "event": "Event item"}
            cleared = [labels[k] for k in result["cleared"]]
            self._log(f"[green bold]Cleared:[/] {', '.join(cleared)}")

        elif command_id == "gift-stamps":
            self._log(f"[green bold]Stamps gifted:[/] {', '.join(result['stamps'])}")

        elif command_id == "download-pokemon":
            self._log(f"[green bold]Saved to {result['output_dir']}:[/] {', '.join(result['saved'])}")

        elif command_id == "download-area":
            self._log(f"[green bold]Area image saved:[/] {result['output_path']}")

        elif command_id == "upload-area":
            self._log(f"[green bold]Area image uploaded:[/] {result['image_path']}")

    def _log(self, message: str) -> None:
        self.query_one("#output-log", RichLog).write(message)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    PokewalkerTUI().run()
