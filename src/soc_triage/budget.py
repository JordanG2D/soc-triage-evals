"""Persistent, conservative per-request spending reservations.

All input categories are charged at $4/M and output at $10/M for the two
allowlisted standard-service models. This deliberately exceeds their declared
prices, including cache writes. It is an accounting ceiling, not an invoice.
Unknown outcomes keep their entire reservation. A separate repository journal
allocates the lifetime $20 before a GitHub Actions run can make requests.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, DecimalException, localcontext
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterator
import uuid

MODELS = ("openai/gpt-6-luna", "anthropic/claude-haiku-4-5-20251001")
MAX_CAP = 20_000_000
ALLOCATION_MICRODOLLARS = 5_000_000
INPUT_MICRODOLLARS = 4
OUTPUT_MICRODOLLARS = 10


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class Reservation:
    id: str
    reserved_microdollars: int


def _count(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("Token bounds and usage must be nonnegative integers")
    return value


def validate_journal(journal: object) -> int:
    """Validate the one lifetime journal and return its consumed allocation.

    Every allocation remains consumed, including one whose worker never starts
    or whose local lease was lost. Historical provenance metadata is optional;
    when present it must have the same shape as newly generated metadata.
    """
    if not isinstance(journal, dict):
        raise ValueError("Budget journal must be an object")
    allowed = {"schema_version", "cap_microdollars", "allocations", "metadata", "requires_usage_reconciliation"}
    if set(journal) - allowed:
        raise ValueError("Unknown budget journal fields")
    if type(journal.get("schema_version")) is not int or journal["schema_version"] != 1:
        raise ValueError("Unknown budget journal schema")
    if type(journal.get("cap_microdollars")) is not int or journal["cap_microdollars"] != MAX_CAP:
        raise ValueError("Budget journal must retain the exact lifetime $20 cap")
    if "metadata" in journal and not isinstance(journal["metadata"], dict):
        raise ValueError("Budget journal metadata must be an object")
    if type(journal.get("requires_usage_reconciliation", False)) is not bool:
        raise ValueError("requires_usage_reconciliation must be a boolean")
    entries = journal.get("allocations")
    if not isinstance(entries, list):
        raise ValueError("Missing budget allocation history")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each budget allocation must be an object")
        if set(entry) - {"run_id", "microdollars", "source_commit", "allocated_at", "journal_commit"}:
            raise ValueError("Unknown budget allocation fields")
        run_id = entry.get("run_id")
        if not isinstance(run_id, str) or re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", run_id) is None or run_id in seen:
            raise ValueError("Duplicate or invalid run identifier")
        seen.add(run_id)
        if type(entry.get("microdollars")) is not int or entry["microdollars"] != ALLOCATION_MICRODOLLARS:
            raise ValueError("Each allocation must be exactly $5 in integer microdollars")
        for name in ("source_commit", "journal_commit"):
            if name in entry and (not isinstance(entry[name], str) or re.fullmatch(r"[0-9a-f]{40}", entry[name]) is None):
                raise ValueError(f"Invalid allocation {name}")
        if "allocated_at" in entry:
            stamp = entry["allocated_at"]
            if not isinstance(stamp, str) or re.match(r"\d{4}-\d{2}-\d{2}T", stamp) is None:
                raise ValueError("Allocation timestamp must be a timezone-aware ISO datetime")
            try:
                parsed = datetime.fromisoformat(stamp)
            except ValueError as error:
                raise ValueError("Invalid allocation timestamp") from error
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("Allocation timestamp must include a timezone")
    total = len(entries) * ALLOCATION_MICRODOLLARS
    if total > MAX_CAP:
        raise ValueError("Budget history already exceeds lifetime cap")
    return total


class BudgetLedger:
    def __init__(self, path: str | Path, cap_usd: str | Decimal = "5", *, lease_id: str = "local-test"):
        try:
            amount = Decimal(str(cap_usd))
            with localcontext() as context:
                # Do not round a long sub-microdollar tail into a valid cap.
                context.prec = max(28, len(amount.as_tuple().digits) + 6)
                cap = amount * 1_000_000
        except DecimalException as error:
            raise ValueError("Cap must be a finite decimal amount") from error
        if not cap.is_finite() or cap != cap.to_integral_value() or not 0 < cap <= MAX_CAP:
            raise ValueError("Cap must be positive, precise to a microdollar, and at most $20")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cap = int(cap)
        self.lease_id = lease_id
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), cap INTEGER NOT NULL, lease TEXT NOT NULL, halted INTEGER NOT NULL DEFAULT 0)")
            connection.execute("CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, model TEXT NOT NULL, purpose TEXT NOT NULL, input_bound INTEGER NOT NULL, output_bound INTEGER NOT NULL, reserved INTEGER NOT NULL, charge INTEGER NOT NULL, status TEXT NOT NULL, usage TEXT)")
            connection.execute("INSERT OR IGNORE INTO settings(id,cap,lease) VALUES(1,?,?)", (self.cap, self.lease_id))
            settings = connection.execute("SELECT cap,lease FROM settings WHERE id=1").fetchone()
            if settings != (self.cap, self.lease_id):
                raise ValueError("Existing ledger is bound to a different cap or run lease")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("PRAGMA busy_timeout=30000")
            # sqlite3's own context commits or rolls back; it does not close.
            with connection:
                yield connection
        finally:
            connection.close()

    def reserve(self, model: str, input_token_bound: int, output_token_bound: int, purpose: str) -> Reservation:
        if model not in MODELS:
            raise ValueError("Model is not covered by the declared price ceiling")
        input_bound, output_bound = _count(input_token_bound), _count(output_token_bound)
        if input_bound > 100_000 or not 0 < output_bound <= 1024:
            raise ValueError("Request exceeds declared token limits")
        amount = input_bound * INPUT_MICRODOLLARS + output_bound * OUTPUT_MICRODOLLARS
        identifier = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT halted FROM settings WHERE id=1").fetchone()[0]:
                raise BudgetExceeded("Ledger halted after a bound violation")
            used = connection.execute("SELECT COALESCE(SUM(charge),0) FROM reservations").fetchone()[0]
            if used + amount > self.cap:
                raise BudgetExceeded("Remaining allocation cannot cover the full request reservation; no request sent")
            connection.execute("INSERT INTO reservations(id,model,purpose,input_bound,output_bound,reserved,charge,status,usage) VALUES(?,?,?,?,?,?,?,?,NULL)", (identifier, model, str(purpose), input_bound, output_bound, amount, amount, "pending"))
        return Reservation(identifier, amount)

    def mark_uncertain(self, reservation_id: str) -> None:
        with self._connect() as connection:
            updated = connection.execute("UPDATE reservations SET status='uncertain' WHERE id=? AND status='pending'", (reservation_id,)).rowcount
            if updated != 1:
                raise ValueError("Unknown or already finalized reservation")

    def settle(self, reservation_id: str, input_tokens: int, output_tokens: int, *, cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> None:
        # Inspect normalizes uncached input separately from cache reads/writes.
        total_input = _count(input_tokens) + _count(cache_read_tokens) + _count(cache_write_tokens)
        output = _count(output_tokens)
        charge = total_input * INPUT_MICRODOLLARS + output * OUTPUT_MICRODOLLARS
        usage = json.dumps({"input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_tokens": cache_read_tokens, "cache_write_tokens": cache_write_tokens})
        violation = False
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT input_bound,output_bound,status FROM reservations WHERE id=?", (reservation_id,)).fetchone()
            if row is None or row[2] != "pending":
                raise ValueError("Unknown or already finalized reservation")
            if total_input > row[0] or output > row[1]:
                connection.execute("UPDATE settings SET halted=1 WHERE id=1")
                connection.execute("UPDATE reservations SET status='bound_violation',charge=MAX(charge,?),usage=? WHERE id=?", (charge, usage, reservation_id))
                violation = True
            else:
                connection.execute("UPDATE reservations SET charge=?,status='settled',usage=? WHERE id=?", (charge, usage, reservation_id))
        if violation:
            raise BudgetExceeded("Provider usage exceeded the reserved token bound; ledger halted")

    def snapshot(self) -> dict:
        with self._connect() as connection:
            # Both reads must describe the same committed ledger state.
            connection.execute("BEGIN")
            rows = connection.execute("SELECT status,COUNT(*),SUM(charge) FROM reservations GROUP BY status").fetchall()
            halted = bool(connection.execute("SELECT halted FROM settings WHERE id=1").fetchone()[0])
        used = sum(row[2] for row in rows)
        return {"lease_id": self.lease_id, "cap_microdollars": self.cap, "charged_upper_microdollars": used, "remaining_microdollars": self.cap - used, "halted": halted, "states": {row[0]: {"count": row[1], "charge_microdollars": row[2]} for row in rows}, "interpretation": "Conservative accounting ceiling; not a provider invoice. Pending and uncertain calls retain their full reservation."}
