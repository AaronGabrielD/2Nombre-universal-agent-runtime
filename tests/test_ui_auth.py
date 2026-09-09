import os
import unittest

from app.ui.auth import authenticate_from_environment, hash_password, verify_password


class UIAuthTests(unittest.TestCase):
    def setUp(self):
        self._old = {
            key: os.environ.get(key)
            for key in ("UAR_AUTH_USERNAME", "UAR_AUTH_PASSWORD_HASH", "UAR_AUTH_ROLE")
        }

    def tearDown(self):
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_hash_and_verify_round_trip(self):
        encoded = hash_password("correct horse battery staple", salt=b"0123456789abcdef")
        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong", encoded))

    def test_environment_auth_rejects_missing_configuration(self):
        os.environ.pop("UAR_AUTH_USERNAME", None)
        os.environ.pop("UAR_AUTH_PASSWORD_HASH", None)
        self.assertIsNone(authenticate_from_environment("admin", "admin"))

    def test_environment_auth_returns_identity_for_matching_credentials(self):
        os.environ["UAR_AUTH_USERNAME"] = "admin"
        os.environ["UAR_AUTH_PASSWORD_HASH"] = hash_password("test-password", salt=b"fedcba9876543210")
        os.environ["UAR_AUTH_ROLE"] = "admin"
        identity = authenticate_from_environment("admin", "test-password")
        self.assertIsNotNone(identity)
        self.assertEqual(identity["identifier"], "admin")
        self.assertEqual(identity["metadata"]["role"], "admin")

    def test_environment_auth_rejects_wrong_password(self):
        os.environ["UAR_AUTH_USERNAME"] = "admin"
        os.environ["UAR_AUTH_PASSWORD_HASH"] = hash_password("test-password", salt=b"fedcba9876543210")
        self.assertIsNone(authenticate_from_environment("admin", "wrong"))


if __name__ == "__main__":
    unittest.main()
