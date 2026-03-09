"""Public-facing routes — no authentication required. Mobile-friendly.

Phase 3 — steps 13–18:
  13. Public event view (shareable link)
  14. Robot lookup / search
  15. My Robot's Fights   (per-robot schedule + results)
  16. Leaderboard         (qualifying standings)
  17. Bracket view        (single-elimination progress)
  18. QR code page        (for venue screens / easy mobile access)
"""

import io
from collections import defaultdict
from typing import Optional

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from config import APP_BASE_URL
from database import get_db
from models import (
    Event,
    EventRobot,
    EventStatus,
    Matchup,
    MatchupStatus,
    Phase,
    PhaseType,
    Result,
    Robot,
    RunOrder,
    RunOrderMatchupType,
    Roboteer,
    SubEvent,
    SubEventMatchup,
    SubEventTeam,
)
from public_data import (
    leaderboard_rows as _leaderboard_rows,
    pending_run_order_items as _load_pending_run_order_items,
    robot_has_event_history as _robot_has_event_history,
    robot_main_history as _load_robot_main_history,
    robot_points_in_event as _robot_points_in_event,
    robot_stats as _robot_stats,
    robot_sub_event_history as _robot_sub_event_history,
)
from robot_images import robot_display_image_url, robot_has_uploaded_image
from scoring import BYE_POINTS
from ui import HTMX_SCRIPT_URL, render_template

router = APIRouter(prefix="/events")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event_nav_links(ev: Event, active: str = "", db: Optional[Session] = None) -> list[dict[str, str | bool]]:
    """Build navigation metadata shown on public event pages."""
    links = [
        ("Overview", f"/events/{ev.id}", "overview"),
        ("Leaderboard", f"/events/{ev.id}/leaderboard", "leaderboard"),
        ("Bracket", f"/events/{ev.id}/bracket", "bracket"),
        ("Live", f"/events/{ev.id}/live", "live"),
        ("Next Up", f"/events/{ev.id}/next-up", "next_up"),
        ("My Robot", f"/events/{ev.id}/lookup", "lookup"),
        ("QR Code", f"/events/{ev.id}/qr", "qr"),
    ]
    # Add Sub-events link if any exist
    if db is not None:
        se_count = db.query(SubEvent).filter(SubEvent.event_id == ev.id).count()
        if se_count:
            links.insert(3, ("Sub-events", f"/events/{ev.id}/sub-events", "sub_events"))

    return [
        {
            "label": label,
            "href": href,
            "active": key == active,
        }
        for label, href, key in links
    ]
def _get_public_event(event_id: int, db: Session) -> Optional[Event]:
    return db.query(Event).filter(Event.id == event_id).first()


def _not_found(request: Request) -> HTMLResponse:
    return render_template(
        request,
        "public/not_found.html",
        title="Not Found",
        context={},
        stylesheets=("css/public.css",),
        body_class="public-page",
        status_code=404,
    )


def _event_is_live(ev: Event) -> bool:
    return ev.status in {
        EventStatus.qualifying,
        EventStatus.bracket,
        EventStatus.sub_events,
    }


def _auto_refresh_attrs(path: str, interval: str = "20s") -> dict[str, str]:
    return {
        "hx_get": path,
        # Avoid a request loop: swapped panels re-enter the DOM, so `load`
        # would fire again immediately after every outerHTML refresh.
        "hx_trigger": f"every {interval}",
        "hx_swap": "outerHTML",
        "cls": "auto-panel",
    }


def _phase_short_label(phase: Phase, matchup: Matchup) -> str:
    if phase.phase_type == PhaseType.qualifying:
        return f"Q{phase.phase_number}"
    return _public_bracket_round_label(matchup.bracket_round or 1, 4)


def _phase_long_label(phase: Phase, matchup: Matchup) -> str:
    if phase.phase_type == PhaseType.qualifying:
        return f"Qualifying Round {phase.phase_number}"
    return _public_bracket_round_label(matchup.bracket_round or 1, 4)


def _pending_run_order_items(event_id: int, db: Session) -> list[dict]:
    return _load_pending_run_order_items(event_id, db, _phase_long_label)
def _robot_main_history(robot_id: int, event_id: int, db: Session) -> list[dict]:
    return _load_robot_main_history(robot_id, event_id, db, _phase_long_label)


