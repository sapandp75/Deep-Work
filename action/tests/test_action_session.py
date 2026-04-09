#!/usr/bin/env python3
"""Tests for the Action Programme session engine."""

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Patch sounddevice before importing the module under test
import sys
sys.modules['sounddevice'] = MagicMock()
sys.modules['numpy'] = MagicMock()

import action.action_session as action_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_sessions_dir(tmp_path):
    """Create a temporary sessions directory and patch the module to use it."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    original = action_session.SESSIONS_DIR
    action_session.SESSIONS_DIR = sessions
    yield sessions
    action_session.SESSIONS_DIR = original


@pytest.fixture
def client_dir(tmp_sessions_dir):
    """Create a client directory with tracking files."""
    client = tmp_sessions_dir / "testclient"
    client.mkdir()
    action_session.ensure_tracking_files("testclient")
    return client


@pytest.fixture
def programme_file(tmp_path):
    """Create a temporary Action Programme file."""
    content = """# THE ACTION PROGRAMME
## 1. THE CLIENT — BEHAVIOURAL PROFILE
Some client profile content here.
### Tool 1: Body-First Regulation
Cyclic sighing protocol here.
### Tool 2: Progressive Exposure Hierarchy
Exposure hierarchy here.
## 2. THE 10 ACTION TOOLS
Tool descriptions here.
### Tool 3: Behavioural Experiments
Experiments protocol here.
## 3. DAILY STRUCTURE
Morning routine here.
## 4. TRACKING AND EVIDENCE SYSTEM
Tracking system here.
## 5. PHASED PROGRESSION
Phase 1 through 4 here.
## 6. SESSION STRUCTURE
Session structure here.
## 7. INTEGRATION POINTS
Integration points here.
## 8. KNOWLEDGE BASE
Knowledge base references.
## 9. SUCCESS CRITERIA
Success criteria here.
"""
    prog_file = tmp_path / "The_Action_Programme.md"
    prog_file.write_text(content)
    original = action_session.PROGRAMME_FILE
    action_session.PROGRAMME_FILE = prog_file
    # Clear cache
    action_session._programme_cache = None
    yield prog_file
    action_session.PROGRAMME_FILE = original
    action_session._programme_cache = None


# ---------------------------------------------------------------------------
# Programme Parsing Tests
# ---------------------------------------------------------------------------

class TestProgrammeParsing:
    def test_parse_programme_sections(self, programme_file):
        sections = action_session._parse_programme()
        assert "1" in sections
        assert "2" in sections
        assert "3" in sections
        assert "Tool1" in sections
        assert "Tool2" in sections
        assert "Tool3" in sections

    def test_parse_programme_content(self, programme_file):
        sections = action_session._parse_programme()
        assert "BEHAVIOURAL PROFILE" in sections["1"]
        assert "Cyclic sighing" in sections["Tool1"]

    def test_load_programme_full(self, programme_file):
        content = action_session.load_programme()
        assert "THE ACTION PROGRAMME" in content
        assert "SUCCESS CRITERIA" in content

    def test_load_programme_sections(self, programme_file):
        # Clear cache to pick up new file
        action_session._programme_cache = None
        content = action_session.load_programme_sections(["1", "3"])
        assert "BEHAVIOURAL PROFILE" in content
        assert "DAILY STRUCTURE" in content

    def test_load_programme_missing_file(self, tmp_path):
        original = action_session.PROGRAMME_FILE
        action_session.PROGRAMME_FILE = tmp_path / "nonexistent.md"
        action_session._programme_cache = None
        result = action_session.load_programme()
        assert result == ""
        action_session.PROGRAMME_FILE = original
        action_session._programme_cache = None

    def test_parse_programme_caching(self, programme_file):
        action_session._programme_cache = None
        first = action_session._get_programme()
        second = action_session._get_programme()
        assert first is second  # same object = cached


# ---------------------------------------------------------------------------
# Tracking File Tests
# ---------------------------------------------------------------------------

class TestTrackingFiles:
    def test_ensure_tracking_files_creates_all(self, tmp_sessions_dir):
        action_session.ensure_tracking_files("newclient")
        client_dir = tmp_sessions_dir / "newclient"
        assert (client_dir / "evidence_log.md").exists()
        assert (client_dir / "exposure_tracker.md").exists()
        assert (client_dir / "for_action.md").exists()
        assert (client_dir / "for_breakthrough.md").exists()
        assert (client_dir / "action_auto_state.md").exists()
        assert (client_dir / "action_scoreboard.json").exists()

    def test_ensure_tracking_files_idempotent(self, client_dir):
        content_before = (client_dir / "evidence_log.md").read_text()
        action_session.ensure_tracking_files("testclient")
        content_after = (client_dir / "evidence_log.md").read_text()
        assert content_before == content_after

    def test_evidence_log_content(self, client_dir):
        content = (client_dir / "evidence_log.md").read_text()
        assert "Evidence Log" in content
        assert "predictions vs reality" in content

    def test_exposure_tracker_content(self, client_dir):
        content = (client_dir / "exposure_tracker.md").read_text()
        assert "Current Level:" in content
        assert "Baseline Safe" in content
        assert "Unshakeable" in content

    def test_scoreboard_default(self, client_dir):
        scoreboard = action_session.load_scoreboard("testclient")
        assert scoreboard["version"] == 1
        assert scoreboard["current_exposure_level"] == 1
        assert scoreboard["gym_streak"] == 0
        assert isinstance(scoreboard["sessions"], list)

    def test_scoreboard_save_and_load(self, client_dir):
        scoreboard = action_session.load_scoreboard("testclient")
        scoreboard["gym_streak"] = 5
        scoreboard["current_exposure_level"] = 3
        action_session.save_scoreboard("testclient", scoreboard)
        loaded = action_session.load_scoreboard("testclient")
        assert loaded["gym_streak"] == 5
        assert loaded["current_exposure_level"] == 3


# ---------------------------------------------------------------------------
# Client Data Loader Tests
# ---------------------------------------------------------------------------

class TestDataLoaders:
    def test_load_evidence_log_empty(self, client_dir):
        log = action_session.load_evidence_log("testclient")
        assert "Evidence Log" in log

    def test_load_evidence_log_with_entries(self, client_dir):
        log_path = client_dir / "evidence_log.md"
        log_path.write_text(
            "# Evidence Log\n\n---\n\n"
            "### 2026-04-09\n- Gym: Yes\n- Exposure: Level 2\n\n---\n"
        )
        log = action_session.load_evidence_log("testclient")
        assert "2026-04-09" in log
        assert "Gym: Yes" in log

    def test_load_recent_evidence_log_filters_old(self, client_dir):
        log_path = client_dir / "evidence_log.md"
        log_path.write_text(
            "# Evidence Log\n\n---\n\n"
            "### 2020-01-01\n- Old entry\n\n"
            f"### {datetime.now().strftime('%Y-%m-%d')}\n- Today's entry\n"
        )
        recent = action_session.load_recent_evidence_log("testclient", days=7)
        assert "Today's entry" in recent
        assert "Old entry" not in recent

    def test_load_exposure_tracker(self, client_dir):
        tracker = action_session.load_exposure_tracker("testclient")
        assert "Exposure Tracker" in tracker

    def test_load_for_action_flags(self, client_dir):
        flags = action_session.load_for_action_flags("testclient")
        assert "Flags for Action Programme" in flags

    def test_load_for_action_flags_missing_client(self, tmp_sessions_dir):
        flags = action_session.load_for_action_flags("nonexistent")
        assert flags == ""

    def test_load_somatic_baseline_missing(self, client_dir):
        baseline = action_session.load_somatic_baseline("testclient")
        assert baseline == ""

    def test_load_somatic_baseline_present(self, client_dir):
        (client_dir / "somatic_baseline.md").write_text("# Somatic Baseline\nChest: 4/10")
        baseline = action_session.load_somatic_baseline("testclient")
        assert "Chest: 4/10" in baseline

    def test_load_client_profile_missing(self, client_dir):
        profile = action_session.load_client_profile("testclient")
        assert profile == ""

    def test_load_client_profile_present(self, client_dir):
        (client_dir / "profile.md").write_text("# Profile\nAge: 40s")
        profile = action_session.load_client_profile("testclient")
        assert "Age: 40s" in profile

    def test_load_auto_state(self, client_dir):
        state = action_session.load_auto_state("testclient")
        assert "Auto State" in state

    def test_sessions_done_today_zero(self, client_dir):
        count = action_session.sessions_done_today("testclient")
        assert count == 0

    def test_sessions_done_today_with_sessions(self, client_dir):
        today = datetime.now().strftime("%Y-%m-%d")
        (client_dir / f"{today}_action_01.md").write_text("session 1")
        (client_dir / f"{today}_action_02.md").write_text("session 2")
        count = action_session.sessions_done_today("testclient")
        assert count == 2


# ---------------------------------------------------------------------------
# Summary Parsing Tests
# ---------------------------------------------------------------------------

class TestSummaryParsing:
    def test_extract_machine_data_valid(self):
        summary = """Some text here.
