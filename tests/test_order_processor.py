"""Tests for versioned event ordering, pending events and duplicates."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from order_simulation import (  # noqa: E402
    UNKNOWN_STATUS,
    InvalidEventError,
    OrderEvent,
    OrderProcessor,
    Outcome,
)


class OutOfOrderDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.processor = OrderProcessor()
        self.order_id = "ORDER-1001"

    def receive(self, version, status):
        return self.processor.receive(OrderEvent(self.order_id, version, status))

    def test_version_2_before_version_1_is_held_as_pending(self):
        result = self.receive(2, "PAID")
        state = self.processor.get_state(self.order_id)

        self.assertIs(result.outcome, Outcome.PENDING)
        self.assertEqual(result.message, "version 2 is pending because version 1 is missing")
        self.assertEqual(result.waiting_for, 1)
        self.assertEqual(state.current_status, UNKNOWN_STATUS)
        self.assertEqual(state.last_applied_version, 0)
        self.assertEqual(state.pending_versions, [2])
        self.assertEqual(state.applied_versions, [])

    def test_pending_version_is_applied_after_missing_version_arrives(self):
        self.receive(2, "PAID")
        result = self.receive(1, "CREATED")
        state = self.processor.get_state(self.order_id)

        self.assertIs(result.outcome, Outcome.APPLIED)
        self.assertEqual([e.version for e in result.released], [2])
        self.assertEqual(state.applied_versions, [1, 2])
        self.assertEqual(state.pending_versions, [])
        self.assertEqual(state.current_status, "PAID")

    def test_duplicate_version_is_ignored_and_does_not_change_state(self):
        self.receive(2, "PAID")
        self.receive(1, "CREATED")
        result = self.receive(2, "PAID")
        state = self.processor.get_state(self.order_id)

        self.assertIs(result.outcome, Outcome.IGNORED_DUPLICATE)
        self.assertEqual(state.current_status, "PAID")
        self.assertEqual(state.last_applied_version, 2)
        self.assertEqual(state.applied_versions, [1, 2])
        self.assertEqual([e.version for e in state.ignored_duplicates], [2])

    def test_full_assignment_sequence_final_status_and_history(self):
        outcomes = [
            self.receive(2, "PAID").outcome,
            self.receive(1, "CREATED").outcome,
            self.receive(2, "PAID").outcome,
        ]
        state = self.processor.get_state(self.order_id)

        self.assertEqual(
            outcomes, [Outcome.PENDING, Outcome.APPLIED, Outcome.IGNORED_DUPLICATE]
        )
        self.assertEqual(state.current_status, "PAID")
        self.assertEqual(state.applied_versions, [1, 2])
        self.assertEqual(
            [(e.version, e.status) for e in state.applied_history],
            [(1, "CREATED"), (2, "PAID")],
        )

    def test_older_event_does_not_overwrite_newer_state(self):
        self.receive(1, "CREATED")
        self.receive(2, "PAID")
        self.receive(3, "SHIPPED")
        result = self.receive(1, "CREATED")
        state = self.processor.get_state(self.order_id)

        self.assertIs(result.outcome, Outcome.IGNORED_DUPLICATE)
        self.assertEqual(state.current_status, "SHIPPED")
        self.assertEqual(state.last_applied_version, 3)
        self.assertEqual(state.applied_versions, [1, 2, 3])

    def test_multiple_pending_versions_drain_in_order(self):
        self.assertIs(self.receive(3, "SHIPPED").outcome, Outcome.PENDING)
        self.assertIs(self.receive(2, "PAID").outcome, Outcome.PENDING)
        result = self.receive(1, "CREATED")
        state = self.processor.get_state(self.order_id)

        self.assertEqual([e.version for e in result.released], [2, 3])
        self.assertEqual(state.applied_versions, [1, 2, 3])
        self.assertEqual(state.current_status, "SHIPPED")
        self.assertEqual(state.pending_versions, [])

    def test_duplicate_of_pending_event_is_ignored(self):
        self.receive(2, "PAID")
        result = self.receive(2, "PAID")
        state = self.processor.get_state(self.order_id)

        self.assertIs(result.outcome, Outcome.IGNORED_DUPLICATE)
        self.assertEqual(state.pending_versions, [2])
        self.assertEqual(state.current_status, UNKNOWN_STATUS)

    def test_in_order_delivery_applies_immediately(self):
        for version, status in [(1, "CREATED"), (2, "PAID"), (3, "SHIPPED")]:
            result = self.receive(version, status)
            self.assertIs(result.outcome, Outcome.APPLIED)
            self.assertEqual(result.released, [])
        self.assertEqual(self.processor.get_state(self.order_id).current_status, "SHIPPED")

    def test_orders_are_tracked_independently(self):
        self.receive(1, "CREATED")
        other = self.processor.receive(OrderEvent("ORDER-OTHER", 2, "PAID"))

        self.assertIs(other.outcome, Outcome.PENDING)
        self.assertEqual(self.processor.get_state(self.order_id).current_status, "CREATED")
        self.assertEqual(self.processor.get_state("ORDER-OTHER").current_status, UNKNOWN_STATUS)


class MissingEventTests(unittest.TestCase):
    def setUp(self):
        self.processor = OrderProcessor()
        self.result = self.processor.receive(OrderEvent("ORDER-MISSING", 3, "SHIPPED"))
        self.state = self.processor.get_state("ORDER-MISSING")

    def test_later_version_is_not_applied(self):
        self.assertIs(self.result.outcome, Outcome.PENDING)
        self.assertEqual(self.state.applied_versions, [])

    def test_order_does_not_jump_to_shipped(self):
        self.assertNotEqual(self.state.current_status, "SHIPPED")
        self.assertEqual(self.state.current_status, UNKNOWN_STATUS)

    def test_later_version_remains_pending(self):
        self.assertEqual(self.state.pending_versions, [3])

    def test_missing_versions_are_identified(self):
        self.assertEqual(self.state.missing_versions, [1, 2])
        self.assertEqual(
            self.result.message, "version 3 is pending because versions 1 and 2 are missing"
        )

    def test_processor_reports_waiting_for_version_1(self):
        self.assertEqual(self.result.waiting_for, 1)
        self.assertEqual(self.state.waiting_for_version, 1)
        self.assertEqual(self.state.next_expected_version, 1)

    def test_filling_part_of_the_gap_still_waits(self):
        self.processor.receive(OrderEvent("ORDER-MISSING", 1, "CREATED"))

        self.assertEqual(self.state.current_status, "CREATED")
        self.assertEqual(self.state.pending_versions, [3])
        self.assertEqual(self.state.missing_versions, [2])
        self.assertEqual(self.state.waiting_for_version, 2)


class InvalidEventTests(unittest.TestCase):
    def test_version_zero_is_rejected(self):
        with self.assertRaises(InvalidEventError):
            OrderEvent("ORDER-1", 0, "CREATED")

    def test_negative_version_is_rejected(self):
        with self.assertRaises(InvalidEventError):
            OrderEvent("ORDER-1", -1, "CREATED")

    def test_non_integer_version_is_rejected(self):
        for bad_version in ["1", 1.0, None, True]:
            with self.subTest(version=bad_version):
                with self.assertRaises(InvalidEventError):
                    OrderEvent("ORDER-1", bad_version, "CREATED")

    def test_unknown_status_is_rejected(self):
        for bad_status in ["DELIVERED", "paid", "", None]:
            with self.subTest(status=bad_status):
                with self.assertRaises(InvalidEventError) as ctx:
                    OrderEvent("ORDER-1", 1, bad_status)
                self.assertIn("Invalid status", str(ctx.exception))

    def test_empty_order_id_is_rejected(self):
        for bad_id in ["", "   ", None, 123]:
            with self.subTest(order_id=bad_id):
                with self.assertRaises(InvalidEventError):
                    OrderEvent(bad_id, 1, "CREATED")

    def test_processor_rejects_non_event_input(self):
        with self.assertRaises(TypeError):
            OrderProcessor().receive({"order_id": "ORDER-1", "version": 1, "status": "CREATED"})

    def test_unknown_order_lookup_raises_key_error(self):
        with self.assertRaises(KeyError):
            OrderProcessor().get_state("NOPE")


if __name__ == "__main__":
    unittest.main()
