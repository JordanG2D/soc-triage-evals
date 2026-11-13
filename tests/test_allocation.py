"""Exercise allocation ordering and failure modes without network or model calls."""

import base64
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from soc_triage.budget import validate_journal


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("allocate_live_budget_under_test", ROOT / "scripts/allocate_live_budget.py")
allocator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(allocator)


def entry(run_id, **metadata):
    return {"run_id": run_id, "microdollars": 5_000_000, **metadata}


class FakeGitHub:
    def __init__(self, directory, entries=(), *, put_error=None, persist_on_error=False, acknowledged_commit="b" * 40):
        self.destination = directory / ".state/live-lease.json"
        self.journal = {"schema_version": 1, "cap_microdollars": 20_000_000, "allocations": list(deepcopy(entries))}
        self.put_error = put_error
        self.persist_on_error = persist_on_error
        self.acknowledged_commit = acknowledged_commit
        self.calls = []

    def __call__(self, method, payload=None):
        # No API request may observe a newly issued local lease before its
        # durable CAS update has been acknowledged.
        assert not self.destination.exists()
        self.calls.append((method, deepcopy(payload)))
        if method == "GET":
            return {"content": base64.b64encode(json.dumps(self.journal).encode()).decode(), "sha": "c" * 40}
        assert method == "PUT"
        assert payload["sha"] == "c" * 40
        assert payload["branch"] == "main"
        proposed = json.loads(base64.b64decode(payload["content"]))
        validate_journal(proposed)
        if self.put_error is None or self.persist_on_error:
            self.journal = proposed
        if self.put_error is not None:
            raise self.put_error
        return {"commit": {"sha": self.acknowledged_commit}}


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": allocator.REPOSITORY,
        "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ID": "105",
        "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40,
        "GH_TOKEN": "offline-fake-token",
    }.items():
        monkeypatch.setenv(key, value)
    return tmp_path


def test_main_commits_request_before_writing_local_lease(workflow, monkeypatch):
    remote = FakeGitHub(workflow)
    monkeypatch.setattr(allocator, "api", remote)
    allocator.main()
    assert [method for method, _ in remote.calls] == ["GET", "PUT"]
    lease = json.loads(remote.destination.read_text())
    assert lease["run_id"] == "105:1"
    assert lease["source_commit"] == "a" * 40
    assert lease["journal_commit"] == "b" * 40
    assert lease["microdollars"] == 5_000_000
    assert remote.journal["allocations"] == [{key: value for key, value in lease.items() if key != "journal_commit"}]


def test_usage_reconciliation_hold_refuses_before_journal_or_lease_mutation(workflow, monkeypatch):
    remote = FakeGitHub(workflow, [entry("100:1"), entry("101:1")])
    remote.journal["requires_usage_reconciliation"] = True
    original = deepcopy(remote.journal)
    monkeypatch.setattr(allocator, "api", remote)
    with pytest.raises(ValueError, match="Historical provider usage requires reconciliation"):
        allocator.main()
    assert [method for method, _ in remote.calls] == ["GET"]
    assert remote.journal == original
    assert not remote.destination.exists()
    assert not remote.destination.parent.exists()


def test_explicit_false_reconciliation_hold_keeps_normal_allocation_path(workflow, monkeypatch):
    remote = FakeGitHub(workflow)
    remote.journal["requires_usage_reconciliation"] = False
    monkeypatch.setattr(allocator, "api", remote)
    allocator.main()
    assert [method for method, _ in remote.calls] == ["GET", "PUT"]
    assert remote.journal["requires_usage_reconciliation"] is False
    assert json.loads(remote.destination.read_text())["run_id"] == "105:1"


@pytest.mark.parametrize("hold", [None, 0, 1, "true", []])
def test_invalid_reconciliation_hold_rejected_before_remote_mutation(workflow, monkeypatch, hold):
    remote = FakeGitHub(workflow)
    remote.journal["requires_usage_reconciliation"] = hold
    original = deepcopy(remote.journal)
    monkeypatch.setattr(allocator, "api", remote)
    with pytest.raises(ValueError, match="requires_usage_reconciliation must be a boolean"):
        allocator.main()
    assert [method for method, _ in remote.calls] == ["GET"]
    assert remote.journal == original
    assert not remote.destination.exists()


def test_cas_rejection_never_issues_local_lease(workflow, monkeypatch):
    remote = FakeGitHub(workflow, put_error=HTTPError("https://example.invalid", 409, "CAS conflict", {}, None))
    monkeypatch.setattr(allocator, "api", remote)
    with pytest.raises(HTTPError):
        allocator.main()
    assert [method for method, _ in remote.calls] == ["GET", "PUT"]
    assert not remote.destination.exists()
    assert remote.journal["allocations"] == []


