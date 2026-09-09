import os
import tempfile
import unittest

from app.core.models import RunContext
from app.identity import (
    IdentityService,
    InMemoryUserRepository,
    RunAccessDeniedError,
    RunAuthorizationService,
    SQLiteUserRepository,
    UserRole,
)


class M26IdentityTests(unittest.TestCase):
    def test_provision_and_authenticate(self):
        repository = InMemoryUserRepository()
        identity_service = IdentityService(repository)
        user = identity_service.provision_user(
            repository,
            username="alice",
            password="strong-test-password",
            role=UserRole.USER,
        )
        identity = identity_service.authenticate("alice", "strong-test-password")
        self.assertIsNotNone(identity)
        self.assertEqual(identity.user_id, user.user_id)
        self.assertEqual(identity.role, UserRole.USER)
        self.assertIsNone(identity_service.authenticate("alice", "wrong-password"))

    def test_admin_and_user_run_isolation(self):
        repository = InMemoryUserRepository()
        service = IdentityService(repository)
        user = service.provision_user(repository, username="alice", password="pass-12345")
        other = service.provision_user(repository, username="bob", password="pass-12345")
        admin = service.provision_user(
            repository, username="admin", password="pass-12345", role=UserRole.ADMIN
        )
        authz = RunAuthorizationService()
        context = RunContext(metadata=authz.owner_metadata(user and service.authenticate("alice", "pass-12345")))

        authz.require_access(service.authenticate("alice", "pass-12345"), context)
        with self.assertRaises(RunAccessDeniedError):
            authz.require_access(service.authenticate("bob", "pass-12345"), context)
        authz.require_access(service.authenticate("admin", "pass-12345"), context)

    def test_sqlite_identity_survives_repository_reopen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "users.db")
            repository = SQLiteUserRepository(path)
            user_service = IdentityService(repository)
            created = user_service.provision_user(
                repository, username="persistent", password="persistent-password", role=UserRole.ADMIN
            )

            reopened = SQLiteUserRepository(path)
            identity_service = IdentityService(reopened)
            identity = identity_service.authenticate("persistent", "persistent-password")
            self.assertIsNotNone(identity)
            self.assertEqual(identity.user_id, created.user_id)
            self.assertEqual(identity.role, UserRole.ADMIN)
            self.assertEqual(len(reopened.list_users()), 1)

    def test_environment_bootstrap_is_persisted_without_overwriting_existing_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "users.db")
            old = {key: os.environ.get(key) for key in (
                "UAR_AUTH_USERNAME", "UAR_AUTH_PASSWORD_HASH", "UAR_AUTH_ROLE"
            )}
            try:
                os.environ["UAR_AUTH_USERNAME"] = "bootstrap"
                from app.ui.auth import hash_password
                os.environ["UAR_AUTH_PASSWORD_HASH"] = hash_password("bootstrap-password")
                os.environ["UAR_AUTH_ROLE"] = "admin"

                repository = SQLiteUserRepository(path)
                service = IdentityService(repository)
                first = service.authenticate("bootstrap", "bootstrap-password")
                second = service.authenticate("bootstrap", "bootstrap-password")
                self.assertIsNotNone(first)
                self.assertEqual(first.user_id, second.user_id)
                self.assertEqual(first.role, UserRole.ADMIN)
                self.assertEqual(len(repository.list_users()), 1)
            finally:
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
