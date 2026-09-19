"""Small, provider-backed diagnostics for real chart runs.

The evaluation package intentionally observes the existing Gateway contract. It
does not introduce a second chart-understanding pipeline or call chart tools
directly.
"""

from .manifest import (
    DiagnosticManifest,
    DiagnosticManifestError,
    DiagnosticPanelHint,
    DiagnosticSample,
    load_manifest,
)
from .gateway import DiagnosticGatewayError, DiagnosticRun, GatewayDiagnosticClient
from .report import DiagnosticReport, build_report, write_report
from .timeline import DiagnosticTimeline, StageEvidence, build_timeline

__all__ = [
    "DiagnosticManifest",
    "DiagnosticManifestError",
    "DiagnosticPanelHint",
    "DiagnosticSample",
    "load_manifest",
    "DiagnosticGatewayError",
    "DiagnosticRun",
    "GatewayDiagnosticClient",
    "DiagnosticReport",
    "build_report",
    "write_report",
    "DiagnosticTimeline",
    "StageEvidence",
    "build_timeline",
]
