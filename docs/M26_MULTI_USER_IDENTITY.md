# M26 — Multi-user durable identity and authorization

M26 turns the M22 single bootstrap account into a durable identity boundary for multiple users while keeping the implementation provider-neutral and standard-library based.

## Identity model

Each user has:

- a stable `user_id`;
- a unique normalized username;
- a PBKDF2-SHA256 password record;
- an explicit `user` or `admin` role;
- an enabled flag;
- creation and update timestamps.

Plaintext passwords are never persisted. The existing M22 password hash format is reused.

## Durable repository

`SQLiteUserRepository` stores explicit identity columns in a SQLite database. Unlike the M21 session repository, identity records are not serialized with `pickle`.

Configure the database with:

```text
UAR_IDENTITY_DB_PATH=runtime_users.db
```

Local identity database files are excluded from source control by `.gitignore`.

## Bootstrap compatibility

The M22 environment variables remain useful for first-time provisioning:

```text
UAR_AUTH_USERNAME=
UAR_AUTH_PASSWORD_HASH=
UAR_AUTH_ROLE=user
```

When the configured username is not yet present in the identity database, the first successful authentication persists it. An existing database record is never silently overwritten by the environment configuration.

## Run authorization

Chainlit attaches `owner_user_id` and `owner_username` to every new runtime session. `RunAuthorizationService` enforces:

- normal users → only their own runs;
- administrators → cross-user run access.

The ownership check runs before gate actions are applied, so knowing another run's identifier is not sufficient for a normal user to operate it.

## Scope boundary

M26 establishes application-level identity and authorization. It is not a replacement for transport security, an external identity provider, OS-level isolation, or a hardened multi-tenant database service. Those remain future deployment concerns.