def _overview_panel_context(ev: Event, db: Session) -> dict:
    phases = db.query(Phase).filter(Phase.event_id == ev.id).order_by(Phase.phase_number).all()
    active_count = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == ev.id, EventRobot.is_reserve == False)
        .count()
    )
    reserve_count = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == ev.id, EventRobot.is_reserve == True)
        .count()
    )
    pending_items = _pending_run_order_items(ev.id, db)

    phase_rows = []
    for ph in phases:
        completed = sum(1 for m in ph.matchups if m.status == MatchupStatus.completed)
        total = len(ph.matchups)
        label = f"Qualifying Round {ph.phase_number}" if ph.phase_type == PhaseType.qualifying else "Main Bracket"
        phase_rows.append(
            {
                "label": label,
                "completed": completed,
                "total": total,
                "status": ph.status.value,
            }
        )

    overview_panel = {
        "id": "overview-panel",
        "class_name": "auto-panel",
        "hx_get": "",
        "hx_trigger": "",
        "hx_swap": "",
    }
    if _event_is_live(ev):
        auto_refresh = _auto_refresh_attrs(f"/events/{ev.id}/overview-panel")
        overview_panel.update(
            {
                "class_name": auto_refresh["cls"],
                "hx_get": auto_refresh["hx_get"],
                "hx_trigger": auto_refresh["hx_trigger"],
                "hx_swap": auto_refresh["hx_swap"],
            }
        )

    return {
        "overview_stats": {
            "active_count": active_count,
            "reserve_count": reserve_count,
            "pending_count": len(pending_items),
        },
        "next_up_items": [
            {
                "slot_number": item["slot_index"] + 1,
                "title": item["title"],
                "type_label": item["type_label"],
                "meta": item["meta"],
            }
            for item in pending_items[:3]
        ],
        "phases": phase_rows,
        "overview_panel": overview_panel,
    }


def _lookup_results_context(event_id: int, q: str, db: Session) -> dict:
    if not q:
        return {
            "searched": False,
            "summary": "",
            "empty_message": "",
            "rows": [],
        }

    q_stripped = q.strip()
    matched_ers = (
        db.query(EventRobot)
        .join(Robot, Robot.id == EventRobot.robot_id)
        .join(Roboteer, Roboteer.id == Robot.roboteer_id)
        .filter(
            EventRobot.event_id == event_id,
            or_(
                Robot.robot_name.ilike(f"%{q_stripped}%"),
                Roboteer.roboteer_name.ilike(f"%{q_stripped}%"),
            ),
        )
        .all()
    )

    return {
        "searched": True,
        "summary": f'{len(matched_ers)} result(s) for “{q_stripped}”',
        "empty_message": f'No robots found matching “{q_stripped}”.',
        "rows": [
            {
                "robot_name": er.robot.robot_name,
                "href": f"/events/{event_id}/robot/{er.robot.id}",
                "roboteer_name": er.robot.roboteer.roboteer_name,
                "weapon_type": er.robot.weapon_type,
                "image_url": robot_display_image_url(er.robot),
            }
            for er in matched_ers
        ],
    }


def _leaderboard_panel_context(ev: Event, db: Session) -> dict:
    rows = _leaderboard_rows(ev.id, db)
    leaderboard_rows = []
    if rows and not all(row["fights"] == 0 for row in rows):
        leaderboard_rows = [
            {
                "rank": index,
                "rank_class": f"rank-{index}" if index <= 3 else "",
                "robot_name": row["robot"].robot_name,
                "href": f"/events/{ev.id}/robot/{row['robot'].id}",
                "roboteer_name": row["roboteer"].roboteer_name,
                "image_url": robot_display_image_url(row["robot"]),
                "total_pts": row["total_pts"],
                "wins": row["wins"],
                "fights": row["fights"],
            }
            for index, row in enumerate(rows, start=1)
        ]

    leaderboard_panel = {
        "id": "leaderboard-panel",
        "class_name": "auto-panel",
        "hx_get": "",
        "hx_trigger": "",
        "hx_swap": "",
    }
    if _event_is_live(ev):
        auto_refresh = _auto_refresh_attrs(f"/events/{ev.id}/leaderboard/panel")
        leaderboard_panel.update(
            {
                "class_name": auto_refresh["cls"],
                "hx_get": auto_refresh["hx_get"],
                "hx_trigger": auto_refresh["hx_trigger"],
                "hx_swap": auto_refresh["hx_swap"],
            }
        )

    return {
        "leaderboard_rows": leaderboard_rows,
        "leaderboard_panel": leaderboard_panel,
    }


