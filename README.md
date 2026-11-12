# Module 7: Time, Ordering & Coordination

A small, deterministic Python simulation of an order-processing service that stays correct when events arrive **out of order**, arrive **twice**, **never arrive**, or are sent by a **stale worker**.

## Overview

An order moves through versioned states:

```text
version 1: CREATED  →  version 2: PAID  →  version 3: SHIPPED
```

Every event carries three fields: `order_id`, `version` and `status`. In a distributed system, the network can reorder, delay, duplicate or drop these events. This simulation shows how a processor stays correct anyway:

- It applies events **only in version order**. It does not trust arrival order or timestamps.
- It holds events that arrive early as **pending** until the gap before them is filled.
- It **ignores duplicates**, so replaying an old event never changes state.
- It uses **fencing tokens** so a worker that lost its lease cannot overwrite a newer worker's write.

All three scenarios run in memory, with no randomness, clocks or network calls, so the output is identical on every run.

## Features

| Feature | How it is implemented |
|---|---|
| Versioned events | `OrderEvent(order_id, version, status)` is a frozen dataclass and is validated on creation ([models.py](src/order_simulation/models.py)). |
| Out-of-order delivery | `OrderProcessor.receive()` applies an event only when `version == last_applied_version + 1` ([processor.py](src/order_simulation/processor.py)). |
| Pending events | Future versions are stored in `OrderState.pending`. After each apply, the processor drains consecutive pending versions automatically. |
| Duplicate detection | A version that is `<= last_applied_version`, or that is already pending, is recorded in `ignored_duplicates` and changes nothing. |
| Missing-event detection | `OrderState.missing_versions` and `waiting_for_version` report exactly which versions are blocking progress. |
| Fencing tokens | `TokenIssuer` hands out strictly increasing tokens (1, 2, 3, …) ([fencing.py](src/order_simulation/fencing.py)). |
| Stale-worker rejection | `FencedOrderStore.write()` raises `StaleTokenError` unless the token is **greater than** the last accepted token for that order, and leaves state untouched. |
| Input validation | Version `0`, negative or non-integer versions, unknown statuses and empty order IDs raise `InvalidEventError`. |

## Project Structure

```text
.
├── src/
│   └── order_simulation/
│       ├── __init__.py       # public exports
│       ├── models.py         # OrderEvent, OrderState, validation
│       ├── processor.py      # OrderProcessor: ordering, pending, duplicates
│       └── fencing.py        # TokenIssuer, FencedOrderStore, StaleTokenError
├── tests/
│   ├── test_order_processor.py
│   └── test_fencing_tokens.py
├── evidence/
│   ├── README.md             # how the evidence was generated
│   └── terminal-output.txt   # real output of the demo and the tests
├── README.md
├── requirements.txt          # empty: standard library only
└── run_demo.py               # runs all three scenarios
```

## Requirements

- **Python:** 3.9 or newer. The assignment targets Python 3.10+, and the code also runs on 3.9. The evidence below was produced with Python 3.9.6.
- **Operating system:** any OS with Python (macOS, Linux or Windows). No OS-specific features are used.
- **Dependencies:** none. Only the Python standard library is used (`dataclasses`, `enum`, `unittest`). `requirements.txt` is intentionally empty.

## Installation and Running

```bash
git clone https://github.com/Revati-sp/Distributed-systems-Time-Ordering-Coordination.git
cd Distributed-systems-Time-Ordering-Coordination
python run_demo.py
python -m unittest discover -s tests -v
```

> **Note:** On macOS and some Linux systems, the interpreter is named `python3` and there is no `python` command. In that case, run the same commands with `python3`:
>
> ```bash
> python3 run_demo.py
> python3 -m unittest discover -s tests -v
> ```

You do not need to install anything. `run_demo.py` and the tests add `src/` to the import path themselves. `run_demo.py` exits with code `0` when every check passes and `1` otherwise.

Optionally, check that every source file compiles:

```bash
python -m compileall .
```

## Correct Event Ordering Evidence

Delivery sequence for `ORDER-1001`: **version 2 → version 1 → version 2 again**.

Output of `python3 run_demo.py`, scenario 1:

