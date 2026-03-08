"""Matching algorithm — qualifying round pairing + bracket generation."""

import random

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    EventRobot,
    Matchup,
    MatchupStatus,
    Phase,
    PhaseStatus,
    PhaseType,
    Result,
    RunOrder,
    RunOrderMatchupType,
    SubEventMatchup,
    SubEventTeam,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_active_robot_ids(event_id: int, db: Session) -> list[int]:
    """Return IDs of active (non-reserve) robots for an event."""
    rows = (
        db.query(EventRobot.robot_id)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == False)
        .all()
    )
    return [r[0] for r in rows]


def get_qualifying_bye_counts(event_id: int, db: Session) -> dict[int, int]:
    """Return {robot_id: bye_count} for all qualifying rounds so far."""
    phases = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.qualifying)
        .all()
    )
    byes: dict[int, int] = {}
    for ph in phases:
        for m in ph.matchups:
            if m.robot2_id is None:
                byes[m.robot1_id] = byes.get(m.robot1_id, 0) + 1
    return byes


def get_qualifying_pairs_set(event_id: int, db: Session) -> set[frozenset]:
    """Return all (robot_id, robot_id) pairings from qualifying rounds."""
    phases = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.qualifying)
        .all()
    )
    pairs: set[frozenset] = set()
    for ph in phases:
        for m in ph.matchups:
            if m.robot2_id is not None:
                pairs.add(frozenset([m.robot1_id, m.robot2_id]))
    return pairs


def _next_slot_index(event_id: int, db: Session) -> int:
    val = (
        db.query(func.max(RunOrder.slot_index))
        .filter(RunOrder.event_id == event_id)
        .scalar()
    )
    return 0 if val is None else val + 1


# ---------------------------------------------------------------------------
# Qualifying rounds
# ---------------------------------------------------------------------------


def _make_qualifying_pairs(
    robot_ids: list[int],
    bye_counts: dict[int, int],
) -> list[tuple[int, int | None]]:
    """
    Randomly pair robots. If the count is odd, the robot with the fewest
    byes (breaking ties randomly) gets the bye this round.
    Returns list of (robot1_id, robot2_id | None).
    """
    robots = list(robot_ids)
    random.shuffle(robots)

    matchups: list[tuple[int, int | None]] = []

    if len(robots) % 2 != 0:
        min_byes = min(bye_counts.get(r, 0) for r in robots)
        bye_candidates = [r for r in robots if bye_counts.get(r, 0) == min_byes]
        bye_robot = random.choice(bye_candidates)
        robots.remove(bye_robot)
        matchups.append((bye_robot, None))

    for i in range(0, len(robots), 2):
        matchups.append((robots[i], robots[i + 1]))

    return matchups


def create_qualifying_round(event_id: int, round_number: int, db: Session) -> Phase:
    """
    Create a new qualifying round Phase with random matchups and RunOrder entries.
    The phase is set to `active` immediately.
    """
    return create_qualifying_round_with_status(
        event_id,
        round_number,
        PhaseStatus.active,
        db,
    )


def create_qualifying_round_with_status(
    event_id: int,
    round_number: int,
    status: PhaseStatus,
    db: Session,
) -> Phase:
    """Create a qualifying round with the provided phase status."""
    robot_ids = get_active_robot_ids(event_id, db)
    bye_counts = get_qualifying_bye_counts(event_id, db)
    pairs = _make_qualifying_pairs(robot_ids, bye_counts)

    phase = Phase(
        event_id=event_id,
        phase_number=round_number,
        phase_type=PhaseType.qualifying,
        status=status,
    )
    db.add(phase)
    db.flush()

    for i, (r1_id, r2_id) in enumerate(pairs):
        m = Matchup(
            phase_id=phase.id,
            robot1_id=r1_id,
            robot2_id=r2_id,
            status=MatchupStatus.pending,
            display_order=i,
            bracket_round=None,
        )
        db.add(m)
        db.flush()

        slot = _next_slot_index(event_id, db)
        db.add(RunOrder(
            event_id=event_id,
            slot_index=slot,
            matchup_type=RunOrderMatchupType.main,
            matchup_id=m.id,
        ))

    return phase


