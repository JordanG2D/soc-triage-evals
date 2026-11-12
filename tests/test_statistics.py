import pytest

from soc_triage.statistics import paired_family_bootstrap


def cases(values):
    return [{"alert_id": f"TEST{i}", "family_id": f"family{i // 2}", "error_cost": value} for i, value in enumerate(values)]


def test_clustered_paired_draws_have_known_direction_and_reproduce():
    baseline = cases([5, 5, 5, 5])
    candidate = cases([2, 2, 4, 4])
    actual = paired_family_bootstrap(baseline, candidate, seed=11, resamples=200)
    assert actual == paired_family_bootstrap(baseline, candidate, seed=11, resamples=200)
    assert actual["mean_difference"] == -2
    assert actual["interval"] == [-3, -1]
    assert actual["family_count"] == 2
    assert actual["case_count"] == 4
    same = paired_family_bootstrap(baseline, baseline, resamples=100)
    assert same["interval"] == [0, 0]


def test_missing_pairs_unscored_cases_and_family_drift_are_fatal():
    baseline = cases([1, 2, 3, 4])
    with pytest.raises(ValueError, match="missing candidate"):
        paired_family_bootstrap(baseline, baseline[:-1])
    with pytest.raises(ValueError, match="declared evaluation scope"):
        paired_family_bootstrap(baseline[:-1], baseline[:-1], expected_alert_ids=[record["alert_id"] for record in baseline])
    candidate = cases([1, 2, 3, 4])
    candidate[0]["error_cost"] = None
    with pytest.raises(ValueError, match="nonnumeric"):
        paired_family_bootstrap(baseline, candidate)
    candidate = cases([1, 2, 3, 4])
    candidate[0]["family_id"] = "different"
    with pytest.raises(ValueError, match="family_id"):
        paired_family_bootstrap(baseline, candidate)


def test_binary_accuracy_is_a_valid_paired_metric():
    baseline = cases([True, True, False, False])
    candidate = cases([True, True, True, True])
    assert paired_family_bootstrap(baseline, candidate, resamples=100)["mean_difference"] == 0.5


def test_duplicates_one_family_and_nonfinite_values_are_refused():
    baseline = cases([1, 2, 3, 4])
    with pytest.raises(ValueError, match="duplicate"):
        paired_family_bootstrap(baseline + [baseline[0]], baseline)
    with pytest.raises(ValueError, match="two independent families"):
        paired_family_bootstrap(baseline[:2], baseline[:2])
    candidate = cases([1, 2, 3, float("nan")])
    with pytest.raises(ValueError, match="nonnumeric"):
        paired_family_bootstrap(baseline, candidate)
