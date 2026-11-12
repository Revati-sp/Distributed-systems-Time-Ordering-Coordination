"""Data models for the order-processing simulation.

An order moves through versioned states, for example:

    version 1: CREATED  ->  version 2: PAID  ->  version 3: SHIPPED

Every event carries exactly three fields: ``order_id``, ``version`` and
``status``. Events are validated as soon as they are created, so invalid
input never reaches the processor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# The only statuses an event may carry.
VALID_STATUSES = ("CREATED", "PAID", "SHIPPED")

# Status shown for an order before any event has been applied to it.
UNKNOWN_STATUS = "UNKNOWN"


class InvalidEventError(ValueError):
    """Raised when an event has a bad order_id, version or status."""


def validate_status(status: object) -> str:
    """Return ``status`` if it is one of VALID_STATUSES, otherwise raise."""
    if not isinstance(status, str) or status not in VALID_STATUSES:
        raise InvalidEventError(
            f"Invalid status {status!r}. Allowed statuses: {', '.join(VALID_STATUSES)}"
        )
    return status


@dataclass(frozen=True)
class OrderEvent:
    """A single versioned update for one order."""

    order_id: str
    version: int
    status: str

    def __post_init__(self) -> None:
        if not isinstance(self.order_id, str) or not self.order_id.strip():
            raise InvalidEventError(
                f"Invalid order_id {self.order_id!r}: must be a non-empty string"
            )
        # bool is a subclass of int in Python, so exclude it explicitly.
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise InvalidEventError(
                f"Invalid version {self.version!r}: must be an integer"
            )
        if self.version < 1:
            raise InvalidEventError(
                f"Invalid version {self.version}: versions start at 1"
            )
        validate_status(self.status)

    def __str__(self) -> str:
        return f"{self.order_id} v{self.version} {self.status}"


@dataclass
class OrderState:
    """Everything the processor knows about one order."""

    order_id: str
    current_status: str = UNKNOWN_STATUS
    last_applied_version: int = 0
    # Events that arrived too early, keyed by version.
    pending: Dict[int, OrderEvent] = field(default_factory=dict)
    # Events that were applied, in the order they were applied.
    applied_history: List[OrderEvent] = field(default_factory=list)
    # Events that were ignored because that version was already seen.
    ignored_duplicates: List[OrderEvent] = field(default_factory=list)

    @property
    def next_expected_version(self) -> int:
        """The only version that may be applied next."""
        return self.last_applied_version + 1

    @property
    def applied_versions(self) -> List[int]:
        return [event.version for event in self.applied_history]

    @property
    def pending_versions(self) -> List[int]:
        return sorted(self.pending)

    @property
    def missing_versions(self) -> List[int]:
        """Versions that must arrive before the pending events can be applied."""
        if not self.pending:
            return []
        highest_pending = max(self.pending)
        return [
            version
            for version in range(self.next_expected_version, highest_pending)
            if version not in self.pending
        ]

    @property
    def waiting_for_version(self) -> Optional[int]:
        """The version that is blocking progress, or None if nothing is blocked."""
        return self.next_expected_version if self.pending else None
