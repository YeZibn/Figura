"""Transient observation reuse, bounded to one authorized tool invocation."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

import numpy as np


@dataclass
class ObservationContext:
    rgb: np.ndarray
    mask: np.ndarray | None
    ocr: object | None = None
    regions: dict[tuple, tuple] = field(default_factory=dict)


_current: ContextVar[ObservationContext | None] = ContextVar("measurement_observation", default=None)


def observation_context():
    return _current.get()


@contextmanager
def shared_observation(rgb, mask):
    token = _current.set(ObservationContext(rgb, mask))
    try:
        yield _current.get()
    finally:
        _current.reset(token)
