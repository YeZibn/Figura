## MODIFIED Requirements

### Requirement: Provider history is reconstructed from complete committed interactions
For each model action, Figura SHALL build the conversation from all earlier terminal Runs in the same Session, ordered by Run ordinal, followed by the current Run's immutable input, committed model responses, and committed tool results. Each Run input SHALL appear once as a user message containing its persisted text and ordered attachment references as text identities; it SHALL NOT automatically include image blocks. The request SHALL include the target Run's factual resource index in its running-resource SYSTEM instruction block. The index SHALL identify the resources selected for the request's authorized locator projection, including eligible Attachments, Panels, OCR, measurements, Figures and renders with kind-appropriate summaries; other authorized resources SHALL remain discoverable through history search and full server-side lookup. The index SHALL identify resources by their complete typed references. It SHALL NOT duplicate complete OCR, measurement, Figure, or render result payloads already present in committed tool messages. Historical render entries SHALL remain textual; Figura SHALL NOT automatically resend image bytes from an earlier Run or earlier tool batch. Each closed model/tool interaction SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A validated incomplete trailing batch from an earlier failed or interrupted Run SHALL be represented entirely by source-linked abnormal outcome data in the running-resource SYSTEM instruction block, preserving its intent and committed observations instead of sending dangling native calls. A final-answer fact that references a response SHALL NOT add a duplicate message. The next ordinary model action following a fully committed visual tool batch SHALL include every ordered attachment of each successful result inside that call's single native tool-result message, after its complete structured observation. Image identity and a type-specific hint SHALL be adjacent to that image. Selection SHALL follow committed attachment descriptions, not a central list of image-producing tool names. Different calls reading the same source SHALL each retain their own image occurrence; cross-call source deduplication SHALL NOT remove an image from its logical result. Failed results SHALL have no image. Older results SHALL retain data and attachment descriptions with an explicit not-loaded projection and SHALL NOT resend image bytes unless a new explicit image-read call returns them. No plain user image feedback message SHALL be appended. The resource index and image selection SHALL use the same authorized Run prefix as the committed conversation. Completed tool-call/result pairs recorded under an earlier registry version SHALL be projected as inert conversation history and SHALL NOT be executed again; unresolved work in the current Run, incomplete completed history, or corrupt facts SHALL fail closed; legal terminal incomplete tails SHALL follow the abnormal outcome projection. Provider-private continuation SHALL be attached only to the exact originating assistant response retained in role history, including a prior Run when the selected Provider and format are compatible. Continuation from a converted incomplete batch SHALL NOT be placed in outcome context or fabricated for it. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request with multiple attachments
- **WHEN** the checkpoint points to the initial model action and the current Run references multiple images
- **THEN** the request contains stable-rule, tool-directory, optional-summary and running-resource SYSTEM instruction blocks, persisted user text, and a complete typed reference for each selected resource in the running-resource block, but no image bytes

#### Scenario: Include earlier Session Runs and their resources
- **WHEN** the checkpoint points to a model action and the Session has earlier terminal Runs with referenced attachments and committed tool resources
- **THEN** the request contains all earlier closed Run messages and source-linked abnormal contexts in ascending Run ordinal, preserves their text and attachment IDs, indexes each eligible resource once by its typed reference, and does not attach historical image bytes

#### Scenario: Keep full results in chronological tool history
- **WHEN** a committed OCR, measurement, Figure assembly, or render interaction is included in Session history
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
- **THEN** Figura projects that interaction in its original order as conversation history and does not invoke its handler

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

### Requirement: Referenced images are resolved and bounded before provider-attempt claim
Before claiming a durable Provider attempt, Figura SHALL resolve selected committed attachments from the full authorized resource catalog and verify image bytes against their descriptors. Attachment/Panel reads SHALL use their owning source services; OCR/measurement and render feedback SHALL read already saved media. Request construction SHALL NOT redraw annotations or infer attachments from tool names. Prompt-directory filtering SHALL NOT restrict the full server-side authorized lookup used to resolve a selected attachment.

