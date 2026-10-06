# bar-chart-measurement Specification

## Purpose

Provides structured, source-bound pixel measurements for two-dimensional bar charts so the Agent can use geometric evidence without treating uncertain image analysis as exact chart data.

## Requirements

### Requirement: Keep bar measurements as candidate evidence
Bar measurements SHALL remain observations for the Agent to interpret. Figura SHALL return chart-unit values only when OCR-derived numeric ticks and pixel-axis geometry pass the declared calibration gate; it SHALL retain pixel geometry and uncertainty when calibration fails. Figura SHALL NOT automatically repeat measurement or block later Agent actions because of a warning, and SHALL NOT expose image overlays, local paths, or raw image bytes in the measurement result. A readable image with uncertain or unsupported geometry SHALL remain a successful observation; source authorization or image-read failures SHALL use the bounded tool error contract.

#### Scenario: Do not infer chart-unit values without calibration
- **WHEN** a bar baseline and geometry are detected but the numeric value axis has no accepted calibration
- **THEN** the result contains pixel lengths and relative ratios only, with null calibrated values

#### Scenario: Leave evidence selection to the Agent
- **WHEN** a measurement result contains warnings or partial evidence
- **THEN** Figura returns the observation without scheduling a repeat measurement or imposing an assembly gate

#### Scenario: Keep image payloads outside measurement results
- **WHEN** the measurement tool returns a result
- **THEN** the durable JSON result contains measurement data only and no image bytes, overlay, or local filesystem path