def _bracket_panel_context(ev: Event, db: Session) -> dict:
    bracket_phase = (
        db.query(Phase)
        .filter(Phase.event_id == ev.id, Phase.phase_type == PhaseType.bracket)
        .first()
    )

    bracket = {"empty_message": "", "rounds": []}
    if not bracket_phase:
        bracket["empty_message"] = (
            "The bracket hasn't been drawn yet. It will appear here once qualifying rounds are complete."
        )
    else:
        matchups = (
            db.query(Matchup)
            .filter(Matchup.phase_id == bracket_phase.id)
            .order_by(Matchup.bracket_round, Matchup.display_order)
            .all()
        )
        if not matchups:
            bracket["empty_message"] = "No bracket matchups yet."
        else:
            rounds: dict[int, list[Matchup]] = {}
            for matchup in matchups:
                rounds.setdefault(matchup.bracket_round or 1, []).append(matchup)
            total_rounds = _total_bracket_rounds(rounds)
            for round_number in sorted(rounds.keys()):
                round_matchups = []
                for matchup in rounds[round_number]:
                    r1 = matchup.robot1
                    r2 = matchup.robot2
                    r1_pts = r2_pts = None
                    r1_win = r2_win = False
                    if matchup.status == MatchupStatus.completed:
                        for res in matchup.results:
                            if r1 and res.robot_id == r1.id:
                                r1_pts = res.points_scored
                            elif r2 and res.robot_id == r2.id:
                                r2_pts = res.points_scored
                        if r1_pts is not None and r2_pts is not None:
                            r1_win = r1_pts >= r2_pts
                            r2_win = r2_pts > r1_pts
                        elif r1_pts is not None:
                            r1_win = True
                    round_matchups.append(
                        {
                            "status": matchup.status.value,
                            "robots": [
                                {
                                    "name": r1.robot_name if r1 else "TBD",
                                    "href": f"/events/{ev.id}/robot/{r1.id}" if r1 else "",
                                    "points": str(r1_pts) if r1_pts is not None else "—",
                                    "is_winner": r1_win,
                                },
                                {
                                    "name": r2.robot_name if r2 else "TBD",
                                    "href": f"/events/{ev.id}/robot/{r2.id}" if r2 else "",
                                    "points": str(r2_pts) if r2_pts is not None else "—",
                                    "is_winner": r2_win,
                                },
                            ],
                        }
                    )
                bracket["rounds"].append(
                    {
                        "label": _public_bracket_round_label(round_number, total_rounds),
                        "matchups": round_matchups,
                    }
                )

    bracket_panel = {"id": "bracket-panel", "class_name": "auto-panel", "hx_get": "", "hx_trigger": "", "hx_swap": ""}
    if _event_is_live(ev):
        auto_refresh = _auto_refresh_attrs(f"/events/{ev.id}/bracket/panel")
        bracket_panel.update(
            {
                "class_name": auto_refresh["cls"],
                "hx_get": auto_refresh["hx_get"],
                "hx_trigger": auto_refresh["hx_trigger"],
                "hx_swap": auto_refresh["hx_swap"],
            }
        )

    return {"bracket": bracket, "bracket_panel": bracket_panel}


def _robot_panel_context(ev: Event, robot: Robot, db: Session) -> dict:
    matchups = (
        db.query(Matchup)
        .join(Phase, Phase.id == Matchup.phase_id)
        .filter(
            Phase.event_id == ev.id,
            or_(Matchup.robot1_id == robot.id, Matchup.robot2_id == robot.id),
        )
        .order_by(Phase.phase_number, Matchup.bracket_round, Matchup.display_order)
        .all()
    )

    total_points = _robot_points_in_event(robot.id, ev.id, db)
    completed_fights = sum(1 for m in matchups if m.status == MatchupStatus.completed)
    fight_rows = []
    for matchup in matchups:
        phase = matchup.phase
        phase_label = f"Q{phase.phase_number}" if phase.phase_type == PhaseType.qualifying else "Bracket"
        phase_full = _phase_long_label(phase, matchup)
        if matchup.robot2_id is None:
            opponent_name = "BYE"
            opponent_href = ""
            result_label, points, row_class = f"BYE ({BYE_POINTS} pts)", str(BYE_POINTS), "fight-row-win"
        else:
            opponent = matchup.robot2 if matchup.robot1_id == robot.id else matchup.robot1
            opponent_name = opponent.robot_name
            opponent_href = f"/events/{ev.id}/robot/{opponent.id}"
            if matchup.status == MatchupStatus.completed:
                my_result = next((r for r in matchup.results if r.robot_id == robot.id), None)
                opp_result = next((r for r in matchup.results if r.robot_id != robot.id), None)
                my_pts = my_result.points_scored if my_result else 0
                opp_pts = opp_result.points_scored if opp_result else 0
                points = str(my_pts)
                if my_pts > opp_pts:
                    result_label, row_class = "Win", "fight-row-win"
                elif my_pts < opp_pts:
                    result_label, row_class = "Loss", "fight-row-loss"
                else:
                    result_label, row_class = "Draw", "fight-row-draw"
            else:
                result_label, points, row_class = "Upcoming", "-", "fight-row-pending"
        if result_label in ("Win", f"BYE ({BYE_POINTS} pts)"):
            points_style = "color:#4ade80;font-weight:600;"
        elif result_label == "Loss":
            points_style = "color:#f87171;"
        else:
            points_style = "color:#888;"
        fight_rows.append(
            {
                "phase_label": phase_label,
                "phase_full": phase_full,
                "phase_badge": phase.status.value,
                "opponent_name": opponent_name,
                "opponent_href": opponent_href,
                "points": points,
                "points_style": points_style,
                "result_label": result_label,
                "row_class": row_class,
            }
        )

    display_image_url = robot_display_image_url(robot)
    has_upload_image = robot_has_uploaded_image(robot)
    robot_panel = {"id": f"robot-panel-{robot.id}", "class_name": "auto-panel", "hx_get": "", "hx_trigger": "", "hx_swap": ""}
    if _event_is_live(ev):
        auto_refresh = _auto_refresh_attrs(f"/events/{ev.id}/robot/{robot.id}/panel")
        robot_panel.update(
            {
                "class_name": auto_refresh["cls"],
                "hx_get": auto_refresh["hx_get"],
                "hx_trigger": auto_refresh["hx_trigger"],
                "hx_swap": auto_refresh["hx_swap"],
            }
        )
    return {
        "robot": robot,
        "roboteer_name": robot.roboteer.roboteer_name,
        "weapon_type": robot.weapon_type,
        "completed_fights": completed_fights,
        "total_points": total_points,
        "fight_rows": fight_rows,
        "display_image_url": display_image_url,
        "has_upload_image": has_upload_image,
        "back_href": f"/events/{ev.id}/lookup",
        "history_href": f"/events/{ev.id}/robot/{robot.id}/history",
        "stats_href": f"/events/{ev.id}/robot/{robot.id}/stats",
        "robot_panel": robot_panel,
    }