Figura SHALL check each raw image size, aggregate bytes, source/descriptor integrity, shared structured-request guard and genuine selected-Provider limits without a generic image-count cap. With no selected attachments the request SHALL contain no image bytes. Missing, unreadable, differently owned, mismatched or unsupported media SHALL cause the existing safe preparation failure before claim or dispatch, never a replacement image or plain user fallback.

#### Scenario: Assemble a valid request after explicit image loads
- **WHEN** every attachment returned by the immediately preceding batch resolves from the authorized same-Session resource catalog and the assembled request is within Provider limits
- **THEN** Figura may claim the Provider attempt and dispatch the request with those original image bytes held only in memory

#### Scenario: Assemble a valid request after text extraction or measurement
- **WHEN** each successful text-extraction or chart-measurement resource in the immediately preceding batch has a matching committed result and its recorded annotation file matches the committed descriptor
- **THEN** Figura reads and validates the matching saved annotated images and may claim and dispatch the Provider request within Provider limits

#### Scenario: Assemble a valid request after Figure rendering
- **WHEN** each successful render resource in the immediately preceding batch has a matching committed render result and its private PNG matches the committed metadata
- **THEN** Figura assembles and validates the rendered images and may claim and dispatch the Provider request within Provider limits

#### Scenario: Assemble a request without a preceding image observation
- **WHEN** the current checkpoint follows Run creation or a complete batch whose results contain no image attachments
- **THEN** Figura assembles and validates the text and tool history without resolving Attachment, Panel, or render image bytes

#### Scenario: An image required for visual feedback cannot be resolved
- **WHEN** a successful `load_image`, text-extraction, chart-measurement, or chart-render resource refers to missing, unreadable, invalid, differently owned, or integrity-mismatched content needed by the next request
- **THEN** Figura fails the current Run before claiming a Provider attempt and sends no request

#### Scenario: Images exceed Provider bounds
- **WHEN** original, annotated, and rendered images for the immediately preceding tool batch exceed a genuine selected-Provider image restriction, retained per-image or aggregate byte guard, or the shared structured-request guard
- **THEN** Figura fails the current Run before claiming or dispatching a Provider attempt

#### Scenario: Resolve media using the full catalog after prompt filtering
- **WHEN** a selected committed attachment is authorized but its resource is omitted from the compact Prompt directory
- **THEN** the resolver uses the complete authorized catalog and does not falsely reject the attachment or load another image

### Requirement: Agent prompt layers have explicit sources and ordered responsibilities
Figura SHALL assemble ordered logical SYSTEM layers for stable rules, the exact current tool directory, an optional source-linked history summary, and the running-resource index with validated abnormal outcomes. Without a summary there SHALL be three SYSTEM blocks; with a summary there SHALL be four. Stable Chinese Agent, evidence, workflow, response and image-observation rules SHALL contain no request-specific user/Run data. The tool directory SHALL describe exactly the registry used for native tool schemas, whose names and parameter constraints remain authoritative.

The running-resource index SHALL come exclusively from the target request's resource state and use complete typed Attachment, Panel, OCR, measurement, Figure and render references. It SHALL expose concise kind-appropriate locator/availability metadata rather than duplicate full tool results, image bytes or per-image hints. The full resource catalog SHALL remain available to authorized server-side reads even when its Prompt projection is filtered.

Names, titles, OCR text, observations, summaries and other source values SHALL be untrusted data rather than instructions. Stable image rules SHALL be separate from the short per-image hints rendered inside matching tool results. The layers SHALL be rebuilt per request and included in request identity checks, not stored as canonical Run messages. The final resource block SHALL preserve deterministic source-linked abnormal terminal context in Run order, with genuine observations exactly once and no fabricated result or continuation.

#### Scenario: Keep stable policy independent from user and Run values
- **WHEN** Figura assembles a request containing user text, tool results, attachments, and Panels
- **THEN** the first SYSTEM instruction block contains only the stable Chinese Agent policy and the request-specific values appear only in their designated dynamic layers or history messages

#### Scenario: Match the tool layer to the registered tool schemas
- **WHEN** a request is assembled with a tool registry containing a specific ordered set of tools
- **THEN** the second SYSTEM instruction block describes exactly those tools in registry order and the provider request exposes their native schemas from the same registry