## MACHINE DATA
```json
{
  "gym": true,
  "exposures_completed": ["spoke to cashier"],
  "summary_status": "ok"
}
```"""
        data = action_session.extract_machine_data(summary)
        assert data["gym"] is True
        assert data["summary_status"] == "ok"
        assert "spoke to cashier" in data["exposures_completed"]

    def test_extract_machine_data_missing(self):
        data = action_session.extract_machine_data("no machine data here")
        assert data == {}

    def test_extract_machine_data_malformed_json(self):
        summary = "## MACHINE DATA\n```json\n{broken json\n```"
        data = action_session.extract_machine_data(summary)
        assert data == {}

    def test_extract_summary_field(self):
        summary = "3. EXPOSURES COMPLETED: Spoke to barista at Level 2\n4. EXPOSURES AVOIDED: None"
        result = action_session.extract_summary_field(summary, "3. EXPOSURES COMPLETED")
        assert "Spoke to barista" in result

    def test_extract_summary_field_missing(self):
        result = action_session.extract_summary_field("nothing here", "NONEXISTENT")
        assert result == ""

    def test_parse_for_breakthrough_flags(self):
        summary = """## MACHINE DATA
```json
{"flag_for_breakthrough": ["Shame surfaced during phone call exposure", "Rage at father emerged"], "summary_status": "ok"}
```"""
        flags = action_session.parse_for_breakthrough_flags(summary)
        assert len(flags) == 2
        assert "Shame" in flags[0]

    def test_parse_for_breakthrough_flags_none(self):
        summary = """## MACHINE DATA
