## ADDED Requirements

### Requirement: Model-facing tool guidance explains selection and consequential semantics
Each registered model-callable tool SHALL provide a nonempty Chinese description explaining its purpose, accepted source, principal result, and consequential limitation or follow-up. Native parameter Schema SHALL describe fields whose meaning cannot be established from structural constraints alone, including coordinate units and frames, opaque reference provenance, optional defaults, search filters, pagination, selectors, and chart-type data semantics. Tool descriptions and parameter annotations SHALL agree with execution behavior and SHALL NOT invent capabilities, success guarantees, or automatic failure retries. Numeric and structural constraints SHALL remain authoritative in Schema rather than being duplicated as a separate fixed tool manual.

#### Scenario: Understand observation scope before calling a sensor
- **WHEN** a model receives an OCR or chart-measurement definition
- **THEN** the native parameters explain normalized source-relative coordinates, the `[x, y]` point shape, include-union minus exclude-union semantics, whole-source behavior when omitted, and the need for remaining observable pixels

#### Scenario: Distinguish decomposition and scoped observation
- **WHEN** the model chooses between Panel decomposition and an observation scope
- **THEN** tool guidance distinguishes creating an independent polygon-cropped Panel with `{x, y}` points from applying a temporary observation mask that preserves the selected source dimensions and result coordinate frame

#### Scenario: Interpret OCR and measurement results accurately
- **WHEN** the model receives OCR, bar, line, scatter, or pie tool guidance
- **THEN** it can distinguish execution success from observation quality, unavailable OCR from an empty available observation, possible truncation, calibrated chart values from pixel geometry, line markers from tick-position trace samples, visible scatter marks from hidden sample counts, and pie proportions from absolute totals

#### Scenario: Construct chart-type data with supported references
- **WHEN** the model receives Figure assembly parameters
- **THEN** guidance explains category/value points for bar and pie, x/y points for line and scatter, category positions and increasing x for line, actual committed measurement reference provenance, and the returned Figure reference without implying that references verify all supplied values

#### Scenario: Render using the exact returned reference
- **WHEN** a model uses a successful assembly result to request rendering
- **THEN** guidance identifies the nested `figure_ref` parameter, describes PNG feedback in the next request, and distinguishes rendering success from semantic approval

### Requirement: Tool guidance shares the request's registry identity
Figura SHALL derive model-facing tool names, descriptions, and native parameters from the same selected registry. Tool definitions whose input acceptance or observation semantics change SHALL use a new registry version. Completed prior-version calls SHALL remain inert readable history; unresolved prior-version work SHALL retain the existing rejection behavior. Prompt and tool metadata changes SHALL participate in existing request identity checks and SHALL NOT silently replace an already bound request.

#### Scenario: Project annotated native parameters
- **WHEN** a tool parameter Schema contains semantic descriptions
- **THEN** the Provider tool projection retains those descriptions and uses the same name and tool description as the request's tool directory

#### Scenario: Resume a request after assets change
- **WHEN** reconstructed prompt or registry metadata differs from an already bound request identity
- **THEN** Figura follows the existing identity mismatch behavior instead of dispatching a different request under the old binding
