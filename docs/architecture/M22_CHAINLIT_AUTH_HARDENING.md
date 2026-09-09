# M22 — Chainlit Authentication Hardening

M22 makes the Chainlit presentation layer explicitly authenticated through Chainlit's password callback mechanism. Chainlit authentication uses `CHAINLIT_AUTH_SECRET`, while application credentials are supplied only through environment variables.

The password verifier uses PBKDF2-HMAC-SHA256 from the Python standard library. Password records contain the algorithm, iteration count, salt, and derived key; plaintext passwords are never stored in the repository.

Configured identity metadata includes a stable identifier and a role. The identifier is available through Chainlit's user session and is used by the existing runtime approval actor helper.

This is a low-dependency bootstrap authentication mechanism, not a full multi-user identity platform. A future production milestone may replace the environment-backed account with an external identity provider or durable user store without changing the UI/runtime boundary.

Chainlit's current authentication documentation states that applications are public by default and require `CHAINLIT_AUTH_SECRET` plus an authentication callback to become private. citeturn628686search2turn628686search0
