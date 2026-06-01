"""Tests for negation-aware signal matching."""

from jobpilot.classifier.features import (
    extract_matched_keywords,
    find_negated_keywords,
    score_negatives,
)
from jobpilot.classifier.rules import SignalConfig, compute_features


# --- find_negated_keywords ---

def test_find_negated_keywords_suppresses_matching_keyword():
    result = find_negated_keywords(
        "no flutter experience needed",
        ["no flutter experience needed"],
        ["flutter", "react"],
    )
    assert result == {"flutter"}


def test_find_negated_keywords_no_match_in_text():
    result = find_negated_keywords(
        "remote work available",
        ["remote is not available"],
        ["remote"],
    )
    assert result == set()


def test_find_negated_keywords_case_insensitive():
    result = find_negated_keywords(
        "Remote Is Not Available for this role",
        ["remote is not available"],
        ["Remote"],
    )
    assert result == {"remote"}


def test_find_negated_keywords_multiple_phrases():
    result = find_negated_keywords(
        "remote is not available. no flutter experience needed.",
        ["remote is not available", "no flutter experience needed"],
        ["remote", "flutter", "react"],
    )
    assert result == {"remote", "flutter"}


def test_find_negated_keywords_no_false_substring_suppression():
    """Keywords that are substrings of words in a phrase must not be suppressed."""
    result = find_negated_keywords(
        "no startup experience needed",
        ["no startup experience needed"],
        ["art", "start", "react"],
    )
    assert result == set()


def test_find_negated_keywords_empty_phrases():
    result = find_negated_keywords("some text", [], ["keyword"])
    assert result == set()


# --- score_negatives with negation_phrases ---

def test_score_negatives_with_negation_phrase_match():
    score = score_negatives(
        "Remote is not available",
        negatives=[],
        negation_phrases=["remote is not available"],
    )
    assert score == 0.4


def test_score_negatives_with_both_negative_and_negation():
    score = score_negatives(
        "Remote is not available. No visa sponsorship.",
        negatives=["no visa sponsorship"],
        negation_phrases=["remote is not available"],
    )
    assert score == 0.1  # 2 negatives total


def test_score_negatives_negation_phrase_not_in_text():
    score = score_negatives(
        "We offer remote work",
        negatives=[],
        negation_phrases=["remote is not available"],
    )
    assert score == 1.0


def test_score_negatives_no_negation_phrases():
    score = score_negatives("Some job text", negatives=[], negation_phrases=None)
    assert score == 1.0


# --- compute_features with suppression ---

def test_compute_features_suppresses_location():
    cfg = SignalConfig(
        locations={"remote": {"weight": 0.9, "target": False}},
        negation_phrases=["remote is not available"],
    )
    features = compute_features("Job", "Remote is not available", cfg)
    location_score = features[2]
    negative_score = features[5]
    assert location_score == 0.0  # remote suppressed
    assert negative_score == 0.4  # one negation phrase matched


def test_compute_features_no_suppression_when_phrase_absent():
    cfg = SignalConfig(
        locations={"remote": {"weight": 0.9, "target": False}},
        negation_phrases=["remote is not available"],
    )
    features = compute_features("Job", "We offer remote work", cfg)
    location_score = features[2]
    assert location_score == 0.9  # phrase not in text, no suppression


def test_compute_features_empty_negation_phrases():
    cfg = SignalConfig(
        locations={"remote": {"weight": 0.9, "target": False}},
        negation_phrases=None,
    )
    features_none = compute_features("Job", "We offer remote work", cfg)

    cfg2 = SignalConfig(
        locations={"remote": {"weight": 0.9, "target": False}},
    )
    features_default = compute_features("Job", "We offer remote work", cfg2)

    assert features_none == features_default  # no regression


def test_compute_features_suppresses_tech_keyword():
    cfg = SignalConfig(
        tech_keywords={"flutter": {"weight": 1.0, "category": "primary"}},
        negation_phrases=["no flutter experience needed"],
    )
    features = compute_features("Job", "No flutter experience needed", cfg)
    tech_score = features[0]
    assert tech_score == 0.0


# --- extract_matched_keywords ---

def test_extract_negation_phrase_in_negative_list():
    cfg = SignalConfig(
        locations={"remote": {"weight": 0.9, "target": False}},
        negation_phrases=["remote is not available"],
    )
    result = extract_matched_keywords(
        "Remote is not available", cfg,
    )
    assert "remote is not available" in result["negative"]
    assert "remote" not in result["positive"]


def test_extract_no_negation_match_unchanged():
    cfg = SignalConfig(
        locations={"remote": {"weight": 0.9, "target": False}},
        negation_phrases=["remote is not available"],
    )
    result = extract_matched_keywords(
        "We offer remote work", cfg,
    )
    assert "remote" in result["positive"]
    assert "remote is not available" not in result["negative"]


def test_extract_multiple_positives_partial_suppression():
    cfg = SignalConfig(
        tech_keywords={
            "flutter": {"weight": 1.0, "category": "primary"},
            "react": {"weight": 1.0, "category": "primary"},
        },
        negation_phrases=["no flutter experience needed"],
    )
    result = extract_matched_keywords(
        "React developer. No flutter experience needed.", cfg,
    )
    assert "react" in result["positive"]
    assert "flutter" not in result["positive"]
    assert "no flutter experience needed" in result["negative"]
