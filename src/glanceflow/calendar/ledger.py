from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from glanceflow.calendar.models import CalendarEventSnapshot, CreateEventRequest


class LedgerIntegrityError(RuntimeError):
    pass


class LedgerState(StrEnum):
    PREPARED = "PREPARED"
    CREATE_PENDING = "CREATE_PENDING"
    EXECUTION_REJECTED = "EXECUTION_REJECTED"
    EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"
    EXECUTED_UNVERIFIED = "EXECUTED_UNVERIFIED"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLBACK_VERIFIED = "ROLLBACK_VERIFIED"
    MANUAL_RECOVERY_REQUIRED = "MANUAL_RECOVERY_REQUIRED"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone information")
    return value


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["calendar-ledger-entry-v1"] = "calendar-ledger-entry-v1"
    operation_id: str
    transaction_id: str
    idempotency_key: str
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    calendar_id_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_id: str
    state: LedgerState
    attempt_count: int = Field(default=0, ge=0)
    last_error: str | None = None
    created_at: datetime
    last_checked_at: datetime

    _created_aware = field_validator("created_at")(_aware)
    _checked_aware = field_validator("last_checked_at")(_aware)


def calendar_id_digest(calendar_id: str) -> str:
    return hashlib.sha256(calendar_id.encode("utf-8")).hexdigest()


def _snapshot_payload(value: CreateEventRequest | CalendarEventSnapshot) -> dict:
    if isinstance(value, CreateEventRequest):
        return {
            "title": value.title,
            "start_time": value.start_time.isoformat(),
            "end_time": value.end_time.isoformat(),
            "timezone": value.timezone,
            "location": value.location or "",
            "description": value.description,
            "private_metadata": dict(sorted(value.private_metadata.items())),
        }
    return {
        "title": value.title,
        "start_time": value.start_time.isoformat(),
        "end_time": value.end_time.isoformat(),
        "timezone": value.timezone,
        "location": value.location or "",
        "description": value.description,
        "private_metadata": {
            key: val
            for key, val in sorted(value.private_metadata.items())
            if key != "glanceflow_idempotency_key"
        },
    }


def recovery_snapshot_digest(value: CreateEventRequest | CalendarEventSnapshot) -> str:
    encoded = json.dumps(
        _snapshot_payload(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class LocalTransactionLedger:
    """Minimal local recovery ledger; never stores credentials or notice contents."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._entries: dict[str, LedgerEntry] = {}
        if path is not None and path.exists():
            self._load()

    def _load(self) -> None:
        assert self.path is not None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != "calendar-transaction-ledger-v1":
                raise LedgerIntegrityError("unsupported calendar ledger schema")
            entries = [LedgerEntry.model_validate(item) for item in payload.get("entries", [])]
            if len({entry.operation_id for entry in entries}) != len(entries):
                raise LedgerIntegrityError("duplicate operation_id in calendar ledger")
            self._entries = {entry.operation_id: entry for entry in entries}
        except (OSError, json.JSONDecodeError, ValidationError, AttributeError) as exc:
            raise LedgerIntegrityError("calendar transaction ledger is invalid") from exc

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "calendar-transaction-ledger-v1",
            "entries": [
                entry.model_dump(mode="json")
                for entry in sorted(self._entries.values(), key=lambda item: item.operation_id)
            ],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, self.path)

    def prepare(
        self,
        *,
        operation_id: str,
        transaction_id: str,
        idempotency_key: str,
        snapshot_hash: str,
        calendar_id_hash: str,
        event_id: str,
    ) -> LedgerEntry:
        existing = self._entries.get(operation_id)
        if existing is not None:
            bindings = (
                existing.transaction_id,
                existing.idempotency_key,
                existing.snapshot_hash,
                existing.calendar_id_hash,
                existing.event_id,
            )
            proposed = (transaction_id, idempotency_key, snapshot_hash, calendar_id_hash, event_id)
            if bindings != proposed:
                raise LedgerIntegrityError("operation_id binding mismatch")
            return existing.model_copy(deep=True)
        now = datetime.now(timezone.utc)
        entry = LedgerEntry(
            operation_id=operation_id,
            transaction_id=transaction_id,
            idempotency_key=idempotency_key,
            snapshot_hash=snapshot_hash,
            calendar_id_hash=calendar_id_hash,
            event_id=event_id,
            state=LedgerState.PREPARED,
            created_at=now,
            last_checked_at=now,
        )
        self._entries[operation_id] = entry
        self._persist()
        return entry.model_copy(deep=True)

    def update(
        self,
        operation_id: str,
        state: LedgerState,
        *,
        last_error: str | None = None,
        increment_attempt: bool = False,
    ) -> LedgerEntry:
        try:
            current = self._entries[operation_id]
        except KeyError as exc:
            raise LedgerIntegrityError("unknown ledger operation") from exc
        updated = current.model_copy(
            update={
                "state": state,
                "last_error": last_error,
                "attempt_count": current.attempt_count + int(increment_attempt),
                "last_checked_at": datetime.now(timezone.utc),
            }
        )
        self._entries[operation_id] = updated
        self._persist()
        return updated.model_copy(deep=True)

    def for_transaction(self, transaction_id: str) -> list[LedgerEntry]:
        return [
            entry.model_copy(deep=True)
            for entry in self._entries.values()
            if entry.transaction_id == transaction_id
        ]

    def incomplete(self) -> list[LedgerEntry]:
        terminal = {
            LedgerState.EXECUTION_REJECTED,
            LedgerState.VERIFIED_SUCCESS,
            LedgerState.ROLLBACK_VERIFIED,
        }
        return [entry.model_copy(deep=True) for entry in self._entries.values() if entry.state not in terminal]