def test_ambiguous_orphan_allocation_stays_consumed_and_new_attempt_can_proceed(workflow, monkeypatch):
    remote = FakeGitHub(workflow, put_error=TimeoutError("Acknowledgement unavailable"), persist_on_error=True)
    monkeypatch.setattr(allocator, "api", remote)
    with pytest.raises(TimeoutError):
        allocator.main()
    assert [method for method, _ in remote.calls] == ["GET", "PUT"]
    assert not remote.destination.exists()
    assert validate_journal(remote.journal) == 5_000_000
    # The same attempt cannot spend a possibly consumed allocation.
    remote.put_error = None
    with pytest.raises(ValueError, match="already allocated"):
        allocator.main()
    assert [method for method, _ in remote.calls] == ["GET", "PUT", "GET"]
    # A genuinely new attempt gets a new allocation; the orphan is not refunded.
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    allocator.main()
    assert validate_journal(remote.journal) == 10_000_000
    assert json.loads(remote.destination.read_text())["run_id"] == "105:2"


def test_four_prior_allocations_refuse_fifth_without_put(workflow, monkeypatch):
    remote = FakeGitHub(workflow, [entry(f"{run}:1") for run in range(100, 104)])
    monkeypatch.setattr(allocator, "api", remote)
    with pytest.raises(ValueError, match="cap reached"):
        allocator.main()
    assert [method for method, _ in remote.calls] == ["GET"]
    assert not remote.destination.exists()


def test_duplicate_attempt_refused_without_put(workflow, monkeypatch):
    remote = FakeGitHub(workflow, [entry("105:1")])
    monkeypatch.setattr(allocator, "api", remote)
    with pytest.raises(ValueError, match="already allocated"):
        allocator.main()
    assert [method for method, _ in remote.calls] == ["GET"]
    assert not remote.destination.exists()


@pytest.mark.parametrize("change", ["float-cap", "duplicate", "invalid-entry", "schema"])
def test_invalid_remote_journal_is_rejected_before_put(workflow, monkeypatch, change):
    remote = FakeGitHub(workflow)
    if change == "float-cap":
        remote.journal["cap_microdollars"] = 20_000_000.0
    elif change == "duplicate":
        remote.journal["allocations"] = [entry("100:1"), entry("100:1")]
    elif change == "invalid-entry":
        remote.journal["allocations"] = [None]
    else:
        remote.journal["schema_version"] = True
    monkeypatch.setattr(allocator, "api", remote)
    with pytest.raises(ValueError):
        allocator.main()
    assert [method for method, _ in remote.calls] == ["GET"]
    assert not remote.destination.exists()


def test_bad_current_source_commit_does_not_write_remote_or_local_lease(workflow, monkeypatch):
    remote = FakeGitHub(workflow)
    monkeypatch.setattr(allocator, "api", remote)
    monkeypatch.setenv("GITHUB_SHA", "invalid")
    with pytest.raises(ValueError, match="source_commit"):
        allocator.main()
    assert [method for method, _ in remote.calls] == ["GET"]
    assert not remote.destination.exists()


def test_invalid_commit_acknowledgement_does_not_issue_lease_or_refund(workflow, monkeypatch):
    remote = FakeGitHub(workflow, acknowledged_commit="not-a-sha")
    monkeypatch.setattr(allocator, "api", remote)
    with pytest.raises(ValueError, match="journal_commit"):
        allocator.main()
    assert not remote.destination.exists()
    assert validate_journal(remote.journal) == 5_000_000


def test_outside_authorized_workflow_cannot_request_allocation(workflow, monkeypatch):
    remote = FakeGitHub(workflow)
    monkeypatch.setattr(allocator, "api", remote)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    with pytest.raises(ValueError, match="restricted"):
        allocator.main()
    assert remote.calls == []
    assert not remote.destination.exists()


def test_api_closes_response_without_real_network(workflow, monkeypatch):
    response = io.BytesIO(b'{"content": "offline"}')
    def fake_urlopen(request, timeout):
        assert request.get_method() == "GET"
        assert timeout == 30
        return response
    monkeypatch.setattr(allocator.urllib.request, "urlopen", fake_urlopen)
    assert allocator.api("GET") == {"content": "offline"}
    assert response.closed


def test_live_verification_rejects_bad_history_even_with_matching_lease(workflow, monkeypatch):
    from soc_triage import live
    lease = entry("105:1", source_commit="a" * 40, allocated_at="2026-11-12T10:00:00+00:00", journal_commit="b" * 40)
    path = workflow / "lease.json"
    path.write_text(json.dumps(lease))
    journal = {"schema_version": True, "cap_microdollars": 20_000_000,
               "allocations": [{key: value for key, value in lease.items() if key != "journal_commit"}]}
    response = {"content": base64.b64encode(json.dumps(journal).encode()).decode()}
    requested = []
    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(live.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ValueError, match="schema"):
        live.verified_lease(path)
    assert len(requested) == 1
