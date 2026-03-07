import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database
from app import app
from auth import require_organizer
from database import get_db
from models import Base, Event, EventStatus, Robot, User


class AdminRefreshSheetUiTests(unittest.TestCase):
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
                google_id="org-1",
                email="org@example.com",
                name="Organizer",
                access_token="token-123",
            )
            db.add(organizer)
            db.flush()

            event = Event(
                event_name="Steel City Smashdown",
                weight_class="Beetleweight",
                google_sheet_url="https://docs.google.com/spreadsheets/d/sheet123/edit#gid=0",
                organizer_id=organizer.id,
                status=EventStatus.setup,
            )
            db.add(event)
            db.commit()

            return {"organizer_id": organizer.id, "event_id": event.id}

    def test_event_detail_includes_refresh_sheet_form(self):
        response = self.client.get(f"/admin/events/{self.ids['event_id']}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Refresh From Sheet", response.text)
        self.assertIn(
            f'action="/admin/events/{self.ids["event_id"]}/refresh-sheet"',
            response.text,
        )
        self.assertIn("Import / Refresh Robots", response.text)

    def test_import_page_includes_refresh_sheet_form(self):
        response = self.client.get(f"/admin/events/{self.ids['event_id']}/import")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Refresh From Sheet", response.text)
        self.assertIn(
            "Refresh the roster from the saved event sheet URL.",
            response.text,
        )
        self.assertIn(
            f'action="/admin/events/{self.ids["event_id"]}/refresh-sheet"',
            response.text,
        )

    def test_event_detail_renders_image_warning_messages(self):
        response = self.client.get(
            f"/admin/events/{self.ids['event_id']}?msg=refreshed&img_warn=Saw+Loser%3A+HTTP+403"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Some robot images could not be downloaded; the original sheet URLs were kept instead.",
            response.text,
        )
        self.assertIn("Saw Loser: HTTP 403", response.text)

    def test_refresh_sheet_redirect_includes_image_warning_details(self):
        registration = {
            "sheet_row_id": "sheet123:2",
            "roboteer_name": "Alex Mordue",
            "robot_name": "Saw Loser",
            "weapon_type": "Hammer-Saw",
            "image_url": "https://drive.google.com/open?id=file123",
        }

        with self.testing_session_local() as db:
            db.add(Robot(robot_name="Saw Loser", roboteer_id=1, sheet_row_id="sheet123:2"))
            db.commit()

        with patch("routes.admin.get_valid_access_token", return_value="token-abc"), patch(
            "routes.admin.fetch_sheet_rows",
            return_value=[{"Robot Name": "Saw Loser"}],
        ), patch(
            "routes.admin.load_registrations",
            return_value=("sheet123", [registration]),
        ), patch(
            "routes.admin._try_import_image",
            return_value="HTTP 403 Forbidden (application/json): access denied",
        ):
            response = self.client.post(
                f"/admin/events/{self.ids['event_id']}/refresh-sheet",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        location = response.headers["location"]
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.path, f"/admin/events/{self.ids['event_id']}")
        self.assertEqual(params["msg"], ["refreshed"])
        self.assertEqual(
            params["img_warn"],
            ["Saw Loser: HTTP 403 Forbidden (application/json): access denied"],
        )
