"""Helpers for importing event registrations from Google Sheets."""

from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy.orm import Session

from google_sheets import extract_sheet_id, parse_robot_registrations
from models import EventRobot, ImageSource, Robot, Roboteer

Registration = dict[str, Any]
ImageImportFn = Callable[[Robot, str], None]


def sheet_id_from_url(sheet_url: str) -> str:
    """Return a stable sheet identifier even when URL parsing fails."""
    try:
        return extract_sheet_id(sheet_url)
    except ValueError:
        return sheet_url


def load_registrations(rows: list[dict], sheet_url: str) -> tuple[str, list[Registration]]:
    """Parse raw Google Sheet rows into registration records."""
    sheet_id = sheet_id_from_url(sheet_url)
    return sheet_id, parse_robot_registrations(rows, sheet_id)


def next_reserve_order(event_id: int, db: Session) -> int:
    """Return the next available reserve ordering slot for an event."""
    max_reserve = (
        db.query(EventRobot.reserve_order)
        .filter(EventRobot.event_id == event_id, EventRobot.is_reserve == True)
        .order_by(EventRobot.reserve_order.desc().nullslast())
        .first()
    )
    return (max_reserve[0] or 0) + 1 if max_reserve else 1


def selected_registrations(
    registrations: Iterable[Registration],
    row_ids: list[str],
) -> list[Registration]:
    """Return the selected registrations in form submission order."""
    registration_by_row_id = {
        registration["sheet_row_id"]: registration for registration in registrations
    }
    return [
        registration_by_row_id[row_id]
        for row_id in row_ids
        if row_id in registration_by_row_id
    ]


def upsert_roboteer(registration: Registration, sheet_id: str, db: Session) -> Roboteer:
    """Find or create the roboteer referenced by a registration row."""
    roboteer = (
        db.query(Roboteer)
        .filter(Roboteer.roboteer_name == registration["roboteer_name"])
        .first()
    )
    if roboteer:
        return roboteer

    roboteer = Roboteer(
        roboteer_name=registration["roboteer_name"],
        contact_email=registration.get("contact_email"),
        imported_from_sheet_id=sheet_id,
    )
    db.add(roboteer)
    db.flush()
    return roboteer


def upsert_robot(
    registration: Registration,
    sheet_id: str,
    db: Session,
    import_image: ImageImportFn | None = None,
) -> Robot:
    """Find or create the robot referenced by a registration row."""
    row_id = registration["sheet_row_id"]
    image_url = registration.get("image_url")
    robot = db.query(Robot).filter(Robot.sheet_row_id == row_id).first()
    if robot:
        # Keep user-uploaded images intact, but allow sheet refreshes to backfill
        # or replace sheet-managed images on existing robots.
        if image_url and import_image and robot.image_source != ImageSource.upload:
            import_image(robot, image_url)
        return robot

    roboteer = upsert_roboteer(registration, sheet_id, db)
    robot = Robot(
        robot_name=registration["robot_name"],
        roboteer_id=roboteer.id,
        weapon_type=registration.get("weapon_type"),
        sheet_row_id=row_id,
        image_source=ImageSource.none,
    )
    db.add(robot)
    db.flush()

    if image_url and import_image:
        import_image(robot, image_url)

    return robot


def ensure_event_robot(
    event_id: int,
    robot_id: int,
    db: Session,
    *,
    is_reserve: bool,
    reserve_order: int | None,
) -> bool:
    """Link a robot to an event unless that roster entry already exists."""
    existing_entry = (
        db.query(EventRobot)
        .filter(EventRobot.event_id == event_id, EventRobot.robot_id == robot_id)
        .first()
    )
    if existing_entry:
        return False

    db.add(
        EventRobot(
            event_id=event_id,
            robot_id=robot_id,
            is_reserve=is_reserve,
            reserve_order=reserve_order,
        )
    )
    return True


def import_selected_event_registrations(
    event_id: int,
    registrations: list[Registration],
    row_ids: list[str],
    reserve_ids: list[str],
    db: Session,
    import_image: ImageImportFn | None = None,
) -> None:
    """Create robots from selected rows and add them to the event roster."""
    if not registrations:
        return

    sheet_id = registrations[0]["sheet_row_id"].split(":", 1)[0]
    reserve_id_set = set(reserve_ids)
    reserve_order = next_reserve_order(event_id, db)

    for registration in selected_registrations(registrations, row_ids):
        robot = upsert_robot(registration, sheet_id, db, import_image=import_image)
        is_reserve = registration["sheet_row_id"] in reserve_id_set
        assigned_order = reserve_order if is_reserve else None
        created = ensure_event_robot(
            event_id,
            robot.id,
            db,
            is_reserve=is_reserve,
            reserve_order=assigned_order,
        )
        if created and is_reserve:
            reserve_order += 1


def refresh_event_registrations(
    event_id: int,
    registrations: list[Registration],
    db: Session,
    import_image: ImageImportFn | None = None,
) -> None:
    """Import any unseen registration rows and link existing robots to the event."""
    if not registrations:
        return

    sheet_id = registrations[0]["sheet_row_id"].split(":", 1)[0]
    for registration in registrations:
        robot = upsert_robot(registration, sheet_id, db, import_image=import_image)
        ensure_event_robot(
            event_id,
            robot.id,
            db,
            is_reserve=False,
            reserve_order=None,
        )