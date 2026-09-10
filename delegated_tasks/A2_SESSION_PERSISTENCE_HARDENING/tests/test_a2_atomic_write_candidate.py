"""Candidate JSON atomic-publication regression.

The current implementation already uses os.replace(); this test documents the
expected invariant that a failed replacement must not destroy the last published
session file. It is not executed by this delegated audit agent.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.models import RunContext
from app.session.json_repository import JsonFileSessionRepository
from app.session.models import SessionRecord
from app.session.repository import SessionRepositoryError


class JsonAtomicWriteCandidateTests(unittest.TestCase):
    def test_replace_failure_preserves_previous_published_file(self):
        with tempfile.TemporaryDirectory() as root:
            repository = JsonFileSessionRepository(root)
            repository.create(SessionRecord(context=RunContext(run_id="run-a")))
            path = Path(root) / "run-a.json"
            before = path.read_bytes()

            record = repository.get("run-a")
            record.context.metadata["changed"] = "yes"
            with patch("app.session.json_repository.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(SessionRepositoryError):
                    repository.save(record)

            self.assertEqual(path.read_bytes(), before)
            self.assertFalse((Path(root) / "run-a.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
