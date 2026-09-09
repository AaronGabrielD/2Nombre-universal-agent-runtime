import unittest
from unittest.mock import patch

from scripts.m29_cloud_smoke import main


class M29SmokeTests(unittest.TestCase):
    def test_requires_base_url_and_token(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(main(), 2)

    def test_rejects_invalid_timeout(self):
        with patch.dict(
            "os.environ",
            {"UAR_SMOKE_BASE_URL": "https://example.invalid", "RUNTIME_EXECUTION_TOKEN": "secret"},
            clear=True,
        ):
            with patch("sys.argv", ["m29_cloud_smoke.py", "--timeout", "0"]):
                self.assertEqual(main(), 2)


if __name__ == "__main__":
    unittest.main()
