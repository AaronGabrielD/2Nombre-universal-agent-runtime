# M02 — Universal Intake

## Boundary

M02 owns the normalization of a user's objective and uploaded-file metadata before architectural reasoning begins.
It decides an ingestion strategy but does not parse documents, call Gemini, execute code, or solve the objective.

## Input

`IntakeFile` accepts:

- display name
- MIME type when known
- declared size in bytes
- an opaque source reference owned by the caller
- optional inline text for small text inputs

The service enforces the global upload-count and upload-size limits from M00 configuration.

## Strategies

| Strategy | Meaning |
|---|---|
| `inline_text` | Small text is already available to the runtime without another file transfer. |
| `remote_file_upload` | The input should be passed to a file-capable adapter (for example a future Gemini Files adapter). |
| `local_parser` | A later registered parser should interpret the text locally. |
| `binary_uninterpreted` | No safe interpretation strategy is selected yet; the raw input remains opaque. |

The strategy enum intentionally remains provider-neutral. Provider-specific mappings belong to adapter modules.

## Session integration

`IntakeService.start_session()` creates a unique M01 session, moves it from `IDLE` to `INTAKE`, stores the objective, and registers each uploaded file as an `ArtifactRef`.

Every file and decision remains scoped to the generated `run_id`.

## Security rules

1. File names and MIME types are metadata, not instructions.
2. Unknown binaries are never guessed or interpreted automatically.
3. Inline text is accepted only with a `text/*` MIME type.
4. Upload limits are enforced before session intake is created.
5. Opaque source references are stored as references; M02 does not fetch arbitrary URLs.
6. No API key, credential, or secret is accepted as intake content by special convention.

## Acceptance criteria

- A valid objective creates a new session in `INTAKE`.
- Every uploaded file receives a stable intake identifier and is registered with M01.
- Small inline text selects `inline_text`.
- Known document/multimedia inputs select `remote_file_upload`.
- Unknown binary input remains `binary_uninterpreted` and produces a warning.
- Upload count and size limits are enforced.
- Invalid inline-text MIME combinations are rejected.
- M02 remains independent of Gemini, CrewAI, Chainlit, and execution backends.
