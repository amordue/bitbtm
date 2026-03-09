# Plan: Robot Combat Tournament Management System

## TL;DR
Build a tournament management system for robot combat events using FastAPI + FastHTML (HTMX-integrated subapp). Roboteers register via Google Forms (data flows to Google Sheets), tournament organizers import selected robots from Google Sheets into the system, manage events and scoring. Roboteers view their matchups via public/shareable links. Tournament format: 3 qualifying rounds (random matching) with point scoring, then top 16 progress to single-elimination bracket. Events support sub-events (e.g. a 2v2 team competition using remaining robots after the 3 qualifying rounds and main bracket round 1).

## Architecture Overview
- **Backend**: FastAPI (REST API core) + FastHTML as subapp (HTMX server-rendered views)
- **Frontend**: HTMX for dynamic interactions, minimal JavaScript
- **Database**: SQLite (dev/local), PostgreSQL (production-ready schema)
- **Auth**: Organizer authentication via Google OAuth (same login used for Sheets access); no separate username/password
- **External Integration**: Google Sheets API via OAuth (organizer grants access through browser login)

## Core Domain Model
- **Roboteers**: Individual robot builders/operators (imported from Google Sheets)
- **Robots**: Individual robots (name, weapon type, image; weight class is set at event level, not per robot)
- **Events**: Tournaments with a fixed weight class, phases, schedule, and associated Google Sheet URL
- **Phases**: Qualifying rounds (1-3) and bracket phase
- **SubEvents**: Optional additional competitions attached to an event (e.g. 2v2 team bracket); each has its own format and status
- **SubEventTeams**: Multi-robot teams created by the organizer for a sub-event
- **Matchups**: Individual 1v1 battles (main event) or team-vs-team battles (sub-event)
- **Results**: Points scored by each robot in a matchup. Scoring scale: 0 (forfeit/no-show), 1 (knocked out), 2 (lost judges decision), 4 (won judges decision), 5 (knocked out opponent). Byes award 5 points.
- **Import tracking**: Track which Google Sheet rows have been imported to prevent duplicates
- **RobotRetirements**: Logs which robot was retired, which reserve replaced it, and at which phase/round

## Steps

### Phase 1: Project Setup & Data Model
1. Initialize FastAPI project structure (app.py, requirements.txt, .env)
2. Set up FastHTML sub-application within FastAPI
3. Set up Google Sheets API credentials and access
4. Design and implement database schema:
   - Users table (organizer only, stores Google OAuth tokens and profile info)
   - Roboteers table (roboteer_name, contact_email, imported_from_sheet_id)
   - Robots table (robot_name, roboteer_id, weapon_type, sheet_row_id, image_url, image_source: "sheet"/"upload"/"none", created_at)
   - Events table (event_name, weight_class, google_sheet_url, status: "setup"/"registration"/"qualifying"/"bracket"/"sub_events"/"complete", organizer_id)
   - EventRobots (registration join table for robots selected for event; includes `is_reserve` boolean and `reserve_order` integer for ordering reserves)
   - Phases table (event_id, phase_number, phase_type: "qualifying"/"bracket", status)
   - Matchups table (phase_id, robot1_id, robot2_id, status: "pending"/"completed", `display_order` integer for fight ordering across both main event and sub-event matchups in the run order)
   - Results table (matchup_id, robot_id, points_scored)
   - SubEvents table (event_id, name, format: "2v2_team_bracket", status: "setup"/"active"/"complete")
   - SubEventTeams table (sub_event_id, team_name, robot1_id, robot2_id)
   - SubEventMatchups table (sub_event_id, team1_id, team2_id, status: "pending"/"completed", display_order, winner_team_id, round_number)
   - RunOrder table (event_id, slot_index, matchup_type: "main"/"sub_event", matchup_id) — unified ordered list of all fights across main and sub-events, used for the "next up" board and live display
5. Create SQLAlchemy models for all entities
6. Set up database migrations (Alembic)