def _robot_history_panel_context(ev: Event, robot: Robot, db: Session) -> dict:
    items = _robot_main_history(robot.id, ev.id, db) + _robot_sub_event_history(robot.id, ev.id, db)
    history_items = []
    for item in items:
        outcome_color = "#4ade80" if item["outcome"] == "Win" else "#f87171" if item["outcome"] == "Loss" else "#fbbf24"
        history_items.append(
            {
                "meta": item["meta"],
                "kind_label": item["kind"].replace("_", " "),
                "title": item["title"],
                "href": item.get("href", ""),
                "score": item["score"],
                "detail": item["detail"],
                "outcome": item["outcome"],
                "outcome_color": outcome_color,
            }
        )
    history_panel = {"id": f"robot-history-panel-{robot.id}", "class_name": "auto-panel", "hx_get": "", "hx_trigger": "", "hx_swap": ""}
    if _event_is_live(ev):
        auto_refresh = _auto_refresh_attrs(f"/events/{ev.id}/robot/{robot.id}/history/panel")
        history_panel.update(
            {
                "class_name": auto_refresh["cls"],
                "hx_get": auto_refresh["hx_get"],
                "hx_trigger": auto_refresh["hx_trigger"],
                "hx_swap": auto_refresh["hx_swap"],
            }
        )
    return {
        "robot_name": robot.robot_name,
        "roboteer_name": robot.roboteer.roboteer_name,
        "history_items": history_items,
        "back_href": f"/events/{ev.id}/robot/{robot.id}",
        "history_panel": history_panel,
    }


def _robot_stats_panel_context(ev: Event, robot: Robot, db: Session) -> dict:
    stats = _robot_stats(robot.id, ev.id, db)
    stat_tiles = [
        {"label": "Main fights", "value": stats["fights"], "meta": f"{stats['wins']}W {stats['losses']}L {stats['draws']}D"},
        {"label": "Total points", "value": stats["points"], "meta": f"{stats['qualifying_points']} qualifying"},
        {"label": "Bracket points", "value": stats["bracket_points"], "meta": f"{stats['byes']} byes"},
        {"label": "Sub-event record", "value": f"{stats['sub_event_wins']}-{stats['sub_event_losses']}", "meta": "team results"},
    ]
    h2h_rows = [
        {
            "opponent_name": row["opponent"].robot_name,
            "href": f"/events/{ev.id}/robot/{row['opponent'].id}",
            "record": f"{row['wins']}-{row['losses']}-{row['draws']}",
            "points": f"{row['points_for']}-{row['points_against']}",
            "fights": row["fights"],
        }
        for row in stats["head_to_head_rows"]
    ]
    stats_panel = {"id": f"robot-stats-panel-{robot.id}", "class_name": "auto-panel", "hx_get": "", "hx_trigger": "", "hx_swap": ""}
    if _event_is_live(ev):
        auto_refresh = _auto_refresh_attrs(f"/events/{ev.id}/robot/{robot.id}/stats/panel")
        stats_panel.update(
            {
                "class_name": auto_refresh["cls"],
                "hx_get": auto_refresh["hx_get"],
                "hx_trigger": auto_refresh["hx_trigger"],
                "hx_swap": auto_refresh["hx_swap"],
            }
        )
    return {
        "robot_name": robot.robot_name,
        "roboteer_name": robot.roboteer.roboteer_name,
        "event_name": ev.event_name,
        "stat_tiles": stat_tiles,
        "h2h_rows": h2h_rows,
        "back_href": f"/events/{ev.id}/robot/{robot.id}",
        "stats_panel": stats_panel,
    }


