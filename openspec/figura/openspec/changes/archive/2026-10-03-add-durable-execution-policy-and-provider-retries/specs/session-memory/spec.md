## MODIFIED Requirements

### Requirement: Session history remains complete and private to its owning Session
Figura SHALL retain the complete projected history and source-linked outcome contexts in memory for request construction and SHALL apply no Memory retention, token or summarization budget; complete request preparation SHALL use the shared execution-payload protection and genuine selected-Provider protocol restrictions rather than deleted generic counts and micro byte limits. It SHALL preserve Session ownership for every Run and attachment reference and SHALL expose no continuation payload or local attachment path through the projection's public surface.

#### Scenario: Preserve full history beyond a Provider request limit
- **WHEN** complete Session history exceeds the complete request payload or image byte guard or a genuine Provider protocol restriction
- **THEN** the projection remains complete and request construction fails before Provider-attempt claim without pruning, summarizing, or dispatching the history

#### Scenario: Reject a cross-Session attachment reference
- **WHEN** an attachment referenced by a historical Run does not belong to the owning Session or cannot be resolved
- **THEN** Figura fails closed without returning image bytes or dispatching a Provider request

### Requirement: Abnormal terminal Runs have deterministic source-linked outcome context
Figura SHALL derive outcome context for each earlier failed or interrupted Run from its validated durable facts without writing a second history or invoking a model. It SHALL identify the source Run, ordinal and safe terminal reason. An incomplete tail SHALL preserve source response text as untrusted intent data and classify each call as committed success, committed failure, not started, or outcome unknown. Every committed observation SHALL retain its source result reference and the existing complete normalized observation format. Calls without results SHALL contain no invented observation. Context SHALL contain no private continuation or automatically loaded image bytes.

#### Scenario: Preserve a partly completed batch
- **WHEN** OCR has a committed success, measurement has a started attempt without a result, and rendering has no attempt in an interrupted Run
- **THEN** context retains the OCR observation, marks measurement outcome unknown and rendering not started, and retains all three call identities in provider order

#### Scenario: Keep a known failure as an actual observation
- **WHEN** a call in an incomplete terminal batch has a committed failed result
- **THEN** context preserves that failure observation and does not reclassify it as unknown

#### Scenario: Explain a failure before a response
- **WHEN** an earlier Run failed before committing any model response
- **THEN** history retains its user input and a safe outcome context without inventing an assistant response

#### Scenario: Preserve source data without trimming
- **WHEN** outcome context makes a subsequent request exceed the complete request payload guard or a genuine Provider protocol restriction
- **THEN** preparation fails before attempt claim without dropping committed observations or summarizing the tail
