# M32 — Orchestration revision notes

M32 adds explicit revision records and durable session-backed history to the runtime recovery path. Architecture and final-result modification decisions are represented as revision requests rather than direct state mutations.

External cloud validation remains intentionally deferred.