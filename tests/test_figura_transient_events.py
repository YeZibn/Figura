from __future__ import annotations

from queue import Empty

from figura.gateway.transient_events import TransientRunEventHub


def test_transient_events_fan_out_only_within_the_session():
    hub = TransientRunEventHub()
    first_token, first = hub.subscribe("session-a", "run-shared")
    second_token, second = hub.subscribe("session-a", "run-shared")
    other_token, other_session = hub.subscribe("session-b", "run-shared")
    try:
        hub.publish("session-a", "run-shared", "attempt-1", 1, "hello")

        expected = {
            "runId": "run-shared",
            "attemptId": "attempt-1",
            "deltaSequence": 1,
            "text": "hello",
        }
        assert first.get_nowait() == expected
        assert second.get_nowait() == expected
        try:
            other_session.get_nowait()
        except Empty:
            pass
        else:
            raise AssertionError("transient output crossed Session ownership")
    finally:
        hub.unsubscribe("session-a", "run-shared", first_token)
        hub.unsubscribe("session-a", "run-shared", second_token)
        hub.unsubscribe("session-b", "run-shared", other_token)


def test_transient_event_queue_is_bounded_and_exposes_a_sequence_gap():
    hub = TransientRunEventHub()
    token, channel = hub.subscribe("session", "run")
    try:
        for sequence in range(1, 140):
            hub.publish("session", "run", "attempt", sequence, str(sequence))

        events = []
        while True:
            try:
                events.append(channel.get_nowait())
            except Empty:
                break

        assert len(events) == 128
        assert events[0]["deltaSequence"] > 1
        assert events[-1]["deltaSequence"] == 139
        assert events[1]["deltaSequence"] == events[0]["deltaSequence"] + 1
    finally:
        hub.unsubscribe("session", "run", token)


def test_transient_event_validation_rejects_private_or_unbounded_chunks():
    hub = TransientRunEventHub()
    token, channel = hub.subscribe("session", "run")
    try:
        hub.publish("session", "run", "attempt", 0, "invalid sequence")
        hub.publish("session", "run", "attempt", 1, "x" * 70_000)
        hub.publish("session", "run", "attempt", 2, "valid")

        assert channel.get_nowait()["text"] == "valid"
        try:
            channel.get_nowait()
        except Empty:
            pass
        else:
            raise AssertionError("invalid transient output was published")
    finally:
        hub.unsubscribe("session", "run", token)
