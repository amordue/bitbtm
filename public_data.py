"""Shared data helpers for public event views."""

from typing import Any, Callable, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models import (
    EventRobot,
    Matchup,
    MatchupStatus,
    Phase,
    PhaseType,
    Result,
    Robot,
    RunOrder,
    RunOrderMatchupType,
    SubEvent,
    SubEventMatchup,
)
from scoring import BYE_POINTS, points_to_outcome_label


def robot_has_event_history(robot_id: int, event_id: int, db: Session) -> bool:
    """Return True if the robot is currently registered or has fought in the event."""
    active_or_reserve = (
        db.query(EventRobot.id)
        .filter(EventRobot.event_id == event_id, EventRobot.robot_id == robot_id)
        .first()
    )
    if active_or_reserve:
        return True

    prior_match = (
        db.query(Matchup.id)
        .join(Phase, Phase.id == Matchup.phase_id)
        .filter(
            Phase.event_id == event_id,
            or_(Matchup.robot1_id == robot_id, Matchup.robot2_id == robot_id),
        )
        .first()
    )
    return prior_match is not None


def robot_points_in_event(robot_id: int, event_id: int, db: Session) -> int:
    """Return total points scored by a robot across all completed matchups in this event."""
    total = (
        db.query(func.sum(Result.points_scored))
        .join(Matchup, Matchup.id == Result.matchup_id)
        .join(Phase, Phase.id == Matchup.phase_id)
        .filter(
            Phase.event_id == event_id,
            Result.robot_id == robot_id,
            Matchup.status == MatchupStatus.completed,
        )
        .scalar()
    )
    return total or 0


def leaderboard_rows(event_id: int, db: Session) -> list[dict[str, Any]]:
    """Aggregate public leaderboard rows used by multiple views."""
    active_ers = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == False)
        .all()
    )

    rows: list[dict[str, Any]] = []
    for er in active_ers:
        robot = er.robot
        results = (
            db.query(Result)
            .join(Matchup, Matchup.id == Result.matchup_id)
            .join(Phase, Phase.id == Matchup.phase_id)
            .filter(
                Phase.event_id == event_id,
                Result.robot_id == robot.id,
                Matchup.status == MatchupStatus.completed,
            )
            .all()
        )

        total_pts = sum(result.points_scored for result in results)
        fights = len(results)
        wins = 0
        matchup_ids = sorted({result.matchup_id for result in results})

        for matchup_id in matchup_ids:
            all_results = db.query(Result).filter(Result.matchup_id == matchup_id).all()
            if len(all_results) >= 2:
                my_pts = next((r.points_scored for r in all_results if r.robot_id == robot.id), 0)
                opp_pts = next((r.points_scored for r in all_results if r.robot_id != robot.id), 0)
                if my_pts > opp_pts:
                    wins += 1
            elif len(all_results) == 1:
                wins += 1

        rows.append(
            {
                "robot": robot,
                "roboteer": robot.roboteer,
                "total_pts": total_pts,
                "fights": fights,
                "wins": wins,
            }
        )

    rows.sort(key=lambda row: (-row["total_pts"], -row["wins"], row["robot"].robot_name.lower()))
    return rows


