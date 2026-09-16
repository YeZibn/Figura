## MODIFIED Requirements

### Requirement: Independent pie-sector extraction tool

The system SHALL provide an `extract_pie_slices` tool for ordinary two-
dimensional pie charts. The tool SHALL return a unified source-image evidence
result containing image dimensions, bounded orientation or transform evidence,
a detected plot region, circular geometry, and one structured entry per
reliably detected sector. Each sector SHALL include a stable identifier,
source-image boundary or polygon evidence, color evidence, start and end
angles, angular size, and a normalized ratio only when the geometry evidence
passes the tool's support and residual gates. The tool SHALL preserve partial
geometry and pixel evidence when some sectors, boundaries, or associations
cannot be resolved.

The tool SHALL treat ordinary circular pies as the supported geometry. It MUST
remain bounded for translated, resized, and supported rotated images, and MUST
mark strong perspective, elliptical, three-dimensional, donut, exploded,
nested, or otherwise unsupported geometry instead of fabricating a complete
flat pie measurement.

#### Scenario: Clean pie sectors are measured with source geometry

- **WHEN** `extract_pie_slices` is called with a clean synthetic pie chart whose
  sectors have distinguishable colors
- **THEN** the result contains the true number of reliably detected sectors
  within the declared fixture tolerance
- **AND** each sector contains a stable ID, source-image boundary evidence,
  color evidence, angle evidence, and a ratio matching the ground truth within
  the declared tolerance
- **AND** the result contains detected plot-region, center, radius, and
  source-image size evidence

#### Scenario: Translated, resized, or rotated pies preserve geometry

- **WHEN** the same ordinary pie chart is translated, resized, or rotated
  within the supported image transformation range
- **THEN** the sensor keeps sector identities, angular spans, and ratios
  stable within the declared tolerance
- **AND** all serialized geometry and generated overlay coordinates remain
  aligned with the transformed source image
- **AND** the result records the supported transform or orientation evidence
  rather than treating a fixed crop boundary as the chart geometry

#### Scenario: Narrow, anti-aliased, or separated sectors remain bounded

- **WHEN** sector boundaries contain anti-aliasing, separator gaps, narrow
  sectors, or small color-sampling interruptions
- **THEN** the sensor uses consistent multi-radius or boundary support to
  preserve a sector when evidence is sufficient
- **AND** it reports boundary support, residual, or uncertainty when the
  measured span is incomplete or ambiguous
- **AND** it does not split, merge, or assign a ratio solely from an
  unsupported single-pixel gap or color match

#### Scenario: Cartesian axes are not required

- **WHEN** a pie chart has no x-axis, y-axis, or numeric tick labels
- **THEN** the sensor still measures sector geometry and ratios when circular
  evidence passes its gates
- **AND** it does not report missing Cartesian calibration as a sensor failure

#### Scenario: Unsupported pie geometry remains inspectable

- **WHEN** the input is a strong-perspective, elliptical, three-dimensional,
  donut, exploded, nested, or otherwise unsupported circular graphic
- **THEN** the result preserves any bounded plot-region or partial pixel
  evidence that can be established
- **AND** it marks the geometry as unsupported or low confidence with a
  material warning
- **AND** it does not emit a complete flat-pie sector ratio dataset

#### Scenario: Non-pie image remains inspectable

- **WHEN** the input contains no reliable circular pie region
- **THEN** the tool returns an empty sector list with a bounded warning rather
  than fabricating sectors or raising an exception
- **AND** any generated overlay preserves the source dimensions and explains
  that no reliable pie region was found

#### Scenario: Missing or malformed input is bounded

- **WHEN** `extract_pie_slices` receives a missing, unauthorized, malformed, or
  non-image input
- **THEN** it returns a structured error without exposing a local source path
  or producing a visual artifact

### Requirement: Pie labels and legend associations are explicit

The pie sensor SHALL return detected legend entries, OCR snippets, and
label-to-sector associations as bounded evidence when available. Association
search SHALL support labels and legends around the detected plot region rather
than assuming one fixed side. A resolved association SHALL include its source,
support, or confidence; an unresolved or ambiguous association SHALL remain
null or uncertain and SHALL be reported in warnings instead of being silently
guessed. Printed percentages or numeric values SHALL be retained separately
from geometry-derived ratios.

#### Scenario: Legend labels are associated with sectors

- **WHEN** a clean pie chart has a legend whose colors match the sectors and
  the legend is placed on any supported side or layout
- **THEN** the result associates each reliably matched legend label with the
  corresponding stable sector ID
- **AND** sector color, legend geometry, label source, and association evidence
  remain available for Agent review

#### Scenario: External labels and leader lines retain evidence

- **WHEN** a pie chart places labels outside the circle and connects them to
  sectors with leader lines or spatial ordering
- **THEN** the sensor preserves the label location and the geometric or
  leader-line evidence used for the association
- **AND** it marks the association unresolved or ambiguous when the evidence
  cannot distinguish between sectors

#### Scenario: Printed values are distinguished from inferred ratios

- **WHEN** a pie chart contains percentage or numeric labels
- **THEN** the result records the recognized printed value and its association
  confidence separately from the sector's geometry-derived ratio
- **AND** an unrecognized or conflicting printed value does not overwrite the
  geometry evidence

#### Scenario: Ambiguous association is surfaced

- **WHEN** two sectors or labels have insufficiently distinguishable color,
  spatial, OCR, or leader-line evidence
- **THEN** the affected association is unresolved or marked uncertain
- **AND** the result contains a warning naming the ambiguity

### Requirement: Pie totals, confidence, and visual evidence are validated

Every pie sensor result SHALL include bounded confidence metadata and warnings
for geometry, sector support, association, and total consistency. It SHALL
report angle and ratio totals, per-sector support or residual evidence when
available, and SHALL identify when the reliably detected sectors do not
account for approximately 360 degrees or 100 percent within the configured
tolerance. The sensor SHALL generate a source-sized overlay marking the
detected plot region, center/radius or boundary geometry, sector boundaries,
stable IDs, colors, resolved associations, and unresolved or unsupported
evidence when present.

#### Scenario: Consistent pie totals pass

- **WHEN** detected sectors cover the pie circle and their ratios sum within
  tolerance of 1.0
- **THEN** the result marks the totals as consistent, keeps every confidence
  value within `[0, 1]`, and returns the source-sized overlay
- **AND** the geometry, sector support, and association status are available
  separately from the overall confidence

#### Scenario: Incomplete sectors produce a warning

- **WHEN** sector boundaries are occluded, merged, narrow beyond reliable
  resolution, or otherwise leave an angle or ratio total outside tolerance
- **THEN** the result preserves the detected sectors and their partial
  geometry evidence
- **AND** it reports a bounded total-consistency or sector-support warning
- **AND** it does not present the incomplete result as a certain complete pie

#### Scenario: Overlay uses one source-image coordinate convention

- **WHEN** the pie sensor returns valid or partial geometry
- **THEN** the overlay draws the same center, boundary, sector IDs, and labels
  represented in the serialized result
- **AND** its dimensions match the original source image
- **AND** material residuals, unresolved associations, or unsupported geometry
  are visible without changing the source dimensions

#### Scenario: Generated evidence is model-visible

- **WHEN** the pie sensor returns structured data and a valid overlay
- **THEN** the existing Agent visual-observation path presents the overlay on
  the next model turn while keeping the structured result available
- **AND** richer pie evidence does not require a new Gateway route or a new
  frontend preview protocol
