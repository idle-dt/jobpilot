"""Tests for geo synonym expansion and remote-location matching."""

from jobpilot.classifier.features import score_location
from jobpilot.classifier.geo import REMOTE_SYNONYMS, expand_locations


def test_distributed_team_replaces_standalone_distributed():
    """Standalone 'distributed' is too broad and must be replaced by the phrase."""
    assert "distributed" not in REMOTE_SYNONYMS
    assert "distributed team" in REMOTE_SYNONYMS


def test_distributed_team_matches_remote_text():
    """'globally distributed team' is a positive remote signal."""
    locations = expand_locations({"remote": {"weight": 1.0, "target": True}})
    assert "distributed team" in locations
    assert score_location("Join our globally distributed team", locations) == 1.0


def test_distributed_systems_is_not_a_remote_signal():
    """'distributed systems' must NOT match any remote synonym."""
    locations = expand_locations({"remote": {"weight": 1.0, "target": True}})
    assert score_location("Experience with distributed systems architecture", locations) == 0.0


def test_hybrid_does_not_inherit_the_remote_weight():
    """Terms that do not reliably mean fully remote must not expand from 'remote'."""
    assert "hybrid" not in REMOTE_SYNONYMS
    assert "home office" not in REMOTE_SYNONYMS

    locations = expand_locations({"remote": {"weight": 1.0, "target": True}})

    assert "hybrid" not in locations
    assert "home office" not in locations


def test_work_from_home_does_not_inherit_the_remote_weight():
    """'Work from home' is a perk an office role can offer, not a remote policy."""
    assert "work from home" not in REMOTE_SYNONYMS
    assert "wfh" not in REMOTE_SYNONYMS

    locations = expand_locations({"remote": {"weight": 1.0, "target": True}})

    assert "work from home" not in locations
    assert "wfh" not in locations


def test_work_from_home_perk_scores_zero_under_a_remote_only_policy():
    """A real on-site listing whose perks mention working from home (job 4856)."""
    locations = expand_locations({"remote": {"weight": 1.0, "target": True}})
    perks = (
        "we offer a safe & healthy workplace, with flexible working hours "
        "and the possibility to work from home"
    )

    assert score_location(perks, locations) == 0.0


def test_a_genuine_remote_statement_still_scores_full_weight():
    """Dropping the perk phrasing must not cost an actually-remote listing."""
    locations = expand_locations({"remote": {"weight": 1.0, "target": True}})

    assert score_location("This is a fully remote position", locations) == 1.0
    assert score_location("Work from anywhere in the EU", locations) == 1.0


def test_hybrid_listing_scores_zero_under_a_remote_only_policy():
    """'Hybrid — 3 days in Amsterdam' no longer scores as a remote match."""
    locations = expand_locations({"remote": {"weight": 1.0, "target": True}})

    assert score_location("Hybrid — 3 days in Amsterdam", locations) == 0.0