### Phase 2: Authentication & Google Sheets Integration
7. Implement Google OAuth flow for organizer login (handles both app authentication and Sheets API access with a single login)
8. Store OAuth tokens securely; refresh tokens automatically for Sheets API calls
9. Create middleware/decorators to protect organizer routes (check valid Google session)
10. Build login page (FastHTML template with "Sign in with Google" button)
11. Implement Google Sheets API client wrapper (uses organizer's OAuth token)
12. Create function to fetch and parse robot registration data from Google Sheets

### Phase 3: Public Roboteer Views (No Auth Required, Mobile-Friendly)
13. Create public event view page (accessible via shareable link/URL with event ID)
14. Build public robot lookup — roboteers can search for their robot by name
15. Create "My Robot's Fights" view — show all matchups for a specific robot (past and upcoming)
16. Build public leaderboard view — anyone can see tournament standings
17. Create public bracket visualization — view single-elimination bracket progress
18. Add QR code generation for event pages (for easy mobile access at tournament venue)

### Phase 4: Organizer Features - Event Management & Import
19. Create event creation form (FastHTML) — organizer sets event name, weight class, Google Sheet URL, robot limit
20. Build Google Sheets import interface:
    - Show preview of data from Google Sheets
    - Allow organizer to select which rows/robots to import
    - Handle duplicate detection (check if robot/team already exists)
    - Map sheet columns to database fields (roboteer name, robot name, weapon type, etc.) — weight class is not expected from roboteers
21. Build event management dashboard — view imported robots, phase status
22. Implement phase transition logic (setup → registration → qualifying → bracket → sub_events → complete)
23. Add ability to manually add/edit/remove robots from event roster
23a. Add ability to designate robots as reserves when importing or managing the roster (ordered list of reserves)
23b. Build "swap in reserve" workflow — organizer can retire a robot (e.g. after round 1) and replace it with the next available reserve for subsequent rounds; retired robot's prior results are preserved
24. Create "refresh from sheet" function to pull latest registrations
24a. During Google Sheets import, attempt to import a robot image from a URL column in the sheet (if present); store URL or download and serve locally
24b. Add manual image upload endpoint and UI for organizers to upload/replace a robot's image (stored in local file storage or object storage)

### Phase 5: Tournament Execution - Matching & Scoring
25. Implement matching algorithm:
    - Qualifying rounds 1-3: Random pairing; if odd number of robots, one gets a bye (awarded 5 points)
    - Generate matchup records, store in database
26. Create organizer interface to view/edit generated matchups — includes drag-and-drop reordering of fights within a phase (persists `display_order` to database via HTMX + SortableJS)
27. Build fight result entry form (FastHTML) — organizer selects outcome per robot from scoring scale (0 forfeit / 1 KO'd / 2 lost decision / 4 won decision / 5 KO'd opponent)
28. Implement bracket advancement: after qualifying rounds, select top 16 and auto-generate single-elimination bracket with random draw (avoiding repeat matchups from qualifying where possible); organizer can manually adjust pairings before starting
29. Create bracket visualization (organizer management view)
30. Add result confirmation/edit workflow

### Phase 5b: Sub-Event Management
31. Build sub-event creation interface — organizer creates a sub-event attached to the main event, selects format (e.g. 2v2 team bracket) and defines the robot eligibility pool (e.g. robots that didn't make top 16 + round 1 bracket losers — system can suggest these automatically); sub-event can be created as soon as the main bracket round 1 is complete
32. Build 2-robot team creation UI — organizer names teams and assigns exactly 2 robots per team from the eligible pool; system warns if a robot is assigned to multiple teams or is ineligible
33. Auto-generate single-elimination bracket for sub-event teams (same bracket logic as main event, adapted for team matchups)
34. Build unified run-order editor — organizer manages a single ordered list of all upcoming fights (main bracket rounds and sub-event rounds interleaved); drag-and-drop reordering updates the RunOrder table via HTMX + SortableJS
35. Build sub-event fight result entry — all 4 robots fight simultaneously; organizer records which team won each matchup (single result per fight); bracket advances accordingly
36. Create public sub-event bracket view and team rosters page

### Phase 6: Enhanced Public Views
37. Add live tournament display mode — large screen view for venue (auto-refreshing current matchup, leaderboard)
38. Implement HTMX polling for auto-refresh of public views when results are entered
39. Create detailed match history view (teams can see past fight results for their robot)
40. Add robot statistics page (wins/losses, total points, performance vs other robots)
41. Build "next up" board — driven by the unified RunOrder; shows upcoming fights from both main event and sub-events in their interleaved order

### Phase 7: Advanced Features & Polish
42. Implement advanced stats/analytics (win rates, head-to-head matchups, ranking trends)
43. Add tournament history archive (past events browsable via public links)
44. Export functionality (CSV of results, brackets, export back to Google Sheets)
45. Responsive design polish (mobile-friendly FastHTML for public views)
46. Error handling and validation improvements
47. Add bulk operations for organizers (batch result entry, bulk robot import)

### Phase 8: Deployment & Testing
48. Write unit tests for matching algorithm, scoring logic, phase transitions, Google Sheets import, sub-event team assignment
49. Write integration tests for main user flows (import robots, create event, view matchups, enter results, sub-event bracket)
50. Mock Google Sheets API for testing
51. Set up PostgreSQL schema/migrations for production
52. Create Docker setup (optional but recommended)
53. Deploy to cloud if needed (Heroku, AWS, etc.)

## Relevant Files (to be created)
- `app.py` — FastAPI main entry point, FastHTML subapp registration
- `config.py` — Database connection, environment variables, Google API credentials
- `models.py` — SQLAlchemy ORM models (users, roboteers, robots, events, matchups, results)
- `schemas.py` — Pydantic input/output schemas for FastAPI endpoints
- `auth.py` — Google OAuth flow, token storage, session management
- `google_sheets.py` — Google Sheets API client, import/export functions
- `matching.py` — Matching algorithm (random, bracket generation)
- `scoring.py` — Result entry and leaderboard calculation
- `routes/` — FastAPI route handlers
  - `routes/auth.py` — organizer login endpoint
  - `routes/admin.py` — organizer-only routes (event management, imports, result entry, image upload, fight reordering)
  - `routes/public.py` — public routes (event view, robot lookup, leaderboards, brackets)
- `templates/` — FastHTML template files (organized by feature)
  - `base.html` — common layout
  - `public_base.html` — public-facing layout (no auth required)
  - `admin/` — organizer dashboard, event management, import interface, result entry
  - `public/` — public event view, robot lookup, leaderboards, bracket display, live board
- `migrations/` — Alembic migration files (Alembic init)
- `tests/` — Unit and integration tests
- `static/uploads/` — local storage for manually uploaded robot images
- `requirements.txt` — Dependencies (fastapi, fasthtml, sqlalchemy, alembic, google-api-python-client, google-auth-oauthlib, python-multipart, pytest, etc.)

## Verification
1. **Google Sheets import**: Create test Google Form/Sheet, fill with sample robot data, import successfully
2. **Organizer auth flow**: Organizer logs in, accesses admin dashboard
3. **Event creation**: Organizer creates event, provides Google Sheet URL, sees preview of registrations
4. **Selective import**: Organizer selects 20 robots from Google Sheet, imports them into event
5. **Duplicate handling**: Re-import same sheet, verify duplicates are detected and skipped
6. **Phase transitions**: Organizer advances event from setup → registration → qualifying
7. **Matching**: System generates random pairings for round 1, validates all robots have matchups
8. **Scoring**: Organizer enters points for a matchup, public leaderboard updates immediately
9. **Public access**: Roboteer visits public event URL, searches for their robot, sees upcoming fights
10. **Bracket generation**: After qualifying rounds complete, top 16 selected, single-elimination bracket auto-generated
11. **Live display**: Open live tournament board on separate screen, verify auto-refresh works
12. **Reserve swap**: Mark a robot as unable to continue after round 1, swap in reserve, verify reserve appears in subsequent matchups and retired robot's results are preserved
13. **Sub-event team creation**: After main bracket round 1, organizer creates a 2v2 sub-event; system suggests eligible robots (non-top-16 + round 1 bracket losers); organizer assigns robots to teams
14. **Sub-event bracket**: Organizer generates bracket for 16 2-robot teams, enters results, bracket advances correctly

## Decisions
- **FastAPI + FastHTML hybrid**: FastAPI handles API logic, FastHTML subapp serves HTMX views. This allows future API integrations while keeping HTMX tight to backend.
- **Google Forms/Sheets for registration**: Eliminates need for team user accounts, simplifies onboarding, leverages familiar tools.
- **Public links instead of team authentication**: Teams access tournament info via shareable URLs, no login friction.
- **Organizer-only authentication**: Organizers log in via Google OAuth; the same token is reused for Sheets API access. No separate username/password system.
- **SQLite for dev/testing, PostgreSQL for production**: SQLite keeps setup simple locally; production migrations support both.
- **Scoring system**: Fixed scale per fight — 0 (forfeit/no-show), 1 (knocked out), 2 (lost judges decision), 4 (won judges decision), 5 (knocked out opponent). Byes in qualifying rounds award 4 points.
- **Form-based result entry by organizer only**: Organizer is source of truth for scoring. Selects outcome from dropdown rather than entering raw numbers.
- **Instant phase transitions**: No approval workflow for phase changes; organizer controls progression.
- **Bracket seeding**: Random draw, avoiding repeat matchups from qualifying rounds where possible. Organizer can manually adjust bracket pairings before play begins.
- **Top 16 hardcoded for bracket phase**: Can be made configurable later if needed.
- **Odd number of robots**: One robot receives a bye each qualifying round (5 points). Algorithm avoids giving the same robot multiple byes across rounds.
- **2v2 sub-event format**: All 4 robots fight simultaneously in the arena; result is a single team win/loss (no per-robot scoring in 2v2 fights).
- **Weight class is event-level**: Roboteers do not specify weight class when registering; the organizer sets it on the event. Weight class is not a field on the Robot record.
- **Sub-events are optional and organizer-driven**: A sub-event is created manually by the organizer once main bracket round 1 is complete. Sub-event rounds are interleaved with remaining main bracket rounds in a single unified run order — there is no strict "finish main event first" requirement. The system auto-suggests eligible robots but the organizer has full control over team composition. Sub-event format for MVP is 2v2 single-elimination only; other formats can be added later.
- **Unified run order for scheduling**: A `RunOrder` table holds a single ordered list of all pending fights (main and sub-event) for the event. The organizer manages this as one drag-and-drop list. The "next up" board and live display are both driven from this table.
- **Google Sheets API read-only for MVP**: Focus on import; export functionality can be added in Phase 7.
- **Reserves as ordered list**: Reserves are designated at import/roster time with an explicit order; the next available reserve (by order) is suggested when a robot is retired. A robot can be retired at round boundaries only.
- **Robot images**: Images are optional. On import, a "Image URL" column in the sheet is checked; if present the URL is stored (no download for MVP). Manually uploaded images are stored locally under `static/uploads/` and served by FastAPI. Either source overwrites the other if updated.
- **Fight reordering**: SortableJS handles drag-and-drop on the unified run-order list; on drop an HTMX PATCH request updates slot indices in the `RunOrder` table. Only pending fights can be reordered. Main and sub-event fights appear in the same list and can be freely interleaved.

## Further Considerations
1. **Google Sheets column mapping**: Should we enforce a strict schema or allow flexible column mapping? *Recommendation: Start with expected column names ("Roboteer Name", "Robot Name", "Weapon Type"), add flexible mapping in Phase 7.*
2. **Real-time updates**: Should bracket/leaderboard update in real-time as results are entered, or require page refresh? *Recommendation: HTMX polling for public views (auto-refresh every 30s during active tournament).*
3. **Google Sheets permissions**: How should organizers share their Google Sheets? *Recommendation: Require "Anyone with the link can view" permission, document this in setup guide.*
4. **Duplicate robot names**: What if two roboteers have robots with same name? *Recommendation: Store roboteer name + robot name as composite identifier, display as "Robot Name - Roboteer Name" in UI.*
5. **Image storage**: For MVP, sheet-imported images are stored as URLs only (no download). Manually uploaded images go to `static/uploads/`. For production, consider moving uploads to object storage (S3/GCS). *Recommendation: Local for MVP, add object storage in Phase 7.*
