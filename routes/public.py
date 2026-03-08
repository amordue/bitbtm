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
    Button,
    Div,
    H1,
    H2,
    H3,
    Img,
    Input,
    Label,
    Li,
    P,
    Small,
    Span,
    Table,
    Tbody,
    Td,
    Th,
    Thead,
    Tr,
    Ul,
    Script,
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
from scoring import BYE_POINTS
from ui import HTMX_SCRIPT_URL, page_response, status_badge

router = APIRouter(prefix="/events")

# ---------------------------------------------------------------------------
# Shared styles (public, mobile-first)
# ---------------------------------------------------------------------------

_CSS = """
body { padding-bottom: 3rem; }
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
/* Leaderboard rank */
.rank-1 { color: #fbbf24; font-weight: 700; }
.rank-2 { color: #d1d5db; font-weight: 700; }
.rank-3 { color: #cd7f32; font-weight: 700; }
/* Fight card */
.fight-row-win  { border-left: 3px solid #22c55e; }
.fight-row-loss { border-left: 3px solid #ef4444; }
.fight-row-draw { border-left: 3px solid #f59e0b; }
.fight-row-pending { border-left: 3px solid #374151; }
/* Bracket round header */
.round-header {
    font-size: 0.8rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.06em; color: #555; margin: 1.2rem 0 0.5rem;
    padding-bottom: 0.3rem; border-bottom: 1px solid #2a2a2a;
}
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
.qr-wrap img {
    display: block;
    width: min(100%, 320px);
    height: auto;
    background: #fff;
    padding: 12px;
    border-radius: 8px;
}
.qr-url {
    font-size: 0.82rem; color: #888; word-break: break-all; text-align: center;
    max-width: 360px;
}
.auto-panel {
    transition: opacity 0.2s ease;
}
.htmx-request.auto-panel { opacity: 0.65; }
.stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 0.8rem;
}
.stat-tile {
    background: linear-gradient(180deg, #181818 0%, #131313 100%);
    border: 1px solid #262626;
    border-radius: 8px;
    padding: 0.9rem;
}
.stat-label {
    color: #777;
    font-size: 0.74rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.35rem;
}
.stat-value {
    font-size: 1.45rem;
    font-weight: 700;
    color: #f8fafc;
}
.stat-meta { color: #60a5fa; font-size: 0.8rem; margin-top: 0.2rem; }
.stack { display: flex; flex-direction: column; gap: 1rem; }
.history-item {
    border: 1px solid #252525;
    border-radius: 8px;
    padding: 0.95rem 1rem;
    background: #171717;
}
.history-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.55rem;
    margin-bottom: 0.55rem;
    align-items: center;
}
.history-title {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: baseline;
    flex-wrap: wrap;
}
.history-score { font-weight: 700; color: #f8fafc; }
.robot-page-shell { max-width: 1080px; }
.robot-detail-hero {
    display: grid;
    gap: 1.25rem;
    align-items: start;
}
.robot-detail-copy { min-width: 0; }
.robot-detail-actions {
    display: flex;
    gap: 0.6rem;
    flex-wrap: wrap;
    margin-bottom: 1rem;
}
.robot-detail-photo-wrap {
    margin: 0.4rem 0 1.35rem;
    width: min(100%, 540px);
}
.robot-detail-photo-button {
    display: block;
    width: 100%;
    padding: 0;
    border: none;
    background: transparent;
    cursor: zoom-in;
    text-align: left;
}
.robot-detail-photo {
    display: block;
    width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: cover;
    border-radius: 16px;
    border: 1px solid #2a2a2a;
    background: #141414;
    box-shadow: 0 18px 40px rgba(0, 0, 0, 0.28);
}
.robot-detail-photo-hint {
    display: inline-block;
    margin-top: 0.55rem;
    color: #7b7b7b;
    font-size: 0.78rem;
    letter-spacing: 0.03em;
    text-transform: uppercase;
}
.robot-lightbox {
    position: fixed;
    inset: 0;
    z-index: 1200;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
    background: rgba(6, 8, 12, 0.88);
}
.robot-lightbox[hidden] { display: none; }
.robot-lightbox-frame {
    position: relative;
    width: min(96vw, 980px);
}
.robot-lightbox-image {
    display: block;
    width: 100%;
    max-height: 88vh;
    object-fit: contain;
    border-radius: 18px;
    border: 1px solid #2d2d2d;
    background: #101010;
    box-shadow: 0 28px 80px rgba(0, 0, 0, 0.45);
}
.robot-lightbox-close {
    position: absolute;
    top: 0.85rem;
    right: 0.85rem;
    z-index: 1;
    background: rgba(15, 23, 42, 0.88);
    color: #f8fafc;
    border: 1px solid rgba(255, 255, 255, 0.14);
}
.robot-lightbox-caption {
    margin-top: 0.75rem;
    color: #cbd5e1;
    text-align: center;
    font-size: 0.9rem;
}
.live-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.4fr) minmax(320px, 1fr);
    gap: 1rem;
}
.live-stage {
    background:
        radial-gradient(circle at top left, rgba(96, 165, 250, 0.18), transparent 32%),
        linear-gradient(180deg, #171717 0%, #101010 100%);
    border: 1px solid #2a2a2a;
    border-radius: 14px;
    padding: 1.3rem;
}
.live-kicker {
    font-size: 0.76rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #60a5fa;
    margin-bottom: 0.85rem;
}
.live-fight-title {
    font-size: clamp(1.7rem, 4vw, 3.2rem);
    line-height: 1.05;
    font-weight: 800;
    margin-bottom: 0.8rem;
}
.live-fight-subtitle { color: #9ca3af; margin-bottom: 1rem; }
.live-robots {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 1rem;
    align-items: center;
}
.live-robot {
    border: 1px solid #2d2d2d;
    border-radius: 12px;
    padding: 1rem;
    min-height: 150px;
    background: rgba(255, 255, 255, 0.02);
}
.live-robot-name { font-size: clamp(1.35rem, 3vw, 2.4rem); font-weight: 800; }
.live-robot-meta { color: #8d8d8d; margin-top: 0.45rem; }
.live-vs {
    font-size: clamp(1.2rem, 2vw, 1.8rem);
    font-weight: 800;
    color: #60a5fa;
    letter-spacing: 0.08em;
}
.queue-list { display: flex; flex-direction: column; gap: 0.75rem; }
.queue-item {
    border: 1px solid #252525;
    border-radius: 10px;
    padding: 0.85rem 0.95rem;
    background: #161616;
}
.queue-item.current {
    border-color: #60a5fa;
    box-shadow: 0 0 0 1px rgba(96, 165, 250, 0.18) inset;
}
.queue-slot {
    color: #60a5fa;
    font-weight: 700;
    font-size: 0.76rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.25rem;
}
.queue-title { font-weight: 700; margin-bottom: 0.2rem; }
.queue-title-link { color: #f5f5f5; text-decoration: none; }
.queue-title-link:hover { color: #93c5fd; text-decoration: underline; }
.queue-meta { color: #7b7b7b; font-size: 0.82rem; }
.live-sidebar { display: flex; flex-direction: column; gap: 1rem; }
.live-sidebar .card { margin-bottom: 0; }
.leaderboard-mini-row {
    display: grid;
    grid-template-columns: 40px 1fr 66px;
    gap: 0.75rem;
    padding: 0.55rem 0;
    border-bottom: 1px solid #1f1f1f;
    align-items: center;
}
.leaderboard-mini-row:last-child { border-bottom: none; }
.leaderboard-mini-rank { color: #777; font-weight: 700; }
.leaderboard-mini-name { font-weight: 600; }
.leaderboard-mini-points { text-align: right; color: #60a5fa; font-weight: 700; }
.board-header {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: end;
    margin-bottom: 1.1rem;
    flex-wrap: wrap;
}
@media (max-width: 820px) {
    .live-grid { grid-template-columns: 1fr; }
    .live-robots { grid-template-columns: 1fr; }
    .live-vs { text-align: center; }
    .board-header { align-items: start; }
}
@media (min-width: 900px) {
    .robot-detail-hero {
        grid-template-columns: minmax(0, 1fr) minmax(340px, 540px);
        gap: 2rem;
    }
    .robot-detail-photo-wrap {
        justify-self: end;
        margin: 0;
    }
}
"""

