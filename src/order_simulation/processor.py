"""Order processor that applies versioned events strictly in version order.

Rules (for each order):

1. The next expected version is ``last_applied_version + 1``.
2. An event with the expected version is APPLIED immediately. Then any
   pending events that now follow consecutively are applied too ("drained").
3. An event with a version higher than expected is held as PENDING. It does
   not change the order's status until every earlier version has arrived.
4. An event whose version was already applied (or is already pending) is an
   IGNORED_DUPLICATE. This also guarantees that an older event can never
   overwrite newer state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from .models import OrderEvent, OrderState


class Outcome(str, Enum):
    APPLIED = "APPLIED"
    PENDING = "PENDING"
    IGNORED_DUPLICATE = "IGNORED DUPLICATE"


@dataclass
class ProcessResult:
    """What happened when one event was received."""

    outcome: Outcome
    event: OrderEvent
    message: str
    # Pending events that were applied as a consequence of this event.
    released: List[OrderEvent] = field(default_factory=list)
    # When the event is pending: the version the order is waiting for.
    waiting_for: Optional[int] = None


class OrderProcessor:
    """Keeps an in-memory OrderState for every order it has seen."""

    def __init__(self) -> None:
        self._orders: Dict[str, OrderState] = {}

    def get_state(self, order_id: str) -> OrderState:
        """Return the state of a known order. Raises KeyError if unknown."""
        return self._orders[order_id]

    def receive(self, event: OrderEvent) -> ProcessResult:
        """Process one incoming event and report what happened."""
        if not isinstance(event, OrderEvent):
            raise TypeError(f"Expected OrderEvent, got {type(event).__name__}")

        state = self._orders.setdefault(event.order_id, OrderState(event.order_id))

        # Rule 4a: this version was already applied -> duplicate or stale.
        if event.version <= state.last_applied_version:
            state.ignored_duplicates.append(event)
            return ProcessResult(
                outcome=Outcome.IGNORED_DUPLICATE,
                event=event,
                message=(
                    f"duplicate version {event.version} is ignored "
                    f"(last applied version is {state.last_applied_version})"
                ),
            )

        # Rule 4b: this version is already waiting in pending -> duplicate.
        if event.version in state.pending:
            state.ignored_duplicates.append(event)
            return ProcessResult(
                outcome=Outcome.IGNORED_DUPLICATE,
                event=event,
                message=f"duplicate version {event.version} is ignored (already pending)",
                waiting_for=state.next_expected_version,
            )

        # Rule 3: a future version -> hold it until the gap is filled.
        if event.version > state.next_expected_version:
            state.pending[event.version] = event
            missing = state.missing_versions
            return ProcessResult(
                outcome=Outcome.PENDING,
                event=event,
                message=(
                    f"version {event.version} is pending because "
                    f"{_describe_versions(missing)} missing"
                ),
                waiting_for=state.next_expected_version,
            )

        # Rule 2: the expected version -> apply, then drain pending events.
        self._apply(state, event)
        released: List[OrderEvent] = []
        while state.next_expected_version in state.pending:
            next_event = state.pending.pop(state.next_expected_version)
            self._apply(state, next_event)
            released.append(next_event)

        return ProcessResult(
            outcome=Outcome.APPLIED,
            event=event,
            message=f"version {event.version} is applied",
            released=released,
        )

    @staticmethod
    def _apply(state: OrderState, event: OrderEvent) -> None:
        state.current_status = event.status
        state.last_applied_version = event.version
        state.applied_history.append(event)


def _describe_versions(versions: List[int]) -> str:
    """Format [1] as 'version 1 is' and [1, 2] as 'versions 1 and 2 are'."""
    if len(versions) == 1:
        return f"version {versions[0]} is"
    numbers = [str(v) for v in versions]
    return f"versions {', '.join(numbers[:-1])} and {numbers[-1]} are"