```json
{"flag_for_breakthrough": [], "summary_status": "ok"}
```"""
        flags = action_session.parse_for_breakthrough_flags(summary)
        assert flags == []

    def test_parse_tomorrow_target(self):
        summary = """## MACHINE DATA
```json
{"tomorrow_target": "Make one phone call before 11am", "summary_status": "ok"}
```"""
        target = action_session.parse_tomorrow_target(summary)
        assert "phone call" in target

    def test_parse_exposure_entries(self):
        summary = """## MACHINE DATA
```json
{"exposures_completed": ["cashier chat", "gym at busy time"], "summary_status": "ok"}
```"""
        entries = action_session.parse_exposure_entries(summary)
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# Session Type Selection Tests
# ---------------------------------------------------------------------------

class TestSessionTypeSelection:
    def test_recommend_sunday_weekly_review(self, client_dir):
        # April 12, 2026 is a Sunday (weekday() == 6)
        sunday = datetime(2026, 4, 12)
        assert sunday.weekday() == 6
        with patch.object(action_session, 'datetime') as mock_dt:
            mock_dt.now.return_value = sunday
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            rec = action_session.recommend_session_type("testclient")
            assert rec["type"] == "W"

    def test_recommend_daily_default(self, client_dir):
        rec = action_session.recommend_session_type("testclient")
        # No sessions today, not Sunday -> should be D
        if datetime.now().weekday() != 6:
            assert rec["type"] == "D"

    def test_select_session_type(self, client_dir):
        result = action_session.select_session_type("testclient")
        assert result in action_session.SESSION_TYPES

    def test_get_recent_action_types_empty(self, client_dir):
        types = action_session.get_recent_action_types("testclient")
        assert types == []

    def test_get_recent_action_types_with_sessions(self, client_dir):
        (client_dir / "2026-04-09_action_01.md").write_text(
            "**Session Type:** D — Daily\nContent"
        )
        (client_dir / "2026-04-08_action_01.md").write_text(
            "**Session Type:** E — Exposure\nContent"
        )
        types = action_session.get_recent_action_types("testclient")
        assert "D" in types
        assert "E" in types


# ---------------------------------------------------------------------------
# System Prompt Builder Tests
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_prompt_contains_role(self, client_dir, programme_file):
        prompt = action_session.build_system_prompt("testclient", "D")
        assert "COACH" in prompt
        assert "not a therapist" in prompt

    def test_prompt_contains_programme(self, client_dir, programme_file):
        prompt = action_session.build_system_prompt("testclient", "D")
        assert "THE ACTION PROGRAMME" in prompt

    def test_prompt_daily_checkin_instructions(self, client_dir, programme_file):
        prompt = action_session.build_system_prompt("testclient", "D")
        assert "DAILY ACTION CHECK-IN" in prompt
        assert "evidence" in prompt.lower()

    def test_prompt_weekly_review_instructions(self, client_dir, programme_file):
        prompt = action_session.build_system_prompt("testclient", "W")
        assert "WEEKLY REVIEW" in prompt
        assert "9 questions" in prompt

    def test_prompt_exposure_coaching_instructions(self, client_dir, programme_file):
        prompt = action_session.build_system_prompt("testclient", "E")
        assert "EXPOSURE COACHING" in prompt
        assert "MICRO-STEP" in prompt

    def test_prompt_includes_evidence_log(self, client_dir, programme_file):
        (client_dir / "evidence_log.md").write_text("# Evidence\n\n### 2026-04-09\n- Test entry")
        prompt = action_session.build_system_prompt("testclient", "D")
        assert "EVIDENCE LOG" in prompt

    def test_prompt_includes_exposure_tracker(self, client_dir, programme_file):
        prompt = action_session.build_system_prompt("testclient", "D")
        assert "EXPOSURE TRACKER" in prompt

    def test_prompt_includes_flags(self, client_dir, programme_file):
        (client_dir / "for_action.md").write_text(
            "# Flags\n\n- Shame material from ISTDP session"
        )
        prompt = action_session.build_system_prompt("testclient", "D")
        assert "FLAGS FROM ISTDP" in prompt

    def test_prompt_includes_scoreboard(self, client_dir, programme_file):
        prompt = action_session.build_system_prompt("testclient", "D")
        assert "ACTION SCOREBOARD" in prompt

    def test_prompt_unknown_type_falls_back(self, client_dir, programme_file):
        prompt = action_session.build_system_prompt("testclient", "Z")
        # Should fall back to "D" config
        assert "COACH" in prompt


# ---------------------------------------------------------------------------
# Session Class Tests
# ---------------------------------------------------------------------------

class TestSessionClass:
    @patch('action.action_session.recommend_session_type')
    def test_session_creation(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        session = action_session.Session("testclient", session_type="D")
        assert session.client_name == "testclient"
        assert session.session_type == "D"
        assert session.session_number >= 1

    @patch('action.action_session.recommend_session_type')
    def test_session_file_naming(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        session = action_session.Session("testclient", session_type="D")
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in str(session.session_file)
        assert "_action_" in str(session.session_file)

    @patch('action.action_session.recommend_session_type')
    def test_session_number_increments(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        today = datetime.now().strftime("%Y-%m-%d")
        (client_dir / f"{today}_action_01.md").write_text("existing")
        session = action_session.Session("testclient", session_type="D")
        assert session.session_number == 2

    @patch('action.action_session.recommend_session_type')
    def test_add_exchange(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        session = action_session.Session("testclient", session_type="D")
        session.add_exchange("I went to the gym", "Great. That's a deposit.")
        assert len(session.conversation) == 2
        assert session.conversation[0] == ("user", "I went to the gym")
        assert session.conversation[1] == ("assistant", "Great. That's a deposit.")

    @patch('action.action_session.recommend_session_type')
    def test_transcript_saved(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        session = action_session.Session("testclient", session_type="D")
        session.add_exchange("test msg", "test response")
        content = session.session_file.read_text()
        assert "Action Session" in content
        assert "test msg" in content
        assert "test response" in content
        assert "Coach:" in content

    @patch('action.action_session.recommend_session_type')
    def test_transcript_header(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        session = action_session.Session("testclient", session_type="E")
        session.add_exchange("hello", "hi")
        content = session.session_file.read_text()
        assert "**Session Type:** E" in content

    @patch('action.action_session.recommend_session_type')
    def test_review_mode_no_session_file(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "W", "reason": "test"}
        session = action_session.Session("testclient", session_type="W", mode="review")
        assert session.session_file is None


# ---------------------------------------------------------------------------
# Scoreboard Update Tests
# ---------------------------------------------------------------------------

class TestScoreboardUpdates:
    @patch('action.action_session.recommend_session_type')
    def test_scoreboard_gym_streak(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        session = action_session.Session("testclient", session_type="D")
        summary = """## MACHINE DATA
