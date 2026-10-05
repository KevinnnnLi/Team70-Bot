import unittest

from roostoo import signing


class SigningPayloadTests(unittest.TestCase):
    def test_sorts_keys_and_coerces_values_to_strings(self):
        payload = signing.signing_payload(
            {"timestamp": 1700000000000, "pair": "BTC/USD"}
        )
        self.assertEqual(payload, "pair=BTC/USD&timestamp=1700000000000")

    def test_float_values_use_plain_python_string_form(self):
        payload = signing.signing_payload({"quantity": 0.5, "timestamp": 1})
        self.assertEqual(payload, "quantity=0.5&timestamp=1")

    def test_empty_params_yield_empty_payload(self):
        self.assertEqual(signing.signing_payload({}), "")


class SignTests(unittest.TestCase):
    """Digests cross-checked against .NET HMACSHA256, not this module."""

    def test_pair_order_request_vector(self):
        digest = signing.sign(
            "abc123", {"pair": "BTC/USD", "timestamp": 1700000000000}
        )
        self.assertEqual(
            digest,
            "fed9c79b86c6055998460d3cc54a0cddfb2848c955b31cd0b5cd755a08f72e28",
        )

    def test_short_open_vector(self):
        digest = signing.sign(
            "s3cr3t",
            {
                "collateral": "1000.00",
                "pair": "BTC/USD",
                "timestamp": 1700000000000,
            },
        )
        self.assertEqual(
            digest,
            "9ee470df11a4bf5d913a30a45ecab20b53dc476ce9fe0942036340813d49dfd6",
        )

    def test_order_vector_with_mixed_value_types(self):
        digest = signing.sign(
            "k",
            {
                "quantity": "0.00123000",
                "side": "BUY",
                "timestamp": 1,
                "type": "MARKET",
            },
        )
        self.assertEqual(
            digest,
            "b3b9c50cd8dfa20d5b176fbd9818194d1bf6edd9d07cfe46ea1ce0c6eb34486d",
        )

    def test_signature_is_lowercase_hex(self):
        digest = signing.sign("k", {"timestamp": 1})
        self.assertEqual(digest, digest.lower())
        self.assertEqual(len(digest), 64)


class TimestampTests(unittest.TestCase):
    def test_offset_is_server_minus_local(self):
        self.assertEqual(
            signing.timestamp_offset(server_time_ms=1_000_500, local_time_ms=1_000_000),
            500,
        )

    def test_signed_timestamp_applies_offset(self):
        self.assertEqual(
            signing.signed_timestamp(local_time_ms=1_000_000, offset_ms=500),
            1_000_500,
        )

    def test_offset_clamped_when_small_noise(self):
        # Sub-second noise is not worth "correcting"; keep the raw offset.
        self.assertEqual(
            signing.timestamp_offset(server_time_ms=1_000_400, local_time_ms=1_000_000),
            400,
        )


class TimestampErrorTests(unittest.TestCase):
    def test_detects_timestamp_errors(self):
        for message in [
            "timestamp expired",
            "invalid timestamp",
            "Timestamp is not valid",
            "request time is out of range",
        ]:
            with self.subTest(message=message):
                self.assertTrue(signing.is_timestamp_error(message))

    def test_ignores_unrelated_errors(self):
        for message in ["insufficient balance", "pair not found", ""]:
            with self.subTest(message=message):
                self.assertFalse(signing.is_timestamp_error(message))


if __name__ == "__main__":
    unittest.main()