def _live_panel_context(ev: Event, db: Session) -> dict:
    pending_items = _pending_run_order_items(ev.id, db)
    current_item = pending_items[0] if pending_items else None
    leaderboard_rows = _leaderboard_rows(ev.id, db)[:8]

    def _live_card(robot: Robot | None, href: str | None, name: str, badge: str, fallback_meta: str) -> dict:
        meta_parts = []
        if robot and robot.roboteer:
            meta_parts.append(robot.roboteer.roboteer_name)
        if robot and robot.weapon_type:
            meta_parts.append(robot.weapon_type)
        meta_text = " · ".join(meta_parts) if meta_parts else fallback_meta
        display_url = robot_display_image_url(robot)
        return {
            "kind": "robot",
            "href": href or "",
            "image_url": display_url or "",
            "placeholder_initial": (name[:1] if name else "?").upper(),
            "name": name,
            "badge": badge,
            "meta": meta_text,
        }

    left_name = "TBD"
    right_name = "BYE"
    if current_item:
        if current_item.get("robot1_name"):
            left_name = current_item["robot1_name"]
            right_name = current_item.get("robot2_name") or "BYE"
        elif " vs " in current_item["title"]:
            left_name, right_name = current_item["title"].split(" vs ", 1)
        else:
            left_name = current_item["title"]

    live_matchup = [
        _live_card(
            current_item.get("robot1") if current_item else None,
            current_item.get("robot1_href") if current_item else None,
            left_name,
            "Red Corner",
            current_item["meta"] if current_item else "Awaiting next matchup",
        ),
        {"kind": "vs"},
        _live_card(
            current_item.get("robot2") if current_item else None,
            current_item.get("robot2_href") if current_item else None,
            right_name,
            "Blue Corner" if current_item and current_item.get("robot2_name") else "Automatic Advance",
            current_item["type_label"] if current_item else "No pending fights",
        ),
    ]

    queue_items = [
        {
            "slot_number": item["slot_index"] + 1,
            "title": item["title"],
            "type_label": item["type_label"],
            "meta": item["meta"],
            "current": index == 0,
        }
        for index, item in enumerate(pending_items[:5])
    ]
    leaderboard_items = []
    if leaderboard_rows and any(row["fights"] > 0 for row in leaderboard_rows):
        leaderboard_items = [
            {
                "rank": index,
                "robot_name": row["robot"].robot_name,
                "roboteer_name": row["roboteer"].roboteer_name,
                "total_pts": row["total_pts"],
            }
            for index, row in enumerate(leaderboard_rows, start=1)
        ]
    live_panel = _auto_refresh_attrs(f"/events/{ev.id}/live/panel", interval="15s")
    return {
        "current_stage": {
            "title": current_item["title"] if current_item else "Awaiting next fight",
            "subtitle": (
                f"{current_item['type_label']} · {current_item['meta']}"
                if current_item
                else "No pending fights are currently scheduled."
            ),
        },
        "live_matchup": live_matchup,
        "queue_items": queue_items,
        "leaderboard_rows": leaderboard_items,
        "live_panel": {
            "id": "live-panel",
            "class_name": "live-panel-shell auto-panel",
            "hx_get": live_panel["hx_get"],
            "hx_trigger": live_panel["hx_trigger"],
            "hx_swap": live_panel["hx_swap"],
        },
    }


def _next_up_panel_context(ev: Event, db: Session) -> dict:
    pending_items = _pending_run_order_items(ev.id, db)
    return {
        "queue_items": [
            {
                "slot_number": item["slot_index"] + 1,
                "title": item["title"],
                "type_label": item["type_label"],
                "meta": item["meta"],
                "current": index == 0,
                "href": item.get("href", ""),
                "robot1_href": item.get("robot1_href", ""),
                "robot2_href": item.get("robot2_href", ""),
                "robot1_name": item.get("robot1_name", ""),
                "robot2_name": item.get("robot2_name", ""),
            }
            for index, item in enumerate(pending_items[:10])
        ],
        "next_up_panel": {
            "id": "next-up-panel",
            "class_name": "auto-panel",
            **_auto_refresh_attrs(f"/events/{ev.id}/next-up/panel"),
        },
    }