def resolve_run_order_item(
    event_id: int,
    run_order: RunOrder,
    db: Session,
    phase_long_label: Callable[[Phase, Matchup], str],
) -> Optional[dict[str, Any]]:
    """Resolve a run-order entry into a display-friendly public view model."""
    if run_order.matchup_type == RunOrderMatchupType.main:
        matchup = db.query(Matchup).filter(Matchup.id == run_order.matchup_id).first()
        if not matchup:
            return None

        phase = matchup.phase
        r1_name = matchup.robot1.robot_name if matchup.robot1 else "TBD"
        r2_name = matchup.robot2.robot_name if matchup.robot2 else "BYE"
        return {
            "run_order_id": run_order.id,
            "slot_index": run_order.slot_index,
            "status": matchup.status,
            "title": f"{r1_name} vs {r2_name}" if matchup.robot2_id else f"{r1_name} receives a bye",
            "meta": phase_long_label(phase, matchup),
            "href": f"/events/{event_id}/bracket" if phase.phase_type == PhaseType.bracket else f"/events/{event_id}/robot/{matchup.robot1_id}",
            "robot1_name": r1_name,
            "robot1_href": f"/events/{event_id}/robot/{matchup.robot1_id}" if matchup.robot1_id else None,
            "robot2_name": r2_name if matchup.robot2_id else None,
            "robot2_href": f"/events/{event_id}/robot/{matchup.robot2_id}" if matchup.robot2_id else None,
            "type_label": "Main Event",
        }

    matchup = db.query(SubEventMatchup).filter(SubEventMatchup.id == run_order.matchup_id).first()
    if not matchup:
        return None

    team1 = matchup.team1.team_name if matchup.team1 else "TBD"
    team2 = matchup.team2.team_name if matchup.team2 else "BYE"
    sub_event_name = matchup.sub_event.name if matchup.sub_event else "Sub-event"
    return {
        "run_order_id": run_order.id,
        "slot_index": run_order.slot_index,
        "status": matchup.status,
        "title": f"{team1} vs {team2}" if matchup.team2_id else f"{team1} advances by bye",
        "meta": f"{sub_event_name} · Round {matchup.round_number}",
        "href": f"/events/{event_id}/sub-events/{matchup.sub_event_id}",
        "type_label": "Sub-event",
    }


def pending_run_order_items(
    event_id: int,
    db: Session,
    phase_long_label: Callable[[Phase, Matchup], str],
) -> list[dict[str, Any]]:
    """Return pending run-order entries in display order."""
    rows = (
        db.query(RunOrder)
        .filter(RunOrder.event_id == event_id)
        .order_by(RunOrder.slot_index)
        .all()
    )

    items: list[dict[str, Any]] = []
    for run_order in rows:
        item = resolve_run_order_item(event_id, run_order, db, phase_long_label)
        if item and item["status"] == MatchupStatus.pending:
            items.append(item)
    return items


def robot_main_history(
    robot_id: int,
    event_id: int,
    db: Session,
    phase_long_label: Callable[[Phase, Matchup], str],
) -> list[dict[str, Any]]:
    """Return completed 1v1 history entries for a robot in an event."""
    matchups = (
        db.query(Matchup)
        .join(Phase, Phase.id == Matchup.phase_id)
        .filter(
            Phase.event_id == event_id,
            Matchup.status == MatchupStatus.completed,
            or_(Matchup.robot1_id == robot_id, Matchup.robot2_id == robot_id),
        )
        .order_by(
            Phase.phase_type.desc(),
            Matchup.bracket_round.desc(),
            Phase.phase_number.desc(),
            Matchup.display_order.desc(),
        )
        .all()
    )

    history: list[dict[str, Any]] = []
    for matchup in matchups:
        phase = matchup.phase
        if matchup.robot2_id is None:
            history.append(
                {
                    "kind": "main",
                    "title": "Bye",
                    "meta": phase_long_label(phase, matchup),
                    "detail": f"Automatic advance for {BYE_POINTS} points.",
                    "score": f"{BYE_POINTS}-0",
                    "outcome": "Win",
                }
            )
            continue

        opponent = matchup.robot2 if matchup.robot1_id == robot_id else matchup.robot1
        my_result = next((result for result in matchup.results if result.robot_id == robot_id), None)
        opp_result = next((result for result in matchup.results if opponent and result.robot_id == opponent.id), None)
        my_pts = my_result.points_scored if my_result else 0
        opp_pts = opp_result.points_scored if opp_result else 0

        if my_pts > opp_pts:
            outcome = "Win"
        elif my_pts < opp_pts:
            outcome = "Loss"
        else:
            outcome = "Draw"

        history.append(
            {
                "kind": "main",
                "title": opponent.robot_name if opponent else "Unknown opponent",
                "href": f"/events/{event_id}/robot/{opponent.id}" if opponent else None,
                "meta": phase_long_label(phase, matchup),
                "detail": points_to_outcome_label(my_pts, opp_pts),
                "score": f"{my_pts}-{opp_pts}",
                "outcome": outcome,
            }
        )

    return history