```text
========================================================================
SCENARIO 1: Out-of-order delivery and duplicate event (ORDER-1001)
========================================================================
  EXPECTED: v2 held as pending, v1 applied, v2 released, duplicate v2 ignored,
            final status PAID, applied versions [1, 2]

  Receive version 2: PAID
    -> PENDING: version 2 is pending because version 1 is missing
    state: status=UNKNOWN, last_applied_version=0, applied_versions=[], pending_versions=[2]
  [PASS] version 2 is PENDING because version 1 is missing
  [PASS] version 2 did not change the status (still UNKNOWN)
  [PASS] order is waiting for version 1

  Receive version 1: CREATED
    -> APPLIED: version 1 is applied
    -> APPLIED: pending version 2 is now applied (PAID)
    state: status=PAID, last_applied_version=2, applied_versions=[1, 2], pending_versions=[]
  [PASS] version 1 is APPLIED
  [PASS] pending version 2 is now APPLIED automatically
  [PASS] pending collection is empty

  Receive version 2 again: PAID
    -> IGNORED DUPLICATE: duplicate version 2 is ignored (last applied version is 2)
    state: status=PAID, last_applied_version=2, applied_versions=[1, 2], pending_versions=[]
  [PASS] duplicate version 2 is IGNORED DUPLICATE
  [PASS] duplicate did not change status or history
  [PASS] duplicate version 2 is recorded in ignored duplicates

  Final result
    final status is PAID
    final applied versions are [1, 2]
    ignored duplicates: ['ORDER-1001 v2 PAID']
  [PASS] final status is PAID
  [PASS] final applied versions are [1, 2]
```

What this shows:

1. Version 2 arrives first and is **not** applied. It is held as pending, and the status stays `UNKNOWN`.
2. Version 1 arrives and is applied (`CREATED`).
3. Pending version 2 is released and applied automatically (`PAID`).
4. The duplicate version 2 is ignored, and the status and history do not change.
5. The final status is `PAID`, and the applied versions are `[1, 2]`.

## Duplicate Handling Evidence

This excerpt comes from the same scenario 1 output above. Version 2 arrives a second time after it has already been applied:

```text
  Receive version 2 again: PAID
    -> IGNORED DUPLICATE: duplicate version 2 is ignored (last applied version is 2)
    state: status=PAID, last_applied_version=2, applied_versions=[1, 2], pending_versions=[]
  [PASS] duplicate version 2 is IGNORED DUPLICATE
  [PASS] duplicate did not change status or history
  [PASS] duplicate version 2 is recorded in ignored duplicates
```

The state is the same before and after the duplicate: status `PAID`, last applied version `2`, and applied versions `[1, 2]`. The ignored event is kept in `ignored_duplicates` for auditing.

The automated tests cover two more duplicate cases:

- A duplicate of an event that is still pending (`test_duplicate_of_pending_event_is_ignored`).
- An old version replayed after newer ones (`test_older_event_does_not_overwrite_newer_state`). Version 1 arrives after version 3, and the status stays `SHIPPED`.

## Missing Event Evidence

Only version 3 is sent for `ORDER-MISSING`. Versions 1 and 2 never arrive.

```text
========================================================================
SCENARIO 2: Missing events (ORDER-MISSING)
========================================================================
  EXPECTED: v3 held as PENDING, status stays UNKNOWN (no jump to SHIPPED),
            missing versions 1 and 2 identified, waiting for version 1

  Receive version 3: SHIPPED   (versions 1 and 2 are never sent)
    -> PENDING: version 3 is pending because versions 1 and 2 are missing
    state: status=UNKNOWN, last_applied_version=0, applied_versions=[], pending_versions=[3]
    missing versions: [1, 2]
    waiting for version: 1
  [PASS] version 3 is PENDING (not applied)
  [PASS] order did NOT jump to SHIPPED
  [PASS] current status remains UNKNOWN
  [PASS] version 3 is recorded as pending
  [PASS] missing versions are identified as [1, 2]
  [PASS] processor reports it is waiting for version 1
  [PASS] no versions have been applied
```

The order never jumps to `SHIPPED`. Version 3 waits in the pending collection, and the processor reports that it is waiting for version 1. Versions 1 and 2 are identified as missing.

## Stale Worker Evidence

