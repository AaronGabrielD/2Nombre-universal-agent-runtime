from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ChainlitConfigTests(unittest.TestCase):
    def test_canonical_config_is_under_chainlit_directory(self):
        config_path = ROOT / ".chainlit" / "config.toml"
        self.assertTrue(config_path.is_file())
        self.assertFalse((ROOT / "config.toml").exists())

        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["meta"]["generated_by"], "2.12.0")
        self.assertFalse(config["features"]["mcp"]["enabled"])
        self.assertFalse(config["features"]["audio"]["enabled"])
        self.assertEqual(config["features"]["spontaneous_file_upload"]["max_files"], 20)
        self.assertEqual(config["features"]["spontaneous_file_upload"]["max_size_mb"], 50)
        self.assertFalse(config["UI"]["unsafe_allow_html"])


if __name__ == "__main__":
    unittest.main()
