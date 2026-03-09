"""Organizer-only admin routes — Phase 4 & 5: Event Management, Import, Matching & Scoring."""

import mimetypes
import os
import re
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from admin_roster import (
    active_event_robots,
    active_robot_count,
    event_robot_entry,
    ordered_event_phases,
    ordered_sub_events,
    qualifying_phases,
    renumber_reserves,
    reserve_event_robots,
    round_one_complete,
)
from auth import get_valid_access_token, require_organizer
from config import UPLOAD_DIR
from database import get_db
from event_imports import (
    import_selected_event_registrations,
    load_registrations,
    next_reserve_order,
    refresh_event_registrations,
)
from google_sheets import fetch_sheet_rows
from matching import (
    activate_next_qualifying_round,
    advance_bracket_round,
    advance_sub_event_bracket,
    create_bracket,
    create_qualifying_round,
    create_qualifying_schedule,
    create_sub_event_bracket,
    get_active_robot_ids,
    get_qualifying_bye_counts,
    get_sub_event_eligible_robots,
    qualifying_standings,
    set_incomplete_qualifying_round_state,
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
from robot_images import robot_display_image_url
from ui import HTMX_SCRIPT_URL, render_template

router = APIRouter(prefix="/admin")

# ---------------------------------------------------------------------------
# Shared page state
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

    success_message = ""
    info_message = ""
    if msg == "created":
        success_message = "Event created successfully."
    elif msg == "deleted":
        info_message = "Event removed."

    event_rows = []
    if events:
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
            event_rows.append(
                {
                    "id": ev.id,
                    "event_name": ev.event_name,
                    "weight_class": ev.weight_class,
                    "status": ev.status,
                    "active_count": active_count,
                    "reserve_count": reserve_count,
                }
            )

    return render_template(
        request,
        "admin/events/dashboard.html",
        title="Dashboard",
        context={
            "user": user,
            "events": event_rows,
            "error_message": "",
            "success_message": success_message,
            "info_message": info_message,
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


# ---------------------------------------------------------------------------
# 2. Event creation
# ---------------------------------------------------------------------------


@router.get("/events/new", response_class=HTMLResponse)
def new_event_form(
    request: Request,
    user: User = Depends(require_organizer),
    error: str = Query(default=""),
):
    return render_template(
        request,
        "admin/events/new.html",
        title="New Event",
        context={
            "user": user,
            "error_message": error,
            "success_message": "",
            "info_message": "",
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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
    error: str = Query(default=""),
    img_warn: list[str] = Query(default=[]),
):
    ev = _get_event_or_404(event_id, user.id, db)

    flash_map = {
        "created": ("Event created.", "success"),
        "imported": ("Robots imported successfully.", "success"),
        "refreshed": ("Sheet refreshed — new robots imported.", "success"),
        "refresh_error": ("Unable to refresh from the saved Google Sheet.", "error"),
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
    error_message = ""
    success_message = ""
    info_message = ""
    if msg in flash_map:
        text, kind = flash_map[msg]
        if kind == "error":
            error_message = text
        elif kind == "success":
            success_message = text
        elif kind == "info":
            info_message = text
    if error:
        error_message = error
    elif msg == "error":
        error_message = "Unable to complete that action."

    warning_message = ""
    warning_items: list[str] = []
    if img_warn:
        warning_message = (
            "Some robot images could not be downloaded; the original sheet URLs were kept instead."
        )
        warning_items = img_warn

    active_ers = active_event_robots(event_id, db)
    reserve_ers = reserve_event_robots(event_id, db)
    phases = ordered_event_phases(event_id, db)

    next_status = _NEXT_STATUS.get(ev.status)
    qual_phases = qualifying_phases(phases)
    bracket_phase = next((ph for ph in phases if ph.phase_type == PhaseType.bracket), None)
    num_complete_qual = sum(1 for ph in qual_phases if ph.status == PhaseStatus.complete)

    phase_actions: list[dict[str, str]] = []
    if ev.status == EventStatus.qualifying:
        max_qual = max((ph.phase_number for ph in qual_phases), default=0)
        last_qual = next((ph for ph in qual_phases if ph.phase_number == max_qual), None)
        last_all_done = last_qual is not None and all(
            m.status == MatchupStatus.completed for m in last_qual.matchups
        )
        if last_qual is None or (last_qual.status == PhaseStatus.complete and max_qual < 3):
            next_round = max_qual + 1
            phase_actions.append({
                "label": f"Generate Round {next_round}",
                "action": f"/admin/events/{event_id}/qualifying/generate",
                "button_class": "btn btn-primary btn-sm",
            })
        if last_qual and last_all_done and last_qual.status == PhaseStatus.active:
            phase_actions.append({
                "label": f"Complete Round {max_qual}",
                "action": f"/admin/events/{event_id}/phases/{last_qual.id}/complete",
                "button_class": "btn btn-success btn-sm",
            })
        if num_complete_qual >= 3 and not bracket_phase:
            phase_actions.append({
                "label": "Generate Bracket (Top 16)",
                "action": f"/admin/events/{event_id}/bracket/generate",
                "button_class": "btn btn-warning btn-sm",
            })

    sub_events = ordered_sub_events(event_id, db)
    r1_done = round_one_complete(bracket_phase)
    can_create_sub_event = r1_done or ev.status in (EventStatus.sub_events, EventStatus.complete)

    active_robots = [_roster_row_context(er, event_id, phases, is_reserve=False) for er in active_ers]
    reserve_robots = [
        _roster_row_context(
            er,
            event_id,
            phases,
            is_reserve=True,
            position=index,
            total_reserves=len(reserve_ers),
        )
        for index, er in enumerate(reserve_ers)
    ]

    phase_rows = []
    for ph in phases:
        total_matchups = len(ph.matchups)
        completed_matchups = sum(1 for matchup in ph.matchups if matchup.status == MatchupStatus.completed)
        if ph.phase_type == PhaseType.qualifying:
            label = f"Qualifying Round {ph.phase_number}"
            manage_href = f"/admin/events/{event_id}/phases/{ph.id}"
            manage_label = "Manage"
        else:
            label = "Bracket"
            manage_href = f"/admin/events/{event_id}/bracket"
            manage_label = "Manage Bracket"
        phase_rows.append({
            "label": label,
            "status": ph.status,
            "progress": f"{completed_matchups}/{total_matchups}",
            "manage_href": manage_href,
            "manage_label": manage_label,
        })

    sub_event_rows = []
    for sub_event in sub_events:
        team_count = db.query(SubEventTeam).filter(SubEventTeam.sub_event_id == sub_event.id).count()
        sub_event_rows.append({
            "id": sub_event.id,
            "name": sub_event.name,
            "format": sub_event.format.value,
            "status": sub_event.status,
            "team_count": team_count,
        })

    return render_template(
        request,
        "admin/events/detail.html",
        title=ev.event_name,
        context={
            "user": user,
            "event": ev,
            "error_message": error_message,
            "success_message": success_message,
            "info_message": info_message,
            "warning_message": warning_message,
            "warning_items": warning_items,
            "show_transition": next_status is not None,
            "transition_label": _TRANSITION_LABELS.get(ev.status, ""),
            "active_robots": active_robots,
            "reserve_robots": reserve_robots,
            "phase_actions": phase_actions,
            "phases": phase_rows,
            "sub_events": sub_event_rows,
            "can_create_sub_event": can_create_sub_event,
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )
def _roster_row_context(
    er: EventRobot,
    event_id: int,
    phases: list,
    *,
    is_reserve: bool,
    position: int = 0,
    total_reserves: int = 0,
) -> dict[str, object]:
    robot: Robot = er.robot
    return {
        "entry_id": er.id,
        "robot_id": robot.id,
        "robot_name": robot.robot_name,
        "roboteer_name": robot.roboteer.roboteer_name,
        "weapon_type": robot.weapon_type or "—",
        "image_url": robot_display_image_url(robot),
        "image_alt": robot.robot_name,
        "is_reserve": is_reserve,
        "position": position + 1,
        "can_retire": bool(phases) and not is_reserve,
        "can_move_up": is_reserve and position > 0,
        "can_move_down": is_reserve and position < total_reserves - 1,
        "event_id": event_id,
    }
def _flash_context(
    msg: str,
    flash_map: dict[str, tuple[str, str]],
    *,
    error: str = "",
    fallback_error: str = "",
) -> dict[str, str]:
    error_message = ""
    success_message = ""
    info_message = ""

    if msg in flash_map:
        text, kind = flash_map[msg]
        if kind == "error":
            error_message = text
        elif kind == "success":
            success_message = text
        elif kind == "info":
            info_message = text

    if error:
        error_message = error
    elif msg == "error" and fallback_error:
        error_message = fallback_error

    return {
        "error_message": error_message,
        "success_message": success_message,
        "info_message": info_message,
    }


def _points_for_matchup_robot(matchup: Matchup, robot_id: int | None) -> int | None:
    if robot_id is None:
        return None
    result = next((item for item in matchup.results if item.robot_id == robot_id), None)
    return result.points_scored if result else 0


def _outcome_code_for_points(r1_pts: int, r2_pts: int) -> str:
    for code, _label in FIGHT_OUTCOMES:
        code_r1_pts, code_r2_pts = outcome_to_points(code)
        if (code_r1_pts, code_r2_pts) == (r1_pts, r2_pts):
            return code
    return ""


def _phase_matchup_context(matchup: Matchup, event_id: int, phase: Phase) -> dict[str, object]:
    robot1 = matchup.robot1
    robot2 = matchup.robot2
    is_bye = robot2 is None
    r1_pts = _points_for_matchup_robot(matchup, robot1.id)
    r2_pts = _points_for_matchup_robot(matchup, robot2.id if robot2 else None)

    if is_bye:
        status_text = f"+{BYE_POINTS} pts (bye)" if matchup.status == MatchupStatus.completed else "Bye pending"
    elif matchup.status == MatchupStatus.completed and r1_pts is not None and r2_pts is not None:
        status_text = f"{points_to_outcome_label(r1_pts, r2_pts)} ({r1_pts}-{r2_pts})"
    else:
        status_text = "Pending"

    can_score = robot2 is not None and phase.status == PhaseStatus.active
    can_complete_bye = is_bye and matchup.status == MatchupStatus.pending and phase.status == PhaseStatus.active

    return {
        "id": matchup.id,
        "robot1_name": robot1.robot_name,
        "robot2_name": robot2.robot_name if robot2 else "BYE",
        "is_bye": is_bye,
        "is_completed": matchup.status == MatchupStatus.completed,
        "status_text": status_text,
        "score_href": f"/admin/events/{event_id}/matchups/{matchup.id}/score" if can_score else "",
        "score_label": "Edit" if matchup.status == MatchupStatus.completed else "Score",
        "complete_bye_action": f"/admin/events/{event_id}/matchups/{matchup.id}/complete-bye" if can_complete_bye else "",
        "show_drag_handle": phase.status == PhaseStatus.active,
    }


def _score_option_context(matchup: Matchup) -> list[dict[str, str]]:
    robot1 = matchup.robot1
    robot2 = matchup.robot2
    selected_code = ""

    if matchup.status == MatchupStatus.completed:
        r1_pts = _points_for_matchup_robot(matchup, robot1.id) or 0
        r2_pts = _points_for_matchup_robot(matchup, robot2.id if robot2 else None) or 0
        selected_code = _outcome_code_for_points(r1_pts, r2_pts)

    options = []
    for code, label in FIGHT_OUTCOMES:
        display = label.replace("Robot 1", robot1.robot_name).replace(
            "Robot 2", robot2.robot_name if robot2 else "Robot 2"
        )
        options.append({
            "value": code,
            "label": display,
            "selected": code == selected_code,
        })
    return options


def _bracket_matchup_context(matchup: Matchup, event_id: int) -> dict[str, object]:
    robot1 = matchup.robot1
    robot2 = matchup.robot2
    r1_pts = _points_for_matchup_robot(matchup, robot1.id)
    r2_pts = _points_for_matchup_robot(matchup, robot2.id if robot2 else None)

    robot1_winner = False
    robot2_winner = False
    if matchup.status == MatchupStatus.completed:
        if robot2 is None:
            robot1_winner = True
        elif r1_pts is not None and r2_pts is not None:
            robot1_winner = r1_pts >= r2_pts
            robot2_winner = r2_pts > r1_pts

    return {
        "id": matchup.id,
        "robot1": {
            "name": robot1.robot_name,
            "href": f"/events/{event_id}/robot/{robot1.id}",
            "points": r1_pts,
            "is_winner": robot1_winner,
        },
        "robot2": {
            "name": robot2.robot_name if robot2 else "TBD",
            "href": f"/events/{event_id}/robot/{robot2.id}" if robot2 else "",
            "points": r2_pts,
            "is_winner": robot2_winner,
            "is_tbd": robot2 is None,
        },
        "is_completed": matchup.status == MatchupStatus.completed,
        "action_href": f"/admin/events/{event_id}/matchups/{matchup.id}/score",
        "action_label": "Edit" if matchup.status == MatchupStatus.completed else "Score",
    }


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
    return render_template(
        request,
        "admin/events/import.html",
        title="Import Robots",
        context={
            "user": user,
            "event": ev,
            "error_message": error,
            "success_message": "",
            "info_message": "",
            "warning_message": "",
            "warning_items": [],
            "has_sheet_url": bool(ev.google_sheet_url),
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


@router.get("/events/{event_id}/import/preview", response_class=HTMLResponse)
def import_preview(
    event_id: int,
    request: Request,
    user: User = Depends(require_organizer),
    db: Session = Depends(get_db),
    sheet_url: str = Query(default=""),
):
    """HTMX endpoint — returns the preview table fragment for the import page."""
    _get_event_or_404(event_id, user.id, db)

    preview_context = {
        "event_id": event_id,
        "sheet_url": sheet_url,
        "preview_rows": [],
        "registration_count": 0,
        "message_kind": "",
        "message_text": "",
    }

    if not sheet_url:
        preview_context["message_kind"] = "error"
        preview_context["message_text"] = "Please enter a Google Sheet URL above."
        return render_template(
            request,
            "admin/partials/import_preview.html",
            title="Import Preview",
            context=preview_context,
        )

    try:
        access_token = get_valid_access_token(user, db)
        rows = fetch_sheet_rows(sheet_url, access_token)
    except ValueError as exc:
        preview_context["message_kind"] = "error"
        preview_context["message_text"] = f"Error: {exc}"
        return render_template(
            request,
            "admin/partials/import_preview.html",
            title="Import Preview",
            context=preview_context,
        )
    except Exception as exc:
        preview_context["message_kind"] = "error"
        preview_context["message_text"] = f"Could not fetch sheet: {exc}"
        return render_template(
            request,
            "admin/partials/import_preview.html",
            title="Import Preview",
            context=preview_context,
        )

    if not rows:
        preview_context["message_kind"] = "info"
        preview_context["message_text"] = "Sheet is empty or has no data rows."
        return render_template(
            request,
            "admin/partials/import_preview.html",
            title="Import Preview",
            context=preview_context,
        )

    _, registrations = load_registrations(rows, sheet_url)

    if not registrations:
        preview_context["message_kind"] = "info"
        preview_context["message_text"] = (
            "No valid robot registrations found. The sheet must have 'Roboteer Name' "
            "and 'Robot Name' columns."
        )
        return render_template(
            request,
            "admin/partials/import_preview.html",
            title="Import Preview",
            context=preview_context,
        )

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
            status_text = "already in event"
            status_class = "preview-status-dup"
        elif row_id in existing_row_ids:
            status_text = "robot exists (will link)"
            status_class = "preview-status-dup"
        else:
            status_text = "new"
            status_class = "preview-status-new"

        table_rows.append(
            {
                "row_id": row_id,
                "roboteer_name": reg["roboteer_name"],
                "robot_name": reg["robot_name"],
                "weapon_type": reg.get("weapon_type") or "—",
                "image_url": reg.get("image_url") or "—",
                "status_text": status_text,
                "status_class": status_class,
                "import_checked": not in_event,
                "import_disabled": in_event,
            }
        )

    preview_context.update(
        {
            "preview_rows": table_rows,
            "registration_count": len(registrations),
        }
    )
    return render_template(
        request,
        "admin/partials/import_preview.html",
        title="Import Preview",
        context=preview_context,
    )


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

    _, registrations = load_registrations(rows, sheet_url)
    image_warnings: list[str] = []
    import_selected_event_registrations(
        event_id,
        registrations,
        row_ids,
        reserve_ids,
        db,
        import_image=_image_importer_with_warnings(access_token, image_warnings),
    )

    db.commit()
    return RedirectResponse(
        _event_redirect_url(event_id, "imported", image_warnings),
        status_code=303,
    )


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

    _, registrations = load_registrations(rows, ev.google_sheet_url)
    image_warnings: list[str] = []
    refresh_event_registrations(
        event_id,
        registrations,
        db,
        import_image=_image_importer_with_warnings(access_token, image_warnings),
    )

    db.commit()
    return RedirectResponse(
        _event_redirect_url(event_id, "refreshed", image_warnings),
        status_code=303,
    )


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
        active_count = active_robot_count(event_id, db)
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

    # Pre-generate all three qualifying rounds so the schedule is visible up front.
    if next_status == EventStatus.qualifying:
        create_qualifying_schedule(event_id, 3, db)

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
    return render_template(
        request,
        "admin/events/add_robot.html",
        title="Add Robot",
        context={
            "user": user,
            "event": ev,
            "error_message": error,
            "success_message": "",
            "info_message": "",
            "warning_message": "",
            "warning_items": [],
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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
        res_order = next_reserve_order(event_id, db)

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
    er = event_robot_entry(event_id, er_id, db)
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
    er = event_robot_entry(event_id, er_id, db)
    if er and not er.is_reserve:
        er.is_reserve = True
        er.reserve_order = next_reserve_order(event_id, db)
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
    er = event_robot_entry(event_id, er_id, db)
    if er and er.is_reserve:
        er.is_reserve = False
        er.reserve_order = None
        db.flush()
        renumber_reserves(event_id, db)
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
    er = event_robot_entry(event_id, er_id, db)
    if not er or not er.is_reserve:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    all_reserves = reserve_event_robots(event_id, db)
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
    er = event_robot_entry(event_id, er_id, db)
    if not er:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    robot: Robot = er.robot
    phases = ordered_event_phases(event_id, db)
    reserves = reserve_event_robots(event_id, db)

    info_message = ""
    if not phases:
        info_message = (
            "Retirement can only be recorded once qualifying phases have been created (Phase 5). "
            "You can still remove robots from the roster using the Remove button."
        )

    return render_template(
        request,
        "admin/events/retire.html",
        title="Retire Robot",
        context={
            "user": user,
            "event": ev,
            "robot": robot,
            "entry_id": er_id,
            "error_message": error,
            "success_message": "",
            "info_message": info_message,
            "warning_message": "",
            "warning_items": [],
            "show_form": bool(phases),
            "phase_options": [
                {"id": ph.id, "label": f"Phase {ph.phase_number} ({ph.phase_type.value})"}
                for ph in phases
            ],
            "reserve_options": [
                {"id": r.id, "label": f"{r.robot.robot_name} (#{i + 1})"}
                for i, r in enumerate(reserves)
            ],
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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
    er = event_robot_entry(event_id, er_id, db)
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
            renumber_reserves(event_id, db)
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
    return render_template(
        request,
        "admin/events/upload_image.html",
        title="Upload Image",
        context={
            "user": user,
            "event": ev,
            "robot": robot,
            "error_message": error,
            "success_message": "",
            "info_message": "",
            "warning_message": "",
            "warning_items": [],
            "current_image_url": robot.image_url or "",
            "default_image_url": robot.image_url if robot.image_source == ImageSource.sheet else "",
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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


def _google_drive_file_id(image_url: str) -> str | None:
    """Extract a Google Drive file id from common sharing URL formats."""
    parsed = urlparse(image_url)
    query_id = parse_qs(parsed.query).get("id")
    if query_id:
        return query_id[0]

    for pattern in (
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"/document/d/([a-zA-Z0-9_-]+)",
        r"/spreadsheets/d/([a-zA-Z0-9_-]+)",
        r"/presentation/d/([a-zA-Z0-9_-]+)",
    ):
        match = re.search(pattern, parsed.path)
        if match:
            return match.group(1)

    return None


def _event_redirect_url(event_id: int, msg: str, image_warnings: list[str] | None = None) -> str:
    """Build the event detail redirect URL with optional image import warnings."""
    query_params: list[tuple[str, str]] = [("msg", msg)]
    if image_warnings:
        trimmed_warnings = image_warnings[:5]
        query_params.extend(("img_warn", warning) for warning in trimmed_warnings)
        remaining = len(image_warnings) - len(trimmed_warnings)
        if remaining > 0:
            query_params.append(
                ("img_warn", f"... and {remaining} more image import warning(s).")
            )
    return f"/admin/events/{event_id}?{urlencode(query_params, doseq=True)}"


def _image_importer_with_warnings(access_token: str | None, image_warnings: list[str]):
    """Wrap image imports so failures are shown to the organizer after redirect."""

    def importer(robot: Robot, image_url: str) -> None:
        warning = _try_import_image(robot, image_url, access_token=access_token)
        if warning:
            image_warnings.append(f"{robot.robot_name}: {warning}")

    return importer


def _build_image_request(image_url: str, access_token: str | None) -> tuple[str, urllib.request.Request]:
    """Return the resolved image URL and the HTTP request used to fetch it."""
    resolved_url = image_url
    headers = {"User-Agent": "BitBT/1.0"}
    drive_file_id = _google_drive_file_id(image_url)
    if drive_file_id and access_token:
        resolved_url = f"https://www.googleapis.com/drive/v3/files/{drive_file_id}?alt=media"
        headers["Authorization"] = f"Bearer {access_token}"
    return resolved_url, urllib.request.Request(resolved_url, headers=headers)


def _image_extension(original_url: str, resolved_url: str, content_type: str | None) -> str:
    """Choose a safe image extension from MIME type or URL hints."""
    allowed_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

    if content_type:
        mime_type = content_type.split(";", 1)[0].strip().lower()
        if mime_type and mime_type not in {"application/octet-stream", "binary/octet-stream"} and not mime_type.startswith("image/"):
            raise ValueError("Imported file is not an image")
        guessed = mimetypes.guess_extension(mime_type) if mime_type else None
        if guessed == ".jpe":
            guessed = ".jpg"
        if guessed in allowed_exts:
            return guessed

    for candidate in (original_url, resolved_url):
        ext = Path(candidate.split("?", 1)[0]).suffix.lower()
        if ext in allowed_exts:
            return ext

    return ".jpg"


def _image_extension_from_headers(headers) -> str | None:
    """Infer a safe image extension from download headers when MIME type is generic."""
    if headers is None or not hasattr(headers, "get"):
        return None

    content_disposition = headers.get("Content-Disposition") or headers.get("content-disposition")
    if not content_disposition:
        return None

    # Handle both `filename="robot.png"` and RFC 5987 `filename*=UTF-8''robot.png` forms.
    for pattern in (
        r"filename\*=UTF-8''([^;]+)",
        r'filename="?([^";]+)"?',
    ):
        match = re.search(pattern, content_disposition, flags=re.IGNORECASE)
        if not match:
            continue
        filename = match.group(1).strip()
        if not filename:
            continue
        ext = Path(filename).suffix.lower()
        if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            return ext

    return None


def _http_error_summary(exc: urllib.error.HTTPError) -> str:
    """Return a concise summary of an HTTP error response."""
    detail = f"HTTP {exc.code} {exc.reason}"
    headers = getattr(exc, "headers", None)
    if headers is not None and hasattr(headers, "get_content_type"):
        content_type = headers.get_content_type()
        if content_type:
            detail = f"{detail} ({content_type})"

    try:
        body = exc.read(200)
    except Exception:
        body = b""
    if body:
        snippet = " ".join(body.decode("utf-8", errors="ignore").split())[:140]
        if snippet:
            detail = f"{detail}: {snippet}"
    return detail


def _try_import_image(robot: Robot, image_url: str, access_token: str | None = None) -> str | None:
    """Attempt to download an image from a URL and save it locally.

    Falls back to storing the URL directly if the download fails.
    Only attempts HTTP/HTTPS URLs to prevent SSRF against internal services.
    """
    if not image_url.startswith(("http://", "https://")):
        return "unsupported image URL scheme"
    try:
        resolved_url, req = _build_image_request(image_url, access_token)
        with urllib.request.urlopen(req, timeout=5) as response:
            content_type = None
            headers = getattr(response, "headers", None)
            if headers is not None and hasattr(headers, "get_content_type"):
                content_type = headers.get_content_type()
            ext = _image_extension(image_url, resolved_url, content_type)
            if ext == ".jpg" and content_type in {"application/octet-stream", "binary/octet-stream"}:
                ext = _image_extension_from_headers(headers) or ext
            image_bytes = response.read()

        filename = f"{uuid.uuid4().hex}{ext}"
        dest = Path(UPLOAD_DIR) / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(image_bytes)
        robot.image_url = f"/static/uploads/{filename}"
        robot.image_source = ImageSource.upload
        return None
    except urllib.error.HTTPError as exc:
        warning = _http_error_summary(exc)
    except urllib.error.URLError as exc:
        warning = f"network error: {exc.reason}"
    except ValueError as exc:
        warning = str(exc)
    except OSError as exc:
        warning = f"filesystem error: {exc}"

    # Fallback: store the URL reference without downloading
    robot.image_url = image_url
    robot.image_source = ImageSource.sheet
    return warning


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
    flash_context = _flash_context(msg, flash_map, fallback_error="Unable to complete that action.")

    matchups = (
        db.query(Matchup)
        .filter(Matchup.phase_id == phase_id)
        .order_by(Matchup.display_order)
        .all()
    )

    all_done = all(m.status == MatchupStatus.completed for m in matchups)
    can_complete = all_done and phase.status == PhaseStatus.active

    return render_template(
        request,
        "admin/phases/detail.html",
        title=phase_label,
        context={
            "user": user,
            "event": ev,
            "phase": phase,
            "phase_label": phase_label,
            "matchups": [_phase_matchup_context(matchup, event_id, phase) for matchup in matchups],
            "can_complete": can_complete,
            "complete_action": f"/admin/events/{event_id}/phases/{phase_id}/complete",
            "completed_count": sum(1 for matchup in matchups if matchup.status == MatchupStatus.completed),
            "total_count": len(matchups),
            "reorder_enabled": phase.status == PhaseStatus.active,
            "reorder_url": f"/admin/events/{event_id}/phases/{phase_id}/reorder",
            **flash_context,
        },
        stylesheets=("css/admin.css",),
        script_srcs=((HTMX_SCRIPT_URL, _SORTABLEJS) if phase.status == PhaseStatus.active else (HTMX_SCRIPT_URL,)),
        body_class="admin-page",
    )


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
        if phase.phase_type == PhaseType.qualifying:
            activate_next_qualifying_round(event_id, phase.phase_number, db)

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
    if phase.phase_type == PhaseType.qualifying:
        activate_next_qualifying_round(event_id, phase.phase_number, db)
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

    form_title = f"{'Edit' if m.status == MatchupStatus.completed else 'Score'} Fight"

    existing_result = None
    if m.status == MatchupStatus.completed:
        r1_pts = _points_for_matchup_robot(m, r1.id) or 0
        r2_pts = _points_for_matchup_robot(m, r2.id if r2 else None) or 0
        existing_result = {
            "label": points_to_outcome_label(r1_pts, r2_pts),
            "score": f"{r1_pts}-{r2_pts}",
        }

    return render_template(
        request,
        "admin/phases/score.html",
        title=form_title,
        context={
            "user": user,
            "event": ev,
            "phase_label": phase_label,
            "back_href": back_href,
            "form_title": form_title,
            "matchup": {
                "id": m.id,
                "robot1_name": r1.robot_name,
                "robot2_name": r2.robot_name if r2 else "BYE",
            },
            "existing_result": existing_result,
            "clear_action": f"/admin/events/{event_id}/matchups/{matchup_id}/clear-score",
            "save_action": f"/admin/events/{event_id}/matchups/{matchup_id}/score",
            "outcome_options": _score_option_context(m),
            "error_message": error,
            "success_message": "",
            "info_message": "",
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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
        if phase.phase_type == PhaseType.qualifying:
            activate_next_qualifying_round(event_id, phase.phase_number, db)

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
    if phase.phase_type == PhaseType.qualifying:
        set_incomplete_qualifying_round_state(event_id, phase.phase_number, db)

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
    flash_context = _flash_context(msg, flash_map, fallback_error="Unable to complete that action.")

    bracket_phase = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.bracket)
        .first()
    )

    if not bracket_phase:
        return render_template(
            request,
            "admin/phases/bracket.html",
            title="Bracket",
            context={
                "user": user,
                "event": ev,
                "bracket_phase": None,
                "rounds": [],
                "show_rearrange": False,
                "rearrange_href": "",
                "can_advance": False,
                "advance_action": "",
                **flash_context,
            },
            stylesheets=("css/admin.css",),
            script_srcs=(HTMX_SCRIPT_URL,),
            body_class="admin-page",
        )

    all_matchups = (
        db.query(Matchup)
        .filter(Matchup.phase_id == bracket_phase.id)
        .order_by(Matchup.bracket_round, Matchup.display_order)
        .all()
    )

    rounds: dict[int, list[Matchup]] = {}
    for m in all_matchups:
        rnd = m.bracket_round or 1
        rounds.setdefault(rnd, []).append(m)

    max_round = max(rounds.keys(), default=0)
    total_rounds = max_round  # will grow as bracket advances

    can_advance = False
    if max_round > 0:
        current_round_done = all(
            m.status == MatchupStatus.completed for m in rounds.get(max_round, [])
        )
        current_round_has_multiple = len(rounds.get(max_round, [])) > 1
        can_advance = current_round_done and current_round_has_multiple

    round1_matchups = rounds.get(1, [])
    return render_template(
        request,
        "admin/phases/bracket.html",
        title="Bracket",
        context={
            "user": user,
            "event": ev,
            "bracket_phase": bracket_phase,
            "rounds": [
                {
                    "label": _bracket_round_label(rnd, max_round),
                    "matchups": [_bracket_matchup_context(matchup, event_id) for matchup in rounds[rnd]],
                }
                for rnd in sorted(rounds.keys())
            ],
            "show_rearrange": bool(round1_matchups) and all(
                matchup.status == MatchupStatus.pending for matchup in round1_matchups
            ),
            "rearrange_href": f"/admin/events/{event_id}/bracket/rearrange",
            "can_advance": can_advance,
            "advance_action": f"/admin/events/{event_id}/bracket/advance",
            **flash_context,
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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

    matchup_options = [
        {
            "value": str(m.id),
            "label": f"Match {i + 1}: {m.robot1.robot_name} vs {m.robot2.robot_name if m.robot2 else 'BYE'}",
        }
        for i, m in enumerate(r1_matchups)
        if m.robot2_id is not None
    ]

    return render_template(
        request,
        "admin/phases/bracket_rearrange.html",
        title="Rearrange Bracket",
        context={
            "user": user,
            "event": ev,
            "matchup_options": matchup_options,
            "submit_action": f"/admin/events/{event_id}/bracket/rearrange",
            "error_message": error,
            "success_message": "",
            "info_message": "",
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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
        rows.append(
            {
                "rank": i,
                "is_top_three": i <= 3,
                "image_url": robot.image_url,
                "robot_name": robot.robot_name,
                "roboteer_name": robot.roboteer.roboteer_name,
                "points": pts,
                "qualifying": qualifying,
            }
        )

    bracket_phase = (
        db.query(Phase)
        .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.bracket)
        .first()
    )
    generate_btn = ""
    can_generate_bracket = False
    if not bracket_phase:
        qual_phases = (
            db.query(Phase)
            .filter(Phase.event_id == event_id, Phase.phase_type == PhaseType.qualifying)
            .all()
        )
        if len(qual_phases) >= 3 and all(ph.status == PhaseStatus.complete for ph in qual_phases):
            can_generate_bracket = True

    return render_template(
        request,
        "admin/phases/standings.html",
        title="Qualifying Standings",
        context={
            "user": user,
            "event": ev,
            "rows": rows,
            "can_generate_bracket": can_generate_bracket,
            "generate_bracket_action": f"/admin/events/{event_id}/bracket/generate",
            "error_message": "",
            "success_message": "",
            "info_message": "",
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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


def _sub_event_matchup_context(
    m: SubEventMatchup,
    sub_event_id: int,
    event_id: int,
    show_actions: bool,
) -> dict[str, object]:
    """Build template context for a sub-event team-vs-team matchup card."""
    t1 = m.team1
    t2 = m.team2

    def _team_row(team: SubEventTeam | None, is_winner: bool) -> dict[str, object]:
        if team is None:
            return {
                "name": "TBD",
                "robots": "",
                "is_winner": False,
                "is_tbd": True,
            }

        return {
            "name": team.team_name,
            "robots": f"{team.robot1.robot_name} & {team.robot2.robot_name}",
            "is_winner": is_winner,
            "is_tbd": False,
        }

    t1_win = m.winner_team_id is not None and m.winner_team_id == (t1.id if t1 else None)
    t2_win = m.winner_team_id is not None and m.winner_team_id == (t2.id if t2 else None)

    is_bye = t2 is None
    action_href = ""
    action_label = ""
    action_class = ""
    if show_actions:
        if is_bye:
            action_label = "BYE"
            action_class = "admin-sub-event-bye"
        elif m.status == MatchupStatus.pending:
            action_href = f"/admin/events/{event_id}/sub-events/{sub_event_id}/matchups/{m.id}/score"
            action_label = "Score"
            action_class = "btn btn-sm btn-primary"
        else:
            action_href = f"/admin/events/{event_id}/sub-events/{sub_event_id}/matchups/{m.id}/score"
            action_label = "Edit"
            action_class = "btn btn-sm btn-secondary"

    return {
        "teams": [_team_row(t1, t1_win), _team_row(t2, t2_win)],
        "action_href": action_href,
        "action_label": action_label,
        "action_class": action_class,
        "is_bye": is_bye,
    }


def _run_order_row_context(ro: RunOrder, db: Session) -> dict[str, object] | None:
    """Build template context for a unified run-order row."""
    if ro.matchup_type == RunOrderMatchupType.main:
        matchup = db.query(Matchup).filter(Matchup.id == ro.matchup_id).first()
        if not matchup:
            return None

        phase = matchup.phase
        if phase.phase_type == PhaseType.qualifying:
            context_label = f"Q{phase.phase_number}"
            context_class = "badge badge-qualifying"
        else:
            context_label = f"Bracket R{matchup.bracket_round or '?'}"
            context_class = "badge badge-bracket"

        return {
            "id": ro.id,
            "context_label": context_label,
            "context_class": context_class,
            "secondary_label": "",
            "left_name": matchup.robot1.robot_name if matchup.robot1 else "?",
            "right_name": matchup.robot2.robot_name if matchup.robot2 else "BYE",
            "has_opponent": matchup.robot2_id is not None,
            "status_label": "Done" if matchup.status == MatchupStatus.completed else "pending",
            "is_completed": matchup.status == MatchupStatus.completed,
        }

    matchup = db.query(SubEventMatchup).filter(SubEventMatchup.id == ro.matchup_id).first()
    if not matchup:
        return None

    sub_event_name = matchup.sub_event.name if matchup.sub_event else "Sub-event"
    return {
        "id": ro.id,
        "context_label": f"SE R{matchup.round_number}",
        "context_class": "badge badge-sub_events",
        "secondary_label": sub_event_name,
        "left_name": matchup.team1.team_name if matchup.team1 else "?",
        "right_name": matchup.team2.team_name if matchup.team2 else "BYE",
        "has_opponent": matchup.team2_id is not None,
        "status_label": "Done" if matchup.status == MatchupStatus.completed else "pending",
        "is_completed": matchup.status == MatchupStatus.completed,
    }


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

    eligible_ids = get_sub_event_eligible_robots(event_id, db)
    eligible_robots = [db.query(Robot).filter(Robot.id == rid).first() for rid in eligible_ids]
    eligible_robots = [r for r in eligible_robots if r]

    return render_template(
        request,
        "admin/sub_events/new.html",
        title="New Sub-event",
        context={
            "user": user,
            "event": ev,
            "eligible_robot_count": len(eligible_robots),
            "eligible_robots": [
                {
                    "robot_name": robot.robot_name,
                    "roboteer_name": robot.roboteer.roboteer_name,
                }
                for robot in eligible_robots[:20]
            ],
            "form_action": f"/admin/events/{event_id}/sub-events/new",
            "cancel_href": f"/admin/events/{event_id}",
            "error_message": error,
            "success_message": "",
            "info_message": "",
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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
    error: str = Query(default=""),
):
    ev = _get_event_or_404(event_id, user.id, db)
    se = db.query(SubEvent).filter(SubEvent.id == sub_event_id, SubEvent.event_id == event_id).first()
    if not se:
        return RedirectResponse(f"/admin/events/{event_id}", status_code=303)

    flash_map = {
        "sub_event_created": ("Sub-event created.", "success"),
        "sub_event_bracket_generated": ("Bracket generated for sub-event.", "success"),
        "sub_event_bracket_advanced": ("Sub-event bracket advanced to next round.", "success"),
        "sub_event_complete": ("Sub-event marked complete.", "success"),
        "se_scored": ("Fight result saved.", "success"),
        "se_score_cleared": ("Fight result cleared.", "info"),
        "team_created": ("Team created.", "success"),
        "team_deleted": ("Team removed.", "info"),
    }
    flash_context = _flash_context(
        msg,
        flash_map,
        error=error,
        fallback_error="Unable to complete that action.",
    )

    teams = (
        db.query(SubEventTeam)
        .filter(SubEventTeam.sub_event_id == sub_event_id)
        .order_by(SubEventTeam.id)
        .all()
    )

    eligible_ids = set(get_sub_event_eligible_robots(event_id, db))

    team_rows = []
    for team in teams:
        team_rows.append(
            {
                "id": team.id,
                "team_name": team.team_name,
                "robot1_name": team.robot1.robot_name,
                "robot2_name": team.robot2.robot_name,
                "robot1_warning": "ineligible" if team.robot1_id not in eligible_ids else "",
                "robot2_warning": "ineligible" if team.robot2_id not in eligible_ids else "",
                "delete_action": f"/admin/events/{event_id}/sub-events/{sub_event_id}/teams/{team.id}/delete",
            }
        )

    # Bracket section
    all_matchups = (
        db.query(SubEventMatchup)
        .filter(SubEventMatchup.sub_event_id == sub_event_id)
        .order_by(SubEventMatchup.round_number, SubEventMatchup.display_order)
        .all()
    )
    has_bracket = bool(all_matchups)

    bracket_rounds = []
    if has_bracket:
        rounds: dict[int, list[SubEventMatchup]] = {}
        for m in all_matchups:
            rounds.setdefault(m.round_number, []).append(m)
        max_round_num = max(rounds.keys())
        for rnd in sorted(rounds.keys()):
            bracket_rounds.append(
                {
                    "label": _se_round_label(rnd, max_round_num),
                    "matchups": [
                        _sub_event_matchup_context(matchup, sub_event_id, event_id, show_actions=True)
                        for matchup in rounds[rnd]
                    ],
                }
            )

    bracket_actions = []
    if not has_bracket and len(teams) >= 2:
        bracket_actions.append(
            {
                "action": f"/admin/events/{event_id}/sub-events/{sub_event_id}/generate-bracket",
                "label": "Generate Bracket",
                "button_class": "btn btn-warning",
            }
        )

    if has_bracket:
        max_round_in_db = max(m.round_number for m in all_matchups)
        current_round_matchups = [m for m in all_matchups if m.round_number == max_round_in_db]
        current_all_done = all(m.status == MatchupStatus.completed for m in current_round_matchups)
        winners_count = sum(1 for m in current_round_matchups if m.winner_team_id)
        if current_all_done and winners_count > 1:
            bracket_actions.append(
                {
                    "action": f"/admin/events/{event_id}/sub-events/{sub_event_id}/bracket/advance",
                    "label": "Generate Next Round &rarr;",
                    "button_class": "btn btn-warning",
                }
            )
        if current_all_done and winners_count <= 1 and se.status == SubEventStatus.active:
            bracket_actions.append(
                {
                    "action": f"/admin/events/{event_id}/sub-events/{sub_event_id}/complete",
                    "label": "Mark Sub-event Complete",
                    "button_class": "btn btn-success",
                }
            )

    return render_template(
        request,
        "admin/sub_events/detail.html",
        title=se.name,
        context={
            "user": user,
            "event": ev,
            "sub_event": se,
            "team_rows": team_rows,
            "team_count": len(teams),
            "can_add_team": se.status == SubEventStatus.setup,
            "add_team_href": f"/admin/events/{event_id}/sub-events/{sub_event_id}/teams/add",
            "bracket_rounds": bracket_rounds,
            "bracket_actions": bracket_actions,
            **flash_context,
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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

    eligible_ids = get_sub_event_eligible_robots(event_id, db)
    eligible_robots = [db.query(Robot).filter(Robot.id == rid).first() for rid in eligible_ids]
    eligible_robots = [r for r in eligible_robots if r]

    existing_teams = db.query(SubEventTeam).filter(SubEventTeam.sub_event_id == sub_event_id).all()
    already_assigned: set[int] = set()
    for t in existing_teams:
        already_assigned.add(t.robot1_id)
        already_assigned.add(t.robot2_id)

    def _robot_option(r: Robot) -> dict[str, object]:
        taken = r.id in already_assigned
        label = f"{r.robot_name} ({r.roboteer.roboteer_name})"
        if taken:
            label += " — already assigned"
        return {
            "value": str(r.id),
            "label": label,
            "disabled": taken,
        }

    robot_options = [{"value": "", "label": "— Select robot —", "disabled": False}] + [
        _robot_option(robot) for robot in eligible_robots
    ]

    return render_template(
        request,
        "admin/sub_events/add_team.html",
        title="Add Team",
        context={
            "user": user,
            "event": ev,
            "sub_event": se,
            "has_eligible_robots": bool(eligible_robots),
            "robot_options": robot_options,
            "already_assigned_count": len(already_assigned),
            "submit_action": f"/admin/events/{event_id}/sub-events/{sub_event_id}/teams/add",
            "cancel_href": f"/admin/events/{event_id}/sub-events/{sub_event_id}",
            "error_message": error,
            "success_message": "",
            "info_message": (
                f"{len(already_assigned)} robot(s) already assigned to teams in this sub-event (marked above)."
                if already_assigned
                else ""
            ),
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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

    existing_result = None
    if m.status == MatchupStatus.completed and m.winner_team_id:
        winner = t1 if m.winner_team_id == t1.id else t2
        existing_result = {"label": f"{winner.team_name} wins"}

    back = f"/admin/events/{event_id}/sub-events/{sub_event_id}"
    form_title = "Edit Fight" if m.status == MatchupStatus.completed else "Score Fight"

    def _team_desc(t: SubEventTeam) -> str:
        return f"{t.team_name}  ({t.robot1.robot_name} & {t.robot2.robot_name})"

    winner_options = [
        {"value": "", "label": "— Select winner —", "selected": False},
        {"value": str(t1.id), "label": t1.team_name, "selected": m.winner_team_id == t1.id},
        {"value": str(t2.id), "label": t2.team_name, "selected": m.winner_team_id == t2.id},
    ]

    return render_template(
        request,
        "admin/sub_events/score.html",
        title=form_title,
        context={
            "user": user,
            "event": ev,
            "sub_event": se,
            "form_title": form_title,
            "back_href": back,
            "matchup": {
                "team1_name": t1.team_name,
                "team2_name": t2.team_name,
                "team1_desc": _team_desc(t1),
                "team2_desc": _team_desc(t2),
            },
            "existing_result": existing_result,
            "winner_options": winner_options,
            "save_action": f"/admin/events/{event_id}/sub-events/{sub_event_id}/matchups/{matchup_id}/score",
            "clear_action": f"/admin/events/{event_id}/sub-events/{sub_event_id}/matchups/{matchup_id}/clear-score",
            "error_message": error,
            "success_message": "",
            "info_message": "",
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL,),
        body_class="admin-page",
    )


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

    run_order_rows = (
        db.query(RunOrder)
        .filter(RunOrder.event_id == event_id)
        .order_by(RunOrder.slot_index)
        .all()
    )

    rows = []
    for run_order_row in run_order_rows:
        row_context = _run_order_row_context(run_order_row, db)
        if row_context:
            rows.append(row_context)

    return render_template(
        request,
        "admin/events/run_order.html",
        title="Run Order",
        context={
            "user": user,
            "event": ev,
            "rows": rows,
            "reorder_enabled": any(not row["is_completed"] for row in rows),
            "reorder_url": f"/admin/events/{event_id}/run-order/reorder",
            "error_message": "",
            "success_message": "Run order saved." if msg == "saved" else "",
            "info_message": "",
        },
        stylesheets=("css/admin.css",),
        script_srcs=(HTMX_SCRIPT_URL, _SORTABLEJS),
        body_class="admin-page",
    )


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
