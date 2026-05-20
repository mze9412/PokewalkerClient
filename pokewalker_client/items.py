"""
Item ID lookup table for Gen 4 (HGSS).
IDs marked with (*) are confirmed against the gifts.py Items class.
"""

ITEMS: dict[int, str] = {
    # Poké Balls
    1: "Master Ball",       # *
    2: "Ultra Ball",        # *
    3: "Great Ball",        # *
    4: "Poké Ball",         # *
    5: "Safari Ball",
    6: "Net Ball",
    7: "Dive Ball",
    8: "Nest Ball",
    9: "Repeat Ball",
    10: "Timer Ball",
    11: "Luxury Ball",
    12: "Premier Ball",
    13: "Dusk Ball",
    14: "Heal Ball",
    15: "Quick Ball",
    16: "Cherish Ball",

    # Medicine
    17: "Potion",           # *
    18: "Antidote",
    19: "Burn Heal",
    20: "Ice Heal",
    21: "Awakening",
    22: "Paralyze Heal",
    23: "Full Heal",
    25: "Fresh Water",
    26: "Super Potion",     # *
    27: "Hyper Potion",     # *
    28: "Max Potion",       # *
    29: "Full Restore",     # *
    30: "Revive",           # *
    31: "Max Revive",       # *

    # Stat boosters / Battle items
    34: "Ether",
    35: "Max Ether",
    36: "Elixir",
    37: "Max Elixir",

    # Vitamins
    41: "HP Up",
    42: "Protein",
    43: "Iron",
    44: "Carbos",
    45: "Calcium",
    46: "Zinc",

    # Rare
    50: "Rare Candy",       # *
    51: "PP Up",            # *
    53: "PP Max",           # *

    # Evolution stones
    80: "Sun Stone",        # *
    81: "Moon Stone",       # *
    82: "Fire Stone",       # *
    83: "Thunder Stone",    # *
    84: "Water Stone",      # *
    85: "Leaf Stone",       # *
    86: "Shiny Stone",
    87: "Dusk Stone",
    88: "Dawn Stone",
    89: "Oval Stone",

    # Valuable items
    92: "Nugget",           # *

    # Berries (149–207; positions anchored by gifts.py: 155=Oran, 157=Lum, 158=Sitrus, 207=Starf)
    149: "Cheri Berry",
    150: "Chesto Berry",
    151: "Pecha Berry",
    152: "Rawst Berry",
    153: "Aspear Berry",
    154: "Leppa Berry",
    155: "Oran Berry",      # *
    156: "Persim Berry",
    157: "Lum Berry",       # *
    158: "Sitrus Berry",    # *
    159: "Figy Berry",
    160: "Wiki Berry",
    161: "Mago Berry",
    162: "Aguav Berry",
    163: "Iapapa Berry",
    164: "Razz Berry",
    165: "Bluk Berry",
    166: "Nanab Berry",
    167: "Wepear Berry",
    168: "Pinap Berry",
    169: "Pomeg Berry",
    170: "Kelpsy Berry",
    171: "Qualot Berry",
    172: "Hondew Berry",
    173: "Grepa Berry",
    174: "Tamato Berry",
    175: "Cornn Berry",
    176: "Magost Berry",
    177: "Rabuta Berry",
    178: "Nomel Berry",
    179: "Spelon Berry",
    180: "Pamtre Berry",
    181: "Watmel Berry",
    182: "Durin Berry",
    183: "Belue Berry",
    184: "Occa Berry",
    185: "Passho Berry",
    186: "Wacan Berry",
    187: "Rindo Berry",
    188: "Yache Berry",
    189: "Chople Berry",
    190: "Kebia Berry",
    191: "Shuca Berry",
    192: "Coba Berry",
    193: "Payapa Berry",
    194: "Tanga Berry",
    195: "Charti Berry",
    196: "Kasib Berry",
    197: "Haban Berry",
    198: "Colbur Berry",
    199: "Babiri Berry",
    200: "Chilan Berry",
    201: "Liechi Berry",
    202: "Ganlon Berry",
    203: "Salac Berry",
    204: "Petaya Berry",
    205: "Apicot Berry",
    206: "Lansat Berry",
    207: "Starf Berry",     # *

    # Held items
    234: "Leftovers",       # *

    # Gen 5+ (may work depending on firmware)
    581: "Big Nugget",      # *
}

ITEMS_BY_NAME: dict[str, int] = {name.lower(): item_id for item_id, name in ITEMS.items()}
