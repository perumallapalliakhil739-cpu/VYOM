import pytest
from backend.services.firms_service import firms_service

def test_higher_frp_strictly_raises_score():
    """Verify that with identical time, repeats, and confidence, higher FRP strictly raises the score."""
    score_low_frp, tier_low, exp_low = firms_service.calculate_observation_priority(
        frp=5.0,
        repeats=2,
        age_hours=3.0,
        confidence_norm="high"
    )
    score_mid_frp, tier_mid, exp_mid = firms_service.calculate_observation_priority(
        frp=45.0,
        repeats=2,
        age_hours=3.0,
        confidence_norm="high"
    )
    score_high_frp, tier_high, exp_high = firms_service.calculate_observation_priority(
        frp=250.0,
        repeats=2,
        age_hours=3.0,
        confidence_norm="high"
    )

    assert score_high_frp > score_mid_frp > score_low_frp
    assert "high FRP" in exp_high
    assert "low FRP" in exp_low

def test_older_detections_strictly_lower_score():
    """Verify that with identical FRP, repeats, and confidence, older observations strictly lower the score."""
    score_fresh, _, exp_fresh = firms_service.calculate_observation_priority(
        frp=50.0,
        repeats=3,
        age_hours=1.0,
        confidence_norm="nominal"
    )
    score_mid_age, _, exp_mid = firms_service.calculate_observation_priority(
        frp=50.0,
        repeats=3,
        age_hours=8.0,
        confidence_norm="nominal"
    )
    score_aged, _, exp_aged = firms_service.calculate_observation_priority(
        frp=50.0,
        repeats=3,
        age_hours=22.0,
        confidence_norm="nominal"
    )

    assert score_fresh > score_mid_age > score_aged
    assert "recent" in exp_fresh
    assert "older pass" in exp_aged

def test_repeat_detections_raise_score():
    """Verify that spatial clustering repeat passes (persistence) strictly raise the observation priority score."""
    score_single, _, exp_single = firms_service.calculate_observation_priority(
        frp=30.0,
        repeats=1,
        age_hours=4.0,
        confidence_norm="nominal"
    )
    score_cluster, _, exp_cluster = firms_service.calculate_observation_priority(
        frp=30.0,
        repeats=5,
        age_hours=4.0,
        confidence_norm="nominal"
    )

    assert score_cluster > score_single
    assert "isolated detection" in exp_single
    assert "5 repeat detections" in exp_cluster

def test_confidence_scaling():
    """Verify high confidence yields a higher score than nominal, which yields higher than low."""
    score_high, _, _ = firms_service.calculate_observation_priority(
        frp=30.0, repeats=2, age_hours=4.0, confidence_norm="high"
    )
    score_nom, _, _ = firms_service.calculate_observation_priority(
        frp=30.0, repeats=2, age_hours=4.0, confidence_norm="nominal"
    )
    score_low, _, _ = firms_service.calculate_observation_priority(
        frp=30.0, repeats=2, age_hours=4.0, confidence_norm="low"
    )

    assert score_high > score_nom > score_low

def test_score_bounds_and_tier_thresholds():
    """Verify scores stay strictly within [0, 100] and match defined tier categories."""
    # Extreme high scenario
    max_score, max_tier, _ = firms_service.calculate_observation_priority(
        frp=1500.0, repeats=10, age_hours=0.1, confidence_norm="high"
    )
    assert max_score <= 100.0
    assert max_tier == "CRITICAL"

    # Extreme low scenario
    min_score, min_tier, _ = firms_service.calculate_observation_priority(
        frp=0.0, repeats=1, age_hours=36.0, confidence_norm="low"
    )
    assert min_score >= 0.0
    assert min_tier == "LOW"

def test_explanation_breakdown_structure():
    """Verify generated explanations contain the 4 drivers: time, FRP, repeat count, and confidence."""
    _, _, explanation = firms_service.calculate_observation_priority(
        frp=85.0,
        repeats=4,
        age_hours=2.5,
        confidence_norm="high",
        confidence_raw="94%"
    )
    assert "Ranked critical because:" in explanation
    assert "recent" in explanation
    assert "high FRP" in explanation
    assert "4 repeat detections" in explanation
    assert "high satellite confidence" in explanation
