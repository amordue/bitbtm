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
from fasthtml.common import (
    A,
    Body,
    Button,
    Div,
    H1,
    H2,
    H3,
    Head,
    Html,
    Img,
    Input,
    Label,
    Li,
    Meta,
    NotStr,
    P,
    Script,
    Small,
    Span,
    Style,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Title,
    Tr,
    Ul,
    Form as HForm,
    to_xml,
)
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
    Roboteer,
    SubEvent,
    SubEventMatchup,
    SubEventTeam,
)
from scoring import BYE_POINTS

router = APIRouter(prefix="/events")

# ---------------------------------------------------------------------------
# Shared styles (public, mobile-first)
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #111;
    color: #f0f0f0;
    min-height: 100vh;
    padding-bottom: 3rem;
}
a { color: #60a5fa; text-decoration: none; }
a:hover { text-decoration: underline; }
/* Top bar */
.topbar {
    background: #161616;
    border-bottom: 1px solid #2a2a2a;
    padding: 0.9rem 1.2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
}
.topbar-title { font-weight: 700; font-size: 1rem; color: #f0f0f0; }
.topbar-links { display: flex; gap: 0.75rem; font-size: 0.82rem; flex-wrap: wrap; }
/* Content */
.content { padding: 1.25rem; max-width: 860px; margin: 0 auto; }
h1 { font-size: 1.55rem; margin-bottom: 0.3rem; }
h2 { font-size: 1.1rem; margin-bottom: 0.85rem; }
h3 { font-size: 0.95rem; font-weight: 600; margin-bottom: 0.5rem; }
.subtitle { color: #888; font-size: 0.88rem; margin-bottom: 1.4rem; }
/* Cards */
.card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    padding: 1.25rem;
    margin-bottom: 1.2rem;
}
/* Buttons */
.btn {
    display: inline-block;
    padding: 0.55rem 1.1rem;
    border-radius: 6px;
    border: none;
    font-size: 0.88rem;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none;
    transition: opacity 0.15s;
}
.btn:hover { opacity: 0.85; text-decoration: none; }
.btn-primary   { background: #3b82f6; color: #fff; }
.btn-secondary { background: #2f2f2f; color: #ccc; border: 1px solid #3a3a3a; }
.btn-sm { padding: 0.3rem 0.7rem; font-size: 0.78rem; }
/* Forms */
.form-group { margin-bottom: 1rem; }
.form-group label { display: block; color: #aaa; font-size: 0.85rem; margin-bottom: 0.3rem; }
.form-control {
    width: 100%;
    background: #111;
    border: 1px solid #333;
    border-radius: 6px;
    color: #f0f0f0;
    padding: 0.55rem 0.75rem;
    font-size: 0.95rem;
}
.form-control:focus { outline: none; border-color: #3b82f6; }
/* Tables */
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: collapse; font-size: 0.87rem; }
th {
    text-align: left; padding: 0.55rem 0.8rem; color: #888; font-weight: 600;
    border-bottom: 1px solid #2a2a2a; white-space: nowrap;
}
td { padding: 0.5rem 0.8rem; border-bottom: 1px solid #1e1e1e; vertical-align: middle; }
tr:last-child td { border-bottom: none; }
/* Badges */
.badge {
    display: inline-block; padding: 0.18rem 0.5rem; border-radius: 99px;
    font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em;
}
.badge-setup       { background: #1f2937; color: #9ca3af; }
.badge-registration{ background: #1e3a5f; color: #60a5fa; }
.badge-qualifying  { background: #1a3a26; color: #4ade80; }
.badge-bracket     { background: #3b1a5f; color: #c084fc; }
.badge-sub_events  { background: #3a2a10; color: #fcd34d; }
.badge-complete    { background: #1a3a1a; color: #86efac; }
.badge-pending     { background: #292929; color: #777; }
.badge-completed   { background: #1a3a26; color: #4ade80; }
/* Leaderboard rank */
.rank-1 { color: #fbbf24; font-weight: 700; }
.rank-2 { color: #d1d5db; font-weight: 700; }
.rank-3 { color: #cd7f32; font-weight: 700; }
/* Fight card */
.fight-row-win  { border-left: 3px solid #22c55e; }
.fight-row-loss { border-left: 3px solid #ef4444; }
.fight-row-draw { border-left: 3px solid #f59e0b; }
.fight-row-pending { border-left: 3px solid #374151; }
/* Robot image */
.robot-thumb { width: 44px; height: 44px; object-fit: cover; border-radius: 6px; }
/* Bracket round header */
.round-header {
    font-size: 0.8rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.06em; color: #555; margin: 1.2rem 0 0.5rem;
    padding-bottom: 0.3rem; border-bottom: 1px solid #2a2a2a;
}
/* Empty */
.empty { color: #555; padding: 1.5rem 0; text-align: center; font-size: 0.9rem; }
/* Search results */
.search-result-item {
    display: flex; align-items: center; gap: 0.75rem;
    padding: 0.65rem 0; border-bottom: 1px solid #1e1e1e;
}
.search-result-item:last-child { border-bottom: none; }
/* Nav links row under the title */
.event-nav { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 1.4rem; }
/* QR code block */
.qr-wrap {
    display: flex; flex-direction: column; align-items: center;
    gap: 1rem; padding: 1.5rem 0;
}
.qr-wrap svg { background: #fff; padding: 12px; border-radius: 8px; }
.qr-url {
    font-size: 0.82rem; color: #888; word-break: break-all; text-align: center;
    max-width: 360px;
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _page(title: str, *body_content) -> HTMLResponse:
    head = Head(
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Title(f"{title} — BitBT"),
        Style(_CSS),
    )
    return HTMLResponse(to_xml(Html(head, Body(Div(*body_content, cls="content")))))


def _event_topbar(ev: Event, active: str = "", db: Optional[Session] = None) -> Div:
    """Navigation bar shown on every public event page."""
    links = [
        ("Overview", f"/events/{ev.id}", "overview"),
        ("Leaderboard", f"/events/{ev.id}/leaderboard", "leaderboard"),
        ("Bracket", f"/events/{ev.id}/bracket", "bracket"),
        ("My Robot", f"/events/{ev.id}/lookup", "lookup"),
        ("QR Code", f"/events/{ev.id}/qr", "qr"),
    ]
    # Add Sub-events link if any exist
    if db is not None:
        se_count = db.query(SubEvent).filter(SubEvent.event_id == ev.id).count()
        if se_count:
            links.insert(3, ("Sub-events", f"/events/{ev.id}/sub-events", "sub_events"))

    nav_links = []
    for label, href, key in links:
        style = "color:#f0f0f0;font-weight:600;" if key == active else ""
        nav_links.append(A(label, href=href, style=style))

    return Div(
        Span(f"⚙ {ev.event_name}", cls="topbar-title"),
        Div(*nav_links, cls="topbar-links"),
        cls="topbar",
    )


def _status_badge(status: EventStatus) -> Span:
    return Span(status.value, cls=f"badge badge-{status.value}")


def _get_public_event(event_id: int, db: Session) -> Optional[Event]:
    return db.query(Event).filter(Event.id == event_id).first()


def _robot_has_event_history(robot_id: int, event_id: int, db: Session) -> bool:
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


def _robot_points_in_event(robot_id: int, event_id: int, db: Session) -> int:
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


# ---------------------------------------------------------------------------
# 13. Public event overview
# ---------------------------------------------------------------------------


@router.get("/{event_id}", response_class=HTMLResponse)
def event_overview(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()

    phases = db.query(Phase).filter(Phase.event_id == event_id).order_by(Phase.phase_number).all()

    active_count = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == False)
        .count()
    )
    reserve_count = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == True)
        .count()
    )

    # Phase cards
    phase_items = []
    for ph in phases:
        completed = sum(
            1 for m in ph.matchups if m.status == MatchupStatus.completed
        )
        total = len(ph.matchups)
        label = f"Qualifying Round {ph.phase_number}" if ph.phase_type == PhaseType.qualifying else "Main Bracket"
        phase_items.append(Li(
            Span(label, style="color:#ccc;"),
            Span(f" — {completed}/{total} fights complete", style="color:#555;font-size:0.85rem;"),
            Span(ph.status.value, cls=f"badge badge-{ph.status.value}", style="margin-left:0.5rem;"),
            style="padding:0.35rem 0;",
        ))

    phases_section = ""
    if phases:
        phases_section = Div(
            H2("Phases"),
            Ul(*phase_items, style="list-style:none;"),
            cls="card",
        )

    stats_card = Div(
        H2("Tournament Info"),
        Ul(
            Li(Span("Weight class: ", style="color:#888;"), ev.weight_class),
            Li(Span("Status: ", style="color:#888;"), _status_badge(ev.status)),
            Li(Span("Active robots: ", style="color:#888;"), str(active_count)),
            Li(Span("Reserves: ", style="color:#888;"), str(reserve_count)),
            style="list-style:none;",
        ),
        style="margin-bottom:1.2rem;",
        cls="card",
    )

    cta = Div(
        A("🔍 Find my robot", href=f"/events/{event_id}/lookup", cls="btn btn-primary"),
        " ",
        A("🏆 Leaderboard", href=f"/events/{event_id}/leaderboard", cls="btn btn-secondary"),
        " ",
        A("🪜 Bracket", href=f"/events/{event_id}/bracket", cls="btn btn-secondary"),
        style="margin-bottom:1.4rem;",
    )

    return _page(
        ev.event_name,
        _event_topbar(ev, "overview", db=db),
        Div(
            H1(ev.event_name),
            P(ev.weight_class, cls="subtitle"),
            cta,
            stats_card,
            phases_section,
        ),
    )


# ---------------------------------------------------------------------------
# 14. Robot lookup (search)
# ---------------------------------------------------------------------------


@router.get("/{event_id}/lookup", response_class=HTMLResponse)
def robot_lookup(
    event_id: int,
    db: Session = Depends(get_db),
    q: str = Query(default=""),
):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()

    results_section = ""

    if q:
        q_stripped = q.strip()
        # Case-insensitive search on robot name or roboteer name
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

        if matched_ers:
            items = []
            for er in matched_ers:
                robot: Robot = er.robot
                thumb = (
                    Img(src=robot.image_url, cls="robot-thumb", alt=robot.robot_name)
                    if robot.image_url
                    else Div(style="width:44px;height:44px;background:#222;border-radius:6px;flex-shrink:0;")
                )
                items.append(
                    Div(
                        thumb,
                        Div(
                            A(
                                robot.robot_name,
                                href=f"/events/{event_id}/robot/{robot.id}",
                                style="font-weight:600;font-size:1rem;",
                            ),
                            Div(
                                Span(robot.roboteer.roboteer_name, style="color:#888;font-size:0.85rem;"),
                                Span(f" · {robot.weapon_type}", style="color:#555;font-size:0.85rem;")
                                if robot.weapon_type
                                else "",
                            ),
                        ),
                        cls="search-result-item",
                    )
                )
            results_section = Div(
                P(f'{len(matched_ers)} result(s) for \u201c{q_stripped}\u201d', style="color:#888;font-size:0.85rem;margin-bottom:0.5rem;"),
                *items,
            )
        else:
            results_section = P(f'No robots found matching \u201c{q_stripped}\u201d.', cls="empty")

    search_form = HForm(
        Div(
            Label("Search by robot name or roboteer name", for_="q"),
            Input(
                type="search",
                id="q",
                name="q",
                cls="form-control",
                value=q,
                placeholder="e.g. Mauler or Alex…",
                autofocus="true",
            ),
            cls="form-group",
        ),
        Button("Search", type="submit", cls="btn btn-primary"),
        method="get",
        action=f"/events/{event_id}/lookup",
    )

    return _page(
        f"Robot Lookup — {ev.event_name}",
        _event_topbar(ev, "lookup", db=db),
        Div(
            H1("🔍 Find Your Robot"),
            P(f"{ev.event_name} · {ev.weight_class}", cls="subtitle"),
            Div(search_form, cls="card"),
            results_section,
        ),
    )


# ---------------------------------------------------------------------------
# 15. My Robot's Fights
# ---------------------------------------------------------------------------


@router.get("/{event_id}/robot/{robot_id}", response_class=HTMLResponse)
def robot_fights(
    event_id: int,
    robot_id: int,
    db: Session = Depends(get_db),
):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()

    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not robot:
        return _not_found()

    if not _robot_has_event_history(robot_id, event_id, db):
        return _not_found()

    # All matchups for this robot in this event, ordered by phase/display_order
    matchups = (
        db.query(Matchup)
        .join(Phase, Phase.id == Matchup.phase_id)
        .filter(
            Phase.event_id == event_id,
            or_(Matchup.robot1_id == robot_id, Matchup.robot2_id == robot_id),
        )
        .order_by(Phase.phase_number, Matchup.bracket_round, Matchup.display_order)
        .all()
    )

    total_points = _robot_points_in_event(robot_id, event_id, db)
    completed_fights = sum(1 for m in matchups if m.status == MatchupStatus.completed)

    # --- Build fight rows ---
    fight_rows = []
    for m in matchups:
        phase: Phase = m.phase
        if phase.phase_type == PhaseType.qualifying:
            phase_label = f"Q{phase.phase_number}"
            phase_full = f"Qualifying Round {phase.phase_number}"
        else:
            phase_full = phase_label = "Bracket"

        is_bye = m.robot2_id is None
        if is_bye:
            opponent_cell = Span("BYE", style="color:#555;font-style:italic;")
            result_label, result_pts, opp_pts = f"BYE ({BYE_POINTS} pts)", str(BYE_POINTS), "—"
            row_cls = "fight-row-win"
        else:
            opponent = m.robot2 if m.robot1_id == robot_id else m.robot1
            opponent_cell = A(opponent.robot_name, href=f"/events/{event_id}/robot/{opponent.id}")

            if m.status == MatchupStatus.completed:
                my_result = next((r for r in m.results if r.robot_id == robot_id), None)
                opp_result = next((r for r in m.results if r.robot_id != robot_id), None)
                my_pts = my_result.points_scored if my_result else 0
                opp_pts = opp_result.points_scored if opp_result else 0

                result_pts = str(my_pts)
                opp_pts_str = str(opp_pts)

                if my_pts > opp_pts:
                    result_label = "Win"
                    row_cls = "fight-row-win"
                elif my_pts < opp_pts:
                    result_label = "Loss"
                    row_cls = "fight-row-loss"
                else:
                    result_label = "Draw"
                    row_cls = "fight-row-draw"
            else:
                result_label = "Upcoming"
                result_pts = "—"
                opp_pts_str = "—"
                row_cls = "fight-row-pending"

        pts_display = (
            Span(result_pts, style="color:#4ade80;font-weight:600;")
            if result_label in ("Win", f"BYE ({BYE_POINTS} pts)")
            else Span(result_pts, style="color:#f87171;" if result_label == "Loss" else "color:#888;")
        )

        fight_rows.append(Tr(
            Td(Span(phase_label, cls=f"badge badge-{phase.status.value}"), title=phase_full),
            Td(opponent_cell),
            Td(pts_display),
            Td(Span(result_label, style="color:#888;font-size:0.82rem;")),
            cls=row_cls,
        ))

    thumb = ""
    if robot.image_url:
        thumb = Img(
            src=robot.image_url,
            style="width:80px;height:80px;object-fit:cover;border-radius:8px;margin-bottom:1rem;",
            alt=robot.robot_name,
        )

    summary_parts = [
        Span(f"{completed_fights} fight(s) played", style="color:#888;font-size:0.88rem;"),
        " · ",
        Span(f"{total_points} pts total", style="color:#60a5fa;font-size:0.88rem;font-weight:600;"),
    ]

    fights_section = ""
    if fight_rows:
        fights_section = Div(
            Div(
                Table(
                    Thead(Tr(Th("Phase"), Th("Opponent"), Th("Pts"), Th("Result"))),
                    Tbody(*fight_rows),
                ),
                cls="table-wrap",
            ),
            cls="card",
        )
    else:
        fights_section = Div(P("No fights scheduled yet.", cls="empty"), cls="card")

    return _page(
        f"{robot.robot_name} — {ev.event_name}",
        _event_topbar(ev, "lookup", db=db),
        Div(
            A("← Robot lookup", href=f"/events/{event_id}/lookup", cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
            thumb,
            H1(robot.robot_name),
            P(
                Span(robot.roboteer.roboteer_name, style="color:#888;"),
                Span(f" · {robot.weapon_type}", style="color:#555;") if robot.weapon_type else "",
                cls="subtitle",
            ),
            Div(*summary_parts, style="margin-bottom:1.4rem;"),
            fights_section,
        ),
    )


# ---------------------------------------------------------------------------
# 16. Leaderboard
# ---------------------------------------------------------------------------


@router.get("/{event_id}/leaderboard", response_class=HTMLResponse)
def leaderboard(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()

    # All active robots in this event
    active_ers = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == False)
        .all()
    )

    # Aggregate points and fight stats per robot
    rows = []
    for er in active_ers:
        robot: Robot = er.robot
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

        total_pts = sum(r.points_scored for r in results)
        fights = len(results)

        # Wins: robot scored more points than opponent in same matchup
        wins = 0
        matchup_ids = list({r.matchup_id for r in results})
        for mid in matchup_ids:
            matchup_results = [r for r in results if r.matchup_id == mid]
            all_results = db.query(Result).filter(Result.matchup_id == mid).all()
            if len(all_results) >= 2:
                my_pts = next((r.points_scored for r in all_results if r.robot_id == robot.id), 0)
                opp_pts = next((r.points_scored for r in all_results if r.robot_id != robot.id), 0)
                if my_pts > opp_pts:
                    wins += 1
            elif len(all_results) == 1 and matchup_results:
                # Bye — always counts as a win
                wins += 1

        rows.append({
            "robot": robot,
            "roboteer": robot.roboteer,
            "total_pts": total_pts,
            "fights": fights,
            "wins": wins,
        })

    # Sort: total points desc, then wins desc
    rows.sort(key=lambda r: (-r["total_pts"], -r["wins"]))

    if not rows or all(r["fights"] == 0 for r in rows):
        body = P("No results yet — check back once fights begin.", cls="empty")
    else:
        table_rows = []
        for i, row in enumerate(rows, start=1):
            rank_cls = f"rank-{i}" if i <= 3 else ""
            robot: Robot = row["robot"]
            thumb = (
                Img(src=robot.image_url, cls="robot-thumb", alt=robot.robot_name)
                if robot.image_url
                else ""
            )
            table_rows.append(Tr(
                Td(Span(str(i), cls=rank_cls)),
                Td(thumb),
                Td(A(robot.robot_name, href=f"/events/{event_id}/robot/{robot.id}")),
                Td(row["roboteer"].roboteer_name, style="color:#888;"),
                Td(
                    Span(str(row["total_pts"]), style="font-weight:700;color:#60a5fa;"),
                ),
                Td(str(row["wins"])),
                Td(str(row["fights"])),
            ))

        body = Div(
            Table(
                Thead(Tr(
                    Th("#"), Th(""), Th("Robot"), Th("Roboteer"),
                    Th("Pts"), Th("Wins"), Th("Fights"),
                )),
                Tbody(*table_rows),
            ),
            cls="table-wrap",
        )

    return _page(
        f"Leaderboard — {ev.event_name}",
        _event_topbar(ev, "leaderboard", db=db),
        Div(
            H1("🏆 Leaderboard"),
            P(f"{ev.event_name} · {ev.weight_class}", cls="subtitle"),
            Div(body, cls="card"),
        ),
    )


# ---------------------------------------------------------------------------
# 17. Bracket view
# ---------------------------------------------------------------------------


@router.get("/{event_id}/bracket", response_class=HTMLResponse)
def bracket_view(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()

    bracket_phase = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.bracket)
        .first()
    )

    if not bracket_phase:
        return _page(
            f"Bracket — {ev.event_name}",
            _event_topbar(ev, "bracket", db=db),
            Div(
                H1("🪜 Bracket"),
                P(f"{ev.event_name} · {ev.weight_class}", cls="subtitle"),
                Div(
                    P(
                        "The bracket hasn't been drawn yet. "
                        "It will appear here once qualifying rounds are complete.",
                        cls="empty",
                    ),
                    cls="card",
                ),
            ),
        )

    matchups = (
        db.query(Matchup)
        .filter(Matchup.phase_id == bracket_phase.id)
        .order_by(Matchup.bracket_round, Matchup.display_order)
        .all()
    )

    if not matchups:
        return _page(
            f"Bracket — {ev.event_name}",
            _event_topbar(ev, "bracket", db=db),
            Div(
                H1("🪜 Bracket"),
                P(f"{ev.event_name} · {ev.weight_class}", cls="subtitle"),
                Div(P("No bracket matchups yet.", cls="empty"), cls="card"),
            ),
        )

    rounds: dict[int, list[Matchup]] = {}
    for matchup in matchups:
        round_number = matchup.bracket_round or 1
        rounds.setdefault(round_number, []).append(matchup)

    total_rounds = _total_bracket_rounds(rounds)

    sections = []
    for round_number in sorted(rounds.keys()):
        sections.append(P(_public_bracket_round_label(round_number, total_rounds), cls="round-header"))
        for m in rounds[round_number]:
            sections.append(_bracket_matchup_card(m, event_id))

    return _page(
        f"Bracket — {ev.event_name}",
        _event_topbar(ev, "bracket", db=db),
        Div(
            H1("🪜 Bracket"),
            P(f"{ev.event_name} · {ev.weight_class}", cls="subtitle"),
            Div(*sections, cls="card"),
        ),
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


def _bracket_matchup_card(m: Matchup, event_id: int) -> Div:
    """Render a single bracket matchup as a compact two-row card."""
    def _robot_row(robot: Optional[Robot], is_winner: bool, pts: Optional[int]) -> Div:
        if robot is None:
            return Div(Span("TBD", style="color:#555;font-style:italic;"), style="padding:0.4rem 0;")
        name_el = A(robot.robot_name, href=f"/events/{event_id}/robot/{robot.id}")
        pts_el = (
            Span(str(pts), style="margin-left:auto;font-weight:700;color:#4ade80;" if is_winner else "margin-left:auto;color:#f87171;")
            if pts is not None
            else Span("—", style="margin-left:auto;color:#444;")
        )
        border = "border-radius:4px;background:#1f3a1f;" if is_winner else ""
        return Div(
            name_el, pts_el,
            style=f"display:flex;align-items:center;padding:0.35rem 0.5rem;{border}",
        )

    r1: Optional[Robot] = m.robot1
    r2: Optional[Robot] = m.robot2

    r1_pts = r2_pts = None
    r1_win = r2_win = False
    if m.status == MatchupStatus.completed:
        for res in m.results:
            if res.robot_id == (r1.id if r1 else None):
                r1_pts = res.points_scored
            elif r2 and res.robot_id == r2.id:
                r2_pts = res.points_scored
        if r1_pts is not None and r2_pts is not None:
            r1_win = r1_pts >= r2_pts
            r2_win = r2_pts > r1_pts
        elif r1_pts is not None:
            r1_win = True  # bye

    status_badge = Span(
        "●" if m.status == MatchupStatus.completed else "○",
        style="color:#4ade80;" if m.status == MatchupStatus.completed else "color:#374151;",
        title=m.status.value,
    )

    return Div(
        Div(
            _robot_row(r1, r1_win, r1_pts),
            Div(style="border-top:1px solid #222;margin:0 0.5rem;"),
            _robot_row(r2, r2_win, r2_pts),
            style="flex:1;",
        ),
        Div(status_badge, style="padding:0.5rem;align-self:center;"),
        style=(
            "display:flex;border:1px solid #2a2a2a;border-radius:6px;"
            "margin-bottom:0.5rem;overflow:hidden;background:#161616;"
        ),
    )


# ---------------------------------------------------------------------------
# 18. QR code page
# ---------------------------------------------------------------------------


@router.get("/{event_id}/qr", response_class=HTMLResponse)
def qr_page(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()

    event_url = f"{APP_BASE_URL}/events/{event_id}"
    svg_data = _make_qr_svg(event_url)

    return _page(
        f"QR Code — {ev.event_name}",
        _event_topbar(ev, "qr", db=db),
        Div(
            H1("📱 Event QR Code"),
            P(f"{ev.event_name} · {ev.weight_class}", cls="subtitle"),
            Div(
                P(
                    "Show this QR code on a screen at the venue for quick mobile access.",
                    style="color:#888;font-size:0.88rem;text-align:center;",
                ),
                Div(
                    NotStr(svg_data),
                    P(event_url, cls="qr-url"),
                    A("Open event page", href=event_url, cls="btn btn-primary btn-sm"),
                    cls="qr-wrap",
                ),
                cls="card",
            ),
        ),
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
# Shared helpers
# ---------------------------------------------------------------------------


def _not_found() -> HTMLResponse:
    return HTMLResponse(
        to_xml(Html(
            Head(Title("Not Found — BitBT"), Style(_CSS)),
            Body(Div(
                H1("Event not found"),
                P("This event doesn't exist or may have been removed.", style="color:#888;"),
                A("← Home", href="/", style="color:#60a5fa;"),
                cls="content",
                style="padding-top:3rem;text-align:center;",
            )),
        )),
        status_code=404,
    )


# ===========================================================================
# Phase 5b — Step 36: Public sub-events view (bracket + team rosters)
# ===========================================================================


@router.get("/{event_id}/sub-events", response_class=HTMLResponse)
def sub_events_list(event_id: int, db: Session = Depends(get_db)):
    """List all sub-events for an event."""
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()

    sub_events = (
        db.query(SubEvent)
        .filter(SubEvent.event_id == event_id)
        .order_by(SubEvent.id)
        .all()
    )

    if not sub_events:
        body = Div(P("No sub-events have been created for this tournament yet.", cls="empty"), cls="card")
    else:
        items = []
        for se in sub_events:
            team_count = db.query(SubEventTeam).filter(SubEventTeam.sub_event_id == se.id).count()
            items.append(Div(
                H2(A(se.name, href=f"/events/{event_id}/sub-events/{se.id}")),
                P(
                    Span(se.format.value, style="color:#888;font-size:0.85rem;"),
                    Span(" · ", style="color:#444;"),
                    Span(f"{team_count} team(s)", style="color:#888;font-size:0.85rem;"),
                    Span(" · ", style="color:#444;"),
                    Span(se.status.value, cls=f"badge badge-{se.status.value}"),
                    style="margin:0.3rem 0 0.75rem;",
                ),
                A("View bracket & teams →", href=f"/events/{event_id}/sub-events/{se.id}",
                  cls="btn btn-secondary btn-sm"),
                cls="card",
            ))
        body = Div(*items)

    return _page(
        f"Sub-events — {ev.event_name}",
        _event_topbar(ev, "sub_events", db=db),
        Div(
            H1("⚔ Sub-events"),
            P(f"{ev.event_name} · {ev.weight_class}", cls="subtitle"),
            body,
        ),
    )


@router.get("/{event_id}/sub-events/{sub_event_id}", response_class=HTMLResponse)
def sub_event_public(
    event_id: int,
    sub_event_id: int,
    db: Session = Depends(get_db),
):
    """Public bracket view and team rosters for a sub-event."""
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()

    se = db.query(SubEvent).filter(SubEvent.id == sub_event_id, SubEvent.event_id == event_id).first()
    if not se:
        return _not_found()

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

    # --- Team rosters card ---
    if teams:
        team_rows = []
        for t in teams:
            r1_thumb = (
                Img(src=t.robot1.image_url, cls="robot-thumb", alt=t.robot1.robot_name, style="width:32px;height:32px;")
                if t.robot1.image_url else ""
            )
            r2_thumb = (
                Img(src=t.robot2.image_url, cls="robot-thumb", alt=t.robot2.robot_name, style="width:32px;height:32px;")
                if t.robot2.image_url else ""
            )
            team_rows.append(Tr(
                Td(t.team_name, style="font-weight:600;"),
                Td(r1_thumb, " ", A(t.robot1.robot_name, href=f"/events/{event_id}/robot/{t.robot1_id}")),
                Td(r2_thumb, " ", A(t.robot2.robot_name, href=f"/events/{event_id}/robot/{t.robot2_id}")),
            ))
        teams_section = Div(
            H2("Teams"),
            Div(
                Table(
                    Thead(Tr(Th("Team"), Th("Robot 1"), Th("Robot 2"))),
                    Tbody(*team_rows),
                ),
                cls="table-wrap",
            ),
            cls="card",
        )
    else:
        teams_section = Div(P("Teams not yet assigned.", cls="empty"), cls="card")

    # --- Bracket card ---
    if all_matchups:
        rounds: dict[int, list[SubEventMatchup]] = {}
        for m in all_matchups:
            rounds.setdefault(m.round_number, []).append(m)

        max_rnd = max(rounds.keys())

        def _se_round_label_pub(rnd: int) -> str:
            terminal = ["Final", "Semi-finals", "Quarter-finals", "Round of 16", "Round of 32"]
            offset = 4 - max_rnd
            idx = rnd + offset - 1
            if 0 <= idx < len(terminal):
                return terminal[idx]
            return f"Round {rnd}"

        bracket_items = []
        for rnd in sorted(rounds.keys()):
            bracket_items.append(P(_se_round_label_pub(rnd), cls="round-header"))
            for m in rounds[rnd]:
                bracket_items.append(_se_matchup_card_public(m, event_id))

        bracket_section = Div(
            H2("Bracket"),
            Div(*bracket_items),
            cls="card",
        )
    else:
        bracket_section = Div(
            H2("Bracket"),
            P("Bracket not yet generated.", cls="empty"),
            cls="card",
        )

    return _page(
        f"{se.name} — {ev.event_name}",
        _event_topbar(ev, "sub_events", db=db),
        Div(
            A("← Sub-events", href=f"/events/{event_id}/sub-events",
              cls="btn btn-secondary btn-sm", style="margin-bottom:1.2rem;display:inline-block;"),
            H1(se.name),
            P(
                Span(se.format.value, style="color:#888;font-size:0.85rem;"),
                Span(" · ", style="color:#444;"),
                Span(se.status.value, cls=f"badge badge-{se.status.value}"),
                cls="subtitle",
            ),
            teams_section,
            bracket_section,
        ),
    )


def _se_matchup_card_public(m: SubEventMatchup, event_id: int) -> Div:
    """Render a public-facing sub-event matchup card."""
    t1: Optional[SubEventTeam] = m.team1
    t2: Optional[SubEventTeam] = m.team2

    def _team_row(team: Optional[SubEventTeam], is_winner: bool) -> Div:
        if team is None:
            return Div(
                Span("TBD", style="color:#555;font-style:italic;"),
                style="padding:0.35rem 0.5rem;",
            )
        name_el = Span(team.team_name, style="font-weight:600;")
        robots_el = Span(
            f"  ({team.robot1.robot_name} & {team.robot2.robot_name})",
            style="color:#666;font-size:0.78rem;",
        )
        win_el = Span(" ✓", style="margin-left:auto;color:#4ade80;font-weight:700;") if is_winner else Span("", style="margin-left:auto;")
        bg = "background:#1f3a1f;" if is_winner else ""
        return Div(name_el, robots_el, win_el,
                   style=f"display:flex;align-items:center;padding:0.35rem 0.5rem;border-radius:4px;{bg}")

    t1_win = m.winner_team_id is not None and t1 is not None and m.winner_team_id == t1.id
    t2_win = m.winner_team_id is not None and t2 is not None and m.winner_team_id == t2.id

    is_bye = t2 is None
    status_dot = Span(
        "●" if m.status == MatchupStatus.completed else "○",
        style="color:#4ade80;" if m.status == MatchupStatus.completed else "color:#374151;",
    )

    return Div(
        Div(
            _team_row(t1, t1_win),
            Div(style="border-top:1px solid #222;margin:0 0.5rem;"),
            _team_row(t2 if not is_bye else None, t2_win),
            style="flex:1;",
        ),
        Div(
            status_dot,
            Span(" BYE", style="color:#555;font-size:0.75rem;") if is_bye else "",
            style="padding:0.5rem;align-self:center;",
        ),
        style=(
            "display:flex;border:1px solid #2a2a2a;border-radius:6px;"
            "margin-bottom:0.5rem;overflow:hidden;background:#161616;"
        ),
    )

