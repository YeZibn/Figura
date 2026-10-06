# line-chart-measurement Specification

## Purpose

Provides source-bound pixel traces and cautiously calibrated point observations for supported two-dimensional line charts, allowing the Agent to use visual measurements without treating uncertain pixels or OCR as exact chart data.

## Requirements

### Requirement: Keep line measurements as candidate evidence
Line measurements SHALL remain observations for the Agent to interpret. OCR labels and geometry SHALL be treated as fallible evidence, and Figura SHALL NOT automatically repeat a measurement, select a preferred series, or block later Agent actions because of a warning. The durable JSON result SHALL NOT contain overlays, image bytes, or local paths.

#### Scenario: Leave series and evidence selection to the Agent
- **WHEN** the result contains multiple series, uncertain labels, or warnings
- **THEN** Figura returns all supported observations and leaves their interpretation and selection to the Agent

#### Scenario: Do not emit uncalibrated numeric points
- **WHEN** a detected line point lies on an uncalibrated numeric axis
- **THEN** the corresponding chart-unit coordinate is null while the source-pixel position remains available
