"""Interface for separate action recognizers supplied to the pipeline."""
from __future__ import annotations

from typing import Protocol

from .models import RecognitionResult


class RecognizerNotConfiguredError(NotImplementedError):
    """No real recognizer has been wired in."""


class Recognizer(Protocol):
    def recognize(self, video_path: str) -> RecognitionResult:
        """Return the video id and raw action predictions (seconds)."""
        ...


class UnconfiguredRecognizer:
    """Explicit placeholder for callers that supply their own adapters."""

    def recognize(self, video_path: str) -> RecognitionResult:
        raise RecognizerNotConfiguredError(
            "Custom action recognizer is not configured. Supply a Recognizer implementation."
        )
