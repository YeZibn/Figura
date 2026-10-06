# image-observation-decoding Specification

## Purpose

Defines consistent visible-pixel decoding for OCR and chart-measurement observations so transparent content cannot become hidden evidence and optional observation regions retain source dimensions and coordinate identity.

## Requirements

### Requirement: Image observations use white-composited visible source pixels
Figura SHALL apply the same visible-pixel decoding behavior to independent OCR and bar, line, scatter, and pie observations over Attachments and Panels. Image alpha SHALL be composited onto a white background before RGB detection. Fully transparent pixels SHALL be excluded from observation regardless of their stored RGB values. Partially transparent pixels SHALL remain observable using their white-composited color. Observation feedback overlays SHALL also white-composite source alpha so they do not reveal hidden RGB while displaying committed candidates. Opaque images SHALL preserve their original RGB data. Observation decoding SHALL NOT modify stored source bytes, crop the image, rescale it, or change its source coordinate frame.

#### Scenario: Ignore hidden color outside a Panel polygon
- **WHEN** a Panel contains alpha-zero pixels outside its accepted polygon whose stored RGB contains text or chart colors
- **THEN** those pixels are white in the observation input and excluded by the observation mask rather than supplying OCR, color, axis, or geometry evidence

#### Scenario: Composite partially transparent pixels
- **WHEN** an observation source contains a pixel with nonzero partial alpha
- **THEN** detection receives its color composited against white and the pixel remains observable

#### Scenario: Preserve an opaque source
- **WHEN** the source is fully opaque and no observation scope is supplied
- **THEN** detection receives its original RGB values and dimensions without an artificial transparency exclusion

### Requirement: Visibility and requested scope form one source-coordinate observation mask
The effective observed pixels SHALL be source-visible pixels intersected with the union of requested include polygons minus the union of requested exclude polygons. Omitted include SHALL begin from the complete source extent. Excluded or fully transparent pixels SHALL be neutralized to white. OCR candidates SHALL be retained only when their entire bounding box is within the effective mask. Geometry detection SHALL operate on remaining pixels and SHALL NOT reconstruct excluded or invisible object parts; clipped shapes SHALL NOT imply complete-source coverage. Existing source-coordinate result identities SHALL be preserved.

#### Scenario: Combine transparency with an explicit scope
- **WHEN** an include polygon crosses visible and transparent Panel pixels and an exclude polygon overlaps part of the visible content
- **THEN** the effective mask retains only visible included pixels outside the exclusion and the observation result still uses that Panel's original pixel coordinate frame

#### Scenario: Reject a text box crossing invisible pixels
- **WHEN** an OCR candidate bounding box intersects an excluded or fully transparent pixel
- **THEN** the complete candidate is omitted rather than reporting a partially observed string as complete text

#### Scenario: Detect only retained geometry
- **WHEN** an observation mask cuts through a colored geometric mark
- **THEN** detection uses only its remaining visible pixels and does not claim that the missing part was observed or restored

### Requirement: Empty observable images fail explicitly
An explicit observation scope that leaves no effective observable pixels SHALL fail with the existing bounded `invalid_observation_scope` error. A source with no visible pixels and no explicit scope SHALL fail with the existing bounded `image_unavailable` error. Neither case SHALL fall back to hidden RGB data or full-source analysis, and no detector SHALL be invoked over an empty observation.

#### Scenario: Scope selects only transparent pixels
- **WHEN** a supplied scope has geometric area but selects no source-visible pixels
- **THEN** the observation tool returns `invalid_observation_scope` without running OCR or geometry detection

#### Scenario: Entire source is transparent
- **WHEN** an Attachment or Panel has no visible pixels and scope is omitted
- **THEN** the observation tool returns `image_unavailable` without creating a successful observation from hidden RGB content
