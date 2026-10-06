# scatter-chart-measurement Specification

## Purpose

Provides source-bound point geometry and cautiously calibrated coordinates for supported two-dimensional scatter charts, preserving series identity and visible uncertainty for Agent interpretation.

## Requirements

### Requirement: Keep scatter measurements as candidate evidence
Scatter measurements SHALL remain observations for the Agent to interpret. OCR labels, point detections, and overlap flags SHALL be treated as fallible evidence, and Figura SHALL NOT automatically repeat measurement or block later Agent actions because of a warning. The durable JSON result SHALL NOT contain overlays, image bytes, or local paths.

#### Scenario: Leave series and evidence selection to the Agent
- **WHEN** a result contains multiple series, ambiguous point associations, or warnings
- **THEN** Figura returns the supported observations and leaves their interpretation and selection to the Agent

#### Scenario: Do not emit uncalibrated numeric coordinates
- **WHEN** a detected point lies on an uncalibrated numeric axis
- **THEN** the corresponding chart-unit coordinate is null while the pixel position remains available
