## MODIFIED Requirements

### Requirement: Provider history is reconstructed from complete committed interactions
For each model action, Figura SHALL build the conversation from all earlier terminal Runs in the same Session, ordered by Run ordinal, followed by the current Run's immutable input, committed model responses, and committed tool results. Without input-aware coverage, each input SHALL appear once with persisted text and ordered attachment identities without automatically including images. With input-aware coverage, covered prior inputs and process SHALL be represented by the source-linked summary; uncovered prior inputs SHALL remain raw. Current input SHALL remain a complete native user message even when current process is summarized. Legacy process-only checkpoints SHALL NOT by themselves authorize omission of prior inputs. The request SHALL include the target Run's factual resource index in its running-resource SYSTEM instruction block. The index SHALL identify the resources selected for the request's authorized locator projection, including eligible Attachments, Panels, OCR, measurements, Figures and renders with kind-appropriate summaries; other authorized resources SHALL remain discoverable through history search and full server-side lookup. The index SHALL identify resources by their complete typed references. It SHALL NOT duplicate complete OCR, measurement, Figure, or render result payloads already present in committed tool messages. Historical render entries SHALL remain textual; Figura SHALL NOT automatically resend image bytes from an earlier Run or earlier tool batch. Each retained raw closed model/tool interaction SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A validated incomplete trailing batch from an earlier failed or interrupted Run SHALL be represented entirely by source-linked abnormal outcome data in the running-resource SYSTEM instruction block, preserving its intent and committed observations instead of sending dangling native calls. A final-answer fact that references a response SHALL NOT add a duplicate message. The next ordinary model action following a fully committed visual tool batch SHALL include every ordered attachment of each successful result inside that call's single native tool-result message, after its complete structured observation. Image identity and a type-specific hint SHALL be adjacent to that image. Selection SHALL follow committed attachment descriptions, not a central list of image-producing tool names. Different calls reading the same source SHALL each retain their own image occurrence; cross-call source deduplication SHALL NOT remove an image from its logical result. Failed results SHALL have no image. Older results retained in raw history SHALL retain data and attachment descriptions with an explicit not-loaded projection and SHALL NOT resend image bytes unless a new explicit image-read call returns them. No plain user image feedback message SHALL be appended. The resource index and image selection SHALL use the same authorized Run prefix as the committed conversation. Completed tool-call/result pairs recorded under an earlier registry version SHALL be projected as inert conversation history and SHALL NOT be executed again; unresolved work in the current Run, incomplete completed history, or corrupt facts SHALL fail closed; legal terminal incomplete tails SHALL follow the abnormal outcome projection. Provider-private continuation SHALL be attached only to the exact originating assistant response retained in role history, including a prior Run when the selected Provider and format are compatible. Continuation from a converted incomplete batch SHALL NOT be placed in outcome context or fabricated for it. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request with multiple attachments
- **WHEN** the checkpoint points to the initial model action and the current Run references multiple images
- **THEN** the request contains stable-rule, tool-directory, optional-summary and running-resource SYSTEM instruction blocks, persisted user text, and a complete typed reference for each selected resource in the running-resource block, but no image bytes

#### Scenario: Include earlier Session Runs and their resources
- **WHEN** the checkpoint points to a model action and the Session has earlier terminal Runs with referenced attachments and committed tool resources
- **THEN** the request represents covered history by its source-linked summary and uncovered closed history in ascending Run ordinal, preserves raw input attachment identities and abnormal contexts, indexes selected resources once by exact typed reference and does not attach historical image bytes

#### Scenario: Keep full results in chronological tool history
- **WHEN** a committed OCR, measurement, Figure assembly, or render interaction is retained in raw Session history
- **THEN** its complete committed tool result appears in its original tool message and the textual resource index contains only a concise reference and summary, without a duplicate full result payload

#### Scenario: Rebuild a completed tool round with explicitly loaded images
- **WHEN** the checkpoint points to a model action after a fully resolved tool batch containing one or more successful `load_image` calls
- **THEN** the request contains the ordered assistant/tool interaction and includes each call's original image inside its own tool-result content in persisted call order

