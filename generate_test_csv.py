#!/usr/bin/env python3
"""Generate a robot-registration CSV for pasting into Google Sheets.

Usage:
    python generate_test_csv.py                # 32 entries to stdout
    python generate_test_csv.py 16             # 16 entries to stdout
    python generate_test_csv.py 64 -o big.csv  # 64 entries to file
    python generate_test_csv.py --seed 42      # reproducible output
"""

import argparse
import csv
import random
import sys

# ---------------------------------------------------------------------------
# Name pools
# ---------------------------------------------------------------------------

_FIRST_NAMES = [
    "Alex", "Jamie", "Sam", "Casey", "Morgan", "Jordan", "Taylor", "Riley",
    "Devon", "Quinn", "Avery", "Skyler", "Drew", "Harley", "Reece", "Logan",
    "Rowan", "Finley", "Phoenix", "Charlie", "Blake", "Sage", "River", "Remy",
    "Arlo", "Piper", "Emery", "Dallas", "Kendall", "Spencer", "Darby", "Ellis",
    "Hayden", "Indigo", "Jesse", "Kai", "Lane", "Maxen", "Nova", "Onyx",
    "Paxton", "Quin", "Raven", "Sloane", "Tatum", "Uma", "Vesper", "Wren",
]

_LAST_NAMES = [
    "Morgan", "Lee", "Rivers", "Ford", "Blake", "West", "Kim", "Stone",
    "Ash", "Hall", "Brooks", "Vane", "Mercer", "Page", "Noble", "Sharp",
    "Cross", "Day", "Ray", "Sun", "Hart", "Knox", "Lowe", "Marsh",
    "Nash", "Oakes", "Price", "Reeves", "Scott", "Thorn", "Upton", "Vale",
    "Ward", "York", "Zane", "Byrne", "Crane", "Drake", "Estes", "Fox",
    "Grant", "Hyde", "Ives", "Jump", "Kirk", "Lake", "Mace", "Nunn",
]

# ---------------------------------------------------------------------------
# Robot name generation
# ---------------------------------------------------------------------------

_ADJECTIVES = [
    "Iron", "Steel", "Shatter", "Thunder", "Inferno", "Chaos", "Venom",
    "Titan", "Rogue", "Apex", "Nexus", "Void", "Storm", "Blaze", "Savage",
    "Hyper", "Ultra", "Turbo", "Cyber", "Quantum", "Lunar", "Solar", "Plasma",
    "Feral", "Chrome", "Obsidian", "Crimson", "Cobalt", "Nitro", "Phantom",
    "Omega", "Alpha", "Delta", "Sigma", "Zeta", "Nova", "Arc", "Bolt",
    "Slash", "Crush", "Spike", "Blitz", "Havoc", "Maul", "Wreck", "Rift",
]

_NOUNS = [
    "Force", "Edge", "Fang", "Claw", "Blade", "Hammer", "Spike", "Wedge",
    "Drum", "Titan", "Vortex", "Fury", "Storm", "Surge", "Crush", "Shred",
    "Ram", "Charge", "Plough", "Bite", "Ripper", "Smasher", "Grinder",
    "Breaker", "Crusher", "Mangler", "Pulser", "Slammer", "Brawler", "Basher",
    "Punisher", "Destroyer", "Annihilator", "Decimator", "Obliterator",
    "Wrecker", "Ravager", "Mutilator", "Rampager", "Bruiser", "Smasher",
    "Warhead", "Payload", "Warpath", "Juggernaut", "Dreadnought",
]

_PREFIXES = ["The", ""]  # sometimes no prefix

# Weapon types — values that exercise the alias table in robot_images.py
_WEAPON_TYPES = [
    # canonical names
    "Flipper",
    "Vertical spinner",
    "Horizontal spinner",
    "Drum spinner",
    "Hammer",
    "Saw",
    "Lifter",
    "Grabber",
    "Cluster",
    "Rammer",
    # alias forms that exercise normalization
    "Spinner",
    "Drum",
    "Wedge",
    "Ram",
    "Vert spinner",
    "Hammer-Saw",
]

# Weighted distribution — spinners and wedges are more common in real events
_WEAPON_WEIGHTS = [
    8,   # Flipper
    14,  # Vertical spinner
    8,   # Horizontal spinner
    10,  # Drum spinner
    10,  # Hammer
    4,   # Saw
    8,   # Lifter
    4,   # Grabber
    4,   # Cluster
    8,   # Rammer
    6,   # Spinner (alias)
    4,   # Drum (alias)
    6,   # Wedge (alias)
    4,   # Ram (alias)
    4,   # Vert spinner (alias)
    4,   # Hammer-Saw (alias)
]


def _unique_full_names(n: int, rng: random.Random) -> list[tuple[str, str]]:
    """Return *n* unique (first, last) name pairs."""
    pool = [
        (f, l)
        for f in _FIRST_NAMES
        for l in _LAST_NAMES
        if f != l
    ]
    rng.shuffle(pool)
    if n > len(pool):
        raise ValueError(f"Cannot generate {n} unique names (pool has {len(pool)})")
    return pool[:n]


def _unique_robot_names(n: int, rng: random.Random) -> list[str]:
    """Return *n* unique robot names."""
    seen: set[str] = set()
    names: list[str] = []
    attempts = 0
    while len(names) < n:
        attempts += 1
        if attempts > n * 20:
            raise ValueError(f"Could not generate {n} unique robot names")
        prefix = rng.choice(_PREFIXES)
        adj = rng.choice(_ADJECTIVES)
        noun = rng.choice(_NOUNS)
        parts = [p for p in (prefix, adj, noun) if p]
        name = " ".join(parts)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def generate_rows(count: int, rng: random.Random) -> list[dict]:
    full_names = _unique_full_names(count, rng)
    robot_names = _unique_robot_names(count, rng)
    weapon_choices = rng.choices(_WEAPON_TYPES, weights=_WEAPON_WEIGHTS, k=count)

    rows = []
    for (first, last), robot_name, weapon in zip(full_names, robot_names, weapon_choices):
        roboteer = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}@example.com"
        # Leave weapon blank for ~5% of entries to exercise the generic fallback
        if rng.random() < 0.05:
            weapon = ""
        # Give ~10% of entries a (fake) image URL
        image_url = ""
        if rng.random() < 0.10:
            slug = robot_name.lower().replace(" ", "-")
            image_url = f"https://example.com/robots/{slug}.jpg"
        rows.append({
            "Roboteer Name": roboteer,
            "Robot Name": robot_name,
            "Weapon Type": weapon,
            "Contact Email": email,
            "Image URL": image_url,
        })
    return rows


def write_csv(rows: list[dict], out) -> None:
    fieldnames = ["Roboteer Name", "Robot Name", "Weapon Type", "Contact Email", "Image URL"]
    writer = csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row[k] for k in fieldnames})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a robot-registration CSV for Google Sheets import."
    )
    parser.add_argument(
        "count", type=int, nargs="?", default=32, metavar="N",
        help="Number of entries to generate (default: 32)",
    )
    parser.add_argument(
        "--output", "-o", default=None, metavar="FILE",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--seed", type=int, default=None, metavar="N",
        help="Random seed for reproducible output",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    rows = generate_rows(args.count, rng)

    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            write_csv(rows, f)
        print(f"Written {args.count} entries to {args.output}")
    else:
        write_csv(rows, sys.stdout)


if __name__ == "__main__":
    main()
