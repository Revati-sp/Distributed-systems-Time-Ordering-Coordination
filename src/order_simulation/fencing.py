"""Fencing tokens: protect an order from stale workers.

Scenario: a worker holds a lease (lock) on an order, then pauses (for example
a long garbage-collection pause or a network partition). Its lease expires,
a second worker gets a new lease, and both workers now believe they own the
order. Fencing tokens make the storage layer reject the stale worker.

Rule enforced by FencedOrderStore:

    A worker update is accepted only if its fencing token is greater than
    the last accepted fencing token for that order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .models import UNKNOWN_STATUS, validate_status


class StaleTokenError(Exception):
    """Raised when a worker writes with a token that is not newer than the last accepted one."""

    def __init__(self, order_id: str, worker: str, token: int, last_accepted_token: int) -> None:
        self.order_id = order_id
        self.worker = worker
        self.token = token
        self.last_accepted_token = last_accepted_token
        super().__init__(
            f"REJECTED STALE WORKER: {worker} used token {token} on {order_id}, "
            f"but token {last_accepted_token} was already accepted"
        )


class TokenIssuer:
    """Hands out strictly increasing fencing tokens (1, 2, 3, ...).

    In a real system this is the lock/lease service; here it is just a counter.
    """

    def __init__(self) -> None:
        self._last_issued = 0

    def issue(self) -> int:
        self._last_issued += 1
        return self._last_issued


@dataclass(frozen=True)
class AcceptedWrite:
    """Record of a write that passed the fencing check."""

    worker: str
    token: int
    status: str
    # The last accepted token before this write (0 if this was the first write).
    previous_token: int


@dataclass
class FencedOrder:
    order_id: str
    status: str = UNKNOWN_STATUS
    last_accepted_token: int = 0
    accepted_writes: List[AcceptedWrite] = field(default_factory=list)


class FencedOrderStore:
    """In-memory storage that checks fencing tokens before every write."""

    def __init__(self) -> None:
        self._orders: Dict[str, FencedOrder] = {}

    def get(self, order_id: str) -> FencedOrder:
        """Return the stored order. Raises KeyError if unknown."""
        return self._orders[order_id]

    def write(self, order_id: str, worker: str, token: int, status: str) -> AcceptedWrite:
        """Update the order's status if ``token`` is newer than the last accepted token.

        Raises StaleTokenError (and leaves the order unchanged) otherwise.
        """
        if isinstance(token, bool) or not isinstance(token, int) or token < 1:
            raise ValueError(f"Invalid fencing token {token!r}: must be a positive integer")
        validate_status(status)

        order = self._orders.setdefault(order_id, FencedOrder(order_id))
        if token <= order.last_accepted_token:
            raise StaleTokenError(order_id, worker, token, order.last_accepted_token)

        write = AcceptedWrite(
            worker=worker, token=token, status=status, previous_token=order.last_accepted_token
        )
        order.status = status
        order.last_accepted_token = token
        order.accepted_writes.append(write)
        return write
