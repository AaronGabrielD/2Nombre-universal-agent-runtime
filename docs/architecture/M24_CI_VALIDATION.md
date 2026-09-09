# M24 — Automated CI Validation

M24 establishes a reproducible GitHub Actions test gate for the runtime. The existing workflow executes the complete `unittest` suite on pushes and pull requests targeting `main`, using Python 3.11 and 3.12.

The suite includes unit, concurrency, tool-authorization, orchestration, HTTP integration, persistence, authentication, and execution-policy tests. The workflow installs the repository's declared runtime dependencies before running the suite.

M24 does not claim to validate a live Google Colab session or a live Gemini API call. Those remain a separate cloud-validation milestone because they require runtime credentials and external services.