Two workers compete to update `ORDER-FENCE`. Worker A gets token 1, pauses, and loses its lease. Worker B then gets token 2.

```text
========================================================================
SCENARIO 3: Stale worker and fencing tokens (ORDER-FENCE)
========================================================================
  EXPECTED: worker B (token 2) ACCEPTED, worker A (token 1)
            REJECTED STALE WORKER, order state unchanged by the rejection

  Worker A acquires the lease and receives fencing token 1
  Worker A pauses (e.g. long GC pause) and its lease expires
  Worker B acquires the lease and receives fencing token 2
  [PASS] worker A has token 1
  [PASS] worker B has token 2

  Worker B writes status SHIPPED with token 2
    -> ACCEPTED: worker-B token 2 is greater than last accepted token 0
    state: status=SHIPPED, last_accepted_token=2
  [PASS] worker B (newer token 2) is ACCEPTED

  Worker A wakes up and writes status PAID with stale token 1
    -> REJECTED STALE WORKER: worker-A used token 1 on ORDER-FENCE, but token 2 was already accepted
    state: status=SHIPPED, last_accepted_token=2
  [PASS] worker A (older token 1) is REJECTED STALE WORKER
  [PASS] rejection did not change status (still SHIPPED)
  [PASS] rejection did not change last accepted token (still 2)
  [PASS] rejection did not add a write to history

  Accepted writes: [('worker-B', 2, 'SHIPPED')]

========================================================================
SUMMARY
========================================================================
  PASS: all scenario checks passed
```

Worker B's write with token 2 is accepted. Worker A's later write with token 1 is rejected with `StaleTokenError`. After the rejection, the status, the last accepted token and the write history are all unchanged.

## Automated Test Evidence

Real output of `python3 -m unittest discover -s tests -v` (32 tests):

```text
test_invalid_status_is_rejected_without_creating_state (test_fencing_tokens.InvalidFencedWriteTests) ... ok
test_invalid_tokens_are_rejected (test_fencing_tokens.InvalidFencedWriteTests) ... ok
test_equal_token_is_rejected (test_fencing_tokens.StaleWorkerTests) ... ok
test_increasing_tokens_are_all_accepted (test_fencing_tokens.StaleWorkerTests) ... ok
test_newer_token_is_accepted (test_fencing_tokens.StaleWorkerTests) ... ok
test_older_token_is_rejected (test_fencing_tokens.StaleWorkerTests) ... ok
test_rejected_stale_worker_does_not_change_state (test_fencing_tokens.StaleWorkerTests) ... ok
test_tokens_are_tracked_per_order (test_fencing_tokens.StaleWorkerTests) ... ok
test_workers_receive_tokens_1_and_2 (test_fencing_tokens.StaleWorkerTests) ... ok
test_tokens_are_strictly_increasing (test_fencing_tokens.TokenIssuerTests) ... ok
test_empty_order_id_is_rejected (test_order_processor.InvalidEventTests) ... ok
test_negative_version_is_rejected (test_order_processor.InvalidEventTests) ... ok
test_non_integer_version_is_rejected (test_order_processor.InvalidEventTests) ... ok
test_processor_rejects_non_event_input (test_order_processor.InvalidEventTests) ... ok
test_unknown_order_lookup_raises_key_error (test_order_processor.InvalidEventTests) ... ok
test_unknown_status_is_rejected (test_order_processor.InvalidEventTests) ... ok
test_version_zero_is_rejected (test_order_processor.InvalidEventTests) ... ok
test_filling_part_of_the_gap_still_waits (test_order_processor.MissingEventTests) ... ok
test_later_version_is_not_applied (test_order_processor.MissingEventTests) ... ok
test_later_version_remains_pending (test_order_processor.MissingEventTests) ... ok
test_missing_versions_are_identified (test_order_processor.MissingEventTests) ... ok
test_order_does_not_jump_to_shipped (test_order_processor.MissingEventTests) ... ok
test_processor_reports_waiting_for_version_1 (test_order_processor.MissingEventTests) ... ok
test_duplicate_of_pending_event_is_ignored (test_order_processor.OutOfOrderDeliveryTests) ... ok
test_duplicate_version_is_ignored_and_does_not_change_state (test_order_processor.OutOfOrderDeliveryTests) ... ok
test_full_assignment_sequence_final_status_and_history (test_order_processor.OutOfOrderDeliveryTests) ... ok
test_in_order_delivery_applies_immediately (test_order_processor.OutOfOrderDeliveryTests) ... ok
test_multiple_pending_versions_drain_in_order (test_order_processor.OutOfOrderDeliveryTests) ... ok
test_older_event_does_not_overwrite_newer_state (test_order_processor.OutOfOrderDeliveryTests) ... ok
test_orders_are_tracked_independently (test_order_processor.OutOfOrderDeliveryTests) ... ok
test_pending_version_is_applied_after_missing_version_arrives (test_order_processor.OutOfOrderDeliveryTests) ... ok
test_version_2_before_version_1_is_held_as_pending (test_order_processor.OutOfOrderDeliveryTests) ... ok

----------------------------------------------------------------------
Ran 32 tests in 0.001s

OK
```