def _sub_events_list_context(ev: Event, event_id: int, db: Session) -> dict:
    sub_events = (
        db.query(SubEvent)
        .filter(SubEvent.event_id == event_id)
        .order_by(SubEvent.id)
        .all()
    )
    return {
        "sub_events": [
            {
                "name": se.name,
                "href": f"/events/{event_id}/sub-events/{se.id}",
                "format": se.format.value,
                "team_count": db.query(SubEventTeam).filter(SubEventTeam.sub_event_id == se.id).count(),
                "status": se.status.value,
            }
            for se in sub_events
        ]
    }


def _sub_event_detail_context(ev: Event, se: SubEvent, event_id: int, sub_event_id: int, db: Session) -> dict:
    teams = (
        db.query(SubEventTeam)
        .filter(SubEventTeam.sub_event_id == sub_event_id)
        .order_by(SubEventTeam.id)
        .all()
    )
    all_matchups = (
        db.query(SubEventMatchup)
        .filter(SubEventMatchup.sub_event_id == sub_event_id)
        .order_by(SubEventMatchup.round_number, SubEventMatchup.display_order)
        .all()
    )
    team_rows = [
        {
            "team_name": team.team_name,
            "robot1": {
                "name": team.robot1.robot_name,
                "href": f"/events/{event_id}/robot/{team.robot1_id}",
                "image_url": robot_display_image_url(team.robot1),
            },
            "robot2": {
                "name": team.robot2.robot_name,
                "href": f"/events/{event_id}/robot/{team.robot2_id}",
                "image_url": robot_display_image_url(team.robot2),
            },
        }
        for team in teams
    ]
    rounds_output = []
    if all_matchups:
        rounds: dict[int, list[SubEventMatchup]] = {}
        for matchup in all_matchups:
            rounds.setdefault(matchup.round_number, []).append(matchup)
        max_rnd = max(rounds.keys())

        def _se_round_label_pub(rnd: int) -> str:
            terminal = ["Final", "Semi-finals", "Quarter-finals", "Round of 16", "Round of 32"]
            offset = 4 - max_rnd
            idx = rnd + offset - 1
            if 0 <= idx < len(terminal):
                return terminal[idx]
            return f"Round {rnd}"

        for rnd in sorted(rounds.keys()):
            round_matchups = []
            for matchup in rounds[rnd]:
                t1 = matchup.team1
                t2 = matchup.team2
                round_matchups.append(
                    {
                        "status": matchup.status.value,
                        "is_bye": t2 is None,
                        "teams": [
                            {
                                "name": t1.team_name if t1 else "TBD",
                                "robots": f"{t1.robot1.robot_name} & {t1.robot2.robot_name}" if t1 else "",
                                "is_winner": matchup.winner_team_id is not None and t1 is not None and matchup.winner_team_id == t1.id,
                            },
                            {
                                "name": t2.team_name if t2 else "TBD",
                                "robots": f"{t2.robot1.robot_name} & {t2.robot2.robot_name}" if t2 else "",
                                "is_winner": matchup.winner_team_id is not None and t2 is not None and matchup.winner_team_id == t2.id,
                            },
                        ],
                    }
                )
            rounds_output.append({"label": _se_round_label_pub(rnd), "matchups": round_matchups})
    return {
        "sub_event": {"name": se.name, "format": se.format.value, "status": se.status.value},
        "teams": team_rows,
        "bracket": {"rounds": rounds_output},
    }
# ---------------------------------------------------------------------------
# 13. Public event overview
# ---------------------------------------------------------------------------


@router.get("/{event_id}", response_class=HTMLResponse)
def event_overview(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)
    return render_template(
        request,
        "public/events/overview.html",
        title=ev.event_name,
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="overview", db=db),
            **_overview_panel_context(ev, db),
        },
        stylesheets=("css/public.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="public-page",
    )


@router.get("/{event_id}/overview-panel", response_class=HTMLResponse)
def event_overview_panel(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)
    return render_template(
        request,
        "public/partials/overview_panel.html",
        title=ev.event_name,
        context={
            "event": ev,
            **_overview_panel_context(ev, db),
        },
    )

# ---------------------------------------------------------------------------
# 14. Robot lookup (search)
# ---------------------------------------------------------------------------


@router.get("/{event_id}/lookup", response_class=HTMLResponse)
def robot_lookup(
    request: Request,
    event_id: int,
    db: Session = Depends(get_db),
    q: str = Query(default=""),
):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)

    return render_template(
        request,
        "public/events/lookup.html",
        title=f"Robot Lookup — {ev.event_name}",
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="lookup", db=db),
            "query": q,
            "results": _lookup_results_context(event_id, q, db),
        },
        stylesheets=("css/public.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="public-page",
    )


# ---------------------------------------------------------------------------
# 15. My Robot's Fights
# ---------------------------------------------------------------------------


