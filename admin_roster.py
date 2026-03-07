"""Roster and reserve helpers for admin event views."""

from typing import Optional

from sqlalchemy.orm import Session

from models import EventRobot, MatchupStatus, Phase, PhaseType, Robot, SubEvent


def active_event_robots(event_id: int, db: Session) -> list[EventRobot]:
    """Return active roster entries ordered by robot name."""
    return (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == False)
        .join(Robot)
        .order_by(Robot.robot_name)
        .all()
    )


def reserve_event_robots(event_id: int, db: Session) -> list[EventRobot]:
    """Return reserve roster entries in reserve order."""
    return (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == True)
        .order_by(EventRobot.reserve_order.asc().nullslast(), EventRobot.id)
        .all()
    )


def ordered_event_phases(event_id: int, db: Session) -> list[Phase]:
    """Return event phases ordered by phase number."""
    return db.query(Phase).filter(Phase.event_id == event_id).order_by(Phase.phase_number).all()


def ordered_sub_events(event_id: int, db: Session) -> list[SubEvent]:
    """Return sub-events ordered by creation order."""
    return db.query(SubEvent).filter(SubEvent.event_id == event_id).order_by(SubEvent.id).all()


def event_robot_entry(event_id: int, event_robot_id: int, db: Session) -> Optional[EventRobot]:
    """Return a roster entry scoped to an event."""
    return (
        db.query(EventRobot)
        .filter(EventRobot.id == event_robot_id, EventRobot.event_id == event_id)
        .first()
    )


def active_robot_count(event_id: int, db: Session) -> int:
    """Count active roster entries for an event."""
    return (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == False)
        .count()
    )


def renumber_reserves(event_id: int, db: Session) -> None:
    """Re-number reserve_order values to be contiguous after a change."""
    for index, reserve in enumerate(reserve_event_robots(event_id, db), start=1):
        reserve.reserve_order = index


def round_one_complete(bracket_phase: Optional[Phase]) -> bool:
    """Return True when bracket round 1 exists and every matchup is complete."""
    if not bracket_phase:
        return False
    round_one_matchups = [m for m in bracket_phase.matchups if m.bracket_round == 1]
    return bool(round_one_matchups) and all(m.status == MatchupStatus.completed for m in round_one_matchups)


def qualifying_phases(phases: list[Phase]) -> list[Phase]:
    """Return only qualifying phases from an event phase list."""
    return [phase for phase in phases if phase.phase_type == PhaseType.qualifying]