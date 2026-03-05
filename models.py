from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EventStatus(str, PyEnum):
    setup = "setup"
    registration = "registration"
    qualifying = "qualifying"
    bracket = "bracket"
    sub_events = "sub_events"
    complete = "complete"


class PhaseType(str, PyEnum):
    qualifying = "qualifying"
    bracket = "bracket"


class PhaseStatus(str, PyEnum):
    pending = "pending"
    active = "active"
    complete = "complete"


class MatchupStatus(str, PyEnum):
    pending = "pending"
    completed = "completed"


class SubEventStatus(str, PyEnum):
    setup = "setup"
    active = "active"
    complete = "complete"


class SubEventFormat(str, PyEnum):
    two_v_two_team_bracket = "2v2_team_bracket"


class ImageSource(str, PyEnum):
    sheet = "sheet"
    upload = "upload"
    none = "none"


class RunOrderMatchupType(str, PyEnum):
    main = "main"
    sub_event = "sub_event"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(Base):
    """Organizer account — authenticated via Google OAuth."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    google_id = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    picture_url = Column(String)
    access_token = Column(Text)
    refresh_token = Column(Text)
    token_expiry = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    events = relationship("Event", back_populates="organizer")


class Roboteer(Base):
    """A robot builder / operator imported from Google Sheets."""
    __tablename__ = "roboteers"

    id = Column(Integer, primary_key=True)
    roboteer_name = Column(String, nullable=False)
    contact_email = Column(String)
    imported_from_sheet_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    robots = relationship("Robot", back_populates="roboteer")


class Robot(Base):
    """An individual robot."""
    __tablename__ = "robots"

    id = Column(Integer, primary_key=True)
    robot_name = Column(String, nullable=False)
    roboteer_id = Column(Integer, ForeignKey("roboteers.id"), nullable=False)
    weapon_type = Column(String)
    sheet_row_id = Column(String)          # original row identifier from Google Sheet
    image_url = Column(String)
    image_source = Column(Enum(ImageSource), default=ImageSource.none)
    created_at = Column(DateTime, default=datetime.utcnow)

    roboteer = relationship("Roboteer", back_populates="robots")
    event_registrations = relationship("EventRobot", back_populates="robot")


class Event(Base):
    """A tournament event."""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    event_name = Column(String, nullable=False)
    weight_class = Column(String, nullable=False)
    google_sheet_url = Column(String)
    status = Column(Enum(EventStatus), default=EventStatus.setup, nullable=False)
    organizer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    organizer = relationship("User", back_populates="events")
    event_robots = relationship("EventRobot", back_populates="event")
    phases = relationship("Phase", back_populates="event", order_by="Phase.phase_number")
    sub_events = relationship("SubEvent", back_populates="event")
    run_order = relationship("RunOrder", back_populates="event", order_by="RunOrder.slot_index")


class EventRobot(Base):
    """Join table: which robots are registered for an event (with reserve status)."""
    __tablename__ = "event_robots"
    __table_args__ = (UniqueConstraint("event_id", "robot_id"),)

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    robot_id = Column(Integer, ForeignKey("robots.id"), nullable=False)
    is_reserve = Column(Boolean, default=False, nullable=False)
    reserve_order = Column(Integer)        # ordering for reserves; NULL for non-reserves

    event = relationship("Event", back_populates="event_robots")
    robot = relationship("Robot", back_populates="event_registrations")


class Phase(Base):
    """A phase within an event (qualifying round or bracket)."""
    __tablename__ = "phases"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    phase_number = Column(Integer, nullable=False)   # 1, 2, 3 for qualifying; 1 for bracket
    phase_type = Column(Enum(PhaseType), nullable=False)
    status = Column(Enum(PhaseStatus), default=PhaseStatus.pending, nullable=False)

    event = relationship("Event", back_populates="phases")
    matchups = relationship("Matchup", back_populates="phase")


class Matchup(Base):
    """A single 1v1 fight in the main event."""
    __tablename__ = "matchups"

    id = Column(Integer, primary_key=True)
    phase_id = Column(Integer, ForeignKey("phases.id"), nullable=False)
    robot1_id = Column(Integer, ForeignKey("robots.id"), nullable=False)
    robot2_id = Column(Integer, ForeignKey("robots.id"))   # NULL = bye
    status = Column(Enum(MatchupStatus), default=MatchupStatus.pending, nullable=False)
    display_order = Column(Integer, default=0)

    phase = relationship("Phase", back_populates="matchups")
    robot1 = relationship("Robot", foreign_keys=[robot1_id])
    robot2 = relationship("Robot", foreign_keys=[robot2_id])
    results = relationship("Result", back_populates="matchup")


class Result(Base):
    """Points scored by a robot in a matchup."""
    __tablename__ = "results"

    id = Column(Integer, primary_key=True)
    matchup_id = Column(Integer, ForeignKey("matchups.id"), nullable=False)
    robot_id = Column(Integer, ForeignKey("robots.id"), nullable=False)
    points_scored = Column(Integer, nullable=False)

    matchup = relationship("Matchup", back_populates="results")
    robot = relationship("Robot")


class SubEvent(Base):
    """An optional sub-competition attached to an event (e.g. 2v2 team bracket)."""
    __tablename__ = "sub_events"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    name = Column(String, nullable=False)
    format = Column(Enum(SubEventFormat), nullable=False)
    status = Column(Enum(SubEventStatus), default=SubEventStatus.setup, nullable=False)

    event = relationship("Event", back_populates="sub_events")
    teams = relationship("SubEventTeam", back_populates="sub_event")
    matchups = relationship("SubEventMatchup", back_populates="sub_event")


class SubEventTeam(Base):
    """A 2-robot team in a sub-event."""
    __tablename__ = "sub_event_teams"

    id = Column(Integer, primary_key=True)
    sub_event_id = Column(Integer, ForeignKey("sub_events.id"), nullable=False)
    team_name = Column(String, nullable=False)
    robot1_id = Column(Integer, ForeignKey("robots.id"), nullable=False)
    robot2_id = Column(Integer, ForeignKey("robots.id"), nullable=False)

    sub_event = relationship("SubEvent", back_populates="teams")
    robot1 = relationship("Robot", foreign_keys=[robot1_id])
    robot2 = relationship("Robot", foreign_keys=[robot2_id])


class SubEventMatchup(Base):
    """A team-vs-team fight in a sub-event bracket."""
    __tablename__ = "sub_event_matchups"

    id = Column(Integer, primary_key=True)
    sub_event_id = Column(Integer, ForeignKey("sub_events.id"), nullable=False)
    team1_id = Column(Integer, ForeignKey("sub_event_teams.id"))
    team2_id = Column(Integer, ForeignKey("sub_event_teams.id"))
    winner_team_id = Column(Integer, ForeignKey("sub_event_teams.id"))
    status = Column(Enum(MatchupStatus), default=MatchupStatus.pending, nullable=False)
    display_order = Column(Integer, default=0)
    round_number = Column(Integer, nullable=False)

    sub_event = relationship("SubEvent", back_populates="matchups")
    team1 = relationship("SubEventTeam", foreign_keys=[team1_id])
    team2 = relationship("SubEventTeam", foreign_keys=[team2_id])
    winner_team = relationship("SubEventTeam", foreign_keys=[winner_team_id])


class RobotRetirement(Base):
    """Records a robot retirement and the reserve that replaced it."""
    __tablename__ = "robot_retirements"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    retired_robot_id = Column(Integer, ForeignKey("robots.id"), nullable=False)
    replacement_robot_id = Column(Integer, ForeignKey("robots.id"))
    retired_after_phase_id = Column(Integer, ForeignKey("phases.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    retired_robot = relationship("Robot", foreign_keys=[retired_robot_id])
    replacement_robot = relationship("Robot", foreign_keys=[replacement_robot_id])
    retired_after_phase = relationship("Phase")


class RunOrder(Base):
    """Unified ordered list of all pending fights for an event (main + sub-event)."""
    __tablename__ = "run_order"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    slot_index = Column(Integer, nullable=False)
    matchup_type = Column(Enum(RunOrderMatchupType), nullable=False)
    matchup_id = Column(Integer, nullable=False)   # FK to matchups or sub_event_matchups

    event = relationship("Event", back_populates="run_order")
