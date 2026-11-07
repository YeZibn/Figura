## ADDED Requirements

### Requirement: Identify repeated successful visual observations within the current Run
For ordinary Agent requests, Figura SHALL identify repeated observations using only successful, committed `extract_text` and `measure_chart` calls in the authorized current Run prefix. Calls SHALL represent the same action only when tool name, registry version and complete normalized JSON arguments match. Normalization SHALL ignore object-key order and insignificant JSON formatting, preserve array order and values, and SHALL NOT infer geometric equivalence, approximate matches, or equivalence between different source IDs. Observations SHALL match only when their complete normalized structured results match, excluding the execution envelope and image attachment identities. Result status, availability, empty observations, warnings, confidence, coverage, evidence and calibration fields SHALL remain part of comparison when present.

For each action, Figura SHALL compare its latest eligible result with earlier eligible results for that action. If at least two results match that latest observation, it SHALL produce one grouped reminder with the matching successful-call count and references to the latest two matching committed results. Intervening actions SHALL NOT prevent matching. A different latest observation SHALL NOT inherit a reminder for an older observation that it does not match. Failed or unresolved calls, other tools and earlier Runs SHALL NOT contribute; replay attempts of one logical call SHALL count as one call.

#### Scenario: Second identical observation produces one reminder
- **WHEN** two distinct successful calls in the current Run use the same eligible tool, registry version and arguments and return identical structured results with different annotated-image attachments
- **THEN** the next ordinary model request includes one reminder counting two matching calls and referencing both results

#### Scenario: Interleaved actions and larger repeated groups
- **WHEN** three matching successful observations of one action are separated by history reads or other actions
- **THEN** the request includes one reminder for that action with count three and references to the latest two matching results

#### Scenario: Meaningful differences do not match
- **WHEN** source identity, scope, chart family, registry version, array order or any structured observation value differs
- **THEN** those calls do not count as identical action-observation pairs, and a latest changed observation has no reminder unless it independently matches another earlier result of its action

#### Scenario: Preserve partial and empty observations
- **WHEN** successful eligible calls repeatedly return the same partial, unsupported, unavailable or empty structured observation
- **THEN** the repeated observation is eligible for a reminder without being represented as a failed call or a confirmed business fact

#### Scenario: Exclude retries and unrelated history
- **WHEN** an attempt is replayed for the same logical call, a call fails or remains unresolved, another tool repeats, or a matching result exists only in an earlier Run
- **THEN** it does not increase the current Run's matching successful-call count

### Requirement: Repeated observation reminders preserve model autonomy and factual boundaries
Figura SHALL place grouped repetition reminders in the dynamic running-state SYSTEM instruction of the next ordinary model request after the tool batch is resolved. Each reminder SHALL state the observed repetition, matching count and latest two source references, and guide the model to consider changing scope or method or delivering supported results with limitations when further observation has no effective path. Reminders SHALL NOT assert correctness, goal completion, impossibility of future improvement or mandatory stopping. They SHALL NOT include full observations, raw tool parameters, images or source text in their repetition metadata. Referenced source values SHALL remain untrusted data.

Figura SHALL preserve original tool results and attachments, SHALL NOT add a user message for the reminder, and SHALL NOT suppress calls, reuse cached results, automatically retry tools, restrict tool permissions or introduce cumulative Run quotas as a consequence of repetition. Multiple reminders SHALL use deterministic ordering and one entry per eligible action, rather than append-only warning history.

#### Scenario: Model can choose a third identical call
- **WHEN** the model receives a repetition reminder and requests another otherwise valid identical call
- **THEN** the existing execution path executes and records that new logical call normally

#### Scenario: Batch-local repetition is observed after completion
- **WHEN** repeated eligible calls are present in one accepted tool batch
- **THEN** Figura resolves the batch normally and includes reminders in the following ordinary model request without intercepting a pending call

#### Scenario: Reminders remain separate from observations
- **WHEN** a reminder is rendered into a request
- **THEN** tool result bodies and attachments remain unchanged and no synthetic user input or tool result is created

### Requirement: Repetition reminders are reproducible from durable facts
Figura SHALL derive reminders from the same authorized committed current Run prefix used to prepare the ordinary model request, independent of summary coverage or retained raw-message tails. It SHALL NOT require a new durable repetition counter, special measurement decision state, database migration or public API field. Restarting execution with the same prefix SHALL produce the same reminder content and ordering. Existing frozen Provider request bindings SHALL remain authoritative for retries; a retry SHALL reproduce the bound request rather than recompute a different reminder from a later prefix or changed prompt assets. Summary requests SHALL NOT receive repetition reminders.

#### Scenario: Restart and compaction preserve reminders
- **WHEN** an executor restarts or raw interactions are covered by a context summary while the underlying committed current Run prefix is unchanged
- **THEN** the next newly prepared ordinary request derives the same repetition metadata and source references

#### Scenario: Retry preserves bound reminder content
- **WHEN** a logical Provider request containing repetition reminders undergoes a transport retry
- **THEN** the retry reproduces its frozen request contract including reminder content and existing fingerprint checks

#### Scenario: Summary request remains dedicated to compaction
- **WHEN** Figura prepares a context-compaction request for a Run with repeated observations
- **THEN** it uses the existing summary contract without adding the ordinary repetition reminder block