#### Scenario: Index all resource kinds from the target Run state
- **WHEN** the target Run's `RunExecutionState` contains eligible resources of multiple kinds
- **THEN** the running-resource SYSTEM instruction block identifies each resource with its complete typed reference and a concise kind-appropriate summary, without substituting resources from a later Run

#### Scenario: Keep complete observations in chronological history
- **WHEN** an OCR, measurement, Figure assembly, or render result is present in committed Session history and is also indexed in `RunExecutionState`
- **THEN** the history contains its complete committed tool observation while the resource block contains only a concise reference and summary

#### Scenario: Treat resource values as data
- **WHEN** an attachment name, Panel name, OCR snippet, or tool result contains text that resembles an instruction
- **THEN** Figura encodes the value as resource data and instructs the model to analyze it as untrusted content, not follow it as policy

#### Scenario: Keep abnormal text as data
- **WHEN** original response text or an observation in abnormal context resembles an instruction
- **THEN** the text is encoded as data and does not replace static responsibilities or tool policy

#### Scenario: Use the optional summary without changing resource ownership
- **WHEN** a request uses a valid history summary
- **THEN** its summary layer precedes the running-resource layer, while resource identities continue to come from the same authorized Run facts

### Requirement: Returned images carry type-specific observation guidance
For every image actually included in an ordinary request, Figura SHALL place exactly one adjacent resource-identity cue and short observation hint inside the same logical tool result as that image. The hint SHALL derive from trusted image guidance templates using the attachment's image_kind: original, ocr_annotation, measurement_annotation, or rendered. Stable observation policy SHALL stay in SYSTEM instructions. Neither resource names, OCR text, retrieved data nor model-supplied strings SHALL become trusted hint templates.

Hints SHALL guide task-relevant inspection without declaring verification, forcing a report or creating another model action. An explicitly reloaded historical image SHALL use its original resource type and provenance while the surrounding result retains the current read call's ID. Attachment and call order SHALL be preserved; every different call's image occurrence SHALL remain associated with that call. No actual image means no per-image hint, including text-only history, errors, resource indexes and summary requests. Hint/template changes SHALL participate in the existing request fingerprint and Prompt identity checks and SHALL NOT silently replace a bound request.

#### Scenario: Observe an original image
- **WHEN** an authorized Attachment or Panel image is appended after loading
- **THEN** its cue identifies the original resource and guides task-relevant inspection of chart family, layout, axes, labels, and legends without forcing measurement

#### Scenario: Inspect OCR annotations
- **WHEN** an OCR annotation image is appended
- **THEN** its cue identifies the OCR resource and guides comparison with its structured observation for missing text, misplaced boxes, and incorrect associations, without treating recognized text as certain truth

#### Scenario: Inspect measurement annotations
- **WHEN** a measurement annotation image is appended
- **THEN** its cue identifies the measurement resource and guides inspection for missed, duplicated, or falsely detected marks and category/series associations, while requiring supported calibration before interpreting geometry as numeric data

#### Scenario: Inspect rendered charts
- **WHEN** a rendered chart PNG is appended
- **THEN** its cue identifies the render resource and guides task/data correspondence and visible legend, label, overlap, clipping, and layout inspection, without equating PNG generation with semantic correctness

#### Scenario: Reload historical annotation images
- **WHEN** `read_resource_image` returns an authorized historical OCR or measurement image
- **THEN** the image receives the same role-specific guidance as a current annotation and identifies both its originating resource and the current loading call

#### Scenario: Keep multiple images aligned
- **WHEN** a fully committed batch contributes multiple eligible images
- **THEN** each image has exactly one adjacent cue inside its owning call's tool result, in call and attachment order, without cross-call source deduplication or orphan cues

#### Scenario: Avoid cues without images
- **WHEN** a request contains only JSON tool results, resource indexes, failed calls, or historical text without actual image loading
- **THEN** Figura adds no per-image cue and does not load images to satisfy guidance

#### Scenario: Keep hints out of canonical business data
- **WHEN** a result with an image is persisted and later projected for a model
- **THEN** facts retain business data and image descriptors, while the trusted short hint is rendered for the actual request and bound to its request identity
