"""Organizer-only admin routes — Phase 4 & 5: Event Management, Import, Matching & Scoring."""

import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fasthtml.common import (
    A,
    Body,
    Button,
    Div,
    H1,
    H2,
    H3,
    Head,
    Header,
    Html,
    Img,
    Input,
    Label,
    Li,
    Meta,
    Nav,
    NotStr,
    Option,
    P,
    Script,
    Select,
    Small,
    Span,
    Strong,
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
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_valid_access_token, require_organizer
from config import UPLOAD_DIR
from database import get_db
from google_sheets import fetch_sheet_rows, parse_robot_registrations
from matching import (
    advance_bracket_round,
    advance_sub_event_bracket,
    create_bracket,
    create_qualifying_round,
    create_sub_event_bracket,
    get_active_robot_ids,
    get_qualifying_bye_counts,
    get_sub_event_eligible_robots,
    qualifying_standings,
)
from models import (
    Event,
    EventRobot,
    EventStatus,
    ImageSource,
    Matchup,
    MatchupStatus,
    Phase,
    PhaseStatus,
    PhaseType,
    Result,
    Robot,
    Roboteer,
    RobotRetirement,
    RunOrder,
    RunOrderMatchupType,
    SubEvent,
    SubEventFormat,
    SubEventMatchup,
    SubEventStatus,
    SubEventTeam,
    User,
)
from scoring import BYE_POINTS, FIGHT_OUTCOMES, outcome_to_points, points_to_outcome_label

router = APIRouter(prefix="/admin")

# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
/* Phase 5 extras */
.matchup-list { list-style: none; }
.matchup-item {
    display: flex; align-items: center; gap: 0.75rem;
    padding: 0.6rem 0.75rem;
    border: 1px solid #2a2a2a; border-radius: 6px;
    margin-bottom: 0.4rem; background: #1a1a1a;
    cursor: default;
}
.matchup-item.is-bye { opacity: 0.65; }
.drag-handle { cursor: grab; color: #444; font-size: 1.1rem; flex-shrink: 0; }
.matchup-robots { flex: 1; font-size: 0.9rem; }
.matchup-vs { color: #555; margin: 0 0.4rem; font-size: 0.8rem; }
.matchup-result-label { font-size: 0.8rem; color: #4ade80; margin-left: auto; white-space: nowrap; }
.matchup-result-pending { font-size: 0.8rem; color: #555; margin-left: auto; white-space: nowrap; }
.bracket-round-header {
    font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.06em; color: #666; padding: 0.4rem 0;
    border-bottom: 1px solid #252525; margin: 1rem 0 0.6rem;
}
.bracket-matchup {
    display: flex; align-items: stretch;
    border: 1px solid #2a2a2a; border-radius: 6px;
    margin-bottom: 0.4rem; overflow: hidden;
}
.bracket-matchup-robots { flex: 1; }
.bracket-robot-row {
    display: flex; align-items: center; padding: 0.35rem 0.75rem;
    font-size: 0.88rem; gap: 0.5rem;
}
.bracket-robot-row + .bracket-robot-row { border-top: 1px solid #222; }
.bracket-robot-winner { background: #0f2a18; }
.bracket-robot-pts { margin-left: auto; font-weight: 700; font-size: 0.85rem; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #111;
    color: #f0f0f0;
    min-height: 100vh;
}
a { color: #60a5fa; text-decoration: none; }
a:hover { text-decoration: underline; }
.topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 2rem;
    border-bottom: 1px solid #2a2a2a;
    background: #161616;
}
.topbar-title { font-size: 1.2rem; font-weight: 700; color: #f0f0f0; }
.topbar-right { display: flex; align-items: center; gap: 1.5rem; font-size: 0.85rem; color: #888; }
.logout { color: #666; font-size: 0.85rem; }
.logout:hover { color: #f0f0f0; text-decoration: none; }
.content { padding: 2rem; max-width: 1100px; margin: 0 auto; }
h1 { font-size: 1.7rem; margin-bottom: 1.5rem; }
h2 { font-size: 1.2rem; margin-bottom: 1rem; }
h3 { font-size: 1rem; font-weight: 600; margin-bottom: 0.75rem; }
.card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
}
.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
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
.btn-primary { background: #3b82f6; color: #fff; }
.btn-secondary { background: #2f2f2f; color: #ccc; border: 1px solid #3a3a3a; }
.btn-danger  { background: #ef4444; color: #fff; }
.btn-warning { background: #f59e0b; color: #111; }
.btn-success { background: #22c55e; color: #111; }
.btn-sm { padding: 0.3rem 0.7rem; font-size: 0.78rem; }
/* Forms */
.form-group { margin-bottom: 1.2rem; }
.form-group label { display: block; font-size: 0.85rem; color: #aaa; margin-bottom: 0.35rem; }
.form-control {
    width: 100%;
    background: #111;
    border: 1px solid #333;
    border-radius: 6px;
    color: #f0f0f0;
    padding: 0.5rem 0.75rem;
    font-size: 0.9rem;
}
.form-control:focus { outline: none; border-color: #3b82f6; }
select.form-control { cursor: pointer; }
/* Tables */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
th { text-align: left; padding: 0.6rem 0.9rem; color: #888; font-weight: 600;
     border-bottom: 1px solid #2a2a2a; white-space: nowrap; }
td { padding: 0.55rem 0.9rem; border-bottom: 1px solid #1e1e1e; vertical-align: middle; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #1e1e1e; }
/* Status badges */
.badge {
    display: inline-block;
    padding: 0.2rem 0.55rem;
    border-radius: 99px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}
.badge-setup       { background: #1f2937; color: #9ca3af; }
.badge-registration{ background: #1e3a5f; color: #60a5fa; }
.badge-qualifying  { background: #1a3a26; color: #4ade80; }
.badge-bracket     { background: #3b1a5f; color: #c084fc; }
.badge-sub_events  { background: #3a2a10; color: #fcd34d; }
.badge-complete    { background: #1a3a1a; color: #86efac; }
.badge-reserve     { background: #292929; color: #a78bfa; }
.badge-pending     { background: #292929; color: #9ca3af; }
.badge-active      { background: #1a3a26; color: #4ade80; }
/* Robot image thumbnails */
.robot-thumb { width: 40px; height: 40px; object-fit: cover; border-radius: 4px; }
/* Empty state */
.empty { color: #555; font-size: 0.9rem; padding: 1.5rem 0; text-align: center; }
/* Inline form (for small action buttons inside table rows) */
.inline-form { display: inline; }
/* Alert / flash messages */
.alert {
    padding: 0.75rem 1rem;
    border-radius: 6px;
    margin-bottom: 1.2rem;
    font-size: 0.9rem;
}
.alert-error   { background: #3b1010; border: 1px solid #ef4444; color: #fca5a5; }
.alert-success { background: #0f2f1a; border: 1px solid #22c55e; color: #86efac; }
.alert-info    { background: #1e2f4a; border: 1px solid #3b82f6; color: #93c5fd; }
/* Preview table specifics */
.preview-status-new { color: #4ade80; font-size: 0.8rem; }
.preview-status-dup { color: #f59e0b; font-size: 0.8rem; }
/* Spinner */
.htmx-indicator { display: none; }
.htmx-request .htmx-indicator { display: inline; }
"""

# ---------------------------------------------------------------------------
# Shared page builder
# ---------------------------------------------------------------------------

_NEXT_STATUS: dict[EventStatus, EventStatus] = {
    EventStatus.setup: EventStatus.registration,
    EventStatus.registration: EventStatus.qualifying,
    EventStatus.qualifying: EventStatus.bracket,
    EventStatus.bracket: EventStatus.sub_events,
    EventStatus.sub_events: EventStatus.complete,
}

_TRANSITION_LABELS: dict[EventStatus, str] = {
    EventStatus.setup: "Begin Registration",
    EventStatus.registration: "Start Qualifying",
    EventStatus.qualifying: "Close Qualifying → Bracket",
    EventStatus.bracket: "Move to Sub-events",
    EventStatus.sub_events: "Complete Event",
}


def _status_badge(status: EventStatus) -> Span:
    return Span(status.value, cls=f"badge badge-{status.value}")


def _topbar(user: User) -> Header:
    return Header(
        Span("⚙ BitBT Admin", cls="topbar-title"),
        Div(
            Span(f"{user.name} ({user.email})"),
            A("Sign out", href="/auth/logout", cls="logout"),
            cls="topbar-right",
        ),
        cls="topbar",
    )


def _page(title: str, *body_content, user: Optional[User] = None) -> HTMLResponse:
    htmx = Script(src="https://unpkg.com/htmx.org@1.9.12")
    head = Head(
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Title(f"{title} — BitBT"),
        Style(_CSS),
        htmx,
    )
    body_children = []
    if user:
        body_children.append(_topbar(user))
    body_children.append(Div(*body_content, cls="content"))
    return HTMLResponse(to_xml(Html(head, Body(*body_children))))


# ---------------------------------------------------------------------------
# 1. Dashboard — list of events
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    msg: str = Query(default=""),
):
    """Organizer dashboard — shows all events."""
    events = db.query(Event).filter(Event.organizer_id == user.id).order_by(Event.created_at.desc()).all()

    flash = ""
    if msg == "created":
        flash = Div("Event created successfully.", cls="alert alert-success")
    elif msg == "deleted":
        flash = Div("Event removed.", cls="alert alert-info")

    if events:
        rows = []
        for ev in events:
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
            rows.append(
                Tr(
                    Td(A(ev.event_name, href=f"/admin/events/{ev.id}")),
                    Td(ev.weight_class),
                    Td(_status_badge(ev.status)),
                    Td(f"{active_count} (+{reserve_count} reserve)"),
                    Td(
                        A("Manage", href=f"/admin/events/{ev.id}", cls="btn btn-sm btn-secondary"),
                        " ",
                        A("Import", href=f"/admin/events/{ev.id}/import", cls="btn btn-sm btn-primary"),
                    ),
                )
            )
        events_table = Div(
            Table(
                Thead(Tr(Th("Event"), Th("Weight Class"), Th("Status"), Th("Robots"), Th("Actions"))),
                Tbody(*rows),
            ),
            cls="table-wrap",
        )
    else:
        events_table = P("No events yet. Create your first event below.", cls="empty")

    page = Div(
        H1("Dashboard"),
        flash if flash else "",
        Div(
            Div(
                H2("Events"),
                A("+ New Event", href="/admin/events/new", cls="btn btn-primary btn-sm"),
                cls="card-header",
            ),
            events_table,
            cls="card",
        ),
    )
    return _page("Dashboard", page, user=user)


# ---------------------------------------------------------------------------
# 2. Event creation
# ---------------------------------------------------------------------------


@router.get("/events/new", response_class=HTMLResponse)
def new_event_form(
    request: Request,
    user: User = Depends(require_organizer),
    error: str = Query(default=""),
):
    err_el = Div(error, cls="alert alert-error") if error else ""
    form = Div(
        H1("New Event"),
        err_el if err_el else "",
        Div(
            HForm(
                Div(
                    Label("Event Name", for_="event_name"),
                    Input(
                        type="text",
                        id="event_name",
                        name="event_name",
                        cls="form-control",
                        placeholder="e.g. Steel City Smashdown 2026",
                        required=True,
                        autofocus=True,
                    ),
                    cls="form-group",
                ),
                Div(
                    Label("Weight Class", for_="weight_class"),
                    Input(
                        type="text",
                        id="weight_class",
                        name="weight_class",
                        cls="form-control",
                        placeholder="e.g. Beetleweight (150g)",
                        required=True,
                    ),
                    cls="form-group",
                ),
                Div(
                    Label("Google Sheet URL (optional — can be set later)", for_="google_sheet_url"),
                    Input(
                        type="url",
                        id="google_sheet_url",
                        name="google_sheet_url",
                        cls="form-control",
                        placeholder="https://docs.google.com/spreadsheets/d/...",
                    ),
                    cls="form-group",
                ),
                Div(
                    Button("Create Event", type="submit", cls="btn btn-primary"),
                    " ",
                    A("Cancel", href="/admin/", cls="btn btn-secondary"),
                    cls="form-group",
                ),
                method="post",
                action="/admin/events",
            ),
            cls="card",
        ),
    )
    return _page("New Event", form, user=user)


@router.post("/events")
def create_event(
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    event_name: str = Form(...),
    weight_class: str = Form(...),
    google_sheet_url: str = Form(default=""),
):
    event_name = event_name.strip()
    weight_class = weight_class.strip()
    google_sheet_url = google_sheet_url.strip() or None

    if not event_name or not weight_class:
        return RedirectResponse("/admin/events/new?error=Name+and+weight+class+are+required", status_code=303)

    ev = Event(
        event_name=event_name,
        weight_class=weight_class,
        google_sheet_url=google_sheet_url,
        organizer_id=user.id,
        status=EventStatus.setup,
    )
    db.add(ev)
    db.commit()
    return RedirectResponse(f"/admin/events/{ev.id}?msg=created", status_code=303)


# ---------------------------------------------------------------------------
# 3. Event detail / management dashboard
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_detail(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    msg: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)

    # Flash message
    flash_map = {
        "created": ("Event created.", "success"),
        "imported": ("Robots imported successfully.", "success"),
        "refreshed": ("Sheet refreshed — new robots imported.", "success"),
        "removed": ("Robot removed from roster.", "info"),
        "added": ("Robot added to roster.", "success"),
        "retired": ("Robot retired and replaced by reserve.", "success"),
        "image_updated": ("Robot image updated.", "success"),
        "transitioned": ("Event status updated.", "success"),
        "reserve_toggled": ("Reserve status updated.", "info"),
        "reserve_moved": ("Reserve order updated.", "info"),
        "round_generated": ("Qualifying round generated.", "success"),
        "round_complete": ("Round marked complete.", "success"),
        "scored": ("Fight result saved.", "success"),
        "score_cleared": ("Fight result cleared.", "info"),
        "bracket_generated": ("Bracket generated — top robots seeded.", "success"),
        "bracket_advanced": ("Bracket advanced to next round.", "success"),
        "bracket_swapped": ("Bracket pairings swapped.", "success"),
        "sub_event_created": ("Sub-event created.", "success"),
        "sub_event_bracket_generated": ("Sub-event bracket generated.", "success"),
        "sub_event_bracket_advanced": ("Sub-event bracket advanced.", "success"),
        "se_scored": ("Sub-event fight result saved.", "success"),
        "se_score_cleared": ("Sub-event fight result cleared.", "info"),
        "team_created": ("Team created.", "success"),
        "team_deleted": ("Team removed.", "info"),
    }
    flash = ""
    if msg in flash_map:
        text, kind = flash_map[msg]
        flash = Div(text, cls=f"alert alert-{kind}")

    # Active robots and reserves
    active_ers = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == False)
        .join(Robot)
        .order_by(Robot.robot_name)
        .all()
    )
    reserve_ers = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == True)
        .order_by(EventRobot.reserve_order.asc().nullslast(), EventRobot.id)
        .all()
    )

    # Phases
    phases = db.query(Phase).filter(Phase.event_id == event_id).order_by(Phase.phase_number).all()

    # --- Event header card ---
    next_status = _NEXT_STATUS.get(ev.status)
    transition_btn = ""
    if next_status:
        transition_btn = HForm(
            Button(
                _TRANSITION_LABELS[ev.status],
                type="submit",
                cls="btn btn-warning btn-sm",
            ),
            method="post",
            action=f"/admin/events/{event_id}/transition",
            style="display:inline;",
        )

    sheet_info = Small(
        f"Sheet: {ev.google_sheet_url or 'not set'}", style="color:#666;"
    )
    header_card = Div(
        Div(
            Div(
                H2(ev.event_name),
                Small(ev.weight_class, style="color:#888;margin-left:0.6rem;"),
            ),
            Div(
                _status_badge(ev.status),
                " ",
                transition_btn,
                " ",
                A("Import / Refresh Robots", href=f"/admin/events/{event_id}/import", cls="btn btn-sm btn-primary"),
                style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap;",
            ),
            cls="card-header",
        ),
        sheet_info,
        cls="card",
    )

    # --- Active robots table ---
    if active_ers:
        robot_rows = [_robot_roster_row(er, event_id, phases, is_reserve=False) for er in active_ers]
        robot_table = Div(
            Table(
                Thead(Tr(
                    Th(""), Th("Robot"), Th("Roboteer"), Th("Weapon"), Th("Actions"),
                )),
                Tbody(*robot_rows),
            ),
            cls="table-wrap",
        )
    else:
        robot_table = P("No active robots yet.", cls="empty")

    active_card = Div(
        Div(
            H2(f"Active Robots ({len(active_ers)})"),
            A("+ Add Robot", href=f"/admin/events/{event_id}/robots/add", cls="btn btn-sm btn-secondary"),
            cls="card-header",
        ),
        robot_table,
        cls="card",
    )

    # --- Reserves table ---
    if reserve_ers:
        reserve_rows = [_robot_roster_row(er, event_id, phases, is_reserve=True, position=i) for i, er in enumerate(reserve_ers)]
        reserve_table = Div(
            Table(
                Thead(Tr(Th("Order"), Th(""), Th("Robot"), Th("Roboteer"), Th("Weapon"), Th("Actions"))),
                Tbody(*reserve_rows),
            ),
            cls="table-wrap",
        )
    else:
        reserve_table = P("No reserves designated.", cls="empty")

    reserves_card = Div(
        Div(
            H2(f"Reserve Robots ({len(reserve_ers)})"),
            cls="card-header",
        ),
        reserve_table,
        cls="card",
    )

    # --- Phases card ---
    # ---- Phase 5: qualifying actions / bracket generation ----
    qual_phases = [ph for ph in phases if ph.phase_type == PhaseType.qualifying]
    bracket_phase = next((ph for ph in phases if ph.phase_type == PhaseType.bracket), None)
    num_complete_qual = sum(1 for ph in qual_phases if ph.status == PhaseStatus.complete)

    phase_actions = []
    if ev.status == EventStatus.qualifying:
        max_qual = max((ph.phase_number for ph in qual_phases), default=0)
        last_qual = next((ph for ph in qual_phases if ph.phase_number == max_qual), None)
        last_all_done = last_qual is not None and all(
            m.status == MatchupStatus.completed for m in last_qual.matchups
        )
        if last_qual is None or (last_qual.status == PhaseStatus.complete and max_qual < 3):
            next_round = max_qual + 1
            phase_actions.append(
                HForm(
                    Button(f"Generate Round {next_round}", type="submit", cls="btn btn-primary btn-sm"),
                    method="post",
                    action=f"/admin/events/{event_id}/qualifying/generate",
                    style="display:inline;",
                )
            )
        if last_qual and last_all_done and last_qual.status == PhaseStatus.active:
            phase_actions.append(
                HForm(
                    Button(f"Complete Round {max_qual}", type="submit", cls="btn btn-success btn-sm"),
                    method="post",
                    action=f"/admin/events/{event_id}/phases/{last_qual.id}/complete",
                    style="display:inline;",
                )
            )
        if num_complete_qual >= 3 and not bracket_phase:
            phase_actions.append(
                HForm(
                    Button("Generate Bracket (Top 16)", type="submit", cls="btn btn-warning btn-sm"),
                    method="post",
                    action=f"/admin/events/{event_id}/bracket/generate",
                    style="display:inline;",
                )
            )

    if phases:
        phase_rows = []
        for ph in phases:
            total_m = len(ph.matchups)
            done_m = sum(1 for m in ph.matchups if m.status == MatchupStatus.completed)
            if ph.phase_type == PhaseType.qualifying:
                label = f"Qualifying Round {ph.phase_number}"
                manage_link = A("Manage", href=f"/admin/events/{event_id}/phases/{ph.id}", cls="btn btn-sm btn-secondary")
            else:
                label = "Bracket"
                manage_link = A("Manage Bracket", href=f"/admin/events/{event_id}/bracket", cls="btn btn-sm btn-secondary")
            phase_rows.append(Tr(
                Td(label),
                Td(Span(ph.status.value, cls=f"badge badge-{ph.status.value}")),
                Td(f"{done_m}/{total_m}"),
                Td(manage_link),
            ))
        phases_table = Div(
            Table(
                Thead(Tr(Th("Phase"), Th("Status"), Th("Fights"), Th(""))),
                Tbody(*phase_rows),
            ),
            cls="table-wrap",
        )
    else:
        phases_table = P(
            "No phases yet. Transition to \"Qualifying\" to generate Round 1.",
            cls="empty",
        )

    phases_card = Div(
        Div(
            H2("Phases"),
            Div(*[act for act in phase_actions], style="display:flex;gap:0.5rem;flex-wrap:wrap;") if phase_actions else "",
            cls="card-header",
        ),
        phases_table,
        cls="card",
    )

    # --- Sub-events card ---
    sub_events = (
        db.query(SubEvent)
        .filter(SubEvent.event_id == event_id)
        .order_by(SubEvent.id)
        .all()
    )

    # Show "Create Sub-event" button when bracket round 1 is complete (or event in sub_events)
    r1_done = False
    if bracket_phase:
        r1_matchups = [m for m in bracket_phase.matchups if m.bracket_round == 1]
        r1_done = bool(r1_matchups) and all(m.status == MatchupStatus.completed for m in r1_matchups)

    can_create_sub_event = r1_done or ev.status in (EventStatus.sub_events, EventStatus.complete)

    se_actions = []
    if can_create_sub_event:
        se_actions.append(
            A("+ New Sub-event", href=f"/admin/events/{event_id}/sub-events/new", cls="btn btn-sm btn-primary")
        )
    se_actions.append(
        A("Run Order", href=f"/admin/events/{event_id}/run-order", cls="btn btn-sm btn-secondary")
    )

    if sub_events:
        se_rows = []
        for se in sub_events:
            team_count = db.query(SubEventTeam).filter(SubEventTeam.sub_event_id == se.id).count()
            se_rows.append(Tr(
                Td(se.name),
                Td(se.format.value),
                Td(Span(se.status.value, cls=f"badge badge-{se.status.value}")),
                Td(f"{team_count} team(s)"),
                Td(A("Manage", href=f"/admin/events/{event_id}/sub-events/{se.id}", cls="btn btn-sm btn-secondary")),
            ))
        se_table = Div(
            Table(
                Thead(Tr(Th("Name"), Th("Format"), Th("Status"), Th("Teams"), Th(""))),
                Tbody(*se_rows),
            ),
            cls="table-wrap",
        )
    else:
        se_table = P(
            "No sub-events yet." + (" Create one once bracket round 1 is complete." if not can_create_sub_event else ""),
            cls="empty",
        )

    sub_events_card = Div(
        Div(
            H2("Sub-events"),
            Div(*se_actions, style="display:flex;gap:0.5rem;"),
            cls="card-header",
        ),
        se_table,
        cls="card",
    )

    page = Div(
        A("← Dashboard", href="/admin/", cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
        flash if flash else "",
        header_card,
        active_card,
        reserves_card,
        phases_card,
        sub_events_card,
    )
    return _page(ev.event_name, page, user=user)


def _robot_roster_row(
    er: EventRobot,
    event_id: int,
    phases: list,
    is_reserve: bool,
    position: int = 0,
) -> Tr:
    robot: Robot = er.robot
    reer: Roboteer = robot.roboteer

    thumb = ""
    if robot.image_url:
        thumb = Img(src=robot.image_url, cls="robot-thumb", alt=robot.robot_name)

    # Actions
    actions = [
        A("Image", href=f"/admin/events/{event_id}/robots/{robot.id}/upload-image", cls="btn btn-sm btn-secondary"),
        " ",
    ]

    if is_reserve:
        actions += [
            _inline_post_btn(f"/admin/events/{event_id}/robots/{er.id}/unset-reserve", "→ Active", "btn-sm btn-secondary"),
            " ",
            _inline_post_btn(f"/admin/events/{event_id}/robots/{er.id}/move-reserve/up", "↑", "btn-sm btn-secondary"),
            " ",
            _inline_post_btn(f"/admin/events/{event_id}/robots/{er.id}/move-reserve/down", "↓", "btn-sm btn-secondary"),
            " ",
        ]
    else:
        actions += [
            _inline_post_btn(f"/admin/events/{event_id}/robots/{er.id}/set-reserve", "→ Reserve", "btn-sm btn-secondary"),
            " ",
        ]
        if phases:
            actions += [
                A(
                    "Retire",
                    href=f"/admin/events/{event_id}/robots/{er.id}/retire",
                    cls="btn btn-sm btn-warning",
                ),
                " ",
            ]

    actions.append(
        _inline_post_btn(f"/admin/events/{event_id}/robots/{er.id}/remove", "Remove", "btn-sm btn-danger"),
    )

    cells = [
        Td(thumb),
        Td(robot.robot_name),
        Td(reer.roboteer_name),
        Td(robot.weapon_type or "—"),
        Td(*actions),
    ]
    if is_reserve:
        cells = [Td(str(position + 1))] + cells
    return Tr(*cells)


def _inline_post_btn(action_url: str, label: str, extra_cls: str = "") -> HForm:
    """Small single-button form for POST actions (renders as inline element)."""
    return HForm(
        Button(label, type="submit", cls=f"btn {extra_cls}"),
        method="post",
        action=action_url,
        style="display:inline;",
    )


# ---------------------------------------------------------------------------
# 4. Google Sheets import interface
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/import", response_class=HTMLResponse)
def import_page(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    error: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)

    err_el = Div(error, cls="alert alert-error") if error else ""

    sheet_url_field = Div(
        Label("Google Sheet URL", for_="sheet_url"),
        Input(
            type="url",
            id="sheet_url",
            name="sheet_url",
            cls="form-control",
            value=ev.google_sheet_url or "",
            placeholder="https://docs.google.com/spreadsheets/d/...",
            style="margin-bottom:0.75rem;",
        ),
        cls="form-group",
    )

    preview_trigger = Div(
        Button(
            "Load Preview",
            type="button",
            cls="btn btn-secondary",
            hx_get=f"/admin/events/{event_id}/import/preview",
            hx_include="#sheet_url",
            hx_target="#preview-area",
            hx_indicator="#preview-spinner",
        ),
        Span(" Loading…", id="preview-spinner", cls="htmx-indicator", style="color:#888;font-size:0.85rem;"),
        style="margin-bottom:1rem;",
    )

    page = Div(
        A("← Event", href=f"/admin/events/{event_id}", cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
        H1(f"Import Robots — {ev.event_name}"),
        err_el if err_el else "",
        Div(
            P(
                "Fetch robot registrations from your Google Sheet. "
                "Select the rows to import and optionally mark any as reserves.",
                style="color:#888;font-size:0.9rem;margin-bottom:1rem;",
            ),
            sheet_url_field,
            preview_trigger,
            Div(id="preview-area"),
            cls="card",
        ),
    )
    return _page("Import Robots", page, user=user)


@router.get("/events/{event_id}/import/preview", response_class=HTMLResponse)
def import_preview(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    sheet_url: str = Query(default=""),
):
    """HTMX endpoint — returns the preview table fragment for the import page."""
    ev = _get_event_or_404(event_id, user.id, db)

    if not sheet_url:
        return HTMLResponse(to_xml(Div(
            P("Please enter a Google Sheet URL above.", cls="alert alert-error"),
        )))

    try:
        access_token = get_valid_access_token(user, db)
        rows = fetch_sheet_rows(sheet_url, access_token)
    except ValueError as exc:
        return HTMLResponse(to_xml(Div(
            P(f"Error: {exc}", cls="alert alert-error"),
        )))
    except Exception as exc:
        return HTMLResponse(to_xml(Div(
            P(f"Could not fetch sheet: {exc}", cls="alert alert-error"),
        )))

    if not rows:
        return HTMLResponse(to_xml(Div(
            P("Sheet is empty or has no data rows.", cls="alert alert-info"),
        )))

    from google_sheets import _extract_sheet_id
    try:
        sheet_id = _extract_sheet_id(sheet_url)
    except ValueError:
        sheet_id = sheet_url

    registrations = parse_robot_registrations(rows, sheet_id)

    if not registrations:
        return HTMLResponse(to_xml(Div(
            P(
                "No valid robot registrations found. "
                "The sheet must have 'Roboteer Name' and 'Robot Name' columns.",
                cls="alert alert-info",
            ),
        )))

    # Determine which sheet_row_ids already exist in the DB
    existing_row_ids = {
        r.sheet_row_id
        for r in db.query(Robot).filter(Robot.sheet_row_id != None).all()
        if r.sheet_row_id
    }

    # Which are already on this event's roster
    event_robot_sheet_ids: set[str] = set()
    for er in db.query(EventRobot).filter(EventRobot.event_id == event_id).all():
        robot = db.query(Robot).filter(Robot.id == er.robot_id).first()
        if robot and robot.sheet_row_id:
            event_robot_sheet_ids.add(robot.sheet_row_id)

    table_rows = []
    for reg in registrations:
        row_id = reg["sheet_row_id"]
        in_event = row_id in event_robot_sheet_ids

        if in_event:
            status_el = Span("already in event", cls="preview-status-dup")
        elif row_id in existing_row_ids:
            status_el = Span("robot exists (will link)", cls="preview-status-dup")
        else:
            status_el = Span("new", cls="preview-status-new")

        table_rows.append(Tr(
            Td(
                Input(
                    type="checkbox",
                    name="row_ids",
                    value=row_id,
                    checked=not in_event,
                    **({"disabled": True} if in_event else {}),
                ),
            ),
            Td(Input(type="checkbox", name="reserve_ids", value=row_id)),
            Td(reg["roboteer_name"]),
            Td(reg["robot_name"]),
            Td(reg.get("weapon_type") or "—"),
            Td(
                reg.get("image_url") or "—",
                style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;",
            ),
            Td(status_el),
        ))

    fragment = HForm(
        P(
            f"{len(registrations)} registrations found. "
            "Check rows to import; tick 'Reserve' to designate as a reserve robot.",
            style="color:#888;font-size:0.85rem;margin-bottom:0.75rem;",
        ),
        Input(type="hidden", name="sheet_url", value=sheet_url),
        Div(
            Table(
                Thead(Tr(
                    Th("Import"),
                    Th("Reserve"),
                    Th("Roboteer"),
                    Th("Robot"),
                    Th("Weapon"),
                    Th("Image URL"),
                    Th("Status"),
                )),
                Tbody(*table_rows),
            ),
            cls="table-wrap",
            style="margin-bottom:1rem;",
        ),
        Div(
            Button("Import Selected", type="submit", cls="btn btn-primary"),
            style="margin-top:0.5rem;",
        ),
        method="post",
        action=f"/admin/events/{event_id}/import",
    )
    return HTMLResponse(to_xml(fragment))


@router.post("/events/{event_id}/import")
def do_import(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    sheet_url: str = Form(...),
    row_ids: list[str] = Form(default=[]),
    reserve_ids: list[str] = Form(default=[]),
):
    ev = _get_event_or_404(event_id, user.id, db)

    if not row_ids:
        return RedirectResponse(
            f"/admin/events/{event_id}/import?error=No+robots+selected", status_code=303
        )

    if not ev.google_sheet_url and sheet_url:
        ev.google_sheet_url = sheet_url
        db.add(ev)

    try:
        access_token = get_valid_access_token(user, db)
        rows = fetch_sheet_rows(sheet_url, access_token)
    except Exception as exc:
        return RedirectResponse(
            f"/admin/events/{event_id}/import?error={str(exc)[:80]}", status_code=303
        )

    from google_sheets import _extract_sheet_id
    try:
        sheet_id = _extract_sheet_id(sheet_url)
    except ValueError:
        sheet_id = sheet_url

    registrations = parse_robot_registrations(rows, sheet_id)
    selected = {r["sheet_row_id"]: r for r in registrations if r["sheet_row_id"] in row_ids}

    max_res = (
        db.query(EventRobot.reserve_order)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == True)
        .order_by(EventRobot.reserve_order.desc().nullslast())
        .first()
    )
    next_reserve_order = (max_res[0] or 0) + 1 if max_res else 1

    for row_id in row_ids:
        reg = selected.get(row_id)
        if not reg:
            continue

        is_res = row_id in reserve_ids

        # Upsert Roboteer
        roboteer = (
            db.query(Roboteer)
            .filter(Roboteer.roboteer_name == reg["roboteer_name"])
            .first()
        )
        if not roboteer:
            roboteer = Roboteer(
                roboteer_name=reg["roboteer_name"],
                contact_email=reg.get("contact_email"),
                imported_from_sheet_id=sheet_id,
            )
            db.add(roboteer)
            db.flush()

        # Upsert Robot (by sheet_row_id to prevent duplicates)
        robot = (
            db.query(Robot)
            .filter(Robot.sheet_row_id == row_id)
            .first()
        )
        if not robot:
            robot = Robot(
                robot_name=reg["robot_name"],
                roboteer_id=roboteer.id,
                weapon_type=reg.get("weapon_type"),
                sheet_row_id=row_id,
                image_source=ImageSource.none,
            )
            db.add(robot)
            db.flush()

            if reg.get("image_url"):
                _try_import_image(robot, reg["image_url"])

        # Add to event roster if not already present
        existing_er = (
            db.query(EventRobot)
            .filter(EventRobot.event_id == event_id, EventRobot.robot_id == robot.id)
            .first()
        )
        if not existing_er:
            res_order = next_reserve_order if is_res else None
            if is_res:
                next_reserve_order += 1
            db.add(EventRobot(
                event_id=event_id,
                robot_id=robot.id,
                is_reserve=is_res,
                reserve_order=res_order,
            ))

    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}?msg=imported", status_code=303)


# ---------------------------------------------------------------------------
# 5. Refresh from sheet
# ---------------------------------------------------------------------------


@router.post("/events/{event_id}/refresh-sheet")
def refresh_sheet(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    """Re-fetch the Google Sheet and import any new rows (skips existing)."""
    ev = _get_event_or_404(event_id, user.id, db)

    if not ev.google_sheet_url:
        return RedirectResponse(
            f"/admin/events/{event_id}/import?error=No+sheet+URL+set.+Set+one+in+the+import+page.",
            status_code=303,
        )

    try:
        access_token = get_valid_access_token(user, db)
        rows = fetch_sheet_rows(ev.google_sheet_url, access_token)
    except Exception as exc:
        return RedirectResponse(
            f"/admin/events/{event_id}?msg=refresh_error",
            status_code=303,
        )

    from google_sheets import _extract_sheet_id
    try:
        sheet_id = _extract_sheet_id(ev.google_sheet_url)
    except ValueError:
        sheet_id = ev.google_sheet_url

    registrations = parse_robot_registrations(rows, sheet_id)

    existing_row_ids = {
        r.sheet_row_id
        for r in db.query(Robot).all()
        if r.sheet_row_id
    }
    event_robot_ids = {
        er.robot_id for er in db.query(EventRobot).filter(EventRobot.event_id == event_id).all()
    }
    max_res = (
        db.query(EventRobot.reserve_order)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == True)
        .order_by(EventRobot.reserve_order.desc().nullslast())
        .first()
    )
    next_reserve_order = (max_res[0] or 0) + 1 if max_res else 1

    for reg in registrations:
        row_id = reg["sheet_row_id"]
        if row_id in existing_row_ids:
            robot = db.query(Robot).filter(Robot.sheet_row_id == row_id).first()
            if robot and robot.id not in event_robot_ids:
                db.add(EventRobot(event_id=event_id, robot_id=robot.id, is_reserve=False))
            continue

        roboteer = (
            db.query(Roboteer).filter(Roboteer.roboteer_name == reg["roboteer_name"]).first()
        )
        if not roboteer:
            roboteer = Roboteer(
                roboteer_name=reg["roboteer_name"],
                contact_email=reg.get("contact_email"),
                imported_from_sheet_id=sheet_id,
            )
            db.add(roboteer)
            db.flush()

        robot = Robot(
            robot_name=reg["robot_name"],
            roboteer_id=roboteer.id,
            weapon_type=reg.get("weapon_type"),
            sheet_row_id=row_id,
            image_source=ImageSource.none,
        )
        db.add(robot)
        db.flush()

        if reg.get("image_url"):
            _try_import_image(robot, reg["image_url"])

        db.add(EventRobot(event_id=event_id, robot_id=robot.id, is_reserve=False))

    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}?msg=refreshed", status_code=303)


# ---------------------------------------------------------------------------
# 6. Phase transitions
# ---------------------------------------------------------------------------


@router.post("/events/{event_id}/transition")
def transition_phase(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    ev = _get_event_or_404(event_id, user.id, db)

    next_status = _NEXT_STATUS.get(ev.status)
    if not next_status:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    if ev.status == EventStatus.registration:
        active_count = (
            db.query(EventRobot)
            .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == False)
            .count()
        )
        if active_count < 2:
            return RedirectResponse(
                f"/admin/events/{event_id}?msg=error"
                f"&error=Need+at+least+2+active+robots+before+starting+qualifying.",
                status_code=303,
            )

    if ev.status == EventStatus.qualifying:
        # Only allow transition to bracket after all 3 qualifying rounds complete
        qual_phases = (
            db.query(Phase)
            .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.qualifying)
            .all()
        )
        if len(qual_phases) < 3 or any(ph.status != PhaseStatus.complete for ph in qual_phases):
            return RedirectResponse(
                f"/admin/events/{event_id}?msg=error"
                f"&error=Complete+all+3+qualifying+rounds+before+transitioning.",
                status_code=303,
            )

    ev.status = next_status
    db.add(ev)

    # Auto-generate Round 1 when entering qualifying
    if next_status == EventStatus.qualifying:
        create_qualifying_round(event_id, 1, db)

    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}?msg=transitioned", status_code=303)


# ---------------------------------------------------------------------------
# 7. Robot roster management — manual add / remove
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/robots/add", response_class=HTMLResponse)
def add_robot_form(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    error: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    err_el = Div(error, cls="alert alert-error") if error else ""

    form = Div(
        A("← Event", href=f"/admin/events/{event_id}", cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
        H1("Add Robot Manually"),
        err_el if err_el else "",
        Div(
            HForm(
                Div(
                    Label("Roboteer Name", for_="roboteer_name"),
                    Input(type="text", id="roboteer_name", name="roboteer_name",
                          cls="form-control", required=True, autofocus=True),
                    cls="form-group",
                ),
                Div(
                    Label("Robot Name", for_="robot_name"),
                    Input(type="text", id="robot_name", name="robot_name",
                          cls="form-control", required=True),
                    cls="form-group",
                ),
                Div(
                    Label("Weapon Type (optional)", for_="weapon_type"),
                    Input(type="text", id="weapon_type", name="weapon_type",
                          cls="form-control", placeholder="e.g. Spinner, Wedge…"),
                    cls="form-group",
                ),
                Div(
                    Label("Contact Email (optional)", for_="contact_email"),
                    Input(type="email", id="contact_email", name="contact_email",
                          cls="form-control"),
                    cls="form-group",
                ),
                Div(
                    Label(
                        Input(type="checkbox", name="is_reserve", value="1"),
                        " Designate as reserve",
                        style="display:flex;align-items:center;gap:0.5rem;cursor:pointer;",
                    ),
                    cls="form-group",
                ),
                Div(
                    Button("Add to Roster", type="submit", cls="btn btn-primary"),
                    " ",
                    A("Cancel", href=f"/admin/events/{event_id}", cls="btn btn-secondary"),
                    cls="form-group",
                ),
                method="post",
                action=f"/admin/events/{event_id}/robots/add",
            ),
            cls="card",
        ),
    )
    return _page("Add Robot", form, user=user)


@router.post("/events/{event_id}/robots/add")
def add_robot(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    roboteer_name: str = Form(...),
    robot_name: str = Form(...),
    weapon_type: str = Form(default=""),
    contact_email: str = Form(default=""),
    is_reserve: str = Form(default=""),
):
    _get_event_or_404(event_id, user.id, db)

    roboteer_name = roboteer_name.strip()
    robot_name = robot_name.strip()
    weapon_type = weapon_type.strip() or None
    contact_email = contact_email.strip() or None
    flag_reserve = is_reserve == "1"

    if not roboteer_name or not robot_name:
        return RedirectResponse(
            f"/admin/events/{event_id}/robots/add?error=Roboteer+name+and+robot+name+are+required",
            status_code=303,
        )

    roboteer = db.query(Roboteer).filter(Roboteer.roboteer_name == roboteer_name).first()
    if not roboteer:
        roboteer = Roboteer(roboteer_name=roboteer_name, contact_email=contact_email)
        db.add(roboteer)
        db.flush()

    robot = Robot(
        robot_name=robot_name,
        roboteer_id=roboteer.id,
        weapon_type=weapon_type,
        image_source=ImageSource.none,
    )
    db.add(robot)
    db.flush()

    res_order = None
    if flag_reserve:
        max_res = (
            db.query(EventRobot.reserve_order)
            .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == True)
            .order_by(EventRobot.reserve_order.desc().nullslast())
            .first()
        )
        res_order = (max_res[0] or 0) + 1 if max_res else 1

    db.add(EventRobot(
        event_id=event_id,
        robot_id=robot.id,
        is_reserve=flag_reserve,
        reserve_order=res_order,
    ))
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}?msg=added", status_code=303)


@router.post("/events/{event_id}/robots/{er_id}/remove")
def remove_robot(
    event_id: int,
    er_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    _get_event_or_404(event_id, user.id, db)
    er = db.query(EventRobot).filter(EventRobot.id == er_id, EventRobot.event_id == event_id).first()
    if er:
        db.delete(er)
        db.commit()
    return RedirectResponse(f"/admin/events/{event_id}?msg=removed", status_code=303)


# ---------------------------------------------------------------------------
# 8. Reserve designation and ordering
# ---------------------------------------------------------------------------


@router.post("/events/{event_id}/robots/{er_id}/set-reserve")
def set_reserve(
    event_id: int,
    er_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    _get_event_or_404(event_id, user.id, db)
    er = db.query(EventRobot).filter(EventRobot.id == er_id, EventRobot.event_id == event_id).first()
    if er and not er.is_reserve:
        max_res = (
            db.query(EventRobot.reserve_order)
            .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == True)
            .order_by(EventRobot.reserve_order.desc().nullslast())
            .first()
        )
        er.is_reserve = True
        er.reserve_order = (max_res[0] or 0) + 1 if max_res else 1
        db.commit()
    return RedirectResponse(f"/admin/events/{event_id}?msg=reserve_toggled", status_code=303)


@router.post("/events/{event_id}/robots/{er_id}/unset-reserve")
def unset_reserve(
    event_id: int,
    er_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    _get_event_or_404(event_id, user.id, db)
    er = db.query(EventRobot).filter(EventRobot.id == er_id, EventRobot.event_id == event_id).first()
    if er and er.is_reserve:
        er.is_reserve = False
        er.reserve_order = None
        db.flush()
        _renumber_reserves(event_id, db)
        db.commit()
    return RedirectResponse(f"/admin/events/{event_id}?msg=reserve_toggled", status_code=303)


@router.post("/events/{event_id}/robots/{er_id}/move-reserve/{direction}")
def move_reserve(
    event_id: int,
    er_id: int,
    direction: str,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    _get_event_or_404(event_id, user.id, db)
    er = db.query(EventRobot).filter(EventRobot.id == er_id, EventRobot.event_id == event_id).first()
    if not er or not er.is_reserve:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    all_reserves = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == True)
        .order_by(EventRobot.reserve_order.asc().nullslast(), EventRobot.id)
        .all()
    )
    idx = next((i for i, r in enumerate(all_reserves) if r.id == er_id), None)
    if idx is None:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    if direction == "up" and idx > 0:
        all_reserves[idx - 1].reserve_order, all_reserves[idx].reserve_order = (
            all_reserves[idx].reserve_order,
            all_reserves[idx - 1].reserve_order,
        )
        db.commit()
    elif direction == "down" and idx < len(all_reserves) - 1:
        all_reserves[idx + 1].reserve_order, all_reserves[idx].reserve_order = (
            all_reserves[idx].reserve_order,
            all_reserves[idx + 1].reserve_order,
        )
        db.commit()

    return RedirectResponse(f"/admin/events/{event_id}?msg=reserve_moved", status_code=303)


def _renumber_reserves(event_id: int, db: Session) -> None:
    """Re-number reserve_order values to be contiguous after a removal."""
    reserves = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == True)
        .order_by(EventRobot.reserve_order.asc().nullslast(), EventRobot.id)
        .all()
    )
    for i, r in enumerate(reserves, start=1):
        r.reserve_order = i


# ---------------------------------------------------------------------------
# 9. Reserve swap / robot retirement
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/robots/{er_id}/retire", response_class=HTMLResponse)
def retire_form(
    event_id: int,
    er_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    error: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    er = db.query(EventRobot).filter(EventRobot.id == er_id, EventRobot.event_id == event_id).first()
    if not er:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    robot: Robot = er.robot
    phases = db.query(Phase).filter(Phase.event_id == event_id).order_by(Phase.phase_number).all()
    reserves = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == True)
        .order_by(EventRobot.reserve_order.asc().nullslast())
        .all()
    )

    err_el = Div(error, cls="alert alert-error") if error else ""

    if not phases:
        info = Div(
            "Retirement can only be recorded once qualifying phases have been created (Phase 5). "
            "You can still remove robots from the roster using the Remove button.",
            cls="alert alert-info",
        )
        page = Div(
            A("← Event", href=f"/admin/events/{event_id}", cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
            H1(f"Retire {robot.robot_name}"),
            info,
        )
        return _page("Retire Robot", page, user=user)

    phase_options = [
        Option(f"Phase {ph.phase_number} ({ph.phase_type.value})", value=str(ph.id))
        for ph in phases
    ]
    reserve_options = (
        [
            Option(f"{r.robot.robot_name} (#{i + 1})", value=str(r.id))
            for i, r in enumerate(reserves)
        ]
        if reserves
        else [Option("No reserves available", value="")]
    )

    page = Div(
        A("← Event", href=f"/admin/events/{event_id}", cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
        H1(f"Retire {robot.robot_name}"),
        err_el if err_el else "",
        Div(
            P(
                "Retiring a robot removes it from the active roster from the selected phase onward. "
                "Its results are preserved. The next available reserve will be swapped in.",
                style="color:#888;font-size:0.9rem;margin-bottom:1rem;",
            ),
            HForm(
                Div(
                    Label("Retired after which phase?", for_="phase_id"),
                    Select(
                        *phase_options,
                        id="phase_id",
                        name="phase_id",
                        cls="form-control",
                        required=True,
                    ),
                    cls="form-group",
                ),
                Div(
                    Label("Replace with reserve (optional)", for_="reserve_er_id"),
                    Select(
                        Option("— No replacement —", value=""),
                        *reserve_options,
                        id="reserve_er_id",
                        name="reserve_er_id",
                        cls="form-control",
                    ),
                    cls="form-group",
                ),
                Div(
                    Button("Confirm Retirement", type="submit", cls="btn btn-warning"),
                    " ",
                    A("Cancel", href=f"/admin/events/{event_id}", cls="btn btn-secondary"),
                    cls="form-group",
                ),
                method="post",
                action=f"/admin/events/{event_id}/robots/{er_id}/retire",
            ),
            cls="card",
        ),
    )
    return _page("Retire Robot", page, user=user)


@router.post("/events/{event_id}/robots/{er_id}/retire")
def retire_robot(
    event_id: int,
    er_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    phase_id: int = Form(...),
    reserve_er_id: str = Form(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    er = db.query(EventRobot).filter(EventRobot.id == er_id, EventRobot.event_id == event_id).first()
    if not er:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    phase = db.query(Phase).filter(Phase.id == phase_id, Phase.event_id == event_id).first()
    if not phase:
        return RedirectResponse(
            f"/admin/events/{event_id}/robots/{er_id}/retire?error=Invalid+phase", status_code=303
        )

    replacement_robot_id = None
    if reserve_er_id:
        reserve_er = db.query(EventRobot).filter(
            EventRobot.id == int(reserve_er_id),
            EventRobot.event_id == event_id,
            EventRobot.is_reserve == True,
        ).first()
        if reserve_er:
            reserve_er.is_reserve = False
            reserve_er.reserve_order = None
            _renumber_reserves(event_id, db)
            replacement_robot_id = reserve_er.robot_id

    retirement = RobotRetirement(
        event_id=event_id,
        retired_robot_id=er.robot_id,
        replacement_robot_id=replacement_robot_id,
        retired_after_phase_id=phase_id,
    )
    db.add(retirement)
    db.delete(er)
    db.commit()

    return RedirectResponse(f"/admin/events/{event_id}?msg=retired", status_code=303)


# ---------------------------------------------------------------------------
# 10. Image upload
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/robots/{robot_id}/upload-image", response_class=HTMLResponse)
def upload_image_form(
    event_id: int,
    robot_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    error: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not robot:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    err_el = Div(error, cls="alert alert-error") if error else ""
    current_img = ""
    if robot.image_url:
        current_img = Div(
            P("Current image:", style="color:#888;font-size:0.85rem;margin-bottom:0.5rem;"),
            Img(src=robot.image_url, style="max-width:200px;max-height:150px;border-radius:6px;"),
            style="margin-bottom:1rem;",
        )

    page = Div(
        A("← Event", href=f"/admin/events/{event_id}", cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
        H1(f"Upload Image — {robot.robot_name}"),
        err_el if err_el else "",
        Div(
            current_img,
            HForm(
                Div(
                    Label("Upload image file", for_="image_file"),
                    Input(type="file", id="image_file", name="image_file",
                          cls="form-control", accept="image/*"),
                    cls="form-group",
                ),
                Div(
                    Label("Or paste image URL", for_="image_url"),
                    Input(
                        type="url",
                        id="image_url",
                        name="image_url",
                        cls="form-control",
                        placeholder="https://example.com/robot.jpg",
                        value=(robot.image_url if robot.image_source == ImageSource.sheet else ""),
                    ),
                    cls="form-group",
                ),
                Div(
                    Button("Save Image", type="submit", cls="btn btn-primary"),
                    " ",
                    A("Cancel", href=f"/admin/events/{event_id}", cls="btn btn-secondary"),
                    cls="form-group",
                ),
                method="post",
                action=f"/admin/events/{event_id}/robots/{robot_id}/upload-image",
                enctype="multipart/form-data",
            ),
            cls="card",
        ),
    )
    return _page("Upload Image", page, user=user)


@router.post("/events/{event_id}/robots/{robot_id}/upload-image")
async def upload_image(
    event_id: int,
    robot_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    image_file: Optional[UploadFile] = File(default=None),
    image_url: str = Form(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not robot:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    image_url = image_url.strip()

    if image_file and image_file.filename:
        ext = Path(image_file.filename).suffix.lower() or ".jpg"
        allowed_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        if ext not in allowed_exts:
            return RedirectResponse(
                f"/admin/events/{event_id}/robots/{robot_id}/upload-image"
                f"?error=Unsupported+file+type.+Use+jpg%2C+png%2C+gif%2C+or+webp.",
                status_code=303,
            )
        filename = f"{uuid.uuid4().hex}{ext}"
        dest = Path(UPLOAD_DIR) / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await image_file.read()
        dest.write_bytes(content)
        robot.image_url = f"/static/uploads/{filename}"
        robot.image_source = ImageSource.upload

    elif image_url:
        robot.image_url = image_url
        robot.image_source = ImageSource.sheet

    else:
        return RedirectResponse(
            f"/admin/events/{event_id}/robots/{robot_id}/upload-image"
            f"?error=Please+upload+a+file+or+enter+a+URL.",
            status_code=303,
        )

    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}?msg=image_updated", status_code=303)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_event_or_404(event_id: int, organizer_id: int, db: Session) -> Event:
    ev = (
        db.query(Event)
        .filter(Event.id == event_id, Event.organizer_id == organizer_id)
        .first()
    )
    if not ev:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Event not found")
    return ev


def _try_import_image(robot: Robot, image_url: str) -> None:
    """Attempt to download an image from a URL and save it locally.

    Falls back to storing the URL directly if the download fails.
    Only attempts HTTP/HTTPS URLs to prevent SSRF against internal services.
    """
    if not image_url.startswith(("http://", "https://")):
        return
    try:
        ext = Path(image_url.split("?")[0]).suffix.lower() or ".jpg"
        allowed_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        if ext not in allowed_exts:
            ext = ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        dest = Path(UPLOAD_DIR) / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(image_url, headers={"User-Agent": "BitBT/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            dest.write_bytes(response.read())
        robot.image_url = f"/static/uploads/{filename}"
        robot.image_source = ImageSource.upload
    except (urllib.error.URLError, OSError, ValueError):
        # Fallback: store the URL reference without downloading
        robot.image_url = image_url
        robot.image_source = ImageSource.sheet


# ---------------------------------------------------------------------------
# Phase 5 — 11. Generate qualifying round (manual, rounds 2 & 3)
# ---------------------------------------------------------------------------


@router.post("/events/{event_id}/qualifying/generate")
def generate_qualifying_round(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    ev = _get_event_or_404(event_id, user.id, db)
    if ev.status != EventStatus.qualifying:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    qual_phases = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.qualifying)
        .order_by(Phase.phase_number)
        .all()
    )
    max_round = max((ph.phase_number for ph in qual_phases), default=0)

    if max_round >= 3:
        return RedirectResponse(
            f"/admin/events/{event_id}?msg=error&error=Only+3+qualifying+rounds+allowed.",
            status_code=303,
        )

    # Ensure the last round is complete before generating the next
    if qual_phases:
        last = qual_phases[-1]
        if last.status != PhaseStatus.complete:
            return RedirectResponse(
                f"/admin/events/{event_id}?msg=error&error=Complete+the+current+round+first.",
                status_code=303,
            )

    create_qualifying_round(event_id, max_round + 1, db)
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}?msg=round_generated", status_code=303)


# ---------------------------------------------------------------------------
# Phase 5 — 12. Phase detail — view matchups + drag-drop reorder
# ---------------------------------------------------------------------------

_SORTABLEJS = "https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"


@router.get("/events/{event_id}/phases/{phase_id}", response_class=HTMLResponse)
def phase_detail(
    event_id: int,
    phase_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    msg: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    phase = db.query(Phase).filter(Phase.id == phase_id, Phase.event_id == event_id).first()
    if not phase:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    if phase.phase_type == PhaseType.qualifying:
        phase_label = f"Qualifying Round {phase.phase_number}"
    else:
        phase_label = "Bracket"

    flash_map = {
        "scored": ("Fight result saved.", "success"),
        "score_cleared": ("Fight result cleared.", "info"),
        "round_complete": ("Round marked complete.", "success"),
    }
    flash = ""
    if msg in flash_map:
        text, kind = flash_map[msg]
        flash = Div(text, cls=f"alert alert-{kind}")

    matchups = (
        db.query(Matchup)
        .filter(Matchup.phase_id == phase_id)
        .order_by(Matchup.display_order)
        .all()
    )

    all_done = all(m.status == MatchupStatus.completed for m in matchups)
    can_complete = all_done and phase.status == PhaseStatus.active

    # Action buttons
    top_actions = [
        A(
            f"← {ev.event_name}",
            href=f"/admin/events/{event_id}",
            cls="btn btn-sm btn-secondary",
            style="margin-bottom:1.2rem;display:inline-block;",
        ),
    ]

    # Matchup list
    items = []
    for m in matchups:
        r1: Robot = m.robot1
        r2: Robot | None = m.robot2

        if r2 is None:
            robot_label = Span(
                Strong(r1.robot_name),
                Span(" — BYE", style="color:#555;font-size:0.82rem;"),
                cls="matchup-robots",
            )
            result_el = Span(f"+{BYE_POINTS} pts (bye)", cls="matchup-result-label")
            item_cls = "matchup-item is-bye"
        else:
            robot_label = Span(
                Strong(r1.robot_name),
                Span(" vs ", cls="matchup-vs"),
                Strong(r2.robot_name),
                cls="matchup-robots",
            )
            if m.status == MatchupStatus.completed:
                r1_res = next((r for r in m.results if r.robot_id == r1.id), None)
                r2_res = next((r for r in m.results if r.robot_id == r2.id), None)
                r1_pts = r1_res.points_scored if r1_res else 0
                r2_pts = r2_res.points_scored if r2_res else 0
                result_el = Span(
                    points_to_outcome_label(r1_pts, r2_pts),
                    f" ({r1_pts}–{r2_pts})",
                    cls="matchup-result-label",
                )
            else:
                result_el = Span("pending", cls="matchup-result-pending")
            item_cls = "matchup-item"

        score_btn = ""
        if r2 is not None:
            if m.status == MatchupStatus.pending and phase.status == PhaseStatus.active:
                score_btn = A(
                    "Score",
                    href=f"/admin/events/{event_id}/matchups/{m.id}/score",
                    cls="btn btn-sm btn-primary",
                )
            elif m.status == MatchupStatus.completed:
                score_btn = A(
                    "Edit",
                    href=f"/admin/events/{event_id}/matchups/{m.id}/score",
                    cls="btn btn-sm btn-secondary",
                )
        else:
            # Bye matchup — can complete directly
            if m.status == MatchupStatus.pending and phase.status == PhaseStatus.active:
                score_btn = HForm(
                    Button("Complete Bye", type="submit", cls="btn btn-sm btn-success"),
                    method="post",
                    action=f"/admin/events/{event_id}/matchups/{m.id}/complete-bye",
                )

        drag = Span("⠿", cls="drag-handle", title="Drag to reorder") if phase.status == PhaseStatus.active else ""

        items.append(
            Li(
                drag,
                robot_label,
                result_el,
                score_btn,
                cls=item_cls,
                data_matchup_id=str(m.id),
            )
        )

    matchup_list = Ul(*items, id="matchup-list", cls="matchup-list")

    # SortableJS script
    sort_script = ""
    if phase.status == PhaseStatus.active:
        sort_script = Script(
            src=_SORTABLEJS,
        )
        sort_init = Script(
            f"""
document.addEventListener('DOMContentLoaded', function() {{
    var el = document.getElementById('matchup-list');
    if (!el) return;
    Sortable.create(el, {{
        animation: 150,
        handle: '.drag-handle',
        onEnd: function() {{
            var order = Array.from(el.querySelectorAll('.matchup-item'))
                            .map(function(e) {{ return e.dataset.matchupId; }});
            fetch('/admin/events/{event_id}/phases/{phase_id}/reorder', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{order: order}})
            }});
        }}
    }});
}});
"""
        )
    else:
        sort_init = ""

    complete_btn = ""
    if can_complete:
        complete_btn = HForm(
            Button("Mark Round Complete", type="submit", cls="btn btn-success"),
            method="post",
            action=f"/admin/events/{event_id}/phases/{phase_id}/complete",
        )

    page = Div(
        *top_actions,
        H1(phase_label),
        Small(
            Span(phase.status.value, cls=f"badge badge-{phase.status.value}"),
            f"  ·  {sum(1 for m in matchups if m.status == MatchupStatus.completed)}/{len(matchups)} complete",
            style="color:#888;display:block;margin-bottom:1.2rem;",
        ),
        flash if flash else "",
        Div(matchup_list, cls="card"),
        complete_btn,
        sort_script,
        sort_init,
    )
    return _page(phase_label, page, user=user)


@router.post("/events/{event_id}/phases/{phase_id}/reorder")
async def reorder_matchups(
    event_id: int,
    phase_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    """AJAX endpoint — receives JSON {order: [matchup_id, ...]} and persists display_order."""
    _get_event_or_404(event_id, user.id, db)
    try:
        body = await request.json()
        order: list[str] = body.get("order", [])
    except Exception:
        return JSONResponse({"ok": False}, status_code=400)

    for i, mid_str in enumerate(order):
        try:
            mid = int(mid_str)
        except ValueError:
            continue
        m = db.query(Matchup).filter(Matchup.id == mid, Matchup.phase_id == phase_id).first()
        if m:
            m.display_order = i
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/events/{event_id}/matchups/{matchup_id}/complete-bye")
def complete_bye(
    event_id: int,
    matchup_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    """Award bye points to robot1 and mark matchup completed."""
    ev = _get_event_or_404(event_id, user.id, db)
    m = db.query(Matchup).filter(Matchup.id == matchup_id).first()
    if not m or m.phase.event_id != event_id or m.robot2_id is not None:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    db.query(Result).filter(Result.matchup_id == matchup_id).delete()
    db.add(Result(matchup_id=matchup_id, robot_id=m.robot1_id, points_scored=BYE_POINTS))
    m.status = MatchupStatus.completed

    phase: Phase = m.phase
    if all(mx.status == MatchupStatus.completed for mx in phase.matchups):
        phase.status = PhaseStatus.complete

    db.commit()
    back = (
        f"/admin/events/{event_id}/phases/{phase.id}?msg=scored"
        if phase.phase_type == PhaseType.qualifying
        else f"/admin/events/{event_id}/bracket?msg=scored"
    )
    return RedirectResponse(back, status_code=303)


@router.post("/events/{event_id}/phases/{phase_id}/complete")
def complete_phase(
    event_id: int,
    phase_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    _get_event_or_404(event_id, user.id, db)
    phase = db.query(Phase).filter(Phase.id == phase_id, Phase.event_id == event_id).first()
    if not phase:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    all_done = all(m.status == MatchupStatus.completed for m in phase.matchups)
    if not all_done:
        return RedirectResponse(
            f"/admin/events/{event_id}/phases/{phase_id}?msg=error",
            status_code=303,
        )

    phase.status = PhaseStatus.complete
    db.commit()
    return RedirectResponse(
        f"/admin/events/{event_id}/phases/{phase_id}?msg=round_complete", status_code=303
    )


# ---------------------------------------------------------------------------
# Phase 5 — 13. Fight result entry (score & clear)
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/matchups/{matchup_id}/score", response_class=HTMLResponse)
def score_form(
    event_id: int,
    matchup_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    error: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    m = db.query(Matchup).filter(Matchup.id == matchup_id).first()
    if not m or m.phase.event_id != event_id:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    r1: Robot = m.robot1
    r2: Robot | None = m.robot2
    phase: Phase = m.phase

    if phase.phase_type == PhaseType.qualifying:
        back_href = f"/admin/events/{event_id}/phases/{phase.id}"
        phase_label = f"Qualifying Round {phase.phase_number}"
    else:
        back_href = f"/admin/events/{event_id}/bracket"
        phase_label = f"Bracket Round {m.bracket_round or ''}"

    err_el = Div(error, cls="alert alert-error") if error else ""

    # Existing result (for edit mode)
    existing_outcome = ""
    if m.status == MatchupStatus.completed:
        r1_res = next((r for r in m.results if r.robot_id == r1.id), None)
        r2_res = next((r for r in m.results if r2 and r.robot_id == r2.id), None)
        r1_pts = r1_res.points_scored if r1_res else 0
        r2_pts = r2_res.points_scored if r2_res else 0
        existing_outcome = Div(
            P(
                f"Current result: {points_to_outcome_label(r1_pts, r2_pts)} ({r1_pts}–{r2_pts})",
                style="color:#4ade80;font-size:0.9rem;margin-bottom:0.75rem;",
            ),
            HForm(
                Button("Clear result", type="submit", cls="btn btn-danger btn-sm"),
                method="post",
                action=f"/admin/events/{event_id}/matchups/{matchup_id}/clear-score",
            ),
            style="margin-bottom:1rem;padding-bottom:1rem;border-bottom:1px solid #2a2a2a;",
        )

    # Build outcome options labelled with robot names
    options = []
    for code, label in FIGHT_OUTCOMES:
        display = (
            label
            .replace("Robot 1", r1.robot_name)
            .replace("Robot 2", r2.robot_name if r2 else "Robot 2")
        )
        options.append(Option(display, value=code))

    form_title = f"{'Edit' if m.status == MatchupStatus.completed else 'Score'} Fight"

    page = Div(
        A(f"← {phase_label}", href=back_href, cls="btn btn-sm btn-secondary",
          style="margin-bottom:1.2rem;display:inline-block;"),
        H1(form_title),
        err_el if err_el else "",
        Div(
            P(
                Span(r1.robot_name, style="font-weight:700;"),
                Span(" vs ", style="color:#555;"),
                Span(r2.robot_name if r2 else "BYE", style="font-weight:700;" if r2 else "color:#555;"),
                Span(f" · {phase_label}", style="color:#666;font-size:0.85rem;"),
                style="margin-bottom:1rem;font-size:1rem;",
            ),
            existing_outcome,
            HForm(
                Div(
                    Label("Fight outcome", for_="outcome"),
                    Select(*options, id="outcome", name="outcome", cls="form-control", required=True),
                    cls="form-group",
                ),
                Div(
                    Button("Save Result", type="submit", cls="btn btn-primary"),
                    " ",
                    A("Cancel", href=back_href, cls="btn btn-secondary"),
                    cls="form-group",
                ),
                method="post",
                action=f"/admin/events/{event_id}/matchups/{matchup_id}/score",
            ),
            cls="card",
        ),
    )
    return _page(form_title, page, user=user)


@router.post("/events/{event_id}/matchups/{matchup_id}/score")
def submit_score(
    event_id: int,
    matchup_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    outcome: str = Form(...),
):
    ev = _get_event_or_404(event_id, user.id, db)
    m = db.query(Matchup).filter(Matchup.id == matchup_id).first()
    if not m or m.phase.event_id != event_id:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    valid_codes = {code for code, _ in FIGHT_OUTCOMES}
    if outcome not in valid_codes:
        return RedirectResponse(
            f"/admin/events/{event_id}/matchups/{matchup_id}/score?error=Invalid+outcome.",
            status_code=303,
        )

    r1_pts, r2_pts = outcome_to_points(outcome)

    # Clear old results
    db.query(Result).filter(Result.matchup_id == matchup_id).delete()

    db.add(Result(matchup_id=matchup_id, robot_id=m.robot1_id, points_scored=r1_pts))
    if m.robot2_id:
        db.add(Result(matchup_id=matchup_id, robot_id=m.robot2_id, points_scored=r2_pts))

    m.status = MatchupStatus.completed

    # Auto-complete phase if all matchups are now done
    phase: Phase = m.phase
    if all(mx.status == MatchupStatus.completed for mx in phase.matchups):
        phase.status = PhaseStatus.complete

    db.commit()

    back = (
        f"/admin/events/{event_id}/phases/{phase.id}?msg=scored"
        if phase.phase_type == PhaseType.qualifying
        else f"/admin/events/{event_id}/bracket?msg=scored"
    )
    return RedirectResponse(back, status_code=303)


@router.post("/events/{event_id}/matchups/{matchup_id}/clear-score")
def clear_score(
    event_id: int,
    matchup_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    ev = _get_event_or_404(event_id, user.id, db)
    m = db.query(Matchup).filter(Matchup.id == matchup_id).first()
    if not m or m.phase.event_id != event_id:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    db.query(Result).filter(Result.matchup_id == matchup_id).delete()
    m.status = MatchupStatus.pending

    # Un-complete the phase if it was marked complete
    phase: Phase = m.phase
    if phase.status == PhaseStatus.complete:
        phase.status = PhaseStatus.active

    db.commit()

    back = (
        f"/admin/events/{event_id}/phases/{phase.id}?msg=score_cleared"
        if phase.phase_type == PhaseType.qualifying
        else f"/admin/events/{event_id}/bracket?msg=score_cleared"
    )
    return RedirectResponse(back, status_code=303)


# ---------------------------------------------------------------------------
# Phase 5 — 14. Bracket generation
# ---------------------------------------------------------------------------


@router.post("/events/{event_id}/bracket/generate")
def generate_bracket(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    ev = _get_event_or_404(event_id, user.id, db)

    # Require 3 complete qualifying rounds
    qual_phases = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.qualifying)
        .all()
    )
    if len(qual_phases) < 3 or any(ph.status != PhaseStatus.complete for ph in qual_phases):
        return RedirectResponse(
            f"/admin/events/{event_id}?msg=error&error=Complete+all+3+qualifying+rounds+first.",
            status_code=303,
        )

    # Don't double-generate
    existing = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.bracket)
        .first()
    )
    if existing:
        return RedirectResponse(f"/admin/events/{event_id}/bracket", status_code=303)

    active_count = len(get_active_robot_ids(event_id, db))
    if active_count < 2:
        return RedirectResponse(
            f"/admin/events/{event_id}?msg=error&error=Not+enough+robots+for+a+bracket.",
            status_code=303,
        )

    create_bracket(event_id, db)
    ev.status = EventStatus.bracket
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}/bracket?msg=bracket_generated", status_code=303)


# ---------------------------------------------------------------------------
# Phase 5 — 15. Bracket admin management view
# ---------------------------------------------------------------------------

_BRACKET_ROUND_LABELS: dict[int, str] = {
    1: "Round of 16",
    2: "Quarter-finals",
    3: "Semi-finals",
    4: "Final",
}


def _bracket_round_label(rnd: int, total_rounds: int) -> str:
    # If fewer than 4 rounds, shift labels (e.g. 3 rounds → SF, F)
    offset = 4 - total_rounds
    return _BRACKET_ROUND_LABELS.get(rnd + offset, f"Round {rnd}")


def _admin_bracket_matchup(m: Matchup, event_id: int, show_actions: bool) -> Div:
    r1: Robot = m.robot1
    r2: Robot | None = m.robot2

    r1_pts = r2_pts = None
    r1_win = r2_win = False
    if m.status == MatchupStatus.completed:
        r1_res = next((r for r in m.results if r.robot_id == r1.id), None)
        r2_res = next((r for r in m.results if r2 and r.robot_id == r2.id), None)
        r1_pts = r1_res.points_scored if r1_res else 0
        r2_pts = r2_res.points_scored if r2_res else 0
        if r2_pts is not None:
            r1_win = r1_pts >= r2_pts
            r2_win = r2_pts > r1_pts
        else:
            r1_win = True

    def robot_row(robot: Robot | None, pts: int | None, is_win: bool) -> Div:
        if robot is None:
            return Div(Span("TBD", style="color:#555;font-style:italic;"), cls="bracket-robot-row")
        cls_ = "bracket-robot-row bracket-robot-winner" if is_win else "bracket-robot-row"
        pts_el = (
            Span(str(pts), style="margin-left:auto;color:#4ade80;font-weight:700;")
            if is_win and pts is not None
            else (
                Span(str(pts), style="margin-left:auto;color:#f87171;")
                if pts is not None
                else Span("—", style="margin-left:auto;color:#444;")
            )
        )
        return Div(
            A(robot.robot_name, href=f"/events/{event_id}/robot/{robot.id}"),
            pts_el,
            cls=cls_,
        )

    action_el = ""
    if show_actions:
        if m.status == MatchupStatus.pending:
            action_el = Div(
                A("Score", href=f"/admin/events/{event_id}/matchups/{m.id}/score", cls="btn btn-sm btn-primary"),
                style="padding:0.5rem 0.5rem;align-self:center;",
            )
        else:
            action_el = Div(
                A("Edit", href=f"/admin/events/{event_id}/matchups/{m.id}/score", cls="btn btn-sm btn-secondary"),
                style="padding:0.5rem 0.5rem;align-self:center;",
            )

    return Div(
        Div(
            robot_row(r1, r1_pts, r1_win),
            Div(style="border-top:1px solid #222;margin:0 0.5rem;"),
            robot_row(r2, r2_pts, r2_win),
            cls="bracket-matchup-robots",
        ),
        action_el,
        cls="bracket-matchup",
    )


@router.get("/events/{event_id}/bracket", response_class=HTMLResponse)
def bracket_admin(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    msg: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)

    flash_map = {
        "scored": ("Fight result saved.", "success"),
        "score_cleared": ("Fight result cleared.", "info"),
        "bracket_generated": ("Bracket generated — top robots seeded.", "success"),
        "bracket_advanced": ("Next bracket round generated.", "success"),
        "bracket_swapped": ("Bracket pairings swapped.", "success"),
    }
    flash = ""
    if msg in flash_map:
        t, k = flash_map[msg]
        flash = Div(t, cls=f"alert alert-{k}")

    bracket_phase = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.bracket)
        .first()
    )

    if not bracket_phase:
        page = Div(
            A("← Event", href=f"/admin/events/{event_id}", cls="btn btn-sm btn-secondary",
              style="margin-bottom:1.2rem;display:inline-block;"),
            H1("Bracket"),
            Div(P("No bracket yet. Generate it from the event page.", cls="empty"), cls="card"),
        )
        return _page("Bracket", page, user=user)

    all_matchups = (
        db.query(Matchup)
        .filter(Matchup.phase_id == bracket_phase.id)
        .order_by(Matchup.bracket_round, Matchup.display_order)
        .all()
    )

    # Group by bracket_round
    rounds: dict[int, list[Matchup]] = {}
    for m in all_matchups:
        rnd = m.bracket_round or 1
        rounds.setdefault(rnd, []).append(m)

    max_round = max(rounds.keys(), default=0)
    total_rounds = max_round  # will grow as bracket advances

    # Determine if current round is all done → show advance button
    advance_btn = ""
    if max_round > 0:
        current_round_done = all(
            m.status == MatchupStatus.completed for m in rounds.get(max_round, [])
        )
        current_round_has_multiple = len(rounds.get(max_round, [])) > 1
        if current_round_done and current_round_has_multiple:
            advance_btn = HForm(
                Button("Generate Next Round →", type="submit", cls="btn btn-warning"),
                method="post",
                action=f"/admin/events/{event_id}/bracket/advance",
            )

    # Swap pairings UI (only for round 1 if all pending)
    swap_section = ""
    round1_matchups = rounds.get(1, [])
    if round1_matchups and all(m.status == MatchupStatus.pending for m in round1_matchups):
        swap_section = Div(
            Div(
                H3("Rearrange Round 1 Pairings"),
                A("Rearrange", href=f"/admin/events/{event_id}/bracket/rearrange",
                  cls="btn btn-sm btn-secondary"),
                cls="card-header",
            ),
            P("Swap robot pairings before any fights begin.", style="color:#888;font-size:0.85rem;"),
            cls="card",
        )

    # Build bracket sections
    sections = []
    for rnd in sorted(rounds.keys()):
        # Recalculate total_rounds as we know the final size
        round_label = _bracket_round_label(rnd, max_round)
        sections.append(P(round_label, cls="bracket-round-header"))
        for m in rounds[rnd]:
            sections.append(_admin_bracket_matchup(m, event_id, show_actions=True))

    standing_link = A(
        "← Event",
        href=f"/admin/events/{event_id}",
        cls="btn btn-sm btn-secondary",
        style="margin-bottom:1.2rem;display:inline-block;",
    )
    standings_link = A(
        "Qualifying standings",
        href=f"/admin/events/{event_id}/qualifying/standings",
        cls="btn btn-sm btn-secondary",
        style="margin-bottom:1.2rem;margin-left:0.5rem;display:inline-block;",
    )

    page = Div(
        standing_link,
        standings_link,
        H1("Bracket"),
        Small(
            Span(bracket_phase.status.value, cls=f"badge badge-{bracket_phase.status.value}"),
            style="display:block;color:#888;margin-bottom:1.2rem;",
        ),
        flash if flash else "",
        swap_section,
        Div(*sections, cls="card") if sections else Div(P("No matchups yet.", cls="empty"), cls="card"),
        advance_btn,
    )
    return _page("Bracket", page, user=user)


@router.post("/events/{event_id}/bracket/advance")
def advance_bracket(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    _get_event_or_404(event_id, user.id, db)
    bracket_phase = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.bracket)
        .first()
    )
    if not bracket_phase:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    max_round = (
        db.query(func.max(Matchup.bracket_round))
        .filter(Matchup.phase_id == bracket_phase.id)
        .scalar()
    ) or 1

    new_matchups = advance_bracket_round(event_id, bracket_phase.id, max_round, db)

    if not new_matchups:
        return RedirectResponse(
            f"/admin/events/{event_id}/bracket?msg=error"
            f"&error=Cannot+advance:+round+not+fully+complete+or+tournament+over.",
            status_code=303,
        )

    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}/bracket?msg=bracket_advanced", status_code=303)


# ---------------------------------------------------------------------------
# Phase 5 — 16. Bracket rearrange (swap Round 1 pairings)
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/bracket/rearrange", response_class=HTMLResponse)
def bracket_rearrange_form(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    error: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    bracket_phase = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.bracket)
        .first()
    )
    if not bracket_phase:
        return RedirectResponse(f"/admin/events/{event_id}/bracket", status_code=303)

    r1_matchups = (
        db.query(Matchup)
        .filter(
            Matchup.phase_id == bracket_phase.id,
            Matchup.bracket_round == 1,
            Matchup.status == MatchupStatus.pending,
        )
        .order_by(Matchup.display_order)
        .all()
    )

    if not r1_matchups:
        return RedirectResponse(f"/admin/events/{event_id}/bracket", status_code=303)

    err_el = Div(error, cls="alert alert-error") if error else ""

    matchup_options = [
        Option(
            f"Match {i + 1}: {m.robot1.robot_name} vs {m.robot2.robot_name if m.robot2 else 'BYE'}",
            value=str(m.id),
        )
        for i, m in enumerate(r1_matchups)
        if m.robot2_id is not None
    ]

    page = Div(
        A("← Bracket", href=f"/admin/events/{event_id}/bracket", cls="btn btn-sm btn-secondary",
          style="margin-bottom:1.2rem;display:inline-block;"),
        H1("Rearrange Round 1"),
        err_el if err_el else "",
        Div(
            P(
                "Select two matchups to swap their lower-seeded robot (robot 2). "
                "This lets you adjust the bracket draw before fights begin.",
                style="color:#888;font-size:0.88rem;margin-bottom:1rem;",
            ),
            HForm(
                Div(
                    Label("Matchup A", for_="matchup_a"),
                    Select(*matchup_options, id="matchup_a", name="matchup_a", cls="form-control", required=True),
                    cls="form-group",
                ),
                Div(
                    Label("Matchup B", for_="matchup_b"),
                    Select(*matchup_options, id="matchup_b", name="matchup_b", cls="form-control", required=True),
                    cls="form-group",
                ),
                Div(
                    Button("Swap Robot 2s", type="submit", cls="btn btn-primary"),
                    " ",
                    A("Cancel", href=f"/admin/events/{event_id}/bracket", cls="btn btn-secondary"),
                    cls="form-group",
                ),
                method="post",
                action=f"/admin/events/{event_id}/bracket/rearrange",
            ),
            cls="card",
        ),
    )
    return _page("Rearrange Bracket", page, user=user)


@router.post("/events/{event_id}/bracket/rearrange")
def bracket_rearrange(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    matchup_a: int = Form(...),
    matchup_b: int = Form(...),
):
    _get_event_or_404(event_id, user.id, db)
    if matchup_a == matchup_b:
        return RedirectResponse(
            f"/admin/events/{event_id}/bracket/rearrange?error=Select+two+different+matchups.",
            status_code=303,
        )

    ma = db.query(Matchup).filter(
        Matchup.id == matchup_a, Matchup.phase.has(event_id=event_id),
        Matchup.status == MatchupStatus.pending,
    ).first()
    mb = db.query(Matchup).filter(
        Matchup.id == matchup_b, Matchup.phase.has(event_id=event_id),
        Matchup.status == MatchupStatus.pending,
    ).first()

    if not ma or not mb or not ma.robot2_id or not mb.robot2_id:
        return RedirectResponse(
            f"/admin/events/{event_id}/bracket/rearrange?error=Invalid+matchup+selection.",
            status_code=303,
        )

    ma.robot2_id, mb.robot2_id = mb.robot2_id, ma.robot2_id
    db.commit()
    return RedirectResponse(f"/admin/events/{event_id}/bracket?msg=bracket_swapped", status_code=303)


# ---------------------------------------------------------------------------
# Phase 5 — 17. Qualifying standings view (for organiser before bracket draw)
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/qualifying/standings", response_class=HTMLResponse)
def qualifying_standings_view(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    ev = _get_event_or_404(event_id, user.id, db)
    standings = qualifying_standings(event_id, db)

    rows = []
    for i, (robot_id, pts) in enumerate(standings, start=1):
        robot = db.query(Robot).filter(Robot.id == robot_id).first()
        if not robot:
            continue
        qualifying = i <= 16
        rows.append(Tr(
            Td(
                Span(str(i), style="color:#fbbf24;font-weight:700;" if i <= 3 else ""),
            ),
            Td(
                Img(src=robot.image_url, cls="robot-thumb", alt=robot.robot_name)
                if robot.image_url else "",
            ),
            Td(robot.robot_name),
            Td(robot.roboteer.roboteer_name, style="color:#888;"),
            Td(Span(str(pts), style="font-weight:700;color:#60a5fa;")),
            Td(
                Span("✓ Bracket", style="color:#4ade80;font-size:0.8rem;")
                if qualifying
                else Span("—", style="color:#555;font-size:0.8rem;"),
            ),
        ))

    bracket_phase = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.bracket)
        .first()
    )
    generate_btn = ""
    if not bracket_phase:
        qual_phases = (
            db.query(Phase)
            .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.qualifying)
            .all()
        )
        if len(qual_phases) >= 3 and all(ph.status == PhaseStatus.complete for ph in qual_phases):
            generate_btn = HForm(
                Button("Generate Bracket (Top 16)", type="submit", cls="btn btn-warning"),
                method="post",
                action=f"/admin/events/{event_id}/bracket/generate",
                style="margin-bottom:1.5rem;",
            )

    page = Div(
        A("← Event", href=f"/admin/events/{event_id}", cls="btn btn-sm btn-secondary",
          style="margin-bottom:1.2rem;display:inline-block;"),
        H1("Qualifying Standings"),
        Small(f"{ev.event_name} · {ev.weight_class}", style="color:#888;display:block;margin-bottom:1.2rem;"),
        generate_btn,
        Div(
            Table(
                Thead(Tr(Th("#"), Th(""), Th("Robot"), Th("Roboteer"), Th("Pts"), Th("Status"))),
                Tbody(*rows) if rows else Tbody(Tr(Td("No results yet.", colspan="6"))),
            ),
            cls="table-wrap card",
        ),
    )
    return _page("Qualifying Standings", page, user=user)


# ===========================================================================
# Phase 5b — Sub-event management (steps 31–35)
# ===========================================================================

_SE_ROUND_LABELS: dict[int, str] = {
    1: "Round of 16",
    2: "Quarter-finals",
    3: "Semi-finals",
    4: "Final",
}


def _se_round_label(rnd: int, total_rounds: int) -> str:
    offset = 4 - total_rounds
    return _SE_ROUND_LABELS.get(rnd + offset, f"Round {rnd}")


def _sub_event_matchup_card(
    m: SubEventMatchup,
    sub_event_id: int,
    event_id: int,
    show_actions: bool,
) -> Div:
    """Render a sub-event matchup (team vs team) as a compact card."""
    t1: SubEventTeam | None = m.team1
    t2: SubEventTeam | None = m.team2

    def _team_row(team: SubEventTeam | None, is_winner: bool) -> Div:
        if team is None:
            return Div(Span("TBD", style="color:#555;font-style:italic;"), cls="bracket-robot-row")
        cls_ = "bracket-robot-row bracket-robot-winner" if is_winner else "bracket-robot-row"
        label = Span(team.team_name, style="font-weight:600;")
        robots_label = Span(
            f" ({team.robot1.robot_name} & {team.robot2.robot_name})",
            style="color:#666;font-size:0.8rem;",
        )
        win_badge = Span(" ✓", style="margin-left:auto;color:#4ade80;font-weight:700;") if is_winner else Span("", style="margin-left:auto;")
        return Div(label, robots_label, win_badge, cls=cls_)

    t1_win = m.winner_team_id is not None and m.winner_team_id == (t1.id if t1 else None)
    t2_win = m.winner_team_id is not None and m.winner_team_id == (t2.id if t2 else None)

    is_bye = t2 is None
    action_el = ""
    if show_actions:
        if is_bye:
            action_el = Div(
                Span("BYE", style="color:#555;font-size:0.8rem;padding:0.5rem;"),
                style="align-self:center;",
            )
        elif m.status == MatchupStatus.pending:
            action_el = Div(
                A(
                    "Score",
                    href=f"/admin/events/{event_id}/sub-events/{sub_event_id}/matchups/{m.id}/score",
                    cls="btn btn-sm btn-primary",
                ),
                style="padding:0.5rem;align-self:center;",
            )
        else:
            action_el = Div(
                A(
                    "Edit",
                    href=f"/admin/events/{event_id}/sub-events/{sub_event_id}/matchups/{m.id}/score",
                    cls="btn btn-sm btn-secondary",
                ),
                style="padding:0.5rem;align-self:center;",
            )

    return Div(
        Div(
            _team_row(t1, t1_win),
            Div(style="border-top:1px solid #222;margin:0 0.5rem;"),
            _team_row(t2, t2_win),
            cls="bracket-matchup-robots",
        ),
        action_el,
        cls="bracket-matchup",
    )


# ---------------------------------------------------------------------------
# 31. Sub-event creation
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/sub-events/new", response_class=HTMLResponse)
def new_sub_event_form(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    error: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    err_el = Div(error, cls="alert alert-error") if error else ""

    # Compute eligible robot pool (for informational display)
    eligible_ids = get_sub_event_eligible_robots(event_id, db)
    eligible_robots = [db.query(Robot).filter(Robot.id == rid).first() for rid in eligible_ids]
    eligible_robots = [r for r in eligible_robots if r]

    eligible_info = Div(
        P(
            f"Eligible robot pool: {len(eligible_robots)} robot(s) "
            "(not in bracket + round 1 bracket losers).",
            style="color:#888;font-size:0.85rem;margin-bottom:0.5rem;",
        ),
        Ul(
            *[Li(f"{r.robot_name} ({r.roboteer.roboteer_name})", style="color:#aaa;font-size:0.82rem;") for r in eligible_robots[:20]],
            style="list-style:disc;padding-left:1.2rem;",
        ) if eligible_robots else P("No eligible robots found.", style="color:#555;font-size:0.82rem;"),
    )

    page = Div(
        A("← Event", href=f"/admin/events/{event_id}", cls="btn btn-sm btn-secondary",
          style="margin-bottom:1.2rem;display:inline-block;"),
        H1("New Sub-event"),
        err_el if err_el else "",
        Div(
            HForm(
                Div(
                    Label("Sub-event Name", for_="name"),
                    Input(type="text", id="name", name="name", cls="form-control",
                          placeholder="e.g. 2v2 Team Brawl", required=True, autofocus=True),
                    cls="form-group",
                ),
                Div(
                    Label("Format", for_="format"),
                    Select(
                        Option("2v2 Team Bracket", value="2v2_team_bracket"),
                        id="format", name="format", cls="form-control",
                    ),
                    cls="form-group",
                ),
                Div(
                    Button("Create Sub-event", type="submit", cls="btn btn-primary"),
                    " ",
                    A("Cancel", href=f"/admin/events/{event_id}", cls="btn btn-secondary"),
                    cls="form-group",
                ),
                method="post",
                action=f"/admin/events/{event_id}/sub-events/new",
            ),
            eligible_info,
            cls="card",
        ),
    )
    return _page("New Sub-event", page, user=user)


@router.post("/events/{event_id}/sub-events/new")
def create_sub_event(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    name: str = Form(...),
    format: str = Form(...),
):
    ev = _get_event_or_404(event_id, user.id, db)

    name = name.strip()
    if not name:
        return RedirectResponse(
            f"/admin/events/{event_id}/sub-events/new?error=Name+is+required.", status_code=303
        )

    valid_formats = {f.value for f in SubEventFormat}
    if format not in valid_formats:
        return RedirectResponse(
            f"/admin/events/{event_id}/sub-events/new?error=Invalid+format.", status_code=303
        )

    se = SubEvent(
        event_id=event_id,
        name=name,
        format=SubEventFormat(format),
        status=SubEventStatus.setup,
    )
    db.add(se)
    db.commit()
    return RedirectResponse(
        f"/admin/events/{event_id}/sub-events/{se.id}?msg=sub_event_created", status_code=303
    )


# ---------------------------------------------------------------------------
# 32. Sub-event detail — teams + bracket
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/sub-events/{sub_event_id}", response_class=HTMLResponse)
def sub_event_detail(
    event_id: int,
    sub_event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    msg: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    se = db.query(SubEvent).filter(SubEvent.id == sub_event_id, SubEvent.event_id == event_id).first()
    if not se:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    flash_map = {
        "sub_event_created": ("Sub-event created.", "success"),
        "sub_event_bracket_generated": ("Bracket generated for sub-event.", "success"),
        "sub_event_bracket_advanced": ("Sub-event bracket advanced to next round.", "success"),
        "se_scored": ("Fight result saved.", "success"),
        "se_score_cleared": ("Fight result cleared.", "info"),
        "team_created": ("Team created.", "success"),
        "team_deleted": ("Team removed.", "info"),
    }
    flash = ""
    if msg in flash_map:
        t, k = flash_map[msg]
        flash = Div(t, cls=f"alert alert-{k}")

    teams = (
        db.query(SubEventTeam)
        .filter(SubEventTeam.sub_event_id == sub_event_id)
        .order_by(SubEventTeam.id)
        .all()
    )

    # Detect robots already assigned
    assigned_robot_ids: set[int] = set()
    for t in teams:
        assigned_robot_ids.add(t.robot1_id)
        assigned_robot_ids.add(t.robot2_id)

    eligible_ids = set(get_sub_event_eligible_robots(event_id, db))

    # Build teams table
    if teams:
        team_rows = []
        for t in teams:
            r1_warn = "⚠ ineligible" if t.robot1_id not in eligible_ids else ""
            r2_warn = "⚠ ineligible" if t.robot2_id not in eligible_ids else ""
            team_rows.append(Tr(
                Td(t.team_name, style="font-weight:600;"),
                Td(
                    Span(t.robot1.robot_name),
                    Span(f" {r1_warn}", style="color:#f59e0b;font-size:0.75rem;") if r1_warn else "",
                ),
                Td(
                    Span(t.robot2.robot_name),
                    Span(f" {r2_warn}", style="color:#f59e0b;font-size:0.75rem;") if r2_warn else "",
                ),
                Td(
                    _inline_post_btn(
                        f"/admin/events/{event_id}/sub-events/{sub_event_id}/teams/{t.id}/delete",
                        "Remove",
                        "btn-sm btn-danger",
                    )
                ),
            ))
        teams_table = Div(
            Table(
                Thead(Tr(Th("Team"), Th("Robot 1"), Th("Robot 2"), Th(""))),
                Tbody(*team_rows),
            ),
            cls="table-wrap",
        )
    else:
        teams_table = P("No teams yet. Add teams from the eligible robot pool.", cls="empty")

    # Bracket section
    all_matchups = (
        db.query(SubEventMatchup)
        .filter(SubEventMatchup.sub_event_id == sub_event_id)
        .order_by(SubEventMatchup.round_number, SubEventMatchup.display_order)
        .all()
    )
    has_bracket = bool(all_matchups)

    bracket_section_items = []
    if has_bracket:
        rounds: dict[int, list[SubEventMatchup]] = {}
        for m in all_matchups:
            rounds.setdefault(m.round_number, []).append(m)
        max_round_num = max(rounds.keys())
        for rnd in sorted(rounds.keys()):
            label = _se_round_label(rnd, max_round_num)
            bracket_section_items.append(P(label, cls="bracket-round-header"))
            for m in rounds[rnd]:
                bracket_section_items.append(
                    _sub_event_matchup_card(m, sub_event_id, event_id, show_actions=True)
                )

    # Action buttons
    bracket_actions = []
    if not has_bracket and len(teams) >= 2:
        bracket_actions.append(HForm(
            Button("Generate Bracket", type="submit", cls="btn btn-warning"),
            method="post",
            action=f"/admin/events/{event_id}/sub-events/{sub_event_id}/generate-bracket",
            style="display:inline;",
        ))

    if has_bracket:
        max_round_in_db = max(m.round_number for m in all_matchups)
        current_round_matchups = [m for m in all_matchups if m.round_number == max_round_in_db]
        current_all_done = all(m.status == MatchupStatus.completed for m in current_round_matchups)
        winners_count = sum(1 for m in current_round_matchups if m.winner_team_id)
        if current_all_done and winners_count > 1:
            bracket_actions.append(HForm(
                Button("Generate Next Round →", type="submit", cls="btn btn-warning"),
                method="post",
                action=f"/admin/events/{event_id}/sub-events/{sub_event_id}/bracket/advance",
                style="display:inline;",
            ))
        # Mark sub-event complete if final is done
        if current_all_done and winners_count <= 1 and se.status == SubEventStatus.active:
            bracket_actions.append(HForm(
                Button("Mark Sub-event Complete", type="submit", cls="btn btn-success"),
                method="post",
                action=f"/admin/events/{event_id}/sub-events/{sub_event_id}/complete",
                style="display:inline;",
            ))

    # Teams card actions
    team_card_actions = []
    if se.status == SubEventStatus.setup:
        team_card_actions.append(
            A("+ Add Team", href=f"/admin/events/{event_id}/sub-events/{sub_event_id}/teams/add",
              cls="btn btn-sm btn-primary")
        )

    teams_card = Div(
        Div(
            H2(f"Teams ({len(teams)})"),
            Div(*team_card_actions) if team_card_actions else "",
            cls="card-header",
        ),
        teams_table,
        cls="card",
    )

    bracket_card = Div(
        Div(
            H2("Bracket"),
            Div(*bracket_actions, style="display:flex;gap:0.5rem;") if bracket_actions else "",
            cls="card-header",
        ),
        (Div(*bracket_section_items) if bracket_section_items else P("No bracket yet.", cls="empty")),
        cls="card",
    )

    page = Div(
        A("← Event", href=f"/admin/events/{event_id}", cls="btn btn-sm btn-secondary",
          style="margin-bottom:1.2rem;display:inline-block;"),
        H1(se.name),
        Small(
            Span(se.status.value, cls=f"badge badge-{se.status.value}"),
            f"  ·  {se.format.value}  ·  {ev.event_name}",
            style="color:#888;display:block;margin-bottom:1.2rem;",
        ),
        flash if flash else "",
        teams_card,
        bracket_card,
    )
    return _page(se.name, page, user=user)


@router.post("/events/{event_id}/sub-events/{sub_event_id}/complete")
def complete_sub_event(
    event_id: int,
    sub_event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    _get_event_or_404(event_id, user.id, db)
    se = db.query(SubEvent).filter(SubEvent.id == sub_event_id, SubEvent.event_id == event_id).first()
    if se:
        se.status = SubEventStatus.complete
        db.commit()
    return RedirectResponse(
        f"/admin/events/{event_id}/sub-events/{sub_event_id}?msg=sub_event_complete", status_code=303
    )


# ---------------------------------------------------------------------------
# 32. Team creation
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/sub-events/{sub_event_id}/teams/add", response_class=HTMLResponse)
def add_team_form(
    event_id: int,
    sub_event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    error: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    se = db.query(SubEvent).filter(SubEvent.id == sub_event_id, SubEvent.event_id == event_id).first()
    if not se:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    err_el = Div(error, cls="alert alert-error") if error else ""

    eligible_ids = get_sub_event_eligible_robots(event_id, db)
    eligible_robots = [db.query(Robot).filter(Robot.id == rid).first() for rid in eligible_ids]
    eligible_robots = [r for r in eligible_robots if r]

    # Robots already assigned to a team in this sub-event
    existing_teams = db.query(SubEventTeam).filter(SubEventTeam.sub_event_id == sub_event_id).all()
    already_assigned: set[int] = set()
    for t in existing_teams:
        already_assigned.add(t.robot1_id)
        already_assigned.add(t.robot2_id)

    if not eligible_robots:
        page = Div(
            A("← Sub-event", href=f"/admin/events/{event_id}/sub-events/{sub_event_id}",
              cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
            H1("Add Team"),
            Div("No eligible robots available for this sub-event.", cls="alert alert-info"),
        )
        return _page("Add Team", page, user=user)

    def _robot_option(r: Robot, slot: str) -> Option:
        taken = r.id in already_assigned
        label = f"{r.robot_name} ({r.roboteer.roboteer_name})"
        if taken:
            label += " — already assigned"
        return Option(label, value=str(r.id), **({"disabled": True} if taken else {}))

    options1 = [Option("— Select robot —", value="")] + [_robot_option(r, "r1") for r in eligible_robots]
    options2 = [Option("— Select robot —", value="")] + [_robot_option(r, "r2") for r in eligible_robots]

    if already_assigned:
        assign_note = P(
            f"{len(already_assigned)} robot(s) already assigned to teams in this sub-event (marked above).",
            style="color:#888;font-size:0.82rem;margin-bottom:0.75rem;",
        )
    else:
        assign_note = ""

    page = Div(
        A("← Sub-event", href=f"/admin/events/{event_id}/sub-events/{sub_event_id}",
          cls="btn btn-sm btn-secondary", style="margin-bottom:1.2rem;display:inline-block;"),
        H1("Add Team"),
        err_el if err_el else "",
        Div(
            assign_note,
            HForm(
                Div(
                    Label("Team Name", for_="team_name"),
                    Input(type="text", id="team_name", name="team_name", cls="form-control",
                          placeholder="e.g. Team Chaos", required=True, autofocus=True),
                    cls="form-group",
                ),
                Div(
                    Label("Robot 1", for_="robot1_id"),
                    Select(*options1, id="robot1_id", name="robot1_id",
                           cls="form-control", required=True),
                    cls="form-group",
                ),
                Div(
                    Label("Robot 2", for_="robot2_id"),
                    Select(*options2, id="robot2_id", name="robot2_id",
                           cls="form-control", required=True),
                    cls="form-group",
                ),
                Div(
                    Button("Add Team", type="submit", cls="btn btn-primary"),
                    " ",
                    A("Cancel", href=f"/admin/events/{event_id}/sub-events/{sub_event_id}",
                      cls="btn btn-secondary"),
                    cls="form-group",
                ),
                method="post",
                action=f"/admin/events/{event_id}/sub-events/{sub_event_id}/teams/add",
            ),
            cls="card",
        ),
    )
    return _page("Add Team", page, user=user)


@router.post("/events/{event_id}/sub-events/{sub_event_id}/teams/add")
def add_team(
    event_id: int,
    sub_event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    team_name: str = Form(...),
    robot1_id: int = Form(...),
    robot2_id: int = Form(...),
):
    _get_event_or_404(event_id, user.id, db)
    se = db.query(SubEvent).filter(SubEvent.id == sub_event_id, SubEvent.event_id == event_id).first()
    if not se:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    team_name = team_name.strip()
    if not team_name:
        return RedirectResponse(
            f"/admin/events/{event_id}/sub-events/{sub_event_id}/teams/add?error=Team+name+required.",
            status_code=303,
        )

    if robot1_id == robot2_id:
        return RedirectResponse(
            f"/admin/events/{event_id}/sub-events/{sub_event_id}/teams/add?error=Robot+1+and+Robot+2+must+be+different.",
            status_code=303,
        )

    # Check that robots aren't already assigned to a team in this sub-event
    existing = db.query(SubEventTeam).filter(SubEventTeam.sub_event_id == sub_event_id).all()
    already_assigned = {t.robot1_id for t in existing} | {t.robot2_id for t in existing}
    conflicts = [rid for rid in (robot1_id, robot2_id) if rid in already_assigned]
    if conflicts:
        names = [db.query(Robot).filter(Robot.id == rid).first() for rid in conflicts]
        names_str = ", ".join(r.robot_name for r in names if r)
        return RedirectResponse(
            f"/admin/events/{event_id}/sub-events/{sub_event_id}/teams/add"
            f"?error={names_str}+already+assigned+to+a+team.",
            status_code=303,
        )

    # Check robots are valid robots
    r1 = db.query(Robot).filter(Robot.id == robot1_id).first()
    r2 = db.query(Robot).filter(Robot.id == robot2_id).first()
    if not r1 or not r2:
        return RedirectResponse(
            f"/admin/events/{event_id}/sub-events/{sub_event_id}/teams/add?error=Invalid+robot+selection.",
            status_code=303,
        )

    db.add(SubEventTeam(
        sub_event_id=sub_event_id,
        team_name=team_name,
        robot1_id=robot1_id,
        robot2_id=robot2_id,
    ))
    db.commit()
    return RedirectResponse(
        f"/admin/events/{event_id}/sub-events/{sub_event_id}?msg=team_created", status_code=303
    )


@router.post("/events/{event_id}/sub-events/{sub_event_id}/teams/{team_id}/delete")
def delete_team(
    event_id: int,
    sub_event_id: int,
    team_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    _get_event_or_404(event_id, user.id, db)
    team = db.query(SubEventTeam).filter(
        SubEventTeam.id == team_id,
        SubEventTeam.sub_event_id == sub_event_id,
    ).first()
    if team:
        db.delete(team)
        db.commit()
    return RedirectResponse(
        f"/admin/events/{event_id}/sub-events/{sub_event_id}?msg=team_deleted", status_code=303
    )


# ---------------------------------------------------------------------------
# 33. Generate sub-event bracket
# ---------------------------------------------------------------------------


@router.post("/events/{event_id}/sub-events/{sub_event_id}/generate-bracket")
def generate_sub_event_bracket(
    event_id: int,
    sub_event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    _get_event_or_404(event_id, user.id, db)
    se = db.query(SubEvent).filter(SubEvent.id == sub_event_id, SubEvent.event_id == event_id).first()
    if not se:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    # Don't regenerate if already has matchups
    existing = db.query(SubEventMatchup).filter(SubEventMatchup.sub_event_id == sub_event_id).first()
    if existing:
        return RedirectResponse(
            f"/admin/events/{event_id}/sub-events/{sub_event_id}?msg=sub_event_bracket_generated",
            status_code=303,
        )

    teams = db.query(SubEventTeam).filter(SubEventTeam.sub_event_id == sub_event_id).all()
    if len(teams) < 2:
        return RedirectResponse(
            f"/admin/events/{event_id}/sub-events/{sub_event_id}"
            f"?msg=error&error=Need+at+least+2+teams+to+generate+a+bracket.",
            status_code=303,
        )

    create_sub_event_bracket(sub_event_id, event_id, db)
    se.status = SubEventStatus.active
    db.commit()
    return RedirectResponse(
        f"/admin/events/{event_id}/sub-events/{sub_event_id}?msg=sub_event_bracket_generated",
        status_code=303,
    )


@router.post("/events/{event_id}/sub-events/{sub_event_id}/bracket/advance")
def advance_sub_event_bracket_route(
    event_id: int,
    sub_event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    _get_event_or_404(event_id, user.id, db)
    se = db.query(SubEvent).filter(SubEvent.id == sub_event_id, SubEvent.event_id == event_id).first()
    if not se:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    max_round = (
        db.query(func.max(SubEventMatchup.round_number))
        .filter(SubEventMatchup.sub_event_id == sub_event_id)
        .scalar()
    ) or 1

    new_matchups = advance_sub_event_bracket(sub_event_id, max_round, event_id, db)
    if not new_matchups:
        return RedirectResponse(
            f"/admin/events/{event_id}/sub-events/{sub_event_id}"
            f"?msg=error&error=Cannot+advance:+round+not+fully+complete+or+tournament+over.",
            status_code=303,
        )

    db.commit()
    return RedirectResponse(
        f"/admin/events/{event_id}/sub-events/{sub_event_id}?msg=sub_event_bracket_advanced",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# 35. Sub-event fight result entry
# ---------------------------------------------------------------------------


@router.get(
    "/events/{event_id}/sub-events/{sub_event_id}/matchups/{matchup_id}/score",
    response_class=HTMLResponse,
)
def sub_event_score_form(
    event_id: int,
    sub_event_id: int,
    matchup_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    error: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    se = db.query(SubEvent).filter(SubEvent.id == sub_event_id, SubEvent.event_id == event_id).first()
    m = db.query(SubEventMatchup).filter(
        SubEventMatchup.id == matchup_id,
        SubEventMatchup.sub_event_id == sub_event_id,
    ).first()
    if not se or not m or m.team2_id is None:
        return RedirectResponse(f"/admin/events/{event_id}/sub-events/{sub_event_id}", status_code=303)

    t1: SubEventTeam = m.team1
    t2: SubEventTeam = m.team2

    err_el = Div(error, cls="alert alert-error") if error else ""

    existing_result = ""
    if m.status == MatchupStatus.completed and m.winner_team_id:
        winner = t1 if m.winner_team_id == t1.id else t2
        existing_result = Div(
            P(
                f"Current result: {winner.team_name} wins",
                style="color:#4ade80;font-size:0.9rem;margin-bottom:0.75rem;",
            ),
            HForm(
                Button("Clear result", type="submit", cls="btn btn-danger btn-sm"),
                method="post",
                action=f"/admin/events/{event_id}/sub-events/{sub_event_id}/matchups/{matchup_id}/clear-score",
            ),
            style="margin-bottom:1rem;padding-bottom:1rem;border-bottom:1px solid #2a2a2a;",
        )

    back = f"/admin/events/{event_id}/sub-events/{sub_event_id}"
    form_title = "Edit Fight" if m.status == MatchupStatus.completed else "Score Fight"

    def _team_desc(t: SubEventTeam) -> str:
        return f"{t.team_name}  ({t.robot1.robot_name} & {t.robot2.robot_name})"

    page = Div(
        A(f"← {se.name}", href=back, cls="btn btn-sm btn-secondary",
          style="margin-bottom:1.2rem;display:inline-block;"),
        H1(form_title),
        err_el if err_el else "",
        Div(
            P(
                Span(t1.team_name, style="font-weight:700;"),
                Span(" vs ", style="color:#555;"),
                Span(t2.team_name, style="font-weight:700;"),
                style="font-size:1rem;margin-bottom:0.5rem;",
            ),
            P(
                Span(_team_desc(t1), style="color:#888;font-size:0.82rem;"),
                Span(" vs ", style="color:#555;font-size:0.82rem;"),
                Span(_team_desc(t2), style="color:#888;font-size:0.82rem;"),
                style="margin-bottom:1rem;",
            ),
            existing_result,
            HForm(
                Div(
                    Label("Winner", for_="winner_team_id"),
                    Select(
                        Option(f"— Select winner —", value=""),
                        Option(t1.team_name, value=str(t1.id)),
                        Option(t2.team_name, value=str(t2.id)),
                        id="winner_team_id",
                        name="winner_team_id",
                        cls="form-control",
                        required=True,
                    ),
                    cls="form-group",
                ),
                Div(
                    Button("Save Result", type="submit", cls="btn btn-primary"),
                    " ",
                    A("Cancel", href=back, cls="btn btn-secondary"),
                    cls="form-group",
                ),
                method="post",
                action=f"/admin/events/{event_id}/sub-events/{sub_event_id}/matchups/{matchup_id}/score",
            ),
            cls="card",
        ),
    )
    return _page(form_title, page, user=user)


@router.post("/events/{event_id}/sub-events/{sub_event_id}/matchups/{matchup_id}/score")
def sub_event_submit_score(
    event_id: int,
    sub_event_id: int,
    matchup_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    winner_team_id: int = Form(...),
):
    _get_event_or_404(event_id, user.id, db)
    se = db.query(SubEvent).filter(SubEvent.id == sub_event_id, SubEvent.event_id == event_id).first()
    m = db.query(SubEventMatchup).filter(
        SubEventMatchup.id == matchup_id,
        SubEventMatchup.sub_event_id == sub_event_id,
    ).first()
    if not se or not m or m.team2_id is None:
        return RedirectResponse(f"/admin/events/{event_id}/sub-events/{sub_event_id}", status_code=303)

    valid_winner_ids = {m.team1_id, m.team2_id}
    if winner_team_id not in valid_winner_ids:
        return RedirectResponse(
            f"/admin/events/{event_id}/sub-events/{sub_event_id}/matchups/{matchup_id}/score"
            f"?error=Invalid+winner+selection.",
            status_code=303,
        )

    m.winner_team_id = winner_team_id
    m.status = MatchupStatus.completed
    db.commit()
    return RedirectResponse(
        f"/admin/events/{event_id}/sub-events/{sub_event_id}?msg=se_scored", status_code=303
    )


@router.post("/events/{event_id}/sub-events/{sub_event_id}/matchups/{matchup_id}/clear-score")
def sub_event_clear_score(
    event_id: int,
    sub_event_id: int,
    matchup_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    _get_event_or_404(event_id, user.id, db)
    m = db.query(SubEventMatchup).filter(
        SubEventMatchup.id == matchup_id,
        SubEventMatchup.sub_event_id == sub_event_id,
    ).first()
    if m:
        m.winner_team_id = None
        m.status = MatchupStatus.pending
        db.commit()
    return RedirectResponse(
        f"/admin/events/{event_id}/sub-events/{sub_event_id}?msg=se_score_cleared", status_code=303
    )


# ---------------------------------------------------------------------------
# 34. Unified run-order editor (Phase 5b)
# ---------------------------------------------------------------------------


@router.get("/events/{event_id}/run-order", response_class=HTMLResponse)
def run_order_editor(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    msg: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)

    flash = Div("Run order saved.", cls="alert alert-success") if msg == "saved" else ""

    run_order_rows = (
        db.query(RunOrder)
        .filter(RunOrder.event_id == event_id)
        .order_by(RunOrder.slot_index)
        .all()
    )

    items = []
    for ro in run_order_rows:
        if ro.matchup_type == RunOrderMatchupType.main:
            m = db.query(Matchup).filter(Matchup.id == ro.matchup_id).first()
            if not m:
                continue
            r1_name = m.robot1.robot_name if m.robot1 else "?"
            r2_name = m.robot2.robot_name if m.robot2 else "BYE"
            phase: Phase = m.phase
            if phase.phase_type == PhaseType.qualifying:
                context = f"Q{phase.phase_number}"
            else:
                context = f"Bracket R{m.bracket_round or '?'}"
            label = Span(
                Span(context, cls="badge badge-qualifying" if phase.phase_type == PhaseType.qualifying else "badge-bracket",
                     style="margin-right:0.5rem;font-size:0.72rem;"),
                Strong(r1_name),
                Span(" vs " if m.robot2_id else " — ", cls="matchup-vs"),
                Strong(r2_name if m.robot2_id else "BYE"),
                cls="matchup-robots",
            )
            is_done = m.status == MatchupStatus.completed
        else:
            m = db.query(SubEventMatchup).filter(SubEventMatchup.id == ro.matchup_id).first()
            if not m:
                continue
            t1_name = m.team1.team_name if m.team1 else "?"
            t2_name = m.team2.team_name if m.team2 else "BYE"
            se_name = m.sub_event.name if m.sub_event else "Sub-event"
            label = Span(
                Span(f"SE R{m.round_number}", cls="badge badge-sub_events",
                     style="margin-right:0.5rem;font-size:0.72rem;"),
                Small(f"[{se_name}] ", style="color:#888;"),
                Strong(t1_name),
                Span(" vs " if m.team2_id else " — ", cls="matchup-vs"),
                Strong(t2_name if m.team2_id else "BYE"),
                cls="matchup-robots",
            )
            is_done = m.status == MatchupStatus.completed

        result_el = (
            Span("✓ Done", cls="matchup-result-label")
            if is_done
            else Span("pending", cls="matchup-result-pending")
        )
        drag = Span("⠿", cls="drag-handle", title="Drag to reorder") if not is_done else Span("", style="width:1.1rem;display:inline-block;")

        items.append(Li(
            drag,
            label,
            result_el,
            cls="matchup-item" + (" is-bye" if is_done else ""),
            data_ro_id=str(ro.id),
            style="opacity:0.5;" if is_done else "",
        ))

    sort_script = Script(src=_SORTABLEJS)
    sort_init = Script(f"""
document.addEventListener('DOMContentLoaded', function() {{
    var el = document.getElementById('run-order-list');
    if (!el) return;
    Sortable.create(el, {{
        animation: 150,
        handle: '.drag-handle',
        filter: '.is-bye',
        onEnd: function() {{
            var order = Array.from(el.querySelectorAll('.matchup-item:not(.is-bye)'))
                            .map(function(e) {{ return e.dataset.roId; }});
            fetch('/admin/events/{event_id}/run-order/reorder', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{order: order}})
            }});
        }}
    }});
}});
""")

    page = Div(
        A("← Event", href=f"/admin/events/{event_id}", cls="btn btn-sm btn-secondary",
          style="margin-bottom:1.2rem;display:inline-block;"),
        H1("Run Order"),
        Small(f"{ev.event_name}  ·  Drag pending fights to set the order.",
              style="color:#888;display:block;margin-bottom:1.2rem;"),
        flash if flash else "",
        Div(
            Ul(*items, id="run-order-list", cls="matchup-list")
            if items
            else P("No fights in the run order yet.", cls="empty"),
            cls="card",
        ),
        sort_script,
        sort_init,
    )
    return _page("Run Order", page, user=user)


@router.post("/events/{event_id}/run-order/reorder")
async def reorder_run_order(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
):
    """AJAX endpoint — receives JSON {order: [ro_id, ...]} and renumbers slot_index."""
    _get_event_or_404(event_id, user.id, db)
    try:
        body = await request.json()
        order: list[str] = body.get("order", [])
    except Exception:
        return JSONResponse({"ok": False}, status_code=400)

    # Fetch all RunOrder rows for this event (to preserve completed-fight positions)
    all_rows = (
        db.query(RunOrder)
        .filter(RunOrder.event_id == event_id)
        .order_by(RunOrder.slot_index)
        .all()
    )

    # Build a map of id → row for quick lookup
    ro_map = {ro.id: ro for ro in all_rows}

    # Collect the RunOrder IDs we're reordering (pending fights only)
    reorder_ids = []
    for id_str in order:
        try:
            reorder_ids.append(int(id_str))
        except ValueError:
            continue

    # Assign new contiguous slot_index values to the reordered pending rows,
    # while preserving the relative positions of completed rows.
    # Strategy: gather current slot values for pending rows, sorted; map new order onto those slots.
    pending_slots = sorted(
        ro_map[rid].slot_index for rid in reorder_ids if rid in ro_map
    )

    for new_pos, ro_id in enumerate(reorder_ids):
        if ro_id in ro_map and new_pos < len(pending_slots):
            ro_map[ro_id].slot_index = pending_slots[new_pos]

    db.commit()
    return JSONResponse({"ok": True})
