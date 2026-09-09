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
from app.ui.auth import hash_password


class M26IdentityTests(unittest.TestCase):
    def test_provision_and_authenticate(self):
        repository = InMemoryUserRepository()
        identity_service = IdentityService(repository)
        user = identity_service.provision_user(
            repository, username="alice", password="strong-test-password", role=UserRole.USER
        )
        identity = identity_service.authenticate("alice", "strong-test-password")
        self.assertIsNotNone(identity)
        self.assertEqual(identity.user_id, user.user_id)
        self.assertEqual(identity.role, UserRole.USER)
        self.assertIsNone(identity_service.authenticate("alice", "wrong-password"))

    def test_admin_and_user_run_isolation(self):
        repository = InMemoryUserRepository()
        service = IdentityService(repository)
        service.provision_user(repository, username="alice", password="pass-12345")
        service.provision_user(repository, username="bob", password="pass-12345")
        service.provision_user(repository, username="admin", password="pass-12345", role=UserRole.ADMIN)
        authz = RunAuthorizationService()
        alice = service.authenticate("alice", "pass-12345")
        bob = service.authenticate("bob", "pass-12345")
        admin = service.authenticate("admin", "pass-12345")
        self.assertIsNotNone(alice)
        self.assertIsNotNone(bob)
        self.assertIsNotNone(admin)

        context = RunContext(metadata=authz.owner_metadata(alice))
        authz.require_access(alice, context)
        with self.assertRaises(RunAccessDeniedError):
            authz.require_access(bob, context)
        authz.require_access(admin, context)

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

    def test_environment_bootstrap_requires_valid_password_and_is_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "users.db")
            old = {key: os.environ.get(key) for key in (
                "UAR_AUTH_USERNAME", "UAR_AUTH_PASSWORD_HASH", "UAR_AUTH_ROLE"
            )}
            try:
                os.environ["UAR_AUTH_USERNAME"] = "bootstrap"
                os.environ["UAR_AUTH_PASSWORD_HASH"] = hash_password("bootstrap-password")
                os.environ["UAR_AUTH_ROLE"] = "admin"

                repository = SQLiteUserRepository(path)
                service = IdentityService(repository)
                self.assertIsNone(service.authenticate("bootstrap", "wrong-password"))
                self.assertEqual(len(repository.list_users()), 0)

                first = service.authenticate("bootstrap", "bootstrap-password")
                second = service.authenticate("bootstrap", "bootstrap-password")
                self.assertIsNotNone(first)
                self.assertIsNotNone(second)
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
