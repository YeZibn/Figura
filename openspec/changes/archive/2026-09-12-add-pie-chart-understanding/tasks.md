## 1. Pie Evidence Contract

- [x] 1.1 Define the pie sensor result shape for circular-region evidence, sector geometry, colors, legend/OCR evidence, totals, confidence, and warnings without changing the existing ChartSpec serialization contract.
- [x] 1.2 Confirm bounded result and error handling matches `ToolResult`, authorized attachment wrappers, and generated visual observation limits.

## 2. Independent Pie Sensor

- [x] 2.1 Add a path-compatible `extract_pie_slices` sensor that validates local image input and detects a reliable circular pie region using the existing image-processing dependencies.
- [x] 2.2 Implement deterministic center/radius estimation, radial color sampling, sector boundary detection, clockwise stable IDs, angular spans, and normalized ratios for clean non-donut pies.
- [x] 2.3 Add separate OCR and legend association evidence for labels, percentages, and numeric values, preserving unresolved or ambiguous associations as warnings.
- [x] 2.4 Add angle/ratio total consistency checks and bounded geometry, association, total, and overall confidence values.
- [x] 2.5 Generate a source-sized pie overlay showing the circular region, sector boundaries, IDs, colors, and unresolved associations.

## 3. Agent Integration

- [x] 3.1 Register `extract_pie_slices` with the chart tool registry and expose only the authorized `attachment_id` schema in Agent mode.
- [x] 3.2 Verify pie tool failures remain structured and do not reveal canonical paths or generate artifacts for unauthorized or unreadable attachments.
- [x] 3.3 Verify the existing Agent visual-observation path delivers valid pie overlays on the next model turn without adding a Gateway route or forcing a fixed tool sequence.
- [x] 3.4 Verify `assemble_spec` and `validate_spec` accept the resulting categorical pie data without axes, while leaving value-source decisions explicit to the Agent.

## 4. Fixtures and Tests

- [x] 4.1 Add deterministic pie fixtures and ground truth for distinguishable sectors, legend labels, printed percentages/numeric labels, and a no-axis chart layout.
- [x] 4.2 Add sensor tests for sector count, center/radius, angular spans, normalized ratios, stable IDs, source-sized overlays, and structured missing/non-image errors.
- [x] 4.3 Add tests for legend/OCR associations, separate printed values versus inferred ratios, ambiguous labels/colors, incomplete sectors, and total-consistency warnings.
- [x] 4.4 Add attachment-boundary and registry tests for authorized and unauthorized pie-sensor calls.
- [x] 4.5 Add an offline scripted Agent-loop acceptance test proving pie evidence can be assembled into an axis-free ChartSpec and independently validated without a prescribed tool order.

## 5. Verification

- [x] 5.1 Run focused pie, ChartSpec, attachment, and Agent-loop tests with `conda run -n agent` and fix regressions.
- [x] 5.2 Run the full Python suite, frontend build, and existing Gateway/UI smoke checks using the documented project commands.
- [x] 5.3 Run `openspec validate add-pie-chart-understanding --type change --strict` and reconcile any proposal, spec, design, or task inconsistencies.