@router.get("/{event_id}/robot/{robot_id}", response_class=HTMLResponse)
def robot_fights(
    request: Request,
    event_id: int,
    robot_id: int,
    db: Session = Depends(get_db),
):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)

    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not robot:
        return _not_found(request)

    if not _robot_has_event_history(robot_id, event_id, db):
        return _not_found(request)
    return render_template(
        request,
        "public/events/robot_detail.html",
        title=f"{robot.robot_name} — {ev.event_name}",
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="lookup", db=db),
            "content_class": "content robot-page-shell",
            **_robot_panel_context(ev, robot, db),
        },
        stylesheets=("css/public.css",),
        script_srcs=(HTMX_SCRIPT_URL, "/static/js/robot-lightbox.js"),
        body_class="public-page",
    )


@router.get("/{event_id}/robot/{robot_id}/panel", response_class=HTMLResponse)
def robot_fights_panel(request: Request, event_id: int, robot_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not ev or not robot or not _robot_has_event_history(robot_id, event_id, db):
        return _not_found(request)
    return render_template(
        request,
        "public/partials/robot_panel.html",
        title=f"{robot.robot_name} — {ev.event_name}",
        context=_robot_panel_context(ev, robot, db),
    )


# ---------------------------------------------------------------------------
# 16. Leaderboard
# ---------------------------------------------------------------------------


@router.get("/{event_id}/leaderboard", response_class=HTMLResponse)
def leaderboard(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)
    return render_template(
        request,
        "public/events/leaderboard.html",
        title=f"Leaderboard — {ev.event_name}",
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="leaderboard", db=db),
            **_leaderboard_panel_context(ev, db),
            "error_message": "",
            "success_message": "",
            "info_message": "",
        },
        stylesheets=("css/public.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="public-page",
    )


@router.get("/{event_id}/leaderboard/panel", response_class=HTMLResponse)
def leaderboard_panel(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)
    return render_template(
        request,
        "public/partials/leaderboard_panel.html",
        title=f"Leaderboard — {ev.event_name}",
        context={
            "event": ev,
            **_leaderboard_panel_context(ev, db),
        },
    )


# ---------------------------------------------------------------------------
# 17. Bracket view
# ---------------------------------------------------------------------------


@router.get("/{event_id}/bracket", response_class=HTMLResponse)
def bracket_view(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)
    return render_template(
        request,
        "public/events/bracket.html",
        title=f"Bracket — {ev.event_name}",
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="bracket", db=db),
            **_bracket_panel_context(ev, db),
        },
        stylesheets=("css/public.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="public-page",
    )


@router.get("/{event_id}/bracket/panel", response_class=HTMLResponse)
def bracket_panel(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)
    return render_template(
        request,
        "public/partials/bracket_panel.html",
        title=f"Bracket — {ev.event_name}",
        context={"event": ev, **_bracket_panel_context(ev, db)},
    )


def _total_bracket_rounds(rounds: dict[int, list[Matchup]]) -> int:
    """Infer the intended bracket depth from the largest round size."""
    if not rounds:
        return 1

    round_one_size = max(len(matchups) for matchups in rounds.values())
    total_rounds = 1
    while round_one_size > 1:
        round_one_size //= 2
        total_rounds += 1
    return total_rounds


def _public_bracket_round_label(round_number: int, total_rounds: int) -> str:
    """Label bracket rounds consistently even before later rounds are generated."""
    labels = {
        1: "Round of 16",
        2: "Quarter-finals",
        3: "Semi-finals",
        4: "Final",
    }
    offset = max(0, 4 - total_rounds)
    return labels.get(round_number + offset, f"Round {round_number}")
# ---------------------------------------------------------------------------
# 18. QR code page
# ---------------------------------------------------------------------------


@router.get("/{event_id}/qr", response_class=HTMLResponse)
def qr_page(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)

    event_url = f"{APP_BASE_URL}/events/{event_id}"
    qr_image_url = f"/events/{event_id}/qr.svg"

    return render_template(
        request,
        "public/events/qr.html",
        title=f"QR Code — {ev.event_name}",
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="qr", db=db),
            "event_url": event_url,
            "qr_image_url": qr_image_url,
        },
        stylesheets=("css/public.css",),
        body_class="public-page",
    )


@router.get("/{event_id}/qr.svg")
def qr_svg(event_id: int, db: Session = Depends(get_db)) -> Response:
    """Return the QR code SVG directly (useful for embedding or downloading)."""
    ev = _get_public_event(event_id, db)
    if not ev:
        return Response(status_code=404)
    event_url = f"{APP_BASE_URL}/events/{event_id}"
    return Response(content=_make_qr_svg(event_url), media_type="image/svg+xml")


