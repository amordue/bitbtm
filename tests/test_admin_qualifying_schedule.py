import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database
from app import app
from auth import require_organizer
from database import get_db
from models import (
    Base,
    Event,
    EventRobot,
    EventStatus,
    MatchupStatus,
    Phase,
    PhaseStatus,
    PhaseType,
    Robot,
    Roboteer,
    RunOrder,
    User,
)


class AdminQualifyingScheduleTests(unittest.TestCase):
    def setUp(self):
        self.test_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.testing_session_local = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.test_engine,
        )

        self.engine_patcher = patch.object(database, "engine", self.test_engine)
        self.session_patcher = patch.object(
            database,
            "SessionLocal",
            self.testing_session_local,
        )
        self.engine_patcher.start()
        self.session_patcher.start()

        Base.metadata.create_all(bind=self.test_engine)

        def override_get_db():
            db = self.testing_session_local()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.ids = self._seed_data()

        def override_require_organizer():
            with self.testing_session_local() as db:
                return db.query(User).filter(User.id == self.ids["organizer_id"]).first()

        app.dependency_overrides[require_organizer] = override_require_organizer
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session_patcher.stop()
        self.engine_patcher.stop()
        Base.metadata.drop_all(bind=self.test_engine)
        self.test_engine.dispose()

    def _seed_data(self):
        with self.testing_session_local() as db:
            organizer = User(
                google_id="org-qual-1",
                email="org@example.com",
                name="Organizer",
                access_token="token-123",
            )
            db.add(organizer)
            db.flush()

            event = Event(
                event_name="Qualifying Showcase",
                weight_class="Beetleweight",
                organizer_id=organizer.id,
                status=EventStatus.registration,
            )
            db.add(event)
            db.flush()

            roboteer = Roboteer(
                roboteer_name="Builder One",
                contact_email="builder@example.com",
            )
            db.add(roboteer)
            db.flush()

            robot_ids = []
            for index in range(6):
                robot = Robot(
                    robot_name=f"Robot {index + 1}",
                    roboteer_id=roboteer.id,
                    weapon_type="Spinner",
                )
                db.add(robot)
                db.flush()
                db.add(EventRobot(event_id=event.id, robot_id=robot.id, is_reserve=False))
                robot_ids.append(robot.id)

            db.commit()
            return {
                "organizer_id": organizer.id,
                "event_id": event.id,
                "robot_ids": robot_ids,
            }

    def test_transition_to_qualifying_creates_three_round_schedule(self):
        response = self.client.post(
            f"/admin/events/{self.ids['event_id']}/transition",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/admin/events/{self.ids['event_id']}?msg=transitioned",
        )

        with self.testing_session_local() as db:
            event = db.query(Event).filter(Event.id == self.ids["event_id"]).first()
            phases = (
                db.query(Phase)
                .filter(Phase.event_id == self.ids["event_id"], Phase.phase_type == PhaseType.qualifying)
                .order_by(Phase.phase_number)
                .all()
            )
            run_order = (
                db.query(RunOrder)
                .filter(RunOrder.event_id == self.ids["event_id"])
                .order_by(RunOrder.slot_index)
                .all()
            )

            self.assertEqual(event.status, EventStatus.qualifying)
            self.assertEqual([phase.phase_number for phase in phases], [1, 2, 3])
            self.assertEqual(
                [phase.status for phase in phases],
                [PhaseStatus.active, PhaseStatus.pending, PhaseStatus.pending],
            )
            self.assertTrue(all(len(phase.matchups) == 3 for phase in phases))
            self.assertEqual(len(run_order), sum(len(phase.matchups) for phase in phases))
            self.assertEqual([item.slot_index for item in run_order], list(range(len(run_order))))

    def test_completing_a_round_activates_the_next_prebuilt_round(self):
        self.client.post(
            f"/admin/events/{self.ids['event_id']}/transition",
            follow_redirects=False,
        )

        with self.testing_session_local() as db:
            phase_one = (
                db.query(Phase)
                .filter(
                    Phase.event_id == self.ids["event_id"],
                    Phase.phase_type == PhaseType.qualifying,
                    Phase.phase_number == 1,
                )
                .first()
            )
            for matchup in phase_one.matchups:
                matchup.status = MatchupStatus.completed
            db.commit()
            phase_one_id = phase_one.id

        response = self.client.post(
            f"/admin/events/{self.ids['event_id']}/phases/{phase_one_id}/complete",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/admin/events/{self.ids['event_id']}/phases/{phase_one_id}?msg=round_complete",
        )

        with self.testing_session_local() as db:
            phases = (
                db.query(Phase)
                .filter(Phase.event_id == self.ids["event_id"], Phase.phase_type == PhaseType.qualifying)
                .order_by(Phase.phase_number)
                .all()
            )

            self.assertEqual(
                [phase.status for phase in phases],
                [PhaseStatus.complete, PhaseStatus.active, PhaseStatus.pending],
            )
