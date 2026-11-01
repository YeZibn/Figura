"""Prepare annotation pixels during execution, before publishing a result."""
from figura.shared.media import ResourceImage
from figura.shared.resource_refs import ToolResourceRef
from figura.tools.contracts import ToolContext, ToolFailure, ToolImageOutput, ToolOutput
from figura.tools.measurements.visualization import render_measurement_overlay


def annotation_output(context: ToolContext, result, source_bytes: bytes, image_kind) -> ToolOutput:
    kind = 'ocr' if image_kind == 'ocr_annotation' else 'measurement'
    try:
        png = render_measurement_overlay(source_bytes, result, 'extract_text' if kind == 'ocr' else 'measure_chart')
        image = ResourceImage.from_bytes(png)
        return ToolOutput(result, (ToolImageOutput(ToolResourceRef(kind, context.run_id, context.call_id), image_kind, image),))
    except (OSError, ValueError, TypeError, RuntimeError):
        raise ToolFailure('image_feedback_unavailable', '观察标注图当前无法准备。', retryable=True) from None
