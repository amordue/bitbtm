import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database
from app import app
from database import get_db
from models import (
    Base,
    Event,
    EventRobot,
    EventStatus,
    Matchup,
    MatchupStatus,
    Phase,
    PhaseStatus,
    PhaseType,
    Result,
    Robot,
    Roboteer,
    RunOrder,
    RunOrderMatchupType,
    SubEvent,
    SubEventFormat,
    SubEventMatchup,
    SubEventStatus,
    SubEventTeam,
    User,
)


class Phase6PublicViewsTests(unittest.TestCase):
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
            organizer = User(google_id="org-1", email="org@example.com", name="Organizer")
            db.add(organizer)
            db.flush()

            roboteers = [
                Roboteer(roboteer_name="Alex"),
                Roboteer(roboteer_name="Blair"),
                Roboteer(roboteer_name="Casey"),
                Roboteer(roboteer_name="Devon"),
            ]
            db.add_all(roboteers)
            db.flush()

            robots = [
                Robot(
                    robot_name="Alpha",
                    roboteer_id=roboteers[0].id,
                    weapon_type="Vertical spinner",
                    image_url="https://example.com/alpha.png",
                ),
                Robot(robot_name="Beta", roboteer_id=roboteers[1].id, weapon_type="Hammer"),
                Robot(robot_name="Gamma", roboteer_id=roboteers[2].id, weapon_type="Lifter"),
                Robot(robot_name="Delta", roboteer_id=roboteers[3].id, weapon_type="Drum"),
            ]
            db.add_all(robots)
            db.flush()

            event = Event(
                event_name="Spring Slam",
                weight_class="Beetleweight",
                organizer_id=organizer.id,
                status=EventStatus.sub_events,
            )
            db.add(event)
            db.flush()

            db.add_all([
                EventRobot(event_id=event.id, robot_id=robot.id, is_reserve=False)
                for robot in robots
            ])

            q1 = Phase(
                event_id=event.id,
                phase_number=1,
                phase_type=PhaseType.qualifying,
                status=PhaseStatus.complete,
            )
            q2 = Phase(
                event_id=event.id,
                phase_number=2,
                phase_type=PhaseType.qualifying,
                status=PhaseStatus.complete,
            )
            bracket = Phase(
                event_id=event.id,
                phase_number=1,
                phase_type=PhaseType.bracket,
                status=PhaseStatus.active,
            )
            db.add_all([q1, q2, bracket])
            db.flush()

            q1_match = Matchup(
                phase_id=q1.id,
                robot1_id=robots[0].id,
                robot2_id=robots[1].id,
                status=MatchupStatus.completed,
                display_order=0,
            )
            q2_match = Matchup(
                phase_id=q2.id,
                robot1_id=robots[0].id,
                robot2_id=robots[3].id,
                status=MatchupStatus.completed,
                display_order=0,
            )
            bracket_match = Matchup(
                phase_id=bracket.id,
                robot1_id=robots[0].id,
                robot2_id=robots[2].id,
                status=MatchupStatus.pending,
                display_order=0,
                bracket_round=1,
            )
            db.add_all([q1_match, q2_match, bracket_match])
            db.flush()

            db.add_all([
                Result(matchup_id=q1_match.id, robot_id=robots[0].id, points_scored=5),
                Result(matchup_id=q1_match.id, robot_id=robots[1].id, points_scored=1),
                Result(matchup_id=q2_match.id, robot_id=robots[0].id, points_scored=2),
                Result(matchup_id=q2_match.id, robot_id=robots[3].id, points_scored=4),
            ])

            sub_event = SubEvent(
                event_id=event.id,
                name="Duo Mayhem",
                format=SubEventFormat.two_v_two_team_bracket,
                status=SubEventStatus.active,
            )
            db.add(sub_event)
            db.flush()

            alpha_team = SubEventTeam(
                sub_event_id=sub_event.id,
                team_name="Skyline",
                robot1_id=robots[0].id,
                robot2_id=robots[2].id,
            )
            beta_team = SubEventTeam(
                sub_event_id=sub_event.id,
                team_name="Iron Pair",
                robot1_id=robots[1].id,
                robot2_id=robots[3].id,
            )
            db.add_all([alpha_team, beta_team])
            db.flush()

            completed_sub_match = SubEventMatchup(
                sub_event_id=sub_event.id,
                team1_id=alpha_team.id,
                team2_id=beta_team.id,
                winner_team_id=beta_team.id,
                status=MatchupStatus.completed,
                display_order=0,
                round_number=1,
            )
            pending_sub_match = SubEventMatchup(
                sub_event_id=sub_event.id,
                team1_id=alpha_team.id,
                team2_id=beta_team.id,
                status=MatchupStatus.pending,
                display_order=1,
                round_number=2,
            )
            db.add_all([completed_sub_match, pending_sub_match])
            db.flush()

            db.add_all([
                RunOrder(
                    event_id=event.id,
                    slot_index=0,
                    matchup_type=RunOrderMatchupType.main,
                    matchup_id=q1_match.id,
                ),
                RunOrder(
                    event_id=event.id,
                    slot_index=1,
                    matchup_type=RunOrderMatchupType.main,
                    matchup_id=bracket_match.id,
                ),
                RunOrder(
                    event_id=event.id,
                    slot_index=2,
                    matchup_type=RunOrderMatchupType.sub_event,
                    matchup_id=pending_sub_match.id,
                ),
            ])

            db.commit()
            return {
                "event_id": event.id,
                "alpha_id": robots[0].id,
                "gamma_id": robots[2].id,
            }

    def test_live_display_shows_current_match_and_leaderboard(self):
        response = self.client.get(f"/events/{self.ids['event_id']}/live")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Live Display", response.text)
        self.assertIn('class="content live-page-shell"', response.text)
        self.assertIn("Alpha vs Gamma", response.text)
        self.assertIn("Leaderboard", response.text)
        self.assertIn(f'hx-get="/events/{self.ids["event_id"]}/live/panel"', response.text)
        self.assertIn('class="live-robot-photo"', response.text)
        self.assertIn('src="https://example.com/alpha.png"', response.text)
        self.assertIn("Alpha", response.text)
        self.assertTrue(
            ">7<" in response.text or "7 qualifying" in response.text,
            msg="Expected Alpha's seven points to appear in the live display.",
        )

    def test_next_up_board_uses_unified_run_order(self):
        response = self.client.get(f"/events/{self.ids['event_id']}/next-up")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Next Up Board", response.text)
        self.assertIn(
            f'<a href="/events/{self.ids["event_id"]}/robot/{self.ids["alpha_id"]}" class="queue-title-link">Alpha</a>',
            response.text,
        )
        self.assertIn(
            f'<a href="/events/{self.ids["event_id"]}/robot/{self.ids["gamma_id"]}" class="queue-title-link">Gamma</a>',
            response.text,
        )
        self.assertIn("Skyline vs Iron Pair", response.text)
        self.assertIn(
            f'href="/events/{self.ids["event_id"]}/robot/{self.ids["alpha_id"]}"',
            response.text,
        )
        self.assertIn(
            f'href="/events/{self.ids["event_id"]}/robot/{self.ids["gamma_id"]}"',
            response.text,
        )
        self.assertNotIn(
            'class="btn btn-sm btn-secondary"',
            response.text,
        )
        self.assertLess(
            response.text.index(
                f'<a href="/events/{self.ids["event_id"]}/robot/{self.ids["alpha_id"]}" class="queue-title-link">Alpha</a>'
            ),
            response.text.index("Skyline vs Iron Pair"),
        )

    def test_robot_history_includes_main_and_sub_event_results(self):
        response = self.client.get(
            f"/events/{self.ids['event_id']}/robot/{self.ids['alpha_id']}/history"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Alpha history", response.text)
        self.assertIn("Duo Mayhem", response.text)
        self.assertIn("Team loss", response.text)
        self.assertTrue(
            "Beta" in response.text or "Delta" in response.text,
            msg="Expected main-event opponents to appear in Alpha's history.",
        )

    def test_robot_stats_show_totals_and_head_to_head(self):
        response = self.client.get(
            f"/events/{self.ids['event_id']}/robot/{self.ids['alpha_id']}/stats"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Alpha stats", response.text)
        self.assertIn("1W 1L 0D", response.text)
        self.assertIn("Beta", response.text)
        self.assertIn("Delta", response.text)
        self.assertIn("5-1", response.text)
        self.assertIn("2-4", response.text)

    def test_robot_page_places_large_image_below_summary(self):
        response = self.client.get(
            f"/events/{self.ids['event_id']}/robot/{self.ids['alpha_id']}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('class="content robot-page-shell"', response.text)
        self.assertIn('class="robot-detail-hero"', response.text)
        self.assertIn('class="robot-detail-photo-button"', response.text)
        self.assertIn('<div hidden class="robot-lightbox">', response.text)
        self.assertIn('data-lightbox-src="https://example.com/alpha.png"', response.text)
        self.assertLess(
            response.text.index("<h1>Alpha</h1>"),
            response.text.index('class="robot-detail-photo-button"'),
        )
        self.assertLess(
            response.text.index("2 fight(s) played"),
            response.text.index('class="robot-detail-photo-button"'),
        )

    def test_qr_page_embeds_svg_endpoint(self):
        page_response = self.client.get(f"/events/{self.ids['event_id']}/qr")
        svg_response = self.client.get(f"/events/{self.ids['event_id']}/qr.svg")

        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Event QR Code", page_response.text)
        self.assertIn(
            f'<img src="/events/{self.ids["event_id"]}/qr.svg"',
            page_response.text,
        )
        self.assertIn("Open event page", page_response.text)
        self.assertNotIn("<?xml", page_response.text)

        self.assertEqual(svg_response.status_code, 200)
        self.assertEqual(svg_response.headers["content-type"], "image/svg+xml")
        self.assertIn("<?xml", svg_response.text)
        self.assertIn("<svg", svg_response.text)

    def test_public_views_include_auto_refresh_panels(self):
        overview_response = self.client.get(f"/events/{self.ids['event_id']}")
        leaderboard_response = self.client.get(f"/events/{self.ids['event_id']}/leaderboard")
        bracket_response = self.client.get(f"/events/{self.ids['event_id']}/bracket")
        live_response = self.client.get(f"/events/{self.ids['event_id']}/live")
        next_up_response = self.client.get(f"/events/{self.ids['event_id']}/next-up")
        robot_response = self.client.get(
            f"/events/{self.ids['event_id']}/robot/{self.ids['alpha_id']}"
        )
        history_response = self.client.get(
            f"/events/{self.ids['event_id']}/robot/{self.ids['alpha_id']}/history"
        )
        stats_response = self.client.get(
            f"/events/{self.ids['event_id']}/robot/{self.ids['alpha_id']}/stats"
        )

        self.assertEqual(overview_response.status_code, 200)
        self.assertEqual(leaderboard_response.status_code, 200)
        self.assertEqual(bracket_response.status_code, 200)
        self.assertEqual(live_response.status_code, 200)
        self.assertEqual(next_up_response.status_code, 200)
        self.assertEqual(robot_response.status_code, 200)
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(stats_response.status_code, 200)
        self.assertIn(
            f'hx-get="/events/{self.ids["event_id"]}/overview-panel"',
            overview_response.text,
        )
        self.assertIn('hx-trigger="every 20s"', overview_response.text)
        self.assertNotIn('hx-trigger="load, every 20s"', overview_response.text)
        self.assertIn(
            f'hx-get="/events/{self.ids["event_id"]}/leaderboard/panel"',
            leaderboard_response.text,
        )
        self.assertIn('hx-trigger="every 20s"', leaderboard_response.text)
        self.assertIn(
            f'hx-get="/events/{self.ids["event_id"]}/bracket/panel"',
            bracket_response.text,
        )
        self.assertIn('hx-trigger="every 20s"', bracket_response.text)
        self.assertIn(
            f'hx-get="/events/{self.ids["event_id"]}/live/panel"',
            live_response.text,
        )
        self.assertIn('hx-trigger="every 15s"', live_response.text)
        self.assertIn(
            f'hx-get="/events/{self.ids["event_id"]}/next-up/panel"',
            next_up_response.text,
        )
        self.assertIn('hx-trigger="every 20s"', next_up_response.text)
        self.assertIn(
            f'hx-get="/events/{self.ids["event_id"]}/robot/{self.ids["alpha_id"]}/panel"',
            robot_response.text,
        )
        self.assertIn('hx-trigger="every 20s"', robot_response.text)
        self.assertIn(
            f'hx-get="/events/{self.ids["event_id"]}/robot/{self.ids["alpha_id"]}/history/panel"',
            history_response.text,
        )
        self.assertIn('hx-trigger="every 20s"', history_response.text)
        self.assertIn(
            f'hx-get="/events/{self.ids["event_id"]}/robot/{self.ids["alpha_id"]}/stats/panel"',
            stats_response.text,
        )
        self.assertIn('hx-trigger="every 20s"', stats_response.text)
        for response in (
            overview_response,
            leaderboard_response,
            bracket_response,
            live_response,
            next_up_response,
            robot_response,
            history_response,
            stats_response,
        ):
            self.assertNotIn('hx-trigger="load, every ', response.text)

    def test_sub_events_list_renders_from_live_page_link(self):
        response = self.client.get(f"/events/{self.ids['event_id']}/sub-events")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Sub-events", response.text)
        self.assertIn("Duo Mayhem", response.text)
        self.assertIn(
            f'href="/events/{self.ids["event_id"]}/sub-events/1"',
            response.text,
        )

    # ------------------------------------------------------------------
    # Fallback archetype images
    # ------------------------------------------------------------------

    def test_robot_detail_shows_fallback_archetype_image_without_lightbox(self):
        """Robot with weapon_type but no image_url gets archetype art, no lightbox."""
        # Beta has weapon_type="Hammer" and no image_url
        with self.testing_session_local() as db:
            beta = db.query(Robot).filter(Robot.robot_name == "Beta").one()
            beta_id = beta.id

        response = self.client.get(f"/events/{self.ids['event_id']}/robot/{beta_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn('/static/robot-archetypes/hammer.svg', response.text)
        self.assertIn('class="robot-detail-photo"', response.text)
        # No lightbox for fallback art
        self.assertNotIn('class="robot-lightbox"', response.text)

    def test_robot_detail_uploaded_image_still_has_lightbox(self):
        """Robot with real image_url still gets the lightbox treatment."""
        response = self.client.get(
            f"/events/{self.ids['event_id']}/robot/{self.ids['alpha_id']}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-lightbox-src="https://example.com/alpha.png"', response.text)
        self.assertIn('class="robot-lightbox"', response.text)

    def test_leaderboard_uses_fallback_thumbnails(self):
        """Leaderboard thumbnails show archetype images for robots without photos."""
        response = self.client.get(f"/events/{self.ids['event_id']}/leaderboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn('/static/robot-archetypes/hammer.svg', response.text)
        self.assertIn('/static/robot-archetypes/drum-spinner.svg', response.text)

    def test_live_display_uses_fallback_images(self):
        """Live display cards show archetype images instead of initial-letter placeholders."""
        response = self.client.get(f"/events/{self.ids['event_id']}/live")
        self.assertEqual(response.status_code, 200)
        # Gamma (Lifter, no image_url) should get fallback art
        self.assertIn('/static/robot-archetypes/lifter.svg', response.text)
        self.assertIn('class="live-robot-photo"', response.text)

    def test_lookup_uses_fallback_thumbnails(self):
        """Robot lookup results show archetype thumbnails for robots without photos."""
        response = self.client.get(
            f"/events/{self.ids['event_id']}/lookup",
            params={"q": "Beta"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('/static/robot-archetypes/hammer.svg', response.text)

    def test_sub_event_team_roster_uses_fallback_thumbnails(self):
        """Sub-event team roster shows archetype thumbnails for image-less robots."""
        with self.testing_session_local() as db:
            se = db.query(SubEvent).filter(SubEvent.name == "Duo Mayhem").one()
            se_id = se.id

        response = self.client.get(
            f"/events/{self.ids['event_id']}/sub-events/{se_id}"
        )
        self.assertEqual(response.status_code, 200)
        # Beta (Hammer) and Delta (Drum) are on Iron Pair team, no uploaded images
        self.assertIn('/static/robot-archetypes/hammer.svg', response.text)
        self.assertIn('/static/robot-archetypes/drum-spinner.svg', response.text)

    def test_tbd_bye_slots_do_not_show_archetype_art(self):
        """TBD/BYE slots should show placeholder, not archetype images."""
        response = self.client.get(f"/events/{self.ids['event_id']}/live")
        self.assertEqual(response.status_code, 200)
        # The "BYE" side should NOT have a robot-archetypes path
        # (only real Robot records get fallback art)
        self.assertNotIn('/static/robot-archetypes/generic.svg" class="live-robot-photo-placeholder"', response.text)


class TestNormalizeWeaponType(unittest.TestCase):
    """Unit tests for weapon_type → archetype alias normalization."""

    def test_known_types(self):
        from robot_images import normalize_weapon_type

        cases = {
            "Vertical spinner": "vertical-spinner",
            "vertical spinner": "vertical-spinner",
            "Hammer": "hammer",
            "Lifter": "lifter",
            "Drum": "drum-spinner",
            "drum spinner": "drum-spinner",
            "Flipper": "flipper",
            "Horizontal spinner": "horizontal-spinner",
            "Saw": "saw",
            "Grabber": "grabber",
            "Cluster": "cluster",
            "Rammer": "rammer",
            "Wedge": "rammer",
            "Spinner": "vertical-spinner",
            "Hammer-Saw": "saw",
        }
        for weapon, expected in cases.items():
            with self.subTest(weapon=weapon):
                self.assertEqual(normalize_weapon_type(weapon), expected)

    def test_unknown_falls_back_to_generic(self):
        from robot_images import normalize_weapon_type

        self.assertEqual(normalize_weapon_type("Laser cannon"), "generic")
        self.assertEqual(normalize_weapon_type("???"), "generic")

    def test_none_and_empty(self):
        from robot_images import normalize_weapon_type

        self.assertEqual(normalize_weapon_type(None), "generic")
        self.assertEqual(normalize_weapon_type(""), "generic")

    def test_messy_whitespace_and_punctuation(self):
        from robot_images import normalize_weapon_type

        self.assertEqual(normalize_weapon_type("  VERTICAL   SPINNER  "), "vertical-spinner")
        self.assertEqual(normalize_weapon_type("hammer--saw"), "saw")


class TestRobotDisplayImageUrl(unittest.TestCase):
    """Unit tests for robot_display_image_url priority logic."""

    def test_none_robot_returns_none(self):
        from robot_images import robot_display_image_url

        self.assertIsNone(robot_display_image_url(None))

    def test_uploaded_image_takes_priority(self):
        from robot_images import robot_display_image_url

        robot = Robot(robot_name="Test", weapon_type="Hammer", image_url="https://example.com/test.png")
        self.assertEqual(robot_display_image_url(robot), "https://example.com/test.png")

    def test_weapon_type_maps_to_archetype(self):
        from robot_images import robot_display_image_url

        robot = Robot(robot_name="Test", weapon_type="Drum")
        self.assertEqual(robot_display_image_url(robot), "/static/robot-archetypes/drum-spinner.svg")

    def test_no_weapon_type_returns_generic(self):
        from robot_images import robot_display_image_url

        robot = Robot(robot_name="Test")
        self.assertEqual(robot_display_image_url(robot), "/static/robot-archetypes/generic.svg")


if __name__ == "__main__":
    unittest.main()
