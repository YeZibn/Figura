## MODIFIED Requirements

### Requirement: User can inspect a conversation

The conversation area SHALL render each completed or active Agent run as one
distinct chronological item containing, in order, the user request, its
expandable execution process, and its final result. Final Agent answers SHALL
be rendered as safe Markdown inside the final result area. Generated chart
artifacts SHALL be presented with the final result rather than as a duplicate
ordinary execution-timeline card, while the execution process SHALL retain a
compact event indicating that the chart was generated. The client SHALL use
the canonical run identifier returned by the Gateway to associate the user
request, assistant answer, execution events, and generated artifacts. New
server-backed runs SHALL NOT leave their user request or assistant answer in
the unassociated-message fallback merely because different layers generated
different local identifiers. The client SHALL preserve genuinely
unassociated legacy messages through a compatible fallback presentation.

#### Scenario: Conversation renders one Run in stable order

- **WHEN** a session contains a user request, an associated run, execution
  events, and a final answer
- **THEN** the UI renders one chronological Run item with the user request
  first, the expandable execution process second, and the final result last
- **AND** opening or closing the process does not change message order or lose
  any event

#### Scenario: Gateway Run identity associates the conversation

- **WHEN** the Gateway accepts a message and returns a Run identifier
- **THEN** the persisted user request, assistant answer, Run summary, and
  execution history use that same canonical identifier for association
- **AND** the UI renders the request and answer inside that Run instead of
  appending them as orphan messages

#### Scenario: Generated chart is shown as a final result

- **WHEN** an associated run produces one or more generated chart artifacts
- **THEN** the UI displays each available chart in the Run's final result area
- **AND** the execution process keeps only a bounded generated-chart event
  indicator instead of rendering the same chart as a second timeline card

#### Scenario: Run association survives live completion and reload

- **WHEN** a run receives an identifier during submission or is restored from
  persisted session data
- **THEN** the client associates the user request and assistant answer with
  that canonical run identifier and keeps them in the same Run item after
  completion or reload
- **AND** the client does not duplicate the user message or final answer

#### Scenario: Legacy messages remain visible

- **WHEN** a session contains a message that cannot be associated with a run
  identifier from the current or legacy data contract
- **THEN** the client renders the message in a compatible fallback position
- **AND** the message is not silently discarded while Run items are built

#### Scenario: Final answer renders Markdown

- **WHEN** the Agent answer contains Markdown headings, lists, tables,
  emphasis, links, or fenced code
- **THEN** the assistant answer displays those structures with safe styling in
  the final result area
- **AND** the source answer remains recoverable for copying or plain-text
  fallback
