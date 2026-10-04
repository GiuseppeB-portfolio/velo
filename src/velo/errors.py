"""Exceptions raised by velo. Messages are user-facing (Italian)."""


class VeloError(Exception):
    """Base class for all expected errors."""


class UnsupportedFileError(VeloError):
    """The file cannot be read safely (wrong format, unknown encoding, ...)."""


class EncodingError(VeloError):
    """A replacement value cannot be written in the file's encoding."""


class PlanError(VeloError):
    """The plan refers to fields that do not exist in the file."""
