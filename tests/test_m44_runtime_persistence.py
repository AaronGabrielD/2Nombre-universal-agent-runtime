import os
import tempfile
import unittest
from unittest.mock import patch

from app.runtime.persistence import (
    RuntimePersistenceConfig,
    RuntimePersistenceError,
    build_session_repository,
    persistence_config_from_environment,
)
from app.session.json_repository import JsonFileSessionRepository
from app.session.repository import InMemorySessionRepository, SQLiteSessionRepository


class M44RuntimePersistenceTests(unittest.TestCase):
    def test_memory_is_default(self):
        with patch.dict(os.environ, {}, clear=True):
            config = persistence_config_from_environment()
        self.assertEqual(config.backend, "memory")
        self.assertIsNone(config.location)
        self.assertIsInstance(build_session_repository(config), InMemorySessionRepository)

    def test_json_repository_is_selected_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            config = RuntimePersistenceConfig(backend="json", location=directory)
            self.assertIsInstance(build_session_repository(config), JsonFileSessionRepository)

    def test_sqlite_repository_is_selected_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, "sessions.db")
            config = RuntimePersistenceConfig(backend="sqlite", location=database)
            self.assertIsInstance(build_session_repository(config), SQLiteSessionRepository)

    def test_non_memory_requires_location(self):
        with self.assertRaises(RuntimePersistenceError):
            RuntimePersistenceConfig(backend="json").validate()
        with self.assertRaises(RuntimePersistenceError):
            RuntimePersistenceConfig(backend="sqlite", location="").validate()

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(RuntimePersistenceError):
            RuntimePersistenceConfig(backend="redis", location="runtime").validate()

    def test_environment_selects_json_path(self):
        with patch.dict(
            os.environ,
            {"UAR_SESSION_REPOSITORY": "json", "UAR_SESSION_REPOSITORY_PATH": "/tmp/uar-tests"},
            clear=True,
        ):
            config = persistence_config_from_environment()
        self.assertEqual(config.backend, "json")
        self.assertEqual(config.location, "/tmp/uar-tests")


if __name__ == "__main__":
    unittest.main()
