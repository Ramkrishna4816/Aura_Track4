"""Interface for separate video labelers supplied to the pipeline."""
from __future__ import annotations

from typing import Protocol, Sequence

from .models import ActionSegment, Label


class LabelerNotConfiguredError(NotImplementedError):
    """No taxonomy-backed labeler has been wired in."""


class VideoLabeler(Protocol):
    def label_video(self, video_id: str, actions: Sequence[ActionSegment]) -> Label:
        """Return a canonical video label with its inference score."""
        ...


class UnconfiguredLabeler:
    """Explicit placeholder for callers that supply their own adapters."""

    def label_video(self, video_id: str, actions: Sequence[ActionSegment]) -> Label:
        raise LabelerNotConfiguredError(
            "Custom video labeler is not configured. Supply a VideoLabeler implementation."
        )