The complete, unedited output of the demo, the tests and `python3 -m compileall .` is in [evidence/terminal-output.txt](evidence/terminal-output.txt).

## Reflection

**Why are timestamps alone not enough to guarantee correct event ordering in a distributed system?**

Each machine stamps events with its own local clock, and those clocks are never perfectly synchronized. Clock skew and drift, which NTP corrects only approximately, mean a later event can carry an earlier timestamp than an event it actually followed. Network delays and retries also mean events arrive in a different order than they were sent, so neither arrival time nor sender time reliably reflects causality. Two events produced concurrently on different machines have no true "before" relationship at all, and comparing their timestamps silently picks an arbitrary winner and can lose an update. That is why this simulation orders events by an explicit per-order **version (sequence) number**, a form of logical ordering like Lamport clocks, and uses monotonically increasing **fencing tokens** instead of wall-clock lease expiry to decide which worker may write.

## Design Explanation

- **Why pending events are needed:** An event that arrives early describes a state that builds on versions the processor has not seen yet. Applying version 3 (`SHIPPED`) before versions 1 and 2 would skip states and could later be overwritten by them. Holding it in `pending` keeps the event without losing it. As soon as the gap is filled, the processor drains `pending` in version order, so delivery order never affects the final state.
- **How duplicates are detected:** Each order tracks `last_applied_version`. Any event with `version <= last_applied_version` has already been applied, so it is ignored as a duplicate or stale replay. An event whose version is already in `pending` is also a duplicate. This single comparison also guarantees that an older event can never overwrite newer state.
- **How fencing tokens prevent stale workers from writing:** The lock service (`TokenIssuer`) gives every new lease a strictly larger token. The storage layer (`FencedOrderStore`) remembers the highest token it has accepted for each order and rejects any write whose token is not greater. A worker that paused and lost its lease still holds an old token, so its late write is rejected even though the worker believes it still owns the lock.
- **Assumptions:**
  - Versions start at 1 and increase by exactly 1 per order, and the producer assigns them correctly.
  - Events for different orders are independent.
  - Allowed statuses are `CREATED`, `PAID` and `SHIPPED`. The processor does not check which status belongs to which version; it trusts the version number.
  - An order's status is `UNKNOWN` until its version 1 is applied.
  - If a duplicate version arrives with different content, the first applied copy wins and the later one is ignored.
  - Following the assignment's rule, a write is accepted only if its token is **strictly greater** than the last accepted token. So in this simulation, each token authorizes a single write, and a second write with the same token is rejected.
  - The ordering processor and fencing store are isolated demonstrations because the assignment evaluates event ordering and stale-worker rejection as separate coordination scenarios; a production system would apply both protections to the same persistent order record.

## Limitations

This is an **in-memory educational simulation**:

- No durable storage. All state is lost when the process exits.
- No distributed consensus. The token issuer is a simple counter, not a replicated lock service such as ZooKeeper or etcd.
- No real network, so there is no real network failure recovery, timeouts or retransmission. Delivery order is scripted.
- Missing events are detected and reported, but they are never requested again. A pending event waits indefinitely, and there is no timeout or dead-letter handling.
- Single-threaded, so there is no real concurrency between workers. The race is simulated step by step.

## Assignment Requirements Checklist