def set_incomplete_qualifying_round_state(
    event_id: int,
    active_round_number: int | None,
    db: Session,
) -> None:
    """Keep completed qualifying phases complete and set the active/pending incomplete ones."""
    qualifying_phases = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.qualifying)
        .order_by(Phase.phase_number)
        .all()
    )

    for phase in qualifying_phases:
        if phase.status == PhaseStatus.complete:
            continue
        phase.status = (
            PhaseStatus.active
            if active_round_number is not None and phase.phase_number == active_round_number
            else PhaseStatus.pending
        )


def create_qualifying_schedule(
    event_id: int,
    total_rounds: int,
    db: Session,
) -> list[Phase]:
    """Create any missing qualifying rounds up to `total_rounds` and activate round 1."""
    existing_rounds = {
        phase_number
        for (phase_number,) in (
            db.query(Phase.phase_number)
            .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.qualifying)
            .all()
        )
    }

    created: list[Phase] = []
    for round_number in range(1, total_rounds + 1):
        if round_number in existing_rounds:
            continue
        created.append(
            create_qualifying_round_with_status(
                event_id,
                round_number,
                PhaseStatus.active if round_number == 1 else PhaseStatus.pending,
                db,
            )
        )

    set_incomplete_qualifying_round_state(event_id, 1, db)
    return created


def activate_next_qualifying_round(
    event_id: int,
    current_round_number: int,
    db: Session,
) -> Phase | None:
    """Activate the next incomplete qualifying round after `current_round_number`, if any."""
    next_phase = (
        db.query(Phase)
        .filter(
            Phase.event_id == event_id,
            Phase.phase_type == PhaseType.qualifying,
            Phase.phase_number > current_round_number,
            Phase.status != PhaseStatus.complete,
        )
        .order_by(Phase.phase_number)
        .first()
    )

    set_incomplete_qualifying_round_state(
        event_id,
        next_phase.phase_number if next_phase else None,
        db,
    )
    return next_phase


# ---------------------------------------------------------------------------
# Qualifying standings
# ---------------------------------------------------------------------------


def qualifying_standings(event_id: int, db: Session) -> list[tuple[int, int]]:
    """
    Calculate per-robot total points across all completed qualifying matchups.
    Returns [(robot_id, total_pts), ...] sorted by points desc then robot_id asc.
    Also includes robots with 0 points.
    """
    phases = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.qualifying)
        .all()
    )
    phase_ids = [ph.id for ph in phases]
    robot_ids = get_active_robot_ids(event_id, db)

    standings: list[tuple[int, int]] = []
    for robot_id in robot_ids:
        pts: int = 0
        if phase_ids:
            pts = (
                db.query(func.sum(Result.points_scored))
                .join(Matchup, Matchup.id == Result.matchup_id)
                .filter(
                    Matchup.phase_id.in_(phase_ids),
                    Result.robot_id == robot_id,
                    Matchup.status == MatchupStatus.completed,
                )
                .scalar()
            ) or 0
        standings.append((robot_id, pts))

    standings.sort(key=lambda x: (-x[1], x[0]))
    return standings


# ---------------------------------------------------------------------------
# Bracket generation
# ---------------------------------------------------------------------------