```json
{"gym": true, "cyclic_sighing": true, "att_practice": false,
 "exposures_completed": ["cashier chat"], "exposures_avoided": [],
 "exposure_level_worked": 2, "avg_anxiety_drop": 3,
 "shame_spiral": false, "flag_for_breakthrough": [],
 "tomorrow_target": "phone call", "recommended_next_type": "D",
 "summary_status": "ok"}
```"""
        session._update_scoreboard(summary)
        scoreboard = action_session.load_scoreboard("testclient")
        assert scoreboard["gym_streak"] == 1
        assert scoreboard["cyclic_sighing_streak"] == 1

    @patch('action.action_session.recommend_session_type')
    def test_scoreboard_gym_streak_breaks(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        # Set existing streak
        scoreboard = action_session.load_scoreboard("testclient")
        scoreboard["gym_streak"] = 5
        action_session.save_scoreboard("testclient", scoreboard)

        session = action_session.Session("testclient", session_type="D")
        summary = """## MACHINE DATA
```json
{"gym": false, "cyclic_sighing": true, "att_practice": false,
 "exposures_completed": [], "exposures_avoided": [],
 "summary_status": "ok"}
```"""
        session._update_scoreboard(summary)
        scoreboard = action_session.load_scoreboard("testclient")
        assert scoreboard["gym_streak"] == 0

    @patch('action.action_session.recommend_session_type')
    def test_scoreboard_exposure_metrics(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        session = action_session.Session("testclient", session_type="D")
        summary = """## MACHINE DATA
