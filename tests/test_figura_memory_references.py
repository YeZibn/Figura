from __future__ import annotations

import pytest

from figura.memory.references import (
    MessageSourceRef,
    ToolResultSourceRef,
    source_ref_from_dict,
)


def test_history_source_references_round_trip_without_losing_run_identity() -> None:
    refs = (
        MessageSourceRef("run-1", "record-1"),
        ToolResultSourceRef("run-2", "call-1"),
    )

    assert tuple(source_ref_from_dict(ref.to_dict()) for ref in refs) == refs
    assert refs[0].to_dict() == {"kind": "message", "run_id": "run-1", "record_id": "record-1"}
    assert refs[1].to_dict() == {"kind": "tool_result", "run_id": "run-2", "call_id": "call-1"}


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"kind": "message", "run_id": "run-1", "record_id": "record-1", "session_id": "other"},
        {"kind": "tool_result", "run_id": "", "call_id": "call-1"},
        {"kind": "unknown", "run_id": "run-1", "call_id": "call-1"},
    ],
)
def test_source_reference_parser_rejects_malformed_or_scoped_references(value) -> None:
    with pytest.raises(ValueError):
        source_ref_from_dict(value)


def test_reference_identifiers_are_nonempty_and_valid_utf8() -> None:
    with pytest.raises(ValueError):
        MessageSourceRef("run-1", "")
    with pytest.raises(ValueError):
        ToolResultSourceRef("run-1", "\ud800")
