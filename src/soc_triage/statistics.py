"""Exploratory paired, family-clustered uncertainty for actual comparisons."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def paired_family_bootstrap(
    baseline: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any]],
    metric: str = "error_cost",
    *,
    resamples: int = 2000,
    seed: int = 1729,
    confidence: float = 0.95,
    expected_alert_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Resample alert families, retaining paired cases and within-family ties.

    A positive difference means candidate minus baseline is higher; whether that
    is better depends on the metric. Missing or unscored pairs are fatal rather
    than silently dropped. This supports DEV exploration, not a frozen test.
    """
    if not 0 < confidence < 1 or resamples < 100:
        raise ValueError("confidence must be in (0,1); use at least 100 resamples")
    def index(records: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
        indexed = {str(record["alert_id"]): record for record in records}
        if len(indexed) != len(records):
            raise ValueError("duplicate alert IDs in paired comparison")
        return indexed
    left, right = index(baseline), index(candidate)
    if expected_alert_ids is not None:
        expected = set(expected_alert_ids)
        if len(expected) != len(expected_alert_ids) or left.keys() != expected or right.keys() != expected:
            raise ValueError("paired comparison is missing cases from the declared evaluation scope")
    if not left or left.keys() != right.keys():
        missing_baseline = sorted(right.keys() - left.keys())
        missing_candidate = sorted(left.keys() - right.keys())
        raise ValueError(f"paired comparison requires every case: missing baseline={missing_baseline}, missing candidate={missing_candidate}")
    families: dict[str, list[float]] = defaultdict(list)
    for alert_id in sorted(left):
        first, second = left[alert_id], right[alert_id]
        family = first.get("family_id")
        if not isinstance(family, str) or not family or second.get("family_id") != family:
            raise ValueError(f"missing or mismatched family_id for {alert_id}")
        values = (first.get(metric), second.get(metric))
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            raise ValueError(f"missing or nonnumeric scored metric {metric} for {alert_id}")
        families[family].append(float(values[1]) - float(values[0]))
    if len(families) < 2:
        raise ValueError("family bootstrap requires at least two independent families")
    family_names = sorted(families)
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        sample = [delta for family in rng.choices(family_names, k=len(family_names)) for delta in families[family]]
        draws.append(sum(sample) / len(sample))
    all_deltas = [delta for family in family_names for delta in families[family]]
    tail = (1 - confidence) / 2
    return {
        "metric": metric,
        "difference_direction": "candidate_minus_baseline",
        "mean_difference": sum(all_deltas) / len(all_deltas),
        "confidence_level": confidence,
        "interval": [_quantile(draws, tail), _quantile(draws, 1 - tail)],
        "case_count": len(all_deltas),
        "family_count": len(families),
        "resamples": resamples,
        "seed": seed,
        "method": "paired percentile bootstrap resampling whole alert families",
        "limitations": "Exploratory DEV uncertainty; few synthetic families, no operational or frozen-test inference.",
    }
