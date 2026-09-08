# M03 — Gemini Adapter

## Boundary

M03 encapsulates communication with Google's Gemini API behind the provider-neutral `LLMProvider` contract.

It is responsible for:

- selecting the requested model supplied by orchestration/configuration
- constructing the official `google-genai` client lazily
- sending generation requests
- normalizing provider responses
- exposing basic token usage metadata when supplied by the provider
- retrying transient failures with bounded exponential backoff
- converting SDK/provider failures into `GeminiAdapterError`

M03 does not create CrewAI agents, manage Chainlit UI, store sessions, ingest files, or execute arbitrary code.

## Provider-neutral API

`GenerationRequest` contains the model, contents and optional generation controls.

`GenerationResponse` contains the provider, model, generated text, optional response identifier and normalized usage counters.

`GeminiAdapter` implements:

```python
adapter.generate(request) -> GenerationResponse
```

## SDK policy

The adapter uses the official `google-genai` Python SDK and keeps the SDK import lazy. This means unit tests can run with a fake client and the rest of the runtime does not need to import the provider until an actual Gemini request is made.

The model is never hardcoded by the adapter. M00 configuration supplies role-specific model names, allowing the runtime to change models without modifying M03.

## Reliability

Transient provider failures such as rate limiting, temporary unavailability and timeouts are retried up to three total attempts. Permanent validation/client failures are not retried.

The adapter never logs or includes the API key in normalized errors.

## Free-tier strategy

The default model configured by M00 remains `gemini-3.5-flash` to preserve the project's $0-first approach. Newer models can be selected through environment variables when their availability/cost is appropriate.

## Acceptance criteria

- A valid request reaches the configured provider client.
- Provider output is normalized into `GenerationResponse`.
- Usage metadata is copied when present.
- Empty requests are rejected before provider calls.
- Transient failures are retried with bounded backoff.
- Permanent failures are not retried.
- API-key absence is only enforced when the adapter must construct its own client.
- Unit tests do not require a live Gemini API call.