def robot_sub_event_history(robot_id: int, event_id: int, db: Session) -> list[dict[str, Any]]:
    """Return completed sub-event history entries for a robot in an event."""
    sub_matchups = (
        db.query(SubEventMatchup)
        .join(SubEvent, SubEvent.id == SubEventMatchup.sub_event_id)
        .filter(
            SubEvent.event_id == event_id,
            SubEventMatchup.status == MatchupStatus.completed,
        )
        .order_by(SubEventMatchup.round_number.desc(), SubEventMatchup.display_order.desc())
        .all()
    )

    history: list[dict[str, Any]] = []
    for matchup in sub_matchups:
        teams = [matchup.team1, matchup.team2]
        my_team = next(
            (
                team for team in teams if team and robot_id in {team.robot1_id, team.robot2_id}
            ),
            None,
        )
        if not my_team:
            continue

        opponent = matchup.team2 if matchup.team1_id == my_team.id else matchup.team1
        won = matchup.winner_team_id == my_team.id
        history.append(
            {
                "kind": "sub_event",
                "title": my_team.team_name,
                "href": f"/events/{event_id}/sub-events/{matchup.sub_event_id}",
                "meta": f"{matchup.sub_event.name} · Round {matchup.round_number}",
                "detail": (
                    f"Defeated {opponent.team_name}" if won and opponent else
                    f"Lost to {opponent.team_name}" if opponent else
                    "Advance by bye"
                ),
                "score": "Team win" if won else "Team loss",
                "outcome": "Win" if won else "Loss",
            }
        )

    return history


def robot_stats(
    robot_id: int,
    event_id: int,
    db: Session,
) -> dict[str, Any]:
    """Aggregate robot performance stats across main event and sub-events."""
    main_matchups = (
        db.query(Matchup)
        .join(Phase, Phase.id == Matchup.phase_id)
        .filter(
            Phase.event_id == event_id,
            Matchup.status == MatchupStatus.completed,
            or_(Matchup.robot1_id == robot_id, Matchup.robot2_id == robot_id),
        )
        .all()
    )

    stats: dict[str, Any] = {
        "fights": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "points": 0,
        "byes": 0,
        "qualifying_points": 0,
        "bracket_points": 0,
        "head_to_head": {},
        "sub_event_wins": 0,
        "sub_event_losses": 0,
    }

    for matchup in main_matchups:
        phase = matchup.phase
        stats["fights"] += 1
        if matchup.robot2_id is None:
            stats["wins"] += 1
            stats["byes"] += 1
            stats["points"] += BYE_POINTS
            if phase.phase_type == PhaseType.qualifying:
                stats["qualifying_points"] += BYE_POINTS
            else:
                stats["bracket_points"] += BYE_POINTS
            continue

        opponent = matchup.robot2 if matchup.robot1_id == robot_id else matchup.robot1
        my_result = next((result for result in matchup.results if result.robot_id == robot_id), None)
        opp_result = next((result for result in matchup.results if opponent and result.robot_id == opponent.id), None)
        my_pts = my_result.points_scored if my_result else 0
        opp_pts = opp_result.points_scored if opp_result else 0

        stats["points"] += my_pts
        if phase.phase_type == PhaseType.qualifying:
            stats["qualifying_points"] += my_pts
        else:
            stats["bracket_points"] += my_pts

        head_to_head = stats["head_to_head"].setdefault(
            opponent.id,
            {
                "opponent": opponent,
                "fights": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "points_for": 0,
                "points_against": 0,
            },
        )
        head_to_head["fights"] += 1
        head_to_head["points_for"] += my_pts
        head_to_head["points_against"] += opp_pts

        if my_pts > opp_pts:
            stats["wins"] += 1
            head_to_head["wins"] += 1
        elif my_pts < opp_pts:
            stats["losses"] += 1
            head_to_head["losses"] += 1
        else:
            stats["draws"] += 1
            head_to_head["draws"] += 1

    for item in robot_sub_event_history(robot_id, event_id, db):
        if item["outcome"] == "Win":
            stats["sub_event_wins"] += 1
        else:
            stats["sub_event_losses"] += 1

    stats["head_to_head_rows"] = sorted(
        stats["head_to_head"].values(),
        key=lambda row: (-row["wins"], row["losses"], row["opponent"].robot_name.lower()),
    )
    return stats