## MODIFIED Requirements

### Requirement: Provider model actions are durably claimed before dispatch
Before an Agent sends a provider request for a Run whose checkpoint points to a model action, Figura SHALL complete local request validation and Provider-specific payload preparation. If preparation succeeds, Figura SHALL atomically record one bounded provider-attempt identity and advance the checkpoint to that attempt, comparing the expected checkpoint revision and current action in the same transaction. A provider request SHALL NOT be dispatched unless its claim commits, and only one attempt SHALL be active for a Run at a time. If local preparation fails, Figura SHALL fail the Run through its existing bounded terminal state without claiming a Provider attempt or dispatching a request. For a known local Provider preparation rejection, the existing Run terminal message SHALL contain a bounded, allowlisted safe explanation of the rejection and the terminal code SHALL remain `execution_failed`. Unknown exceptions SHALL use the generic safe failure message. The explanation SHALL exclude continuation content and references, prompts, credentials, endpoints, raw SDK errors, and response bodies, and SHALL be retained on later Run reads through the existing public terminal-message projection. No additional execution fact or event payload field SHALL be created for preparation failures. Attempt metadata SHALL not contain the serialized prompt, tool schemas, credentials, raw endpoint, or provider response body.

#### Scenario: Prepare and claim the current model action
- **WHEN** local request preparation succeeds and the expected checkpoint revision is current and points to a model action
- **THEN** Figura records the attempt and advances the checkpoint to the matching provider-attempt action atomically before dispatch

#### Scenario: Reject a locally incompatible request before attempt claim
- **WHEN** local Provider request validation or payload preparation rejects the model action
- **THEN** Figura commits the existing bounded Run failure state, creates no Provider attempt, and sends no Provider request

#### Scenario: Claim races with another executor
- **WHEN** two callers claim the same model action using the same checkpoint revision
- **THEN** at most one claim commits and the caller whose claim fails does not dispatch a provider request

#### Scenario: Attempt claim cannot be persisted
- **WHEN** storage fails before the provider-attempt claim commits
- **THEN** Figura leaves the prior checkpoint and facts unchanged and sends no provider request

#### Scenario: Explain a missing DeepSeek continuation locally
- **WHEN** local preparation rejects a DeepSeek tool-history request because a required continuation is genuinely absent
- **THEN** the failed Run's existing terminal message explains the missing required history safely within 256 UTF-8 bytes
- **AND** no Provider attempt or network request is created

#### Scenario: Suppress unsafe unexpected preparation errors
- **WHEN** local preparation raises an unrecognized exception containing internal or sensitive details
- **THEN** the Run uses the generic safe terminal message without persisting or projecting those details
