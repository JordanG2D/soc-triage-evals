from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from soc_triage.budget import BudgetExceeded, BudgetLedger, MODELS, validate_journal


def test_concurrent_reservations_cannot_overdraw(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.db", "0.09")
    def attempt(_):
        try:
            ledger.reserve(MODELS[0], 10_000, 1000, "test")
            return True
        except BudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(16))) == 1
    assert ledger.snapshot()["charged_upper_microdollars"] == 50_000


def test_crash_and_ambiguous_call_preserve_charge(tmp_path):
    path = tmp_path / "budget.db"
    ledger = BudgetLedger(path, "0.06")
    reservation = ledger.reserve(MODELS[0], 10_000, 1000, "test")
    del ledger
    resumed = BudgetLedger(path, "0.06")
    with pytest.raises(BudgetExceeded):
        resumed.reserve(MODELS[0], 10_000, 1000, "again")
    resumed.mark_uncertain(reservation.id)
    assert resumed.snapshot()["charged_upper_microdollars"] == 50_000
    with pytest.raises(ValueError):
        resumed.settle(reservation.id, 0, 0)
    with pytest.raises(ValueError):
        resumed.mark_uncertain(reservation.id)
    assert BudgetLedger(path, "0.06").snapshot()["states"] == {
        "uncertain": {"count": 1, "charge_microdollars": 50_000}
    }


def test_settlement_counts_all_cache_categories(tmp_path):
    ledger = BudgetLedger(tmp_path / "b.db")
    reservation = ledger.reserve(MODELS[1], 100, 10, "test")
    ledger.settle(reservation.id, 10, 5, cache_read_tokens=20, cache_write_tokens=30)
    assert ledger.snapshot()["charged_upper_microdollars"] == 290
    with pytest.raises(ValueError):
        ledger.settle(reservation.id, 10, 5)


def test_bound_breach_halts_persistently(tmp_path):
    ledger = BudgetLedger(tmp_path / "b.db")
    reservation = ledger.reserve(MODELS[0], 100, 10, "test")
    with pytest.raises(BudgetExceeded):
        ledger.settle(reservation.id, 101, 10)
    with pytest.raises(BudgetExceeded):
        ledger.reserve(MODELS[0], 100, 10, "test")
    assert ledger.snapshot()["halted"]


def test_cap_and_lease_cannot_be_silently_reset(tmp_path):
    with pytest.raises(ValueError):
        BudgetLedger(tmp_path / "x.db", "20.000001")
    path = tmp_path / "b.db"
    BudgetLedger(path, "1", lease_id="first")
    with pytest.raises(ValueError):
        BudgetLedger(path, "2", lease_id="first")
    with pytest.raises(ValueError):
        BudgetLedger(path, "1", lease_id="second")
    assert BudgetLedger(path, "1", lease_id="first").snapshot()["cap_microdollars"] == 1_000_000


def test_abrupt_process_exit_preserves_pending_reservation(tmp_path):
    path = tmp_path / "crashed.db"
    source_root = Path(__file__).resolve().parents[1] / "src"
    code = """
import os
import sys
sys.path.insert(0, sys.argv[2])
from soc_triage.budget import BudgetLedger, MODELS
ledger = BudgetLedger(sys.argv[1], '0.06')
ledger.reserve(MODELS[0], 10_000, 1000, 'interrupted process')
os._exit(17)
"""
    result = subprocess.run([sys.executable, "-c", code, str(path), str(source_root)], capture_output=True, text=True)
    assert result.returncode == 17, result.stderr
    resumed = BudgetLedger(path, "0.06")
    assert resumed.snapshot()["states"] == {
        "pending": {"count": 1, "charge_microdollars": 50_000}
    }
    with pytest.raises(BudgetExceeded):
        resumed.reserve(MODELS[0], 10_000, 1000, "retry must reserve again")


def test_only_one_concurrent_finalization_succeeds(tmp_path):
    ledger = BudgetLedger(tmp_path / "b.db")
    reservation = ledger.reserve(MODELS[0], 100, 10, "test")
    def finalize(index):
        try:
            if index % 2:
                ledger.mark_uncertain(reservation.id)
                return "uncertain"
            ledger.settle(reservation.id, 10, 5)
            return "settled"
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        winners = [status for status in pool.map(finalize, range(16)) if status]
    assert len(winners) == 1
    expected_charge = 500 if winners[0] == "uncertain" else 90
    assert ledger.snapshot()["states"] == {
        winners[0]: {"count": 1, "charge_microdollars": expected_charge}
    }


def test_cached_input_cannot_bypass_reserved_bound(tmp_path):
    path = tmp_path / "b.db"
    ledger = BudgetLedger(path, "0.001")
    reservation = ledger.reserve(MODELS[1], 100, 10, "test")
    with pytest.raises(BudgetExceeded):
        ledger.settle(reservation.id, 10, 0, cache_read_tokens=50, cache_write_tokens=41)
    snapshot = BudgetLedger(path, "0.001").snapshot()
    assert snapshot["halted"]
    # A bound violation never releases its original reservation, even if the
    # total measured charge happens to be lower due to shorter output.
    assert snapshot["charged_upper_microdollars"] == 500
    connection = sqlite3.connect(path)
    try:
        usage = connection.execute("SELECT usage FROM reservations WHERE id=?", (reservation.id,)).fetchone()[0]
        assert json.loads(usage)["cache_write_tokens"] == 41
    finally:
        connection.close()
    with pytest.raises(BudgetExceeded):
        BudgetLedger(path, "0.001").reserve(MODELS[1], 1, 1, "blocked")


