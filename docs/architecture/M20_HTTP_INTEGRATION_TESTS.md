# M20 — HTTP Integration Tests

M20 validates the real HTTP contract between M08 `ColabExecutionBackend` and M12 `RuntimeColabHTTPServer` without a real Google Colab session or an external provider.

The test starts the actual M12 HTTP server on loopback, points the actual M08 client at it, and verifies the request/response contract, bearer authentication, network admission policy, and artifact retrieval.

The execution used by the test is a controlled Python fixture (`print` and creation of a small text artifact). No shell command or external network access is used.

These tests are intended to run in CI or a local development environment with the repository dependencies installed. The GitHub connector used in this development session does not provide a Python test runner, so no execution result is claimed here.
