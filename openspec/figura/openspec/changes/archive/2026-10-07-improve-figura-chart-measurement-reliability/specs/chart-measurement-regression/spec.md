## Purpose

Provides reproducible image-based regression evaluation for Figura chart measurement, separating visible extraction targets, numeric evidence and OCR performance from model-generated estimates and end-to-end Agent completion.

## ADDED Requirements

### Requirement: Maintain reproducible images and visible reference targets
Regression cases SHALL have stable identity, image hash/dimensions, generation/source provenance, chart-family and optional fixed Panel/scope definitions, visible target objects/labels/values, visibility declarations and predefined tolerance rules. Generated images and answers SHALL share one source of truth. The initial suite SHALL cover ten single-family images and three multi-chart canvases. Unrecoverable original data SHALL NOT be reconstructed from model estimates as exact truth; regenerated cases SHALL explicitly record replacement provenance.

#### Scenario: Reproduce a generated case
- **WHEN** a case is regenerated in its recorded renderer/font environment
- **THEN** image identity and reference targets can be verified and a changed hash requires an explicit manifest update

#### Scenario: Preserve uncertainty in old images
- **WHEN** exact generation data cannot be recovered
- **THEN** old image hashes and diagnostic status are retained and new reproducible cases are labeled as regenerated without claiming exact old truth

### Requirement: Evaluate production measurement independently of answer generation
The evaluator SHALL use the production source-authorized measurement path with a specified family and source/scope, without a Provider request. Gallery testing SHALL use fixed reference Panel regions to isolate measurement from Agent decomposition decisions. Ground truth, renderer internals and case filenames SHALL NOT be production detection inputs. Fixed-OCR algorithm tests and real-OCR integration tests SHALL be reported separately.

#### Scenario: Evaluate a Gallery Panel
- **WHEN** the evaluator registers the reference Panel through normal source authorization
- **THEN** the ordinary family algorithm measures its pixels without receiving reference values or geometry

#### Scenario: Isolate OCR failures
- **WHEN** geometry passes with fixed OCR candidates but real OCR fails
- **THEN** results report the two modes separately rather than treating mocked OCR success as real extraction success

### Requirement: Match visible targets and report separate error categories
Evaluation SHALL match objects one-to-one through geometry and semantic associations rather than emitted IDs or total count alone. It SHALL separately report missing/spurious geometry, category/series/dimension/hierarchy association errors, supported-value coverage and error, unsupported non-null values, and expected null/issue behavior. Tolerances SHALL be defined before tuning, based on reference rendering resolution/calibration and text normalization, and SHALL NOT grow with prediction error or the tested sensor's residual. Reports SHALL record case hashes, environment, contract/code versions and per-family results without raw private session data or credentials.

#### Scenario: Reject a correct count with wrong associations
- **WHEN** twelve bars are found but category or series mapping is wrong
- **THEN** count alone does not pass the case and association errors are reported

#### Scenario: Do not reward fabricated numbers
- **WHEN** a value is emitted without required visual support even if numerically near a reference
- **THEN** the result records an unsupported-value failure

#### Scenario: Distinguish sampling from original points
- **WHEN** an unmarked line only supports tick-position samples or scatter points are hidden by overlap
- **THEN** evaluation checks declared visible targets without demanding hidden original samples

### Requirement: Gate the initial supported sample suite and uncertainty variants
The initial supported suite SHALL pass exact declared visible structures and associations, all declared readable numeric targets within their predefined tolerances, and zero unsupported non-null values. It SHALL verify bar 3×4, line 2×6 visible targets, scatter 9, donut 5, area 2×5, histogram 6, box plot 3 groups, radar 2×5, heatmap 4×5 and treemap 4 leaves plus supported grouping. The suite SHALL also exercise changed palettes, size/font/alpha, internal legends, small objects, negative/nonzero axes, missing calibration, same-color neighboring cells, scoped/excluded geometry, blank sources, family mismatch and unsupported layouts. Expected uncertainty SHALL pass only with correct null/issue behavior.

#### Scenario: Preserve missing calibration
- **WHEN** a variant removes the necessary scale support
- **THEN** supported geometry remains and unsupported values are null with explicit issues

#### Scenario: Keep local observations local
- **WHEN** a scope clips objects or excludes labels
- **THEN** regression verifies original-source coordinates, truthful scoped coverage and no newly created Panel

#### Scenario: Report regression scope honestly
- **WHEN** the initial synthetic suite passes
- **THEN** its report labels the result as regression evidence and not general external benchmark accuracy or Agent completion rate