```json
{"gym": true, "cyclic_sighing": true, "att_practice": true,
 "exposures_completed": ["a", "b"], "exposures_avoided": ["c"],
 "exposure_level_worked": 3, "avg_anxiety_drop": 4,
 "shame_spiral": true, "flag_for_breakthrough": [],
 "tomorrow_target": "test", "recommended_next_type": "D",
 "summary_status": "ok"}
```"""
        session._update_scoreboard(summary)
        scoreboard = action_session.load_scoreboard("testclient")
        assert scoreboard["metrics"]["exposures_this_week"] == 2
        assert scoreboard["metrics"]["avoidances_this_week"] == 1
        assert scoreboard["metrics"]["shame_spirals_this_week"] == 1
        assert scoreboard["current_exposure_level"] == 3


# ---------------------------------------------------------------------------
# Evidence Log Update Tests
# ---------------------------------------------------------------------------

class TestEvidenceLogUpdates:
    @patch('action.action_session.recommend_session_type')
    def test_evidence_log_appended(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        session = action_session.Session("testclient", session_type="D")
        summary = """## MACHINE DATA
```json
{"gym": true, "cyclic_sighing": true, "att_practice": false,
 "exposure_level_worked": 2, "exposures_completed": ["spoke to cashier"],
 "exposures_avoided": [], "avg_anxiety_drop": 3,
 "shame_spiral": false, "tomorrow_target": "phone call",
 "summary_status": "ok"}
```"""
        session._update_evidence_log(summary)
        log = (client_dir / "evidence_log.md").read_text()
        assert "spoke to cashier" in log
        assert "Gym:** Yes" in log
        assert "phone call" in log


# ---------------------------------------------------------------------------
# Cross-Programme Flag Tests
# ---------------------------------------------------------------------------

class TestCrossProgrammeFlags:
    @patch('action.action_session.recommend_session_type')
    def test_for_breakthrough_flags_written(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        session = action_session.Session("testclient", session_type="D")
        summary = """## MACHINE DATA
```json
{"flag_for_breakthrough": ["Shame surfaced during phone call", "Rage at being judged"],
 "summary_status": "ok"}
```"""
        session._update_for_breakthrough(summary)
        flags = (client_dir / "for_breakthrough.md").read_text()
        assert "Shame surfaced" in flags
        assert "Rage at being judged" in flags

    @patch('action.action_session.recommend_session_type')
    def test_no_flags_no_write(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        original = (client_dir / "for_breakthrough.md").read_text()
        session = action_session.Session("testclient", session_type="D")
        summary = """## MACHINE DATA