_ROBOT_DETAIL_SCRIPT = """
document.addEventListener('click', function (event) {
    const trigger = event.target.closest('[data-lightbox-src]');
    if (trigger) {
        const panel = trigger.closest('[id^="robot-panel-"]');
        if (!panel) {
            return;
        }
        const lightbox = panel.querySelector('.robot-lightbox');
        const image = lightbox ? lightbox.querySelector('.robot-lightbox-image') : null;
        const caption = lightbox ? lightbox.querySelector('.robot-lightbox-caption') : null;
        if (!lightbox || !image) {
            return;
        }
        image.src = trigger.dataset.lightboxSrc || '';
        image.alt = trigger.dataset.lightboxAlt || '';
        if (caption) {
            caption.textContent = trigger.dataset.lightboxCaption || '';
        }
        lightbox.hidden = false;
        document.body.style.overflow = 'hidden';
        return;
    }

    const closeButton = event.target.closest('[data-lightbox-close]');
    const overlay = event.target.classList && event.target.classList.contains('robot-lightbox')
        ? event.target
        : null;
    const lightbox = closeButton ? closeButton.closest('.robot-lightbox') : overlay;
    if (lightbox) {
        lightbox.hidden = true;
        document.body.style.overflow = '';
    }
});

document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') {
        return;
    }
    document.querySelectorAll('.robot-lightbox').forEach(function (lightbox) {
        lightbox.hidden = true;
    });
    document.body.style.overflow = '';
});
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _page(title: str, *body_content) -> HTMLResponse:
    return page_response(
        title,
        Div(*body_content, cls="content"),
        css=_CSS,
        script_srcs=(HTMX_SCRIPT_URL,),
    )


def _robot_page(title: str, *body_content) -> HTMLResponse:
    return page_response(
        title,
        Div(*body_content, Script(_ROBOT_DETAIL_SCRIPT), cls="content robot-page-shell"),
        css=_CSS,
        script_srcs=(HTMX_SCRIPT_URL,),
    )


def _event_topbar(ev: Event, active: str = "", db: Optional[Session] = None) -> Div:
    """Navigation bar shown on every public event page."""
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
    return status_badge(status)


def _get_public_event(event_id: int, db: Session) -> Optional[Event]:
    return db.query(Event).filter(Event.id == event_id).first()


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


def _render_next_up_title(item: dict):
    if item.get("robot1_href"):
        if item.get("robot2_href"):
            return Span(
                A(item["robot1_name"], href=item["robot1_href"], cls="queue-title-link"),
                " vs ",
                A(item["robot2_name"], href=item["robot2_href"], cls="queue-title-link"),
            )
        return Span(
            A(item["robot1_name"], href=item["robot1_href"], cls="queue-title-link"),
            " receives a bye",
        )
    if item.get("href"):
        return A(item["title"], href=item["href"], cls="queue-title-link")
    return Span(item["title"])


def _robot_main_history(robot_id: int, event_id: int, db: Session) -> list[dict]:
    return _load_robot_main_history(robot_id, event_id, db, _phase_long_label)


def _render_overview_panel(ev: Event, db: Session) -> Div:
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

    phase_items = []
    for ph in phases:
        completed = sum(1 for m in ph.matchups if m.status == MatchupStatus.completed)
        total = len(ph.matchups)
        label = f"Qualifying Round {ph.phase_number}" if ph.phase_type == PhaseType.qualifying else "Main Bracket"
        phase_items.append(Li(
            Span(label, style="color:#ccc;"),
            Span(f" - {completed}/{total} fights complete", style="color:#555;font-size:0.85rem;"),
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
            Li(Span("Pending fights: ", style="color:#888;"), str(len(pending_items))),
            style="list-style:none;",
        ),
        style="margin-bottom:1.2rem;",
        cls="card",
    )

    cta = Div(
        A("Find my robot", href=f"/events/{ev.id}/lookup", cls="btn btn-primary"),
        " ",
        A("Leaderboard", href=f"/events/{ev.id}/leaderboard", cls="btn btn-secondary"),
        " ",
        A("Live display", href=f"/events/{ev.id}/live", cls="btn btn-secondary"),
        " ",
        A("Next up board", href=f"/events/{ev.id}/next-up", cls="btn btn-secondary"),
        style="margin-bottom:1.4rem;",
    )

    next_up = Div(
        H2("Next Up"),
        Div(
            *[
                Div(
                    Div(f"Slot {item['slot_index'] + 1}", cls="queue-slot"),
                    Div(item["title"], cls="queue-title"),
                    Div(f"{item['type_label']} · {item['meta']}", cls="queue-meta"),
                    cls="queue-item" + (" current" if index == 0 else ""),
                )
                for index, item in enumerate(pending_items[:3])
            ]
            if pending_items else [P("No pending fights in the run order.", cls="empty")],
            cls="queue-list",
        ),
        cls="card",
    )

    panel_attrs = {"id": "overview-panel", "cls": "auto-panel"}
    if _event_is_live(ev):
        panel_attrs.update(_auto_refresh_attrs(f"/events/{ev.id}/overview-panel"))
        panel_attrs["id"] = "overview-panel"

    return Div(
        H1(ev.event_name),
        P(ev.weight_class, cls="subtitle"),
        cta,
        stats_card,
        next_up,
        phases_section,
        **panel_attrs,
    )


def _render_robot_fights_panel(ev: Event, robot: Robot, db: Session) -> Div:
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
    for m in matchups:
        phase = m.phase
        phase_label = f"Q{phase.phase_number}" if phase.phase_type == PhaseType.qualifying else "Bracket"
        phase_full = _phase_long_label(phase, m)

        if m.robot2_id is None:
            opponent_cell = Span("BYE", style="color:#555;font-style:italic;")
            result_label, result_pts, row_cls = f"BYE ({BYE_POINTS} pts)", str(BYE_POINTS), "fight-row-win"
        else:
            opponent = m.robot2 if m.robot1_id == robot.id else m.robot1
            opponent_cell = A(opponent.robot_name, href=f"/events/{ev.id}/robot/{opponent.id}")
            if m.status == MatchupStatus.completed:
                my_result = next((r for r in m.results if r.robot_id == robot.id), None)
                opp_result = next((r for r in m.results if r.robot_id != robot.id), None)
                my_pts = my_result.points_scored if my_result else 0
                opp_pts = opp_result.points_scored if opp_result else 0
                result_pts = str(my_pts)
                if my_pts > opp_pts:
                    result_label, row_cls = "Win", "fight-row-win"
                elif my_pts < opp_pts:
                    result_label, row_cls = "Loss", "fight-row-loss"
                else:
                    result_label, row_cls = "Draw", "fight-row-draw"
            else:
                result_label, result_pts, row_cls = "Upcoming", "-", "fight-row-pending"

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
        thumb = Div(
            Button(
                Img(
                    src=robot.image_url,
                    cls="robot-detail-photo",
                    alt=robot.robot_name,
                ),
                Span("Tap to expand", cls="robot-detail-photo-hint"),
                cls="robot-detail-photo-button",
                type="button",
                data_lightbox_src=robot.image_url,
                data_lightbox_alt=f"{robot.robot_name} full size image",
                data_lightbox_caption=robot.robot_name,
            ),
            cls="robot-detail-photo-wrap",
        )

    lightbox = ""
    if robot.image_url:
        lightbox = Div(
            Div(
                Button("Close", cls="btn btn-sm robot-lightbox-close", type="button", data_lightbox_close="true"),
                Img(src=robot.image_url, cls="robot-lightbox-image", alt=robot.robot_name),
                P(robot.robot_name, cls="robot-lightbox-caption"),
                cls="robot-lightbox-frame",
            ),
            cls="robot-lightbox",
            hidden=True,
        )

    fights_section = Div(
        Div(
            Table(
                Thead(Tr(Th("Phase"), Th("Opponent"), Th("Pts"), Th("Result"))),
                Tbody(*fight_rows) if fight_rows else Tbody(Tr(Td("No fights scheduled yet.", colspan="4", cls="empty"))),
            ),
            cls="table-wrap",
        ),
        cls="card",
    )

    panel_attrs = {"id": f"robot-panel-{robot.id}", "cls": "auto-panel"}
    if _event_is_live(ev):
        panel_attrs.update(_auto_refresh_attrs(f"/events/{ev.id}/robot/{robot.id}/panel"))
        panel_attrs["id"] = f"robot-panel-{robot.id}"

    return Div(
        A("<- Robot lookup", href=f"/events/{ev.id}/lookup", cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
        Div(
            Div(
                H1(robot.robot_name),
                P(
                    Span(robot.roboteer.roboteer_name, style="color:#888;"),
                    Span(f" · {robot.weapon_type}", style="color:#555;") if robot.weapon_type else "",
                    cls="subtitle",
                ),
                Div(
                    Span(f"{completed_fights} fight(s) played", style="color:#888;font-size:0.88rem;"),
                    " · ",
                    Span(f"{total_points} pts total", style="color:#60a5fa;font-size:0.88rem;font-weight:600;"),
                    style="margin-bottom:0.9rem;",
                ),
                Div(
                    A("Detailed history", href=f"/events/{ev.id}/robot/{robot.id}/history", cls="btn btn-sm btn-secondary"),
                    A("Robot stats", href=f"/events/{ev.id}/robot/{robot.id}/stats", cls="btn btn-sm btn-secondary"),
                    cls="robot-detail-actions",
                ),
                cls="robot-detail-copy",
            ),
            thumb,
            cls="robot-detail-hero",
        ),
        lightbox,
        fights_section,
        **panel_attrs,
    )


def _render_leaderboard_panel(ev: Event, db: Session) -> Div:
    rows = _leaderboard_rows(ev.id, db)
    if not rows or all(row["fights"] == 0 for row in rows):
        body = P("No results yet - check back once fights begin.", cls="empty")
    else:
        table_rows = []
        for i, row in enumerate(rows, start=1):
            rank_cls = f"rank-{i}" if i <= 3 else ""
            robot = row["robot"]
            thumb = Img(src=robot.image_url, cls="robot-thumb", alt=robot.robot_name) if robot.image_url else ""
            table_rows.append(Tr(
                Td(Span(str(i), cls=rank_cls)),
                Td(thumb),
                Td(A(robot.robot_name, href=f"/events/{ev.id}/robot/{robot.id}")),
                Td(row["roboteer"].roboteer_name, style="color:#888;"),
                Td(Span(str(row["total_pts"]), style="font-weight:700;color:#60a5fa;")),
                Td(str(row["wins"])),
                Td(str(row["fights"])),
            ))
        body = Div(
            Table(
                Thead(Tr(Th("#"), Th(""), Th("Robot"), Th("Roboteer"), Th("Pts"), Th("Wins"), Th("Fights"))),
                Tbody(*table_rows),
            ),
            cls="table-wrap",
        )

    panel_attrs = {"id": "leaderboard-panel", "cls": "auto-panel"}
    if _event_is_live(ev):
        panel_attrs.update(_auto_refresh_attrs(f"/events/{ev.id}/leaderboard/panel"))
        panel_attrs["id"] = "leaderboard-panel"

    return Div(
        H1("Leaderboard"),
        P(f"{ev.event_name} · {ev.weight_class}", cls="subtitle"),
        Div(body, cls="card"),
        **panel_attrs,
    )


def _render_bracket_panel(ev: Event, db: Session) -> Div:
    bracket_phase = (
        db.query(Phase)
        .filter(Phase.event_id == ev.id, Phase.phase_type == PhaseType.bracket)
        .first()
    )

    if not bracket_phase:
        content = Div(
            P(
                "The bracket hasn't been drawn yet. It will appear here once qualifying rounds are complete.",
                cls="empty",
            ),
            cls="card",
        )
    else:
        matchups = (
            db.query(Matchup)
            .filter(Matchup.phase_id == bracket_phase.id)
            .order_by(Matchup.bracket_round, Matchup.display_order)
            .all()
        )
        if not matchups:
            content = Div(P("No bracket matchups yet.", cls="empty"), cls="card")
        else:
            rounds: dict[int, list[Matchup]] = {}
            for matchup in matchups:
                rounds.setdefault(matchup.bracket_round or 1, []).append(matchup)
            total_rounds = _total_bracket_rounds(rounds)
            sections = []
            for round_number in sorted(rounds.keys()):
                sections.append(P(_public_bracket_round_label(round_number, total_rounds), cls="round-header"))
                for matchup in rounds[round_number]:
                    sections.append(_bracket_matchup_card(matchup, ev.id))
            content = Div(*sections, cls="card")

    panel_attrs = {"id": "bracket-panel", "cls": "auto-panel"}
    if _event_is_live(ev):
        panel_attrs.update(_auto_refresh_attrs(f"/events/{ev.id}/bracket/panel"))
        panel_attrs["id"] = "bracket-panel"

    return Div(
        H1("Bracket"),
        P(f"{ev.event_name} · {ev.weight_class}", cls="subtitle"),
        content,
        **panel_attrs,
    )


def _render_live_panel(ev: Event, db: Session) -> Div:
    pending_items = _pending_run_order_items(ev.id, db)
    current_item = pending_items[0] if pending_items else None
    leaderboard_rows = _leaderboard_rows(ev.id, db)[:8]

    current_stage = Div(
        Div("Now Fighting", cls="live-kicker"),
        H2(current_item["title"], cls="live-fight-title") if current_item else H2("Awaiting next fight", cls="live-fight-title"),
        P(
            f"{current_item['type_label']} · {current_item['meta']}" if current_item else "No pending fights are currently scheduled.",
            cls="live-fight-subtitle",
        ),
        Div(
            *(
                [
                    Div(
                        Div(current_item["title"].split(" vs ")[0], cls="live-robot-name"),
                        Div(current_item["meta"], cls="live-robot-meta"),
                        cls="live-robot",
                    ),
                    Div("VS", cls="live-vs"),
                    Div(
                        Div(current_item["title"].split(" vs ")[1] if " vs " in current_item["title"] else "BYE", cls="live-robot-name"),
                        Div(current_item["type_label"], cls="live-robot-meta"),
                        cls="live-robot",
                    ),
                ]
                if current_item and " vs " in current_item["title"]
                else [Div(P("The run order is empty right now.", cls="empty"), cls="card")]
            ),
            cls="live-robots",
        ),
        A("Open next-up board", href=f"/events/{ev.id}/next-up", cls="btn btn-secondary", style="margin-top:1rem;display:inline-block;"),
        cls="live-stage",
    )

    queue_items = []
    for index, item in enumerate(pending_items[:5]):
        queue_items.append(Div(
            Div(f"Slot {item['slot_index'] + 1}", cls="queue-slot"),
            Div(item["title"], cls="queue-title"),
            Div(f"{item['type_label']} · {item['meta']}", cls="queue-meta"),
            cls="queue-item" + (" current" if index == 0 else ""),
        ))

    if not queue_items:
        queue_items.append(P("No fights are currently queued.", cls="empty"))

    leaderboard_items = []
    if leaderboard_rows and any(row["fights"] > 0 for row in leaderboard_rows):
        for index, row in enumerate(leaderboard_rows, start=1):
            leaderboard_items.append(Div(
                Div(str(index), cls="leaderboard-mini-rank"),
                Div(
                    Div(row["robot"].robot_name, cls="leaderboard-mini-name"),
                    Div(row["roboteer"].roboteer_name, cls="queue-meta"),
                ),
                Div(str(row["total_pts"]), cls="leaderboard-mini-points"),
                cls="leaderboard-mini-row",
            ))
    else:
        leaderboard_items.append(P("Leaderboard will populate once results are entered.", cls="empty"))

    return Div(
        Div(
            Div(
                H1("Live Display"),
                P(f"{ev.event_name} · auto-refreshing venue screen", cls="subtitle"),
            ),
            A("Public overview", href=f"/events/{ev.id}", cls="btn btn-secondary"),
            cls="board-header",
        ),
        Div(
            current_stage,
            Div(
                Div(H2("Up Next"), Div(*queue_items, cls="queue-list"), cls="card"),
                Div(H2("Leaderboard"), Div(*leaderboard_items), cls="card"),
                cls="live-sidebar",
            ),
            cls="live-grid",
        ),
        id="live-panel",
        **_auto_refresh_attrs(f"/events/{ev.id}/live/panel", interval="15s"),
    )


def _render_next_up_panel(ev: Event, db: Session) -> Div:
    pending_items = _pending_run_order_items(ev.id, db)
    queue = []
    for index, item in enumerate(pending_items[:10]):
        queue.append(Div(
            Div(f"Slot {item['slot_index'] + 1}", cls="queue-slot"),
            Div(_render_next_up_title(item), cls="queue-title"),
            Div(f"{item['type_label']} · {item['meta']}", cls="queue-meta"),
            cls="queue-item" + (" current" if index == 0 else ""),
        ))

    if not queue:
        queue.append(P("No pending fights in the run order.", cls="empty"))

    return Div(
        H1("Next Up Board"),
        P(f"{ev.event_name} · unified fight order", cls="subtitle"),
        Div(*queue, cls="queue-list"),
        id="next-up-panel",
        **_auto_refresh_attrs(f"/events/{ev.id}/next-up/panel"),
    )


def _render_robot_history_panel(ev: Event, robot: Robot, db: Session) -> Div:
    main_history = _robot_main_history(robot.id, ev.id, db)
    sub_history = _robot_sub_event_history(robot.id, ev.id, db)
    items = main_history + sub_history

    panels = []
    for item in items:
        title = A(item["title"], href=item["href"]) if item.get("href") else Span(item["title"], style="font-weight:700;")
        outcome_color = "#4ade80" if item["outcome"] == "Win" else "#f87171" if item["outcome"] == "Loss" else "#fbbf24"
        panels.append(Div(
            Div(
                Span(item["meta"], cls="badge badge-pending"),
                Span(item["kind"].replace("_", " "), style="color:#666;font-size:0.78rem;text-transform:uppercase;letter-spacing:0.06em;"),
                cls="history-meta",
            ),
            Div(title, Span(item["score"], cls="history-score"), cls="history-title"),
            P(item["detail"], style="color:#8d8d8d;margin-top:0.45rem;"),
            P(item["outcome"], style=f"color:{outcome_color};font-weight:700;margin-top:0.55rem;"),
            cls="history-item",
        ))

    if not panels:
        panels.append(P("No completed fight history yet.", cls="empty"))

    panel_attrs = {"id": f"robot-history-panel-{robot.id}", "cls": "auto-panel"}
    if _event_is_live(ev):
        panel_attrs.update(_auto_refresh_attrs(f"/events/{ev.id}/robot/{robot.id}/history/panel"))
        panel_attrs["id"] = f"robot-history-panel-{robot.id}"

    return Div(
        A("<- Back to robot", href=f"/events/{ev.id}/robot/{robot.id}", cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
        H1(f"{robot.robot_name} history"),
        P(f"{robot.roboteer.roboteer_name} · completed results only", cls="subtitle"),
        Div(*panels, cls="stack"),
        **panel_attrs,
    )


def _render_robot_stats_panel(ev: Event, robot: Robot, db: Session) -> Div:
    stats = _robot_stats(robot.id, ev.id, db)
    tiles = [
        ("Main fights", stats["fights"], f"{stats['wins']}W {stats['losses']}L {stats['draws']}D"),
        ("Total points", stats["points"], f"{stats['qualifying_points']} qualifying"),
        ("Bracket points", stats["bracket_points"], f"{stats['byes']} byes"),
        ("Sub-event record", f"{stats['sub_event_wins']}-{stats['sub_event_losses']}", "team results"),
    ]

    h2h_rows = []
    for row in stats["head_to_head_rows"]:
        h2h_rows.append(Tr(
            Td(A(row["opponent"].robot_name, href=f"/events/{ev.id}/robot/{row['opponent'].id}")),
            Td(f"{row['wins']}-{row['losses']}-{row['draws']}"),
            Td(f"{row['points_for']}-{row['points_against']}"),
            Td(str(row["fights"])),
        ))

    h2h_section = Div(
        H2("Performance vs other robots"),
        Div(
            Table(
                Thead(Tr(Th("Opponent"), Th("Record"), Th("Points"), Th("Fights"))),
                Tbody(*h2h_rows) if h2h_rows else Tbody(Tr(Td("No completed 1v1 opponents yet.", colspan="4", cls="empty"))),
            ),
            cls="table-wrap",
        ),
        cls="card",
    )

    panel_attrs = {"id": f"robot-stats-panel-{robot.id}", "cls": "auto-panel"}
    if _event_is_live(ev):
        panel_attrs.update(_auto_refresh_attrs(f"/events/{ev.id}/robot/{robot.id}/stats/panel"))
        panel_attrs["id"] = f"robot-stats-panel-{robot.id}"

    return Div(
        A("<- Back to robot", href=f"/events/{ev.id}/robot/{robot.id}", cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
        H1(f"{robot.robot_name} stats"),
        P(f"{robot.roboteer.roboteer_name} · {ev.event_name}", cls="subtitle"),
        Div(*[
            Div(
                Div(label, cls="stat-label"),
                Div(str(value), cls="stat-value"),
                Div(meta, cls="stat-meta"),
                cls="stat-tile",
            )
            for label, value, meta in tiles
        ], cls="stat-grid card"),
        h2h_section,
        **panel_attrs,
    )


# ---------------------------------------------------------------------------
# 13. Public event overview
# ---------------------------------------------------------------------------


@router.get("/{event_id}", response_class=HTMLResponse)
def event_overview(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()
    return _page(
        ev.event_name,
        _event_topbar(ev, "overview", db=db),
        _render_overview_panel(ev, db),
    )


@router.get("/{event_id}/overview-panel", response_class=HTMLResponse)
def event_overview_panel(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()
    return HTMLResponse(to_xml(_render_overview_panel(ev, db)))


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
    return _robot_page(
        f"{robot.robot_name} — {ev.event_name}",
        _event_topbar(ev, "lookup", db=db),
        _render_robot_fights_panel(ev, robot, db),
    )


@router.get("/{event_id}/robot/{robot_id}/panel", response_class=HTMLResponse)
def robot_fights_panel(event_id: int, robot_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not ev or not robot or not _robot_has_event_history(robot_id, event_id, db):
        return _not_found()
    return HTMLResponse(to_xml(_render_robot_fights_panel(ev, robot, db)))


# ---------------------------------------------------------------------------
# 16. Leaderboard
# ---------------------------------------------------------------------------


@router.get("/{event_id}/leaderboard", response_class=HTMLResponse)
def leaderboard(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()
    return _page(
        f"Leaderboard — {ev.event_name}",
        _event_topbar(ev, "leaderboard", db=db),
        _render_leaderboard_panel(ev, db),
    )


@router.get("/{event_id}/leaderboard/panel", response_class=HTMLResponse)
def leaderboard_panel(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()
    return HTMLResponse(to_xml(_render_leaderboard_panel(ev, db)))


# ---------------------------------------------------------------------------
# 17. Bracket view
# ---------------------------------------------------------------------------


@router.get("/{event_id}/bracket", response_class=HTMLResponse)
def bracket_view(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()
    return _page(
        f"Bracket — {ev.event_name}",
        _event_topbar(ev, "bracket", db=db),
        _render_bracket_panel(ev, db),
    )


@router.get("/{event_id}/bracket/panel", response_class=HTMLResponse)
def bracket_panel(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()
    return HTMLResponse(to_xml(_render_bracket_panel(ev, db)))


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
    qr_image_url = f"/events/{event_id}/qr.svg"

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
                    Img(src=qr_image_url, alt=f"QR code for {ev.event_name}"),
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
# Phase 6 — Enhanced public views
# ---------------------------------------------------------------------------


@router.get("/{event_id}/live", response_class=HTMLResponse)
def live_display(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()
    return _page(
        f"Live Display — {ev.event_name}",
        _event_topbar(ev, "live", db=db),
        _render_live_panel(ev, db),
    )


@router.get("/{event_id}/live/panel", response_class=HTMLResponse)
def live_display_panel(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()
    return HTMLResponse(to_xml(_render_live_panel(ev, db)))


@router.get("/{event_id}/next-up", response_class=HTMLResponse)
def next_up_board(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()
    return _page(
        f"Next Up — {ev.event_name}",
        _event_topbar(ev, "next_up", db=db),
        _render_next_up_panel(ev, db),
    )


@router.get("/{event_id}/next-up/panel", response_class=HTMLResponse)
def next_up_board_panel(event_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    if not ev:
        return _not_found()
    return HTMLResponse(to_xml(_render_next_up_panel(ev, db)))


@router.get("/{event_id}/robot/{robot_id}/history", response_class=HTMLResponse)
def robot_history(event_id: int, robot_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not ev or not robot or not _robot_has_event_history(robot_id, event_id, db):
        return _not_found()
    return _page(
        f"{robot.robot_name} History — {ev.event_name}",
        _event_topbar(ev, "lookup", db=db),
        _render_robot_history_panel(ev, robot, db),
    )


@router.get("/{event_id}/robot/{robot_id}/history/panel", response_class=HTMLResponse)
def robot_history_panel(event_id: int, robot_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not ev or not robot or not _robot_has_event_history(robot_id, event_id, db):
        return _not_found()
    return HTMLResponse(to_xml(_render_robot_history_panel(ev, robot, db)))


@router.get("/{event_id}/robot/{robot_id}/stats", response_class=HTMLResponse)
def robot_stats(event_id: int, robot_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not ev or not robot or not _robot_has_event_history(robot_id, event_id, db):
        return _not_found()
    return _page(
        f"{robot.robot_name} Stats — {ev.event_name}",
        _event_topbar(ev, "lookup", db=db),
        _render_robot_stats_panel(ev, robot, db),
    )


@router.get("/{event_id}/robot/{robot_id}/stats/panel", response_class=HTMLResponse)
def robot_stats_panel(event_id: int, robot_id: int, db: Session = Depends(get_db)):
    ev = _get_public_event(event_id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not ev or not robot or not _robot_has_event_history(robot_id, event_id, db):
        return _not_found()
    return HTMLResponse(to_xml(_render_robot_stats_panel(ev, robot, db)))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _not_found() -> HTMLResponse:
    response = page_response(
        "Not Found",
        Div(
            H1("Event not found"),
            P("This event doesn't exist or may have been removed.", style="color:#888;"),
            A("<- Home", href="/", style="color:#60a5fa;"),
            cls="content",
            style="padding-top:3rem;text-align:center;",
        ),
        css=_CSS,
        script_srcs=(HTMX_SCRIPT_URL,),
    )
    response.status_code = 404
    return response


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

