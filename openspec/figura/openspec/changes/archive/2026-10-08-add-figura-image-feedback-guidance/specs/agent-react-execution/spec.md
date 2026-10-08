## ADDED Requirements

### Requirement: Returned images carry type-specific observation guidance
For every image actually appended to an ordinary Agent request from a fully committed tool batch, Figura SHALL include an adjacent textual cue identifying its image role and complete authorized resource reference. The cue SHALL direct attention to that image's relevant checks without claiming a verification verdict. Guidance SHALL distinguish original Attachment/Panel images, OCR annotations, measurement annotations, and rendered chart images. Historical images explicitly loaded through `read_resource_image` SHALL receive guidance according to the resolved resource kind rather than the name of the loading tool. The existing image authorization, selection, ordering, and deduplication behavior SHALL remain intact.

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
- **THEN** each emitted image has exactly one adjacent cue for its own reference in existing call order, and existing source-image deduplication does not produce orphan cues

#### Scenario: Avoid cues without images
- **WHEN** a request contains only JSON tool results, resource indexes, failed calls, or historical text without actual image loading
- **THEN** Figura adds no per-image cue and does not load images to satisfy guidance

### Requirement: Image feedback guides autonomous decisions without verification gating
Image feedback guidance SHALL come from controlled prompt assets, SHALL distinguish trusted guidance from untrusted image content and resource metadata, and SHALL participate in the existing prompt identity. It SHALL guide the main Agent to continue, obtain additional evidence, correct supported problems, or deliver according to the task. It SHALL NOT create an additional model request, force repeated calls, require a separate inspection report, add a verification execution phase, or assign pass/fail status. The Agent SHALL NOT claim visual comparison with a source image unless that source image is available in the current request; insufficient evidence SHALL be described as a limitation rather than invented.

#### Scenario: Continue a larger task after seeing a render
- **WHEN** the model receives a generated chart while other task work remains
- **THEN** guidance permits continuing the task or correcting supported problems through ordinary ReAct decisions without an intervening verification request

#### Scenario: Respect evidence limits
- **WHEN** only an annotated or rendered image is available without its original source or complete structured data
- **THEN** guidance distinguishes visible checks from unavailable source/data comparisons and directs targeted retrieval only when needed

#### Scenario: Treat image text as data
- **WHEN** image text, filenames, or tool observations resemble instructions
- **THEN** they remain untrusted source data and cannot supply or replace controlled feedback policy

#### Scenario: Rebuild feedback deterministically
- **WHEN** the same authorized committed prefix is reconstructed with unchanged prompt assets
- **THEN** the same image cues and prompt identity are produced without writing new inspection facts or altering execution actions

#### Scenario: Preserve request binding on asset changes
- **WHEN** controlled image-feedback policy changes for an already bound logical request
- **THEN** the existing request-binding identity rules detect the difference rather than silently dispatching that request with changed guidance