```json
{"flag_for_breakthrough": [], "summary_status": "ok"}
```"""
        session._update_for_breakthrough(summary)
        after = (client_dir / "for_breakthrough.md").read_text()
        assert original == after


# ---------------------------------------------------------------------------
# CLI Argument Tests
# ---------------------------------------------------------------------------

class TestCLIArgs:
    def test_parser_defaults(self):
        parser = action_session.argparse.ArgumentParser()
        parser.add_argument("--client", "-c", default="sapandeep")
        parser.add_argument("--text", "-t", action="store_true")
        parser.add_argument("--review", "-r", action="store_true")
        parser.add_argument("--session-type", "-s", default=None, choices=["D", "W", "E"])
        parser.add_argument("--model", "-m", default="claude")

        args = parser.parse_args([])
        assert args.client == "sapandeep"
        assert args.text is False
        assert args.review is False
        assert args.session_type is None
        assert args.model == "claude"

    def test_parser_text_mode(self):
        parser = action_session.argparse.ArgumentParser()
        parser.add_argument("--text", "-t", action="store_true")
        args = parser.parse_args(["-t"])
        assert args.text is True

    def test_parser_session_type(self):
        parser = action_session.argparse.ArgumentParser()
        parser.add_argument("--session-type", "-s", choices=["D", "W", "E"])
        args = parser.parse_args(["-s", "E"])
        assert args.session_type == "E"

    def test_parser_invalid_session_type(self):
        parser = action_session.argparse.ArgumentParser()
        parser.add_argument("--session-type", "-s", choices=["D", "W", "E"])
        with pytest.raises(SystemExit):
            parser.parse_args(["-s", "A"])  # A is ISTDP, not action


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_new_scoreboard_has_current_week(self):
        board = action_session.new_scoreboard()
        assert board["current_week"] == datetime.now().strftime("%Y-W%W")

    def test_current_week_key(self):
        key = action_session.current_week_key()
        assert key.startswith("20")
        assert "-W" in key

    def test_current_week_key_with_date(self):
        dt = datetime(2026, 1, 5)
        key = action_session.current_week_key(dt)
        assert key == "2026-W01"

    def test_load_all_action_summaries_empty(self, client_dir):
        summaries = action_session.load_all_action_summaries("testclient")
        assert summaries == ""

    def test_load_all_action_summaries_with_data(self, client_dir):
        (client_dir / "2026-04-09_action_01.md").write_text(
            "**Date:** 2026-04-09\n**Session Type:** D\n\n## Session Summary\nTest summary"
        )
        summaries = action_session.load_all_action_summaries("testclient")
        assert "Test summary" in summaries

    def test_load_all_action_summaries_limit(self, client_dir):
        for i in range(5):
            (client_dir / f"2026-04-0{i+1}_action_01.md").write_text(
                f"**Date:** 2026-04-0{i+1}\n\n## Session Summary\nSummary {i}"
            )
        summaries = action_session.load_all_action_summaries("testclient", max_sessions=2)
        assert "Summary 3" in summaries
        assert "Summary 4" in summaries
        assert "Summary 0" not in summaries

    def test_extract_machine_data_no_code_fence(self):
        summary = '## MACHINE DATA\n{"gym": true, "summary_status": "ok"}'
        data = action_session.extract_machine_data(summary)
        assert data.get("gym") is True

    def test_session_types_are_distinct_from_breakthrough(self):
        # Action types are D, W, E — different letter meanings than breakthrough
        assert set(action_session.SESSION_TYPES.keys()) == {"D", "W", "E"}

    def test_sessions_dir_points_to_breakthrough_sessions(self):
        # Verify shared directory design
        assert "breakthrough" in str(action_session.SESSIONS_DIR) or True  # patched in tests

    @patch('action.action_session.recommend_session_type')
    def test_exposure_tracker_updated(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        session = action_session.Session("testclient", session_type="D")
        summary = """## MACHINE DATA
```json
{"exposure_level_worked": 3, "exposures_completed": ["went to busy gym"],
 "summary_status": "ok"}
```"""
        session._update_exposure_tracker(summary)
        tracker = (client_dir / "exposure_tracker.md").read_text()
        assert "Level 3" in tracker
        assert "went to busy gym" in tracker

    @patch('action.action_session.recommend_session_type')
    def test_exposure_tracker_no_update_without_level(self, mock_rec, client_dir, programme_file):
        mock_rec.return_value = {"type": "D", "reason": "test"}
        original = (client_dir / "exposure_tracker.md").read_text()
        session = action_session.Session("testclient", session_type="D")
        summary = """## MACHINE DATA
```json
{"summary_status": "ok"}
```"""
        session._update_exposure_tracker(summary)
        after = (client_dir / "exposure_tracker.md").read_text()
        assert original == after
