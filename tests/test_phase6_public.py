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
                Robot(robot_name="Alpha", roboteer_id=roboteers[0].id, weapon_type="Vertical spinner"),
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
            }

    def test_live_display_shows_current_match_and_leaderboard(self):
        response = self.client.get(f"/events/{self.ids['event_id']}/live")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Live Display", response.text)
        self.assertIn("Alpha vs Gamma", response.text)
        self.assertIn("Leaderboard", response.text)
        self.assertIn(f'hx-get="/events/{self.ids["event_id"]}/live/panel"', response.text)
        self.assertIn("Alpha", response.text)
        self.assertTrue(
            ">7<" in response.text or "7 qualifying" in response.text,
            msg="Expected Alpha's seven points to appear in the live display.",
        )

    def test_next_up_board_uses_unified_run_order(self):
        response = self.client.get(f"/events/{self.ids['event_id']}/next-up")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Next Up Board", response.text)
        self.assertIn("Alpha vs Gamma", response.text)
        self.assertIn("Skyline vs Iron Pair", response.text)
        self.assertLess(
            response.text.index("Alpha vs Gamma"),
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

    def test_public_views_include_auto_refresh_panels(self):
        leaderboard_response = self.client.get(f"/events/{self.ids['event_id']}/leaderboard")
        robot_response = self.client.get(
            f"/events/{self.ids['event_id']}/robot/{self.ids['alpha_id']}"
        )

        self.assertEqual(leaderboard_response.status_code, 200)
        self.assertEqual(robot_response.status_code, 200)
        self.assertIn(
            f'hx-get="/events/{self.ids["event_id"]}/leaderboard/panel"',
            leaderboard_response.text,
        )
        self.assertIn(
            f'hx-get="/events/{self.ids["event_id"]}/robot/{self.ids["alpha_id"]}/panel"',
            robot_response.text,
        )


if __name__ == "__main__":
    unittest.main()
