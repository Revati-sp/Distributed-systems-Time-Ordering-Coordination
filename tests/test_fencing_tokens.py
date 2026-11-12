"""Tests for fencing-token protection against stale workers."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from order_simulation import (  # noqa: E402
    InvalidEventError,
    FencedOrderStore,
    StaleTokenError,
    TokenIssuer,
)


class TokenIssuerTests(unittest.TestCase):
    def test_tokens_are_strictly_increasing(self):
        issuer = TokenIssuer()
        self.assertEqual([issuer.issue() for _ in range(3)], [1, 2, 3])


class StaleWorkerTests(unittest.TestCase):
    def setUp(self):
        issuer = TokenIssuer()
        self.token_a = issuer.issue()  # worker A: token 1
        self.token_b = issuer.issue()  # worker B: token 2
        self.store = FencedOrderStore()
        self.order_id = "ORDER-FENCE"

    def test_workers_receive_tokens_1_and_2(self):
        self.assertEqual((self.token_a, self.token_b), (1, 2))

    def test_newer_token_is_accepted(self):
        write = self.store.write(self.order_id, "worker-B", self.token_b, "SHIPPED")
        order = self.store.get(self.order_id)

        self.assertEqual(write.token, 2)
        self.assertEqual(write.previous_token, 0)
        self.assertEqual(order.status, "SHIPPED")
        self.assertEqual(order.last_accepted_token, 2)

    def test_older_token_is_rejected(self):
        self.store.write(self.order_id, "worker-B", self.token_b, "SHIPPED")

        with self.assertRaises(StaleTokenError) as ctx:
            self.store.write(self.order_id, "worker-A", self.token_a, "PAID")

        error = ctx.exception
        self.assertEqual(error.worker, "worker-A")
        self.assertEqual(error.token, 1)
        self.assertEqual(error.last_accepted_token, 2)
        self.assertIn("REJECTED STALE WORKER", str(error))

    def test_rejected_stale_worker_does_not_change_state(self):
        self.store.write(self.order_id, "worker-B", self.token_b, "SHIPPED")
        order = self.store.get(self.order_id)
        writes_before = list(order.accepted_writes)

        with self.assertRaises(StaleTokenError):
            self.store.write(self.order_id, "worker-A", self.token_a, "PAID")

        self.assertEqual(order.status, "SHIPPED")
        self.assertEqual(order.last_accepted_token, 2)
        self.assertEqual(order.accepted_writes, writes_before)

    def test_equal_token_is_rejected(self):
        self.store.write(self.order_id, "worker-B", self.token_b, "PAID")
        with self.assertRaises(StaleTokenError):
            self.store.write(self.order_id, "worker-X", self.token_b, "SHIPPED")
        self.assertEqual(self.store.get(self.order_id).status, "PAID")

    def test_increasing_tokens_are_all_accepted(self):
        self.store.write(self.order_id, "worker-A", self.token_a, "CREATED")
        self.store.write(self.order_id, "worker-B", self.token_b, "PAID")
        order = self.store.get(self.order_id)

        self.assertEqual(order.status, "PAID")
        self.assertEqual([w.token for w in order.accepted_writes], [1, 2])

    def test_tokens_are_tracked_per_order(self):
        self.store.write(self.order_id, "worker-B", self.token_b, "SHIPPED")
        self.store.write("ORDER-OTHER", "worker-A", self.token_a, "CREATED")

        self.assertEqual(self.store.get("ORDER-OTHER").last_accepted_token, 1)
        self.assertEqual(self.store.get(self.order_id).last_accepted_token, 2)


class InvalidFencedWriteTests(unittest.TestCase):
    def test_invalid_tokens_are_rejected(self):
        store = FencedOrderStore()
        for bad_token in [0, -1, "2", None, True]:
            with self.subTest(token=bad_token):
                with self.assertRaises(ValueError):
                    store.write("ORDER-FENCE", "worker-A", bad_token, "PAID")

    def test_invalid_status_is_rejected_without_creating_state(self):
        store = FencedOrderStore()
        with self.assertRaises(InvalidEventError):
            store.write("ORDER-FENCE", "worker-A", 1, "LOST")
        with self.assertRaises(KeyError):
            store.get("ORDER-FENCE")


if __name__ == "__main__":
    unittest.main()