**Event model**
- [x] Event contains `order_id`, `version` and `status`: `OrderEvent` in [src/order_simulation/models.py](src/order_simulation/models.py)
- [x] States move through `CREATED → PAID → SHIPPED`: `VALID_STATUSES` in [models.py](src/order_simulation/models.py)

**Out-of-order processing (`ORDER-1001`: v2, v1, v2 again)**
- [x] Version 2 is not applied while version 1 is missing: `OrderProcessor.receive` in [processor.py](src/order_simulation/processor.py); `test_version_2_before_version_1_is_held_as_pending`; scenario 1 in [run_demo.py](run_demo.py)
- [x] Version 2 is stored as pending: `OrderState.pending`; [Correct Event Ordering Evidence](#correct-event-ordering-evidence)
- [x] Version 1 is applied first, then pending version 2 is applied automatically: the drain loop in [processor.py](src/order_simulation/processor.py); `test_pending_version_is_applied_after_missing_version_arrives`
- [x] Duplicate version 2 is ignored: `test_duplicate_version_is_ignored_and_does_not_change_state`; [Duplicate Handling Evidence](#duplicate-handling-evidence)
- [x] An older event never overwrites newer state: `test_older_event_does_not_overwrite_newer_state`
- [x] Final status is `PAID` and final applied versions are `[1, 2]`: `test_full_assignment_sequence_final_status_and_history`; scenario 1 "Final result"

**Missing events (`ORDER-MISSING`: only v3 sent)**
- [x] The order does not jump to `SHIPPED` and the status stays `UNKNOWN`: `MissingEventTests` in [tests/test_order_processor.py](tests/test_order_processor.py); scenario 2 in [run_demo.py](run_demo.py)
- [x] Version 3 is recorded as pending: `test_later_version_remains_pending`; [Missing Event Evidence](#missing-event-evidence)
- [x] The missing versions are identified and the processor reports it is waiting for version 1: `missing_versions` and `waiting_for_version` in [models.py](src/order_simulation/models.py); `test_processor_reports_waiting_for_version_1`

**Stale worker and fencing tokens (`ORDER-FENCE`)**
- [x] Worker A gets token 1 and worker B gets token 2: `TokenIssuer` in [fencing.py](src/order_simulation/fencing.py); `test_workers_receive_tokens_1_and_2`
- [x] Worker B (newer token) is accepted: `test_newer_token_is_accepted`; scenario 3 in [run_demo.py](run_demo.py)
- [x] Worker A (stale token) is rejected with `StaleTokenError`: `FencedOrderStore.write` in [fencing.py](src/order_simulation/fencing.py); `test_older_token_is_rejected`
- [x] The rejection does not change state: `test_rejected_stale_worker_does_not_change_state`; [Stale Worker Evidence](#stale-worker-evidence)
- [x] Rule: a write is accepted only if its token is greater than the last accepted token: `token <= order.last_accepted_token` check in [fencing.py](src/order_simulation/fencing.py); `test_equal_token_is_rejected`

**Validation and tests**
- [x] Invalid versions (0, negative, non-integer) and unknown statuses are rejected with a clear error: `InvalidEventError` in [models.py](src/order_simulation/models.py); `InvalidEventTests`, `InvalidFencedWriteTests`
- [x] Automated tests pass with `python -m unittest discover -s tests -v` (32 tests): [tests/](tests/); [Automated Test Evidence](#automated-test-evidence)
- [x] Demo runs all three scenarios with PASS and status labels using `python run_demo.py`: [run_demo.py](run_demo.py)
- [x] Deterministic: no randomness, timestamps or network calls: [src/order_simulation/](src/order_simulation/)
- [x] Standard library only, no dependencies: [requirements.txt](requirements.txt)

**Documentation and evidence**
- [x] Overview, features, requirements and installation/run commands: the sections at the top of this README
- [x] Real terminal output of the demo and the tests: [evidence/terminal-output.txt](evidence/terminal-output.txt), explained in [evidence/README.md](evidence/README.md)
- [x] Reflection on why timestamps are not enough (5 sentences): [Reflection](#reflection)
- [x] Design explanation and assumptions: [Design Explanation](#design-explanation)
- [x] Limitations: [Limitations](#limitations)
