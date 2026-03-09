#!/usr/bin/env python3
"""Populate qualifying round results for a test event.

Finds pending qualifying matchups in the database and scores them with
random realistic outcomes. Can optionally create new qualifying rounds first.

Usage:
    # Score all pending qualifying matchups for the most recent event
    python generate_qualifying_results.py

    # Create 3 qualifying rounds and score them for event ID 1
    python generate_qualifying_results.py --event-id 1 --rounds 3

    # Dry run — show what would happen without writing to the DB
    python generate_qualifying_results.py --dry-run

    # Reproducible output
    python generate_qualifying_results.py --seed 42
"""

import argparse
import random
import sys

from sqlalchemy.orm import Session

import database
from matching import (
    activate_next_qualifying_round,
    create_qualifying_round,
    qualifying_standings,
)
from models import (
    Event,
    EventStatus,
    Matchup,
    MatchupStatus,
    Phase,
    PhaseStatus,
    PhaseType,
    Result,
    Robot,
)
from scoring import BYE_POINTS, outcome_to_points

# ---------------------------------------------------------------------------
# Outcome probability table
# ---------------------------------------------------------------------------
# (outcome_code, weight)  — weights are approximate for a typical beetle event
_OUTCOMES = [
    ("r1_ko",        40),
    ("r1_decision",  30),
    ("r2_ko",        40),
    ("r2_decision",  30),
    ("r1_forfeit",    4),
    ("r2_forfeit",    4),
    ("both_forfeit",  2),
]
_OUTCOME_CODES    = [o for o, _ in _OUTCOMES]
_OUTCOME_WEIGHTS  = [w for _, w in _OUTCOMES]


def _pick_outcome(rng: random.Random) -> str:
    return rng.choices(_OUTCOME_CODES, weights=_OUTCOME_WEIGHTS, k=1)[0]


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def _find_event(event_id: int | None, db: Session) -> Event:
    if event_id is not None:
        ev = db.query(Event).filter(Event.id == event_id).first()
        if not ev:
            print(f"Error: no event with id={event_id}", file=sys.stderr)
            sys.exit(1)
        return ev
    ev = db.query(Event).order_by(Event.id.desc()).first()
    if not ev:
        print("Error: no events in database.", file=sys.stderr)
        sys.exit(1)
    return ev


def _next_round_number(event_id: int, db: Session) -> int:
    last = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.qualifying)
        .order_by(Phase.phase_number.desc())
        .first()
    )
    return (last.phase_number + 1) if last else 1


def _score_matchup(
    m: Matchup,
    rng: random.Random,
    db: Session,
    dry_run: bool,
) -> str:
    """Score a single matchup. Returns a description string."""
    if m.robot2_id is None:
        # Bye
        r1: Robot = m.robot1
        desc = f"  BYE   {r1.robot_name:<24} → {BYE_POINTS} pts"
        if not dry_run:
            db.query(Result).filter(Result.matchup_id == m.id).delete()
            db.add(Result(matchup_id=m.id, robot_id=m.robot1_id, points_scored=BYE_POINTS))
            m.status = MatchupStatus.completed
        return desc

    outcome = _pick_outcome(rng)
    r1_pts, r2_pts = outcome_to_points(outcome)
    r1: Robot = m.robot1
    r2: Robot = m.robot2
    desc = (
        f"  {r1.robot_name:<24} {r1_pts} — {r2_pts}  {r2.robot_name}"
    )
    if not dry_run:
        db.query(Result).filter(Result.matchup_id == m.id).delete()
        db.add(Result(matchup_id=m.id, robot_id=m.robot1_id, points_scored=r1_pts))
        db.add(Result(matchup_id=m.id, robot_id=m.robot2_id, points_scored=r2_pts))
        m.status = MatchupStatus.completed
    return desc


def _complete_phase_if_done(phase: Phase, db: Session, dry_run: bool) -> bool:
    """Mark phase complete if all matchups are done. Returns True if completed."""
    if dry_run:
        return True  # assume all will complete in dry-run
    if all(mx.status == MatchupStatus.completed for mx in phase.matchups):
        phase.status = PhaseStatus.complete
        return True
    return False


def run(
    event_id: int | None,
    rounds_to_create: int,
    dry_run: bool,
    rng: random.Random,
) -> None:
    db: Session = database.SessionLocal()
    try:
        ev = _find_event(event_id, db)
        tag = "[DRY RUN] " if dry_run else ""
        print(f"{tag}Event: {ev.event_name!r} (id={ev.id}, status={ev.status})")

        # ---- Optionally create new qualifying rounds ----
        if rounds_to_create > 0:
            start = _next_round_number(ev.id, db)
            for i in range(rounds_to_create):
                rn = start + i
                print(f"\n{tag}Creating qualifying round {rn}…")
                if not dry_run:
                    phase = create_qualifying_round(ev.id, rn, db)
                    db.flush()
                    print(f"  Phase id={phase.id} created with {len(phase.matchups)} matchup(s)")
                else:
                    print("  (skipped in dry-run)")

        # ---- Score all pending qualifying matchups ----
        phases = (
            db.query(Phase)
            .filter(
                Phase.event_id == ev.id,
                Phase.phase_type == PhaseType.qualifying,
            )
            .order_by(Phase.phase_number)
            .all()
        )

        if not phases:
            print("\nNo qualifying phases found. Use --rounds N to create some.")
            return

        total_scored = 0
        for phase in phases:
            pending = [m for m in phase.matchups if m.status == MatchupStatus.pending]
            if not pending:
                continue
            print(f"\n{tag}Round {phase.phase_number} — scoring {len(pending)} matchup(s):")
            for m in pending:
                desc = _score_matchup(m, rng, db, dry_run)
                print(desc)
                total_scored += 1

            if not dry_run:
                completed = _complete_phase_if_done(phase, db, dry_run)
                if completed:
                    activate_next_qualifying_round(ev.id, phase.phase_number, db)
                    print(f"  → Round {phase.phase_number} complete.")

        if not dry_run and total_scored > 0:
            db.commit()
            print(f"\nCommitted. {total_scored} matchup(s) scored.")
        elif dry_run:
            print(f"\n(Dry run complete — {total_scored} matchup(s) would be scored.)")
        else:
            print("\nNo pending matchups found.")

        # ---- Print standings summary ----
        print("\nStandings after scoring:")
        standings = qualifying_standings(ev.id, db)
        robot_map: dict[int, Robot] = {
            r.id: r
            for r in db.query(Robot).filter(Robot.id.in_([rid for rid, _ in standings])).all()
        }
        for rank, (robot_id, pts) in enumerate(standings, 1):
            robot = robot_map.get(robot_id)
            name = robot.robot_name if robot else f"robot#{robot_id}"
            print(f"  {rank:>3}. {name:<26} {pts} pts")

    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate random qualifying round results for a test event."
    )
    parser.add_argument(
        "--event-id", type=int, default=None, metavar="ID",
        help="Event ID to target (default: most recently created event)",
    )
    parser.add_argument(
        "--rounds", type=int, default=0, metavar="N",
        help="Number of new qualifying rounds to create before scoring (default: 0)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen without writing to the database",
    )
    parser.add_argument(
        "--seed", type=int, default=None, metavar="N",
        help="Random seed for reproducible results",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    run(args.event_id, args.rounds, args.dry_run, rng)


if __name__ == "__main__":
    main()
