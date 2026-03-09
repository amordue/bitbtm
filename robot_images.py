"""Fallback image resolution for robots without uploaded photos.

Priority order:
  1. Uploaded / sheet image (robot.image_url)
  2. Archetype image based on normalized weapon_type
  3. Generic robot blueprint
"""

import re
from typing import Optional

from models import Robot

# Canonical archetype slugs matching filenames in static/robot-archetypes/
_ARCHETYPES = frozenset({
    "flipper",
    "vertical-spinner",
    "horizontal-spinner",
    "drum-spinner",
    "hammer",
    "saw",
    "lifter",
    "grabber",
    "cluster",
    "rammer",
    "generic",
})

# Maps lowercased / stripped weapon labels to archetype slugs.
_WEAPON_ALIASES: dict[str, str] = {
    "flipper": "flipper",
    "flip": "flipper",
    "vertical spinner": "vertical-spinner",
    "vert spinner": "vertical-spinner",
    "vert": "vertical-spinner",
    "spinner": "vertical-spinner",
    "horizontal spinner": "horizontal-spinner",
    "horiz spinner": "horizontal-spinner",
    "full body spinner": "horizontal-spinner",
    "bar spinner": "horizontal-spinner",
    "drum": "drum-spinner",
    "drum spinner": "drum-spinner",
    "hammer": "hammer",
    "axe": "hammer",
    "hammer-saw": "saw",
    "hammer saw": "saw",
    "saw": "saw",
    "lifter": "lifter",
    "lift": "lifter",
    "grabber": "grabber",
    "grab": "grabber",
    "crusher": "grabber",
    "clamp": "grabber",
    "cluster": "cluster",
    "clusterbot": "cluster",
    "cluster bot": "cluster",
    "multibot": "cluster",
    "rammer": "rammer",
    "ram": "rammer",
    "wedge": "rammer",
    "pusher": "rammer",
}

_CLEAN_RE = re.compile(r"[^a-z0-9 ]")


def normalize_weapon_type(weapon_type: Optional[str]) -> str:
    """Return the archetype slug for *weapon_type*, or ``'generic'``."""
    if not weapon_type:
        return "generic"
    cleaned = _CLEAN_RE.sub(" ", weapon_type.lower()).strip()
    cleaned = " ".join(cleaned.split())  # collapse whitespace
    return _WEAPON_ALIASES.get(cleaned, "generic")


def robot_display_image_url(robot: Optional[Robot]) -> Optional[str]:
    """Return the best image URL for *robot*, or ``None`` for non-robots.

    Returns ``None`` when *robot* is ``None`` (TBD / BYE slots).
    """
    if robot is None:
        return None
    if robot.image_url:
        return robot.image_url
    archetype = normalize_weapon_type(robot.weapon_type)
    return f"/static/robot-archetypes/{archetype}.svg"


def robot_has_uploaded_image(robot: Optional[Robot]) -> bool:
    """True when *robot* has a real uploaded or sheet-sourced image."""
    return robot is not None and bool(robot.image_url)