def test_excess_actual_charge_is_retained_and_halted(tmp_path):
    ledger = BudgetLedger(tmp_path / "b.db", "0.0005")
    reservation = ledger.reserve(MODELS[0], 100, 10, "test")
    with pytest.raises(BudgetExceeded):
        ledger.settle(reservation.id, 200, 20)
    snapshot = ledger.snapshot()
    assert snapshot["charged_upper_microdollars"] == 1000
    assert snapshot["remaining_microdollars"] == -500
    assert snapshot["halted"]


def test_settlement_releases_only_known_unused_reservation(tmp_path):
    path = tmp_path / "b.db"
    ledger = BudgetLedger(path, "0.001")
    first = ledger.reserve(MODELS[0], 100, 10, "first")
    second = ledger.reserve(MODELS[0], 100, 10, "second")
    with pytest.raises(BudgetExceeded):
        ledger.reserve(MODELS[0], 1, 1, "over exact cap")
    ledger.settle(first.id, 10, 0)
    resumed = BudgetLedger(path, "0.001")
    third = resumed.reserve(MODELS[0], 100, 6, "released capacity")
    assert third.reserved_microdollars == 460
    assert resumed.snapshot()["charged_upper_microdollars"] == 1000
    resumed.mark_uncertain(second.id)
    with pytest.raises(BudgetExceeded):
        resumed.reserve(MODELS[0], 0, 1, "still full")


@pytest.mark.parametrize("cap", ["0", "-1", "20.000001", "0.0000001", "NaN", "Infinity", "not-a-number", "20.0000000000000000000000000000000000000001", "1.0000000000000000000000000000000000000001"])
def test_invalid_caps_fail_before_creating_ledger(tmp_path, cap):
    path = tmp_path / "invalid.db"
    with pytest.raises(ValueError):
        BudgetLedger(path, cap)
    assert not path.exists()


@pytest.mark.parametrize("input_bound,output_bound", [(-1, 1), (True, 1), (1, False), (100_001, 1), (1, 0), (1, 1025)])
def test_invalid_bounds_do_not_reserve(tmp_path, input_bound, output_bound):
    ledger = BudgetLedger(tmp_path / "b.db")
    with pytest.raises(ValueError):
        ledger.reserve(MODELS[0], input_bound, output_bound, "invalid")
    assert ledger.snapshot()["charged_upper_microdollars"] == 0


def test_connections_close_on_success_and_failure(tmp_path, monkeypatch):
    opened = []
    real_connect = sqlite3.connect
    class TrackingConnection(sqlite3.Connection):
        closed = False
        def close(self):
            self.closed = True
            super().close()
    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs, factory=TrackingConnection)
        opened.append(connection)
        return connection
    monkeypatch.setattr("soc_triage.budget.sqlite3.connect", connect)
    path = tmp_path / "b.db"
    ledger = BudgetLedger(path, "0.0005")
    reservation = ledger.reserve(MODELS[0], 100, 10, "test")
    with pytest.raises(BudgetExceeded):
        ledger.reserve(MODELS[0], 1, 1, "over cap")
    ledger.snapshot()
    ledger.settle(reservation.id, 0, 0)
    with pytest.raises(ValueError):
        ledger.mark_uncertain(reservation.id)
    with pytest.raises(ValueError):
        BudgetLedger(path, "1")
    assert len(opened) == 7
    assert all(connection.closed for connection in opened)


def test_snapshot_reads_one_consistent_state_during_finalization(tmp_path, monkeypatch):
    path = tmp_path / "b.db"
    ledger = BudgetLedger(path)
    reservation = ledger.reserve(MODELS[0], 100, 10, "test")
    connection = sqlite3.connect(path)
    try:
        # WAL permits the interleaved writer to commit while a read snapshot
        # remains open, making the two-read consistency failure deterministic.
        connection.execute("PRAGMA journal_mode=WAL")
    finally:
        connection.close()
    real_connect = sqlite3.connect
    triggered = False
    class InterleavingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            nonlocal triggered
            cursor = super().execute(sql, *args, **kwargs)
            if sql.startswith("SELECT status,COUNT(*)") and not triggered:
                triggered = True
                with pytest.raises(BudgetExceeded):
                    ledger.settle(reservation.id, 101, 10)
            return cursor
    def connect(*args, **kwargs):
        return real_connect(*args, **kwargs, factory=InterleavingConnection)
    monkeypatch.setattr("soc_triage.budget.sqlite3.connect", connect)
    snapshot = ledger.snapshot()
    assert triggered
    assert not snapshot["halted"]
    assert snapshot["states"] == {"pending": {"count": 1, "charge_microdollars": 500}}
    later = ledger.snapshot()
    assert later["halted"]
    assert later["states"] == {"bound_violation": {"count": 1, "charge_microdollars": 504}}


