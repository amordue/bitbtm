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
from models import Base, Event, EventRobot, EventStatus, Robot, Roboteer, User


class JinjaFoundationTests(unittest.TestCase):
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
        self.session_patcher = patch.object(database, "SessionLocal", self.testing_session_local)
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
                google_id="org-1",
                email="org@example.com",
                name="Organizer",
            )
            db.add(organizer)
            db.flush()

            event = Event(
                event_name="Steel City Smashdown",
                weight_class="Beetleweight",
                organizer_id=organizer.id,
                status=EventStatus.setup,
            )
            db.add(event)
            db.commit()

            return {"organizer_id": organizer.id, "event_id": event.id}

    def test_login_page_uses_jinja_layout_and_assets(self):
        response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn("<title>Sign In - BitBT</title>", response.text)
        self.assertIn("Sign in with Google", response.text)
        self.assertIn('/static/css/base.css', response.text)
        self.assertIn('/static/css/auth.css', response.text)

    def test_admin_dashboard_uses_admin_shell_and_event_table(self):
        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("BitBT Admin", response.text)
        self.assertIn("Steel City Smashdown", response.text)
        self.assertIn('/static/css/admin.css', response.text)
        self.assertIn('href="/admin/events/1"', response.text)

    def test_admin_new_event_page_uses_admin_shell_and_form(self):
        response = self.client.get("/admin/events/new")

        self.assertEqual(response.status_code, 200)
        self.assertIn("BitBT Admin", response.text)
        self.assertIn("<h1>New Event</h1>", response.text)
        self.assertIn('action="/admin/events"', response.text)
        self.assertIn('/static/css/admin.css', response.text)

    def test_admin_event_detail_uses_admin_shell_and_lifecycle_controls(self):
        with self.testing_session_local() as db:
            roboteer = Roboteer(roboteer_name="Jamie Driver")
            db.add(roboteer)
            db.flush()

            robot = Robot(
                robot_name="Clamp Champ",
                roboteer_id=roboteer.id,
                weapon_type="Grabber",
            )
            db.add(robot)
            db.flush()

            db.add(EventRobot(event_id=self.ids["event_id"], robot_id=robot.id, is_reserve=False))
            db.commit()

        response = self.client.get(f"/admin/events/{self.ids['event_id']}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Steel City Smashdown", response.text)
        self.assertIn("Begin Registration", response.text)
        self.assertIn("Import / Refresh Robots", response.text)
        self.assertIn("Clamp Champ", response.text)
        self.assertIn("Active Robots (1)", response.text)

    def test_admin_event_detail_shows_transition_error_messages(self):
        with self.testing_session_local() as db:
            event = db.query(Event).filter(Event.id == self.ids["event_id"]).first()
            event.status = EventStatus.registration
            db.commit()

        response = self.client.post(f"/admin/events/{self.ids['event_id']}/transition", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Need at least 2 active robots before starting qualifying.", response.text)
        self.assertIn("Steel City Smashdown", response.text)

    def test_public_qr_page_uses_public_shell_and_assets(self):
        response = self.client.get(f"/events/{self.ids['event_id']}/qr")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Event QR Code", response.text)
        self.assertIn("Steel City Smashdown", response.text)
        self.assertIn('/static/css/public.css', response.text)
        self.assertIn(f'href="/events/{self.ids["event_id"]}"', response.text)