def _make_bracket_pairs(
    robot_ids: list[int],
    prior_pairs: set[frozenset],
) -> list[tuple[int, int]]:
    """
    Standard bracket seeding: 1v(n), 2v(n-1), ...
    Shuffles lower seeds up to 200 times to minimise qualifying rematches.
    """
    n = len(robot_ids)
    top = robot_ids[: n // 2]
    bottom = list(reversed(robot_ids[n // 2 :]))

    def count_rematches(b: list[int]) -> int:
        return sum(1 for a, c in zip(top, b) if frozenset([a, c]) in prior_pairs)

    best_bottom = list(bottom)
    best_rem = count_rematches(bottom)

    if best_rem > 0:
        for _ in range(200):
            random.shuffle(bottom)
            rem = count_rematches(bottom)
            if rem < best_rem:
                best_bottom = list(bottom)
                best_rem = rem
            if best_rem == 0:
                break

    return list(zip(top, best_bottom))


def create_bracket(event_id: int, db: Session) -> Phase:
    """
    Generate the single-elimination bracket from the top 16 robots by
    qualifying points.  Creates a bracket Phase and Round-1 Matchups.
    """
    standings = qualifying_standings(event_id, db)
    bracket_robots = [rid for rid, _ in standings[:16]]

    # Ensure even number for clean bracket
    if len(bracket_robots) % 2 != 0:
        bracket_robots = bracket_robots[:-1]

    prior_pairs = get_qualifying_pairs_set(event_id, db)
    pairs = _make_bracket_pairs(bracket_robots, prior_pairs)

    phase = Phase(
        event_id=event_id,
        phase_number=1,
        phase_type=PhaseType.bracket,
        status=PhaseStatus.active,
    )
    db.add(phase)
    db.flush()

    for i, (r1_id, r2_id) in enumerate(pairs):
        m = Matchup(
            phase_id=phase.id,
            robot1_id=r1_id,
            robot2_id=r2_id,
            status=MatchupStatus.pending,
            display_order=i,
            bracket_round=1,
        )
        db.add(m)
        db.flush()

        slot = _next_slot_index(event_id, db)
        db.add(RunOrder(
            event_id=event_id,
            slot_index=slot,
            matchup_type=RunOrderMatchupType.main,
            matchup_id=m.id,
        ))

    return phase


# ---------------------------------------------------------------------------
# Bracket advancement
# ---------------------------------------------------------------------------


def _matchup_winner(m: Matchup) -> int | None:
    """Return the winning robot_id from a completed matchup (or None if incomplete)."""
    if m.status != MatchupStatus.completed:
        return None
    if m.robot2_id is None:
        return m.robot1_id  # bye
    r1_pts = next((r.points_scored for r in m.results if r.robot_id == m.robot1_id), 0)
    r2_pts = next((r.points_scored for r in m.results if r.robot_id == m.robot2_id), 0)
    return m.robot1_id if r1_pts >= r2_pts else m.robot2_id


def advance_bracket_round(
    event_id: int,
    bracket_phase_id: int,
    current_round: int,
    db: Session,
) -> list[Matchup]:
    """
    Generate the next bracket round from the winners of `current_round`.
    Returns the list of new Matchups, or [] if not all fights are complete.
    """
    current_matchups = (
        db.query(Matchup)
        .filter(
            Matchup.phase_id == bracket_phase_id,
            Matchup.bracket_round == current_round,
        )
        .order_by(Matchup.display_order)
        .all()
    )

    winners: list[int] = []
    for m in current_matchups:
        winner = _matchup_winner(m)
        if winner is None:
            return []  # round not fully complete
        winners.append(winner)

    if len(winners) <= 1:
        return []  # final already played

    next_round = current_round + 1
    new_matchups: list[Matchup] = []

    max_order = (
        db.query(func.max(Matchup.display_order))
        .filter(Matchup.phase_id == bracket_phase_id)
        .scalar()
    ) or 0

    for i in range(0, len(winners), 2):
        r1_id = winners[i]
        r2_id = winners[i + 1] if i + 1 < len(winners) else None
        m = Matchup(
            phase_id=bracket_phase_id,
            robot1_id=r1_id,
            robot2_id=r2_id,
            status=MatchupStatus.pending,
            display_order=max_order + i + 1,
            bracket_round=next_round,
        )
        db.add(m)
        db.flush()

        slot = _next_slot_index(event_id, db)
        db.add(RunOrder(
            event_id=event_id,
            slot_index=slot,
            matchup_type=RunOrderMatchupType.main,
            matchup_id=m.id,
        ))
        new_matchups.append(m)

    return new_matchups


# ---------------------------------------------------------------------------
# Sub-event helpers
# ---------------------------------------------------------------------------


def get_sub_event_eligible_robots(event_id: int, db: Session) -> list[int]:
    """
    Return robot IDs eligible for sub-event participation:
      1. Active robots NOT in the bracket (didn't make the top 16).
      2. Robots that participated in bracket round 1 and lost.
    If no bracket exists, returns all active robot IDs.
    """
    active_robot_ids = set(get_active_robot_ids(event_id, db))

    bracket_phase = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.bracket)
        .first()
    )

    if not bracket_phase:
        return sorted(active_robot_ids)

    r1_matchups = (
        db.query(Matchup)
        .filter(
            Matchup.phase_id == bracket_phase.id,
            Matchup.bracket_round == 1,
        )
        .all()
    )

    bracket_robot_ids: set[int] = set()
    round1_losers: set[int] = set()

    for m in r1_matchups:
        bracket_robot_ids.add(m.robot1_id)
        if m.robot2_id:
            bracket_robot_ids.add(m.robot2_id)
        if m.status == MatchupStatus.completed and m.robot2_id:
            r1_pts = next((r.points_scored for r in m.results if r.robot_id == m.robot1_id), 0)
            r2_pts = next((r.points_scored for r in m.results if r.robot_id == m.robot2_id), 0)
            if r1_pts >= r2_pts:
                round1_losers.add(m.robot2_id)
            else:
                round1_losers.add(m.robot1_id)

    non_bracket = active_robot_ids - bracket_robot_ids
    return sorted(non_bracket | round1_losers)


def create_sub_event_bracket(sub_event_id: int, event_id: int, db: Session) -> list[SubEventMatchup]:
    """
    Generate Round 1 SubEventMatchup records for the sub-event bracket.
    Teams are randomly drawn. If the count is odd the last team gets a bye (auto-win).
    Returns the list of new SubEventMatchup objects.
    """
    teams = (
        db.query(SubEventTeam)
        .filter(SubEventTeam.sub_event_id == sub_event_id)
        .all()
    )
    if len(teams) < 2:
        return []

    team_ids = [t.id for t in teams]
    random.shuffle(team_ids)

    bye_team_id: int | None = None
    if len(team_ids) % 2 != 0:
        bye_team_id = team_ids.pop()

    half = len(team_ids) // 2
    pairs = list(zip(team_ids[:half], reversed(team_ids[half:])))

    new_matchups: list[SubEventMatchup] = []

    for i, (t1_id, t2_id) in enumerate(pairs):
        m = SubEventMatchup(
            sub_event_id=sub_event_id,
            team1_id=t1_id,
            team2_id=t2_id,
            status=MatchupStatus.pending,
            display_order=i,
            round_number=1,
        )
        db.add(m)
        db.flush()

        slot = _next_slot_index(event_id, db)
        db.add(RunOrder(
            event_id=event_id,
            slot_index=slot,
            matchup_type=RunOrderMatchupType.sub_event,
            matchup_id=m.id,
        ))
        new_matchups.append(m)

    if bye_team_id is not None:
        m = SubEventMatchup(
            sub_event_id=sub_event_id,
            team1_id=bye_team_id,
            team2_id=None,
            winner_team_id=bye_team_id,
            status=MatchupStatus.completed,
            display_order=len(pairs),
            round_number=1,
        )
        db.add(m)
        db.flush()
        new_matchups.append(m)

    return new_matchups


def advance_sub_event_bracket(
    sub_event_id: int,
    current_round: int,
    event_id: int,
    db: Session,
) -> list[SubEventMatchup]:
    """
    Generate the next sub-event bracket round from the winners of `current_round`.
    Returns new SubEventMatchup objects, or [] if the round is incomplete / tournament over.
    """
    current_matchups = (
        db.query(SubEventMatchup)
        .filter(
            SubEventMatchup.sub_event_id == sub_event_id,
            SubEventMatchup.round_number == current_round,
        )
        .order_by(SubEventMatchup.display_order)
        .all()
    )

    if any(m.status != MatchupStatus.completed for m in current_matchups):
        return []

    winners = [m.winner_team_id for m in current_matchups if m.winner_team_id]
    if len(winners) <= 1:
        return []  # final already decided

    bye_winner_id: int | None = None
    if len(winners) % 2 != 0:
        bye_winner_id = winners.pop()

    half = len(winners) // 2
    pairs = list(zip(winners[:half], reversed(winners[half:])))

    next_round = current_round + 1
    new_matchups: list[SubEventMatchup] = []

    for i, (t1_id, t2_id) in enumerate(pairs):
        m = SubEventMatchup(
            sub_event_id=sub_event_id,
            team1_id=t1_id,
            team2_id=t2_id,
            status=MatchupStatus.pending,
            display_order=i,
            round_number=next_round,
        )
        db.add(m)
        db.flush()

        slot = _next_slot_index(event_id, db)
        db.add(RunOrder(
            event_id=event_id,
            slot_index=slot,
            matchup_type=RunOrderMatchupType.sub_event,
            matchup_id=m.id,
        ))
        new_matchups.append(m)

    if bye_winner_id is not None:
        m = SubEventMatchup(
            sub_event_id=sub_event_id,
            team1_id=bye_winner_id,
            team2_id=None,
            winner_team_id=bye_winner_id,
            status=MatchupStatus.completed,
            display_order=len(pairs),
            round_number=next_round,
        )
        db.add(m)
        db.flush()
        new_matchups.append(m)

    return new_matchups
