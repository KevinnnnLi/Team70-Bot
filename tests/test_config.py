import unittest
from pathlib import Path

from roostoo.config import ConfigError, load_config


class LoadConfigTests(unittest.TestCase):
    def test_refuses_to_start_without_an_api_key(self):
        with self.assertRaises(ConfigError):
            load_config({"ROOSTOO_SECRET_KEY": "secret"})

    def test_refuses_to_start_without_a_secret(self):
        with self.assertRaises(ConfigError):
            load_config({"ROOSTOO_API_KEY": "key"})

    def test_refuses_whitespace_only_credentials(self):
        with self.assertRaises(ConfigError):
            load_config(
                {"ROOSTOO_API_KEY": "   ", "ROOSTOO_SECRET_KEY": "secret"}
            )

    def test_defaults_base_url_to_the_mock_api(self):
        config = load_config(
            {"ROOSTOO_API_KEY": "key", "ROOSTOO_SECRET_KEY": "secret"}
        )
        self.assertEqual(config.base_url, "https://mock-api.roostoo.com")

    def test_strips_a_trailing_slash_from_base_url(self):
        config = load_config(
            {
                "ROOSTOO_API_KEY": "key",
                "ROOSTOO_SECRET_KEY": "secret",
                "ROOSTOO_BASE_URL": "https://example.test/",
            }
        )
        self.assertEqual(config.base_url, "https://example.test")

    def test_strategy_parameters_are_fixed_by_the_spec(self):
        config = load_config(
            {"ROOSTOO_API_KEY": "key", "ROOSTOO_SECRET_KEY": "secret"}
        )
        self.assertEqual(config.loop_seconds, 300)
        self.assertAlmostEqual(config.max_drawdown, 0.20)
        self.assertAlmostEqual(config.taker_fee, 0.001)
        self.assertAlmostEqual(config.dust_usd, 75.0)

    def test_binance_base_url_defaults_to_binance(self):
        config = load_config(
            {"ROOSTOO_API_KEY": "key", "ROOSTOO_SECRET_KEY": "secret"}
        )
        self.assertEqual(config.binance_base_url, "https://api.binance.com")

    def test_state_and_log_paths_are_overridable(self):
        config = load_config(
            {
                "ROOSTOO_API_KEY": "key",
                "ROOSTOO_SECRET_KEY": "secret",
                "ROOSTOO_STATE_PATH": "/tmp/x/state.json",
                "ROOSTOO_LOG_DIR": "/tmp/x/logs",
            }
        )
        self.assertEqual(str(config.state_path), str(Path("/tmp/x/state.json")))
        self.assertEqual(str(config.log_dir), str(Path("/tmp/x/logs")))


if __name__ == "__main__":
    unittest.main()
