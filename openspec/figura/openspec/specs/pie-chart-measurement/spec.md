# pie-chart-measurement Specification

## Purpose

Provides source-bound geometric observations for supported two-dimensional circular pie charts, allowing the Agent to use sector ratios while preserving uncertainty and unsupported-chart boundaries.

## Requirements

### Requirement: Keep pie measurements as candidate evidence
Pie measurements SHALL remain observations for the Agent to interpret. Figura SHALL derive a sector ratio only from angular coverage of the observed full pie and SHALL NOT infer source data values from labels, colors, or OCR. It SHALL NOT automatically repeat measurement or block later Agent actions because of a warning. The durable JSON result SHALL NOT contain overlays, image bytes, or local paths.

#### Scenario: Do not infer source values from sector appearance
- **WHEN** a pie sector has a visible label or color but its angular share is uncertain
- **THEN** Figura leaves `ratio` null and does not convert the label or color into a numeric source value

#### Scenario: Leave evidence selection to the Agent
- **WHEN** a pie result contains warnings or partial evidence
- **THEN** Figura returns the observation without scheduling a repeat measurement or imposing an assembly gate

#### Scenario: Keep image payloads outside pie results
- **WHEN** the pie measurement tool returns a result
- **THEN** the durable JSON result contains measurement data only and no image bytes, overlay, or local filesystem path