def _make_qr_svg(url: str) -> str:
    """Generate a QR code as an inline SVG string."""
    factory = qrcode.image.svg.SvgFillImage
    img = qrcode.make(url, image_factory=factory, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


# ---------------------------------------------------------------------------
# Phase 6 — Enhanced public views
# ---------------------------------------------------------------------------


@router.get("/{event_id}/live", response_class=HTMLResponse)
def live_display(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)
    return render_template(
        request,
        "public/events/live.html",
        title=f"Live Display — {ev.event_name}",
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="live", db=db),
            "content_class": "content live-page-shell",
            **_live_panel_context(ev, db),
        },
        stylesheets=("css/public.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="public-page",
    )


@router.get("/{event_id}/live/panel", response_class=HTMLResponse)
def live_display_panel(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)
    return render_template(
        request,
        "public/partials/live_panel.html",
        title=f"Live Display — {ev.event_name}",
        context={"event": ev, **_live_panel_context(ev, db)},
    )


@router.get("/{event_id}/next-up", response_class=HTMLResponse)
def next_up_board(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)
    return render_template(
        request,
        "public/events/next_up.html",
        title=f"Next Up — {ev.event_name}",
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="next_up", db=db),
            **_next_up_panel_context(ev, db),
        },
        stylesheets=("css/public.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="public-page",
    )


@router.get("/{event_id}/next-up/panel", response_class=HTMLResponse)
def next_up_board_panel(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)
    return render_template(
        request,
        "public/partials/next_up_panel.html",
        title=f"Next Up — {ev.event_name}",
        context={"event": ev, **_next_up_panel_context(ev, db)},
    )


@router.get("/{event_id}/robot/{robot_id}/history", response_class=HTMLResponse)
def robot_history(request: Request, event_id: int, robot_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not ev or not robot or not _robot_has_event_history(robot_id, event_id, db):
        return _not_found(request)
    return render_template(
        request,
        "public/events/robot_history.html",
        title=f"{robot.robot_name} History — {ev.event_name}",
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="lookup", db=db),
            "content_class": "content robot-page-shell",
            **_robot_history_panel_context(ev, robot, db),
        },
        stylesheets=("css/public.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="public-page",
    )


@router.get("/{event_id}/robot/{robot_id}/history/panel", response_class=HTMLResponse)
def robot_history_panel(request: Request, event_id: int, robot_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not ev or not robot or not _robot_has_event_history(robot_id, event_id, db):
        return _not_found(request)
    return render_template(
        request,
        "public/partials/robot_history_panel.html",
        title=f"{robot.robot_name} History — {ev.event_name}",
        context=_robot_history_panel_context(ev, robot, db),
    )


@router.get("/{event_id}/robot/{robot_id}/stats", response_class=HTMLResponse)
def robot_stats(request: Request, event_id: int, robot_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not ev or not robot or not _robot_has_event_history(robot_id, event_id, db):
        return _not_found(request)
    return render_template(
        request,
        "public/events/robot_stats.html",
        title=f"{robot.robot_name} Stats — {ev.event_name}",
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="lookup", db=db),
            "content_class": "content robot-page-shell",
            **_robot_stats_panel_context(ev, robot, db),
        },
        stylesheets=("css/public.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="public-page",
    )


@router.get("/{event_id}/robot/{robot_id}/stats/panel", response_class=HTMLResponse)
def robot_stats_panel(request: Request, event_id: int, robot_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not ev or not robot or not _robot_has_event_history(robot_id, event_id, db):
        return _not_found(request)
    return render_template(
        request,
        "public/partials/robot_stats_panel.html",
        title=f"{robot.robot_name} Stats — {ev.event_name}",
        context=_robot_stats_panel_context(ev, robot, db),
    )


# ---------------------------------------------------------------------------


@router.get("/{event_id}/sub-events", response_class=HTMLResponse)
def sub_events_list(request: Request, event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)
    return render_template(
        request,
        "public/events/sub_events_list.html",
        title=f"Sub-events — {ev.event_name}",
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="sub_events", db=db),
            **_sub_events_list_context(ev, event_id, db),
        },
        stylesheets=("css/public.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="public-page",
    )


@router.get("/{event_id}/sub-events/{sub_event_id}", response_class=HTMLResponse)
def sub_event_detail(request: Request, event_id: int, sub_event_id: int, db: Session = Depends(get_db)):
    """Public bracket view and team rosters for a sub-event."""
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found(request)

    se = db.query(SubEvent).filter(SubEvent.id == sub_event_id, SubEvent.event_id == event_id).first()
    if not se:
        return _not_found(request)
    return render_template(
        request,
        "public/events/sub_event_detail.html",
        title=f"{se.name} — {ev.event_name}",
        context={
            "event": ev,
            "event_title": ev.event_name,
            "event_nav": _event_nav_links(ev, active="sub_events", db=db),
            **_sub_event_detail_context(ev, se, event_id, sub_event_id, db),
        },
        stylesheets=("css/public.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="public-page",
    )

