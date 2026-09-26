## 1. Provider Configuration and Factory

- [x] 1.1 Add Figura-owned provider IDs and a fixed allowlist mapping `qwen`, `deepseek`, and `mimo` to their selected model IDs.
- [x] 1.2 Resolve provider credentials, base URLs, timeout, and thinking options from `FIGURA_*` settings; require Qwen's regional base URL and support a configured MiMo Token Plan URL/key pair.
- [x] 1.3 Add configuration-only availability results and a factory that requires an explicit provider selection and never infers or falls back to another provider.
- [x] 1.4 Document the provider environment variables in `.env.example` without adding real credentials.

## 2. Provider Request and Response Contracts

- [x] 2.1 Define typed in-memory request options, instruction blocks, ordered conversation messages, text/image content blocks, function schemas, and tool replies.
- [x] 2.2 Define normalized tool calls, provider responses, bounded usage metadata, finish reasons, and provider-private continuation payloads.
- [x] 2.3 Define bounded provider failure categories that distinguish definitive rejection from unknown remote outcome and exclude raw SDK/provider bodies.

## 3. Provider Request and Response Adapters

- [x] 3.1 Implement the Qwen `qwen3.8-flash` policy for instruction/message mapping, image encoding, tool schema compatibility, thinking options, and continuation replay.
- [x] 3.2 Implement the DeepSeek `deepseek-flash` policy for instruction/message mapping, image encoding, tool schema compatibility, thinking options, and required `reasoning_content` replay.
- [x] 3.3 Implement the MiMo `mimo-v2.6-flash` policy for instruction/message mapping, Base64 images, function tools, thinking toggle, and private continuation replay.
- [x] 3.4 Reject unsupported message content or tool schemas explicitly; do not weaken schema constraints or expose provider-specific options to callers.

## 4. Transport, Streaming, and Failure Behavior

- [x] 4.1 Configure the shared OpenAI SDK transport with provider-specific endpoint, credential, timeout, and SDK automatic retries disabled.
- [x] 4.2 Assemble streaming text and tool-call deltas into the same normalized result shape used by non-streaming responses.
- [x] 4.3 Normalize provider errors into safe bounded metadata; do not automatically retry any failure with unknown remote outcome or switch providers.
- [x] 4.4 Exclude credentials, raw endpoints, image bytes, private continuation content, and raw provider response objects from logs and public availability/results.

## 5. Verification and Handoff

- [x] 5.1 Add mocked-transport coverage for provider allowlisting, configuration availability, each provider's request mapping, image/tool conversion, and unsupported schemas.
- [x] 5.2 Add response coverage for non-streaming and streaming normalization, ordered tool calls, private continuation replay, and safe failure classification.
- [x] 5.3 Verify the provider package can be called directly without RunCoordinator, AttachmentStore, ToolRegistry, Gateway, CLI, or frontend integration.
- [x] 5.4 Update `docs/figura-implementation-content.md` with the implemented field names and provider behavior after reconciling it against the code.
