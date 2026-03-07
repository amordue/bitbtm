import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from event_imports import upsert_robot
from google_sheets import fetch_sheet_rows, parse_robot_registrations
from models import ImageSource, Robot, Roboteer
from routes.admin import _try_import_image


class _FakeResponse:
    def __init__(self, payload: bytes, content_type: str, content_disposition: str | None = None):
        self._payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if content_disposition:
            self.headers["Content-Disposition"] = content_disposition

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._payload


class _FakeSheetsGetRequest:
    def __init__(self, result: dict):
        self._result = result

    def execute(self) -> dict:
        return self._result


class _FakeSpreadsheetsService:
    def __init__(self, result: dict):
        self._result = result

    def get(self, **kwargs):
        return _FakeSheetsGetRequest(self._result)


class _FakeSheetsService:
    def __init__(self, result: dict):
        self._result = result

    def spreadsheets(self):
        return _FakeSpreadsheetsService(self._result)


class GoogleSheetsImportTests(unittest.TestCase):
    def test_fetch_sheet_rows_uses_hyperlink_targets(self):
        service_result = {
            "sheets": [
                {
                    "data": [
                        {
                            "rowData": [
                                {
                                    "values": [
                                        {"formattedValue": "Roboteer Name"},
                                        {"formattedValue": "Email"},
                                        {"formattedValue": "Robot Name"},
                                        {"formattedValue": "Image URL"},
                                        {"formattedValue": "Weapon Type"},
                                    ]
                                },
                                {
                                    "values": [
                                        {"formattedValue": "Alex Mordue"},
                                        {"formattedValue": "alex@example.com"},
                                        {"formattedValue": "Saw Loser"},
                                        {
                                            "formattedValue": "Saw Loser 2 thing - Alex Mordue.PNG",
                                            "hyperlink": "https://drive.google.com/file/d/file123/view?usp=drive_link",
                                        },
                                        {"formattedValue": "Hammer-Saw"},
                                    ]
                                },
                            ]
                        }
                    ]
                }
            ]
        }

        with patch(
            "google_sheets._build_service",
            return_value=_FakeSheetsService(service_result),
        ):
            rows = fetch_sheet_rows(
                "https://docs.google.com/spreadsheets/d/sheet123/edit#gid=0",
                "token-123",
            )

        self.assertEqual(
            rows,
            [
                {
                    "Roboteer Name": "Alex Mordue",
                    "Email": "alex@example.com",
                    "Robot Name": "Saw Loser",
                    "Image URL": "https://drive.google.com/file/d/file123/view?usp=drive_link",
                    "Weapon Type": "Hammer-Saw",
                }
            ],
        )

        registrations = parse_robot_registrations(rows, "sheet123")
        self.assertEqual(registrations[0]["contact_email"], "alex@example.com")
        self.assertEqual(
            registrations[0]["image_url"],
            "https://drive.google.com/file/d/file123/view?usp=drive_link",
        )

    def test_try_import_image_downloads_google_drive_file_with_bearer_token(self):
        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            return _FakeResponse(b"png-bytes", "image/png")

        robot = Robot(robot_name="Saw Loser", roboteer_id=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("routes.admin.UPLOAD_DIR", tmpdir), patch(
                "routes.admin.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ):
                _try_import_image(
                    robot,
                    "https://drive.google.com/file/d/file123/view?usp=drive_link",
                    access_token="token-abc",
                )

            self.assertEqual(
                captured["url"],
                "https://www.googleapis.com/drive/v3/files/file123?alt=media",
            )
            self.assertEqual(captured["authorization"], "Bearer token-abc")
            self.assertEqual(robot.image_source, ImageSource.upload)
            self.assertTrue(robot.image_url.startswith("/static/uploads/"))

            saved_name = Path(robot.image_url).name
            saved_path = Path(tmpdir) / saved_name
            self.assertTrue(saved_path.exists())
            self.assertEqual(saved_path.read_bytes(), b"png-bytes")

    def test_try_import_image_accepts_octet_stream_when_filename_is_image(self):
        robot = Robot(robot_name="Saw Loser", roboteer_id=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("routes.admin.UPLOAD_DIR", tmpdir), patch(
                "routes.admin.urllib.request.urlopen",
                return_value=_FakeResponse(
                    b"png-bytes",
                    "application/octet-stream",
                    'attachment; filename="Saw Loser.png"',
                ),
            ):
                _try_import_image(
                    robot,
                    "https://drive.google.com/open?id=file123",
                    access_token="token-abc",
                )

            self.assertEqual(robot.image_source, ImageSource.upload)
            self.assertTrue(robot.image_url.startswith("/static/uploads/"))
            self.assertTrue(robot.image_url.endswith(".png"))

            saved_name = Path(robot.image_url).name
            saved_path = Path(tmpdir) / saved_name
            self.assertTrue(saved_path.exists())
            self.assertEqual(saved_path.read_bytes(), b"png-bytes")


class ExistingRobotImageRefreshTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_local = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        Base.metadata.create_all(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_existing_robot_without_uploaded_image_backfills_from_sheet(self):
        registration = {
            "sheet_row_id": "sheet123:2",
            "roboteer_name": "Alex Mordue",
            "robot_name": "Saw Loser",
            "weapon_type": "Hammer-Saw",
            "image_url": "https://example.com/saw-loser.png",
        }
        imported = []

        def fake_import_image(robot, image_url):
            imported.append((robot.id, image_url))
            robot.image_url = "/static/uploads/backfilled.png"
            robot.image_source = ImageSource.sheet

        with self.session_local() as db:
            roboteer = Roboteer(roboteer_name="Alex Mordue")
            db.add(roboteer)
            db.flush()
            robot = Robot(
                robot_name="Saw Loser",
                roboteer_id=roboteer.id,
                weapon_type="Hammer-Saw",
                sheet_row_id="sheet123:2",
                image_source=ImageSource.none,
            )
            db.add(robot)
            db.commit()

            refreshed = upsert_robot(
                registration,
                "sheet123",
                db,
                import_image=fake_import_image,
            )

            self.assertEqual(refreshed.id, robot.id)
            self.assertEqual(imported, [(robot.id, "https://example.com/saw-loser.png")])
            self.assertEqual(refreshed.image_source, ImageSource.sheet)
            self.assertEqual(refreshed.image_url, "/static/uploads/backfilled.png")

    def test_existing_robot_with_uploaded_image_is_not_overwritten(self):
        registration = {
            "sheet_row_id": "sheet123:2",
            "roboteer_name": "Alex Mordue",
            "robot_name": "Saw Loser",
            "weapon_type": "Hammer-Saw",
            "image_url": "https://example.com/saw-loser.png",
        }

        with self.session_local() as db:
            roboteer = Roboteer(roboteer_name="Alex Mordue")
            db.add(roboteer)
            db.flush()
            robot = Robot(
                robot_name="Saw Loser",
                roboteer_id=roboteer.id,
                weapon_type="Hammer-Saw",
                sheet_row_id="sheet123:2",
                image_url="/static/uploads/manual.png",
                image_source=ImageSource.upload,
            )
            db.add(robot)
            db.commit()

            upsert_robot(
                registration,
                "sheet123",
                db,
                import_image=lambda *_args: self.fail("manual upload should be preserved"),
            )

            self.assertEqual(robot.image_source, ImageSource.upload)
            self.assertEqual(robot.image_url, "/static/uploads/manual.png")
