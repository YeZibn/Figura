"""Errors shared by Gateway persistence collaborators."""


class HistoryStoreError(Exception):
    """A bounded persistence or artifact failure."""


__all__ = ["HistoryStoreError"]