#### Scenario: Include visual feedback for the latest observation batch
- **WHEN** the immediately preceding fully committed tool batch contains successful `extract_text` or `measure_chart` calls for any supported family
- **THEN** the request contains each corresponding JSON tool result and one matching saved annotated image within each successful call's tool result in tool-call order, with the tool name and call ID identified

#### Scenario: Include a rendered Figure in the next model action
- **WHEN** the immediately preceding fully committed tool batch contains one or more successful `render_chart_figure` calls
- **THEN** the next Provider request contains each corresponding JSON tool result and one matching stored PNG inside each successful render call's tool result in call order

#### Scenario: Do not repeat images from an older tool batch
- **WHEN** the latest completed tool batch has no successful result with image attachments
- **THEN** the request contains no image bytes from earlier batches or Runs

#### Scenario: Preserve completed prior-version calls as inert history
- **WHEN** an earlier Run or a completed interaction in the current Run contains a fully paired assistant tool call and result recorded under a prior registry version
- **THEN** Figura retains the interaction in original order when raw or represents it through authorized summary coverage, and never invokes its historical handler

#### Scenario: Fail closed on a prior-version unresolved tool call
- **WHEN** a tool call from a prior registry version is unresolved in the current Run, or belongs to an incomplete completed historical Run
- **THEN** Figura does not construct or dispatch a Provider request and does not execute the old call under the current registry

#### Scenario: Replay only compatible source continuation
- **WHEN** an earlier Run has a compatible private continuation for an assistant response retained in role history
- **THEN** Figura attaches that unchanged continuation to its exact source response while keeping it out of neutral Memory and abnormal outcome data

#### Scenario: Include abnormal tail observations without duplicate payloads
- **WHEN** an earlier interrupted Run has a partly completed tool batch
- **THEN** the running-resource instruction block contains its source-linked outcome context, role history contains only its closed interactions, and the resource index contains only eligible references and summaries

#### Scenario: Do not create a second result for image content
- **WHEN** one successful call returns business data and image attachments
- **THEN** Figura emits a single native tool-result message containing both rather than a text result followed by another message using the same tool_call_id

#### Scenario: Keep shared images associated with each caller
- **WHEN** two successful calls in one batch load the same authorized resource
- **THEN** each result retains its own image and hint under its own call ID even when storage reuses the same bytes

#### Scenario: Compact active process and retain current input
- **WHEN** a summary covers earlier complete interactions of the current Run
- **THEN** Figura sends their source-linked summary, recent complete raw interactions and the full current user input exactly once


### Requirement: Agent requests preserve complete Session history within Provider limits
Figura SHALL reconstruct ordinary requests from complete durable Session facts using the canonical streaming Provider path and ordered stable-rule, exact-tool, optional-summary and running-resource SYSTEM layers. Source-linked compaction SHALL replace eligible old history under the session-context-compaction contract, including prior user input only with input-aware coverage. Current user input SHALL remain complete. Resource filtering SHALL affect model-visible locator metadata without reducing authorized lookup. The assembled request SHALL satisfy shared payload/image protections and genuine selected-Provider protocol limits before attempt claim. Local estimates and soft targets SHALL NOT introduce cumulative Run quotas or silently truncate canonical facts, current input or retained complete tool interactions. If an existing preparation limit is violated, Figura SHALL fail before claiming or dispatching an ordinary attempt.


Abnormal context SHALL remain complete in its existing normalized observation format and SHALL count toward the shared complete-request JSON guard. Neither abnormal intent nor observation text SHALL be treated as system policy.

#### Scenario: Send full raw history when no summary applies
- **WHEN** all earlier same-Session Runs have valid complete histories, no summary applies and the assembled request is within Provider limits
- **THEN** Figura sends the entire earlier history and current Run prefix in ordinal and committed fact order, with three ordered SYSTEM instruction blocks when no summary applies

#### Scenario: Complete history exceeds a Provider limit
- **WHEN** the full request exceeds the shared complete-request guard, retained image byte protections or a genuine selected-Provider protocol restriction
- **THEN** Figura preserves all source facts, fails the current Run, and makes no Provider-attempt claim or network request

#### Scenario: Keep a tool result associated with its call
- **WHEN** a successful or failed tool result from a closed interaction is projected into native Provider role history
- **THEN** Figura sends a bounded JSON observation in a tool message associated with the original call ID and omits implementation details from an error observation
