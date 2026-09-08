import unittest

from app.core.states import WorkflowState
from app.intake.models import IngestStrategy, IntakeFile
from app.intake.service import IntakeService


class UniversalIntakeTests(unittest.TestCase):
    def setUp(self):
        self.service = IntakeService()

    def test_creates_intake_session_and_registers_objective(self):
        result = self.service.start_session("Build a useful report")
        self.assertTrue(result.run_id)
        self.assertEqual(result.objective, "Build a useful report")
        self.assertEqual(
            self.service.session_manager.get_context(result.run_id).state,
            WorkflowState.INTAKE,
        )
        messages = self.service.session_manager.snapshot(result.run_id).messages
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[0].content, "Build a useful report")

    def test_small_text_with_inline_content_uses_inline_strategy(self):
        file = IntakeFile(
            name="notes.txt",
            mime_type="text/plain",
            size_bytes=12,
            inline_text="hello world",
        )
        result = self.service.start_session("Review notes", files=[file])
        item = result.items[0]
        self.assertEqual(item.strategy, IngestStrategy.INLINE_TEXT)
        self.assertEqual(item.inline_text, "hello world")

    def test_multimodal_file_uses_remote_upload_strategy(self):
        file = IntakeFile(
            name="image.png",
            mime_type="image/png",
            size_bytes=1024,
            source_ref="upload-1",
        )
        result = self.service.start_session("Inspect image", files=[file])
        self.assertEqual(result.items[0].strategy, IngestStrategy.REMOTE_FILE_UPLOAD)

    def test_unknown_binary_is_not_falsely_interpreted(self):
        file = IntakeFile(name="data.bin", mime_type="application/octet-stream", size_bytes=64)
        result = self.service.start_session("Inspect binary", files=[file])
        self.assertEqual(result.items[0].strategy, IngestStrategy.BINARY_UNINTERPRETED)
        self.assertEqual(len(result.warnings), 1)

    def test_file_count_limit_is_enforced(self):
        self.service.settings.max_uploads_per_message = 1
        first = IntakeFile(name="a.txt", mime_type="text/plain")
        second = IntakeFile(name="b.txt", mime_type="text/plain")
        with self.assertRaises(ValueError):
            self.service.start_session("Too many", files=[first, second])

    def test_file_size_limit_is_enforced(self):
        oversized = IntakeFile(name="huge.bin", size_bytes=101 * 1024 * 1024)
        with self.assertRaises(ValueError):
            self.service.start_session("Too large", files=[oversized])

    def test_inline_text_requires_text_mime(self):
        invalid = IntakeFile(
            name="image.png",
            mime_type="image/png",
            inline_text="not actually image data",
        )
        with self.assertRaises(ValueError):
            invalid.validate(max_size_bytes=200 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
