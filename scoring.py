"""Scoring helpers — fight outcome interpretation and point calculation.

Scoring scale (per plan):
  0  — forfeit / no-show
  1  — knocked out (loser)
  2  — lost judges decision
  4  — won judges decision
  5  — knocked out opponent (winner by KO)
  4  — bye (awarded to robot that receives a bye; treated like a judges-decision win)
"""

# ---------------------------------------------------------------------------
# Fight outcomes (shown in dropdown for organiser)
# ---------------------------------------------------------------------------

# Each entry: (outcome_code, display_label)
# The display_label is shown in the score-entry form.
FIGHT_OUTCOMES: list[tuple[str, str]] = [
    ("r1_ko",        "Robot 1 wins by KO  (R1: 5 pts, R2: 1 pt)"),
    ("r1_decision",  "Robot 1 wins — Judges Decision  (R1: 4 pts, R2: 2 pts)"),
    ("r2_ko",        "Robot 2 wins by KO  (R2: 5 pts, R1: 1 pt)"),
    ("r2_decision",  "Robot 2 wins — Judges Decision  (R2: 4 pts, R1: 2 pts)"),
    ("r1_forfeit",   "Robot 1 forfeit / no-show  (R1: 0 pts, R2: 5 pts)"),
    ("r2_forfeit",   "Robot 2 forfeit / no-show  (R2: 0 pts, R1: 5 pts)"),
    ("both_forfeit", "Double forfeit  (both 0 pts)"),
]

# Byes are handled automatically (not via this form): 4 points for the bye robot.
BYE_POINTS = 4

# ---------------------------------------------------------------------------
# Outcome → points
# ---------------------------------------------------------------------------

_OUTCOME_MAP: dict[str, tuple[int, int]] = {
    "r1_ko":        (5, 1),
    "r1_decision":  (4, 2),
    "r2_ko":        (1, 5),
    "r2_decision":  (2, 4),
    "r1_forfeit":   (0, 5),
    "r2_forfeit":   (5, 0),
    "both_forfeit": (0, 0),
}


def outcome_to_points(outcome: str) -> tuple[int, int]:
    """Return (robot1_pts, robot2_pts) for the given outcome code."""
    return _OUTCOME_MAP.get(outcome, (0, 0))


def points_to_outcome_label(r1_pts: int, r2_pts: int) -> str:
    """Human-readable description of the scoring result."""
    if r1_pts == 5 and r2_pts == 1:
        return "Robot 1 wins by KO"
    if r1_pts == 4 and r2_pts == 2:
        return "Robot 1 wins — decision"
    if r1_pts == 1 and r2_pts == 5:
        return "Robot 2 wins by KO"
    if r1_pts == 2 and r2_pts == 4:
        return "Robot 2 wins — decision"
    if r1_pts == 5 and r2_pts == 0:
        return "Robot 2 forfeited"
    if r1_pts == 0 and r2_pts == 5:
        return "Robot 1 forfeited"
    if r1_pts == 0 and r2_pts == 0:
        return "Double forfeit"
    return f"{r1_pts} — {r2_pts}"
