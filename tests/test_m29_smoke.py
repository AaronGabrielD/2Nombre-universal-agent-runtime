import unittest

from scripts.m29_cloud_smoke import main


class M29SmokeTests(unittest.TestCase):
    def test_requires_base_url_and_token(self):
        self.assertEqual(main([]), 2)

    def test_rejects_invalid_timeout(self):
        self.assertEqual(
            main(["--base-url", "https://example.invalid", "--token", "secret", "--timeout", "0"]),
            2,
        )


if __name__ == "__main__":
    unittest.main()
