# A2 patch integration policy

No production patch is applied by this delegated audit branch.

The authoritative implementation changes are specified in `../PROPOSED_CHANGES.md`. The candidate tests under `../tests/` target the expected post-hardening behavior.

A unified patch is intentionally not generated here because this audit agent does not have a local checkout from which to produce and validate an exact `git diff` against the audited commit. The project lead should generate/apply the patch from the reviewed `main` baseline so the diff is exact and independently validated.