def test_invalid_usage_never_releases_reservation(tmp_path):
    ledger = BudgetLedger(tmp_path / "b.db", "0.0005")
    reservation = ledger.reserve(MODELS[0], 100, 10, "test")
    with pytest.raises(ValueError):
        ledger.settle(reservation.id, 0, 0, cache_write_tokens=True)
    assert ledger.snapshot()["states"] == {"pending": {"count": 1, "charge_microdollars": 500}}
    with pytest.raises(BudgetExceeded):
        ledger.reserve(MODELS[0], 0, 1, "still fully reserved")
    ledger.settle(reservation.id, 0, 0)
    assert ledger.snapshot()["charged_upper_microdollars"] == 0


def test_journal_counts_optional_metadata_and_orphan_allocations():
    entries = [
        {"run_id": "100:1", "microdollars": 5_000_000},
        {"run_id": "100:2", "microdollars": 5_000_000, "source_commit": "a" * 40,
         "journal_commit": "b" * 40, "allocated_at": "2026-11-12T10:00:00+00:00"},
        {"run_id": "101:1", "microdollars": 5_000_000},
        {"run_id": "102:1", "microdollars": 5_000_000},
    ]
    journal = {"schema_version": 1, "cap_microdollars": 20_000_000,
               "allocations": entries, "metadata": {"note": "Unstarted allocations are not refunded"}}
    assert validate_journal(journal) == 20_000_000
    assert validate_journal({"schema_version": 1, "cap_microdollars": 20_000_000, "allocations": []}) == 0


@pytest.mark.parametrize("journal", [
    None, [], {},
    {"schema_version": True, "cap_microdollars": 20_000_000, "allocations": []},
    {"schema_version": 1.0, "cap_microdollars": 20_000_000, "allocations": []},
    {"schema_version": 2, "cap_microdollars": 20_000_000, "allocations": []},
    {"schema_version": 1, "cap_microdollars": 20_000_000.0, "allocations": []},
    {"schema_version": 1, "cap_microdollars": "20000000", "allocations": []},
    {"schema_version": 1, "cap_microdollars": 25_000_000, "allocations": []},
    {"schema_version": 1, "cap_microdollars": 20_000_000, "allocations": {}},
    {"schema_version": 1, "cap_microdollars": 20_000_000, "allocations": [None]},
    {"schema_version": 1, "cap_microdollars": 20_000_000, "allocations": [], "metadata": []},
    {"schema_version": 1, "cap_microdollars": 20_000_000, "allocations": [], "replacement_cap": 25_000_000},
])
def test_journal_rejects_malformed_schema_and_numeric_lookalikes(journal):
    with pytest.raises(ValueError):
        validate_journal(journal)


@pytest.mark.parametrize("entry", [
    {}, {"run_id": "100:1"},
    {"run_id": "100:1", "microdollars": True},
    {"run_id": "100:1", "microdollars": 5_000_000.0},
    {"run_id": "100:1", "microdollars": -5_000_000},
    {"run_id": "100:1", "microdollars": 4_000_000},
    {"run_id": 100, "microdollars": 5_000_000},
    {"run_id": "", "microdollars": 5_000_000},
    {"run_id": "100", "microdollars": 5_000_000},
    {"run_id": "100:0", "microdollars": 5_000_000},
    {"run_id": "100:01", "microdollars": 5_000_000},
    {"run_id": "100:1", "microdollars": 5_000_000, "source_commit": None},
    {"run_id": "100:1", "microdollars": 5_000_000, "source_commit": "g" * 40},
    {"run_id": "100:1", "microdollars": 5_000_000, "journal_commit": "b" * 39},
    {"run_id": "100:1", "microdollars": 5_000_000, "allocated_at": 123},
    {"run_id": "100:1", "microdollars": 5_000_000, "allocated_at": "2026-11-12"},
    {"run_id": "100:1", "microdollars": 5_000_000, "allocated_at": "2026-11-12T10:00:00"},
    {"run_id": "100:1", "microdollars": 5_000_000, "allocated_at": "2026-99-12T10:00:00Z"},
    {"run_id": "100:1", "microdollars": 5_000_000, "refunded": True},
])
def test_journal_rejects_invalid_entries_and_provenance(entry):
    with pytest.raises(ValueError):
        validate_journal({"schema_version": 1, "cap_microdollars": 20_000_000, "allocations": [entry]})


def test_journal_rejects_duplicate_attempt_and_fifth_allocation():
    entry = {"run_id": "100:1", "microdollars": 5_000_000}
    with pytest.raises(ValueError, match="Duplicate"):
        validate_journal({"schema_version": 1, "cap_microdollars": 20_000_000, "allocations": [entry, dict(entry)]})
    with pytest.raises(ValueError, match="exceeds"):
        validate_journal({"schema_version": 1, "cap_microdollars": 20_000_000,
                          "allocations": [{"run_id": f"{run}:1", "microdollars": 5_000_000} for run in range(100, 105)]})
