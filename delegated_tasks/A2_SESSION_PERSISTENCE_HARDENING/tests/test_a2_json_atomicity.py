"""Candidate regression for JSON atomic publication behavior."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.models import RunContext
from app.session.json_repository import JsonFileSessionRepository
from app.session.models import SessionRecord
from app.session.repository import SessionRepositoryError


class JsonAtomicityTests(unittest.TestCase):
    def test_replace_failure_preserves_previous_published_record(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            repository.create(SessionRecord(context=RunContext(run_id="run-a")))
            path = Path(root) / "run-a.json"
            before = path.read_text(encoding="utf-8")

            record = repository.get("run-a")
            record.context.metadata["changed"] = "yes"
            with patch("app.session.json_repository.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(SessionRepositoryError):
                    repository.save(record)

            self.assertEqual(path.read_text(encoding="utf-8"), before)
            self.assertFalse(any(item.suffix == ".tmp" for item in Path(root).iterdir()))


if __name__ == "__main__":
    unittest.main()
