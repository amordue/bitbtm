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


class AdminCompetitionJinjaTests(unittest.TestCase):
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
                google_id="org-competition-1",
                email="org@example.com",
                name="Organizer",
                access_token="token-123",
            )
            db.add(organizer)
            db.flush()

            roboteers = [
                Roboteer(roboteer_name="Builder One"),
                Roboteer(roboteer_name="Builder Two"),
                Roboteer(roboteer_name="Builder Three"),
                Roboteer(roboteer_name="Builder Four"),
            ]
            db.add_all(roboteers)
            db.flush()

            robots = [
                Robot(robot_name="Alpha", roboteer_id=roboteers[0].id, weapon_type="Spinner"),
                Robot(robot_name="Beta", roboteer_id=roboteers[1].id, weapon_type="Hammer"),
                Robot(robot_name="Gamma", roboteer_id=roboteers[2].id, weapon_type="Lifter"),
                Robot(robot_name="Delta", roboteer_id=roboteers[3].id, weapon_type="Drum"),
                Robot(robot_name="Epsilon", roboteer_id=roboteers[0].id, weapon_type="Horizontal Spinner"),
                Robot(robot_name="Zeta", roboteer_id=roboteers[1].id, weapon_type="Control"),
            ]
            db.add_all(robots)
            db.flush()

            event = Event(
                event_name="Qualifying Showcase",
                weight_class="Beetleweight",
                organizer_id=organizer.id,
                status=EventStatus.bracket,
            )
            db.add(event)
            db.flush()

            standings_event = Event(
                event_name="Standings Showcase",
                weight_class="Beetleweight",
                organizer_id=organizer.id,
                status=EventStatus.qualifying,
            )
            db.add(standings_event)
            db.flush()

            for robot in robots:
                db.add(EventRobot(event_id=event.id, robot_id=robot.id, is_reserve=False))

            for robot in robots[:4]:
                db.add(EventRobot(event_id=standings_event.id, robot_id=robot.id, is_reserve=False))

            qualifying_phases = []
            for phase_number in range(1, 4):
                phase = Phase(
                    event_id=event.id,
                    phase_number=phase_number,
                    phase_type=PhaseType.qualifying,
                    status=PhaseStatus.complete if phase_number < 3 else PhaseStatus.active,
                )
                db.add(phase)
                qualifying_phases.append(phase)
            db.flush()

            pending_matchup = Matchup(
                phase_id=qualifying_phases[2].id,
                robot1_id=robots[0].id,
                robot2_id=robots[1].id,
                status=MatchupStatus.pending,
                display_order=0,
            )
            bye_matchup = Matchup(
                phase_id=qualifying_phases[2].id,
                robot1_id=robots[2].id,
                robot2_id=None,
                status=MatchupStatus.pending,
                display_order=1,
            )
            completed_matchup = Matchup(
                phase_id=qualifying_phases[0].id,
                robot1_id=robots[0].id,
                robot2_id=robots[3].id,
                status=MatchupStatus.completed,
                display_order=0,
            )
            db.add_all([pending_matchup, bye_matchup, completed_matchup])
            db.flush()
            db.add_all([
                Result(matchup_id=completed_matchup.id, robot_id=robots[0].id, points_scored=5),
                Result(matchup_id=completed_matchup.id, robot_id=robots[3].id, points_scored=1),
            ])

            standings_phases = []
            for phase_number in range(1, 4):
                phase = Phase(
                    event_id=standings_event.id,
                    phase_number=phase_number,
                    phase_type=PhaseType.qualifying,
                    status=PhaseStatus.complete,
                )
                db.add(phase)
                standings_phases.append(phase)
            db.flush()

            standings_matchup = Matchup(
                phase_id=standings_phases[0].id,
                robot1_id=robots[0].id,
                robot2_id=robots[1].id,
                status=MatchupStatus.completed,
                display_order=0,
            )
            db.add(standings_matchup)
            db.flush()
            db.add_all([
                Result(matchup_id=standings_matchup.id, robot_id=robots[0].id, points_scored=5),
                Result(matchup_id=standings_matchup.id, robot_id=robots[1].id, points_scored=1),
            ])

            bracket_phase = Phase(
                event_id=event.id,
                phase_number=1,
                phase_type=PhaseType.bracket,
                status=PhaseStatus.active,
            )
            db.add(bracket_phase)
            db.flush()

            bracket_match_one = Matchup(
                phase_id=bracket_phase.id,
                robot1_id=robots[0].id,
                robot2_id=robots[1].id,
                status=MatchupStatus.pending,
                display_order=0,
                bracket_round=1,
            )
            bracket_match_two = Matchup(
                phase_id=bracket_phase.id,
                robot1_id=robots[2].id,
                robot2_id=robots[3].id,
                status=MatchupStatus.pending,
                display_order=1,
                bracket_round=1,
            )
            db.add_all([bracket_match_one, bracket_match_two])
            db.flush()

            active_sub_event = SubEvent(
                event_id=event.id,
                name="Duo Mayhem",
                format=SubEventFormat.two_v_two_team_bracket,
                status=SubEventStatus.active,
            )
            setup_sub_event = SubEvent(
                event_id=event.id,
                name="Tag Teams",
                format=SubEventFormat.two_v_two_team_bracket,
                status=SubEventStatus.setup,
            )
            db.add_all([active_sub_event, setup_sub_event])
            db.flush()

            skyline = SubEventTeam(
                sub_event_id=active_sub_event.id,
                team_name="Skyline",
                robot1_id=robots[0].id,
                robot2_id=robots[1].id,
            )
            storm_front = SubEventTeam(
                sub_event_id=active_sub_event.id,
                team_name="Storm Front",
                robot1_id=robots[2].id,
                robot2_id=robots[3].id,
            )
            db.add_all([skyline, storm_front])
            db.flush()

            completed_sub_match = SubEventMatchup(
                sub_event_id=active_sub_event.id,
                team1_id=skyline.id,
                team2_id=storm_front.id,
                winner_team_id=skyline.id,
                status=MatchupStatus.completed,
                display_order=0,
                round_number=1,
            )
            pending_sub_match = SubEventMatchup(
                sub_event_id=active_sub_event.id,
                team1_id=skyline.id,
                team2_id=storm_front.id,
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
                    matchup_id=bracket_match_one.id,
                ),
                RunOrder(
                    event_id=event.id,
                    slot_index=1,
                    matchup_type=RunOrderMatchupType.sub_event,
                    matchup_id=completed_sub_match.id,
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
                "organizer_id": organizer.id,
                "event_id": event.id,
                "standings_event_id": standings_event.id,
                "active_phase_id": qualifying_phases[2].id,
                "pending_matchup_id": pending_matchup.id,
                "bye_matchup_id": bye_matchup.id,
                "completed_matchup_id": completed_matchup.id,
                "bracket_match_one_id": bracket_match_one.id,
                "bracket_match_two_id": bracket_match_two.id,
                "active_sub_event_id": active_sub_event.id,
                "setup_sub_event_id": setup_sub_event.id,
                "completed_sub_match_id": completed_sub_match.id,
                "pending_sub_match_id": pending_sub_match.id,
            }

    def test_phase_detail_uses_jinja_matchup_list_and_sortable_hook(self):
        response = self.client.get(
            f"/admin/events/{self.ids['event_id']}/phases/{self.ids['active_phase_id']}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Qualifying Round 3", response.text)
        self.assertIn('id="matchup-list"', response.text)
        self.assertIn("Complete Bye", response.text)
        self.assertIn("Sortable.create", response.text)
        self.assertIn('/static/css/admin.css', response.text)

    def test_score_form_uses_jinja_shell_and_preselects_existing_result(self):
        response = self.client.get(
            f"/admin/events/{self.ids['event_id']}/matchups/{self.ids['completed_matchup_id']}/score"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Edit Fight", response.text)
        self.assertIn("Current result:", response.text)
        self.assertIn("Clear result", response.text)
        self.assertIn('selected', response.text)
        self.assertIn(
            f'action="/admin/events/{self.ids["event_id"]}/matchups/{self.ids["completed_matchup_id"]}/score"',
            response.text,
        )

    def test_bracket_admin_uses_jinja_round_sections_and_rearrange_link(self):
        response = self.client.get(f"/admin/events/{self.ids['event_id']}/bracket")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Bracket", response.text)
        self.assertIn("Qualifying standings", response.text)
        self.assertIn("Rearrange Round 1 Pairings", response.text)
        self.assertIn("Alpha", response.text)
        self.assertIn("Beta", response.text)

    def test_bracket_rearrange_form_uses_jinja_shell(self):
        response = self.client.get(f"/admin/events/{self.ids['event_id']}/bracket/rearrange")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Rearrange Round 1", response.text)
        self.assertIn("Swap Robot 2s", response.text)
        self.assertIn('name="matchup_a"', response.text)
        self.assertIn('name="matchup_b"', response.text)

    def test_qualifying_standings_uses_jinja_table_and_bracket_call_to_action(self):
        response = self.client.get(
            f"/admin/events/{self.ids['standings_event_id']}/qualifying/standings"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Qualifying Standings", response.text)
        self.assertIn("Generate Bracket (Top 16)", response.text)
        self.assertIn("Builder One", response.text)
        self.assertIn("Bracket", response.text)

    def test_new_sub_event_form_uses_jinja_and_lists_eligible_robot_pool(self):
        response = self.client.get(f"/admin/events/{self.ids['event_id']}/sub-events/new")

        self.assertEqual(response.status_code, 200)
        self.assertIn("New Sub-event", response.text)
        self.assertIn("Eligible Robot Pool", response.text)
        self.assertIn("Epsilon", response.text)
        self.assertIn('action="/admin/events/', response.text)

    def test_sub_event_detail_uses_jinja_cards_and_completion_flash(self):
        response = self.client.get(
            f"/admin/events/{self.ids['event_id']}/sub-events/{self.ids['active_sub_event_id']}?msg=sub_event_complete"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Duo Mayhem", response.text)
        self.assertIn("Sub-event marked complete.", response.text)
        self.assertIn("Skyline", response.text)
        self.assertIn("Storm Front", response.text)
        self.assertIn("Score", response.text)

    def test_add_team_form_uses_jinja_selects_for_eligible_robots(self):
        response = self.client.get(
            f"/admin/events/{self.ids['event_id']}/sub-events/{self.ids['setup_sub_event_id']}/teams/add"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Add Team", response.text)
        self.assertIn('name="robot1_id"', response.text)
        self.assertIn('name="robot2_id"', response.text)
        self.assertIn("Epsilon", response.text)
        self.assertIn("Zeta", response.text)

    def test_sub_event_score_form_uses_jinja_shell_and_existing_winner(self):
        response = self.client.get(
            f"/admin/events/{self.ids['event_id']}/sub-events/{self.ids['active_sub_event_id']}/matchups/{self.ids['completed_sub_match_id']}/score"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Edit Fight", response.text)
        self.assertIn("Current result:", response.text)
        self.assertIn("Clear result", response.text)
        self.assertIn("selected", response.text)

    def test_run_order_editor_uses_jinja_list_and_sortable_hook(self):
        response = self.client.get(f"/admin/events/{self.ids['event_id']}/run-order")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Run Order", response.text)
        self.assertIn('id="run-order-list"', response.text)
        self.assertIn("Sortable.create", response.text)
        self.assertIn("SE R2", response.text)
        self.assertIn("Duo Mayhem", response.text)
        self.assertIn("is-locked", response.text)