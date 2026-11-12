"""Run all three Module 7 scenarios and print deterministic, grader-friendly output.

Usage:
    python run_demo.py      (or: python3 run_demo.py)

Exit code is 0 when every check passes and 1 otherwise.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from order_simulation import (  # noqa: E402
    UNKNOWN_STATUS,
    FencedOrderStore,
    OrderEvent,
    OrderProcessor,
    Outcome,
    StaleTokenError,
    TokenIssuer,
)

LINE = "=" * 72
failures = []


def heading(title):
    print()
    print(LINE)
    print(title)
    print(LINE)


def check(description, condition):
    """Print a PASS/FAIL line and remember failures."""
    print(f"  [{'PASS' if condition else 'FAIL'}] {description}")
    if not condition:
        failures.append(description)


def show_result(result):
    print(f"    -> {result.outcome.value}: {result.message}")
    for event in result.released:
        print(f"    -> APPLIED: pending version {event.version} is now applied ({event.status})")


def show_state(state):
    print(f"    state: status={state.current_status}, "
          f"last_applied_version={state.last_applied_version}, "
          f"applied_versions={state.applied_versions}, "
          f"pending_versions={state.pending_versions}")


# ---------------------------------------------------------------------------
# Scenario 1: version 2, version 1, version 2 again
# ---------------------------------------------------------------------------
def scenario_out_of_order_and_duplicate():
    heading("SCENARIO 1: Out-of-order delivery and duplicate event (ORDER-1001)")
    print("  EXPECTED: v2 held as pending, v1 applied, v2 released, duplicate v2 ignored,")
    print("            final status PAID, applied versions [1, 2]")
    processor = OrderProcessor()
    order_id = "ORDER-1001"

    print("\n  Receive version 2: PAID")
    r1 = processor.receive(OrderEvent(order_id, 2, "PAID"))
    show_result(r1)
    state = processor.get_state(order_id)
    show_state(state)
    check("version 2 is PENDING because version 1 is missing", r1.outcome is Outcome.PENDING)
    check("version 2 did not change the status (still UNKNOWN)",
          state.current_status == UNKNOWN_STATUS)
    check("order is waiting for version 1", r1.waiting_for == 1)

    print("\n  Receive version 1: CREATED")
    r2 = processor.receive(OrderEvent(order_id, 1, "CREATED"))
    show_result(r2)
    show_state(state)
    check("version 1 is APPLIED", r2.outcome is Outcome.APPLIED)
    check("pending version 2 is now APPLIED automatically",
          [e.version for e in r2.released] == [2])
    check("pending collection is empty", state.pending_versions == [])

    print("\n  Receive version 2 again: PAID")
    status_before = state.current_status
    history_before = list(state.applied_versions)
    r3 = processor.receive(OrderEvent(order_id, 2, "PAID"))
    show_result(r3)
    show_state(state)
    check("duplicate version 2 is IGNORED DUPLICATE", r3.outcome is Outcome.IGNORED_DUPLICATE)
    check("duplicate did not change status or history",
          state.current_status == status_before and state.applied_versions == history_before)
    check("duplicate version 2 is recorded in ignored duplicates",
          [e.version for e in state.ignored_duplicates] == [2])

    print("\n  Final result")
    print(f"    final status is {state.current_status}")
    print(f"    final applied versions are {state.applied_versions}")
    print(f"    ignored duplicates: {[str(e) for e in state.ignored_duplicates]}")
    check("final status is PAID", state.current_status == "PAID")
    check("final applied versions are [1, 2]", state.applied_versions == [1, 2])


# ---------------------------------------------------------------------------
# Scenario 2: only version 3 arrives
# ---------------------------------------------------------------------------
def scenario_missing_event():
    heading("SCENARIO 2: Missing events (ORDER-MISSING)")
    print("  EXPECTED: v3 held as PENDING, status stays UNKNOWN (no jump to SHIPPED),")
    print("            missing versions 1 and 2 identified, waiting for version 1")
    processor = OrderProcessor()
    order_id = "ORDER-MISSING"

    print("\n  Receive version 3: SHIPPED   (versions 1 and 2 are never sent)")
    result = processor.receive(OrderEvent(order_id, 3, "SHIPPED"))
    show_result(result)
    state = processor.get_state(order_id)
    show_state(state)
    print(f"    missing versions: {state.missing_versions}")
    print(f"    waiting for version: {state.waiting_for_version}")

    check("version 3 is PENDING (not applied)", result.outcome is Outcome.PENDING)
    check("order did NOT jump to SHIPPED", state.current_status != "SHIPPED")
    check("current status remains UNKNOWN", state.current_status == UNKNOWN_STATUS)
    check("version 3 is recorded as pending", state.pending_versions == [3])
    check("missing versions are identified as [1, 2]", state.missing_versions == [1, 2])
    check("processor reports it is waiting for version 1",
          state.waiting_for_version == 1 and result.waiting_for == 1)
    check("no versions have been applied", state.applied_versions == [])


# ---------------------------------------------------------------------------
# Scenario 3: stale worker with fencing tokens
# ---------------------------------------------------------------------------
def scenario_fencing_tokens():
    heading("SCENARIO 3: Stale worker and fencing tokens (ORDER-FENCE)")
    print("  EXPECTED: worker B (token 2) ACCEPTED, worker A (token 1)")
    print("            REJECTED STALE WORKER, order state unchanged by the rejection")
    issuer = TokenIssuer()
    store = FencedOrderStore()
    order_id = "ORDER-FENCE"

    token_a = issuer.issue()
    print(f"\n  Worker A acquires the lease and receives fencing token {token_a}")
    print("  Worker A pauses (e.g. long GC pause) and its lease expires")
    token_b = issuer.issue()
    print(f"  Worker B acquires the lease and receives fencing token {token_b}")
    check("worker A has token 1", token_a == 1)
    check("worker B has token 2", token_b == 2)

    print(f"\n  Worker B writes status SHIPPED with token {token_b}")
    write_b = store.write(order_id, "worker-B", token_b, "SHIPPED")
    order = store.get(order_id)
    print(f"    -> ACCEPTED: {write_b.worker} token {write_b.token} is greater than "
          f"last accepted token {write_b.previous_token}")
    print(f"    state: status={order.status}, last_accepted_token={order.last_accepted_token}")
    check("worker B (newer token 2) is ACCEPTED", order.status == "SHIPPED")

    print(f"\n  Worker A wakes up and writes status PAID with stale token {token_a}")
    status_before = order.status
    token_before = order.last_accepted_token
    writes_before = list(order.accepted_writes)
    rejected = False
    try:
        store.write(order_id, "worker-A", token_a, "PAID")
    except StaleTokenError as error:
        rejected = True
        print(f"    -> {error}")
    print(f"    state: status={order.status}, last_accepted_token={order.last_accepted_token}")
    check("worker A (older token 1) is REJECTED STALE WORKER", rejected)
    check("rejection did not change status (still SHIPPED)", order.status == status_before)
    check("rejection did not change last accepted token (still 2)",
          order.last_accepted_token == token_before)
    check("rejection did not add a write to history", order.accepted_writes == writes_before)
    print(f"\n  Accepted writes: {[(w.worker, w.token, w.status) for w in order.accepted_writes]}")


def main():
    scenario_out_of_order_and_duplicate()
    scenario_missing_event()
    scenario_fencing_tokens()

    heading("SUMMARY")
    if failures:
        print(f"  FAIL: {len(failures)} check(s) failed:")
        for description in failures:
            print(f"    - {description}")
        return 1
    print("  PASS: all scenario checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
