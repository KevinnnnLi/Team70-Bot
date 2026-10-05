import unittest

from bot import main, parse_args


class ArgumentTests(unittest.TestCase):
    def test_defaults_to_the_live_loop(self):
        args = parse_args([])
        self.assertFalse(args.check)
        self.assertFalse(args.dry_run)
        self.assertFalse(args.once)

    def test_check_flag(self):
        self.assertTrue(parse_args(["--check"]).check)

    def test_version_exits_cleanly(self):
        with self.assertRaises(SystemExit) as caught:
            parse_args(["--version"])
        self.assertEqual(caught.exception.code, 0)


class MainTests(unittest.TestCase):
    def test_missing_credentials_exit_with_code_2(self):
        self.assertEqual(main(["--check"], env={}), 2)

    def test_missing_api_key_only_exits_with_code_2(self):
        self.assertEqual(
            main(["--check"], env={"ROOSTOO_SECRET_KEY": "secret"}), 2
        )


if __name__ == "__main__":
    unittest.main()
