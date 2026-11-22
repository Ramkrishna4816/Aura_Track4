"""Zero-shot activity classification and coarse action localization from CLIP."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Iterable, Iterator, Protocol, Sequence, TypeVar

import numpy as np
from numpy.typing import NDArray

from .importance_scoring import FrameEvidence, VisualEvidence
from .models import ActionSegment, Label
from .taxonomy import Taxonomy

DEFAULT_PROMPT_BANK = Path(__file__).resolve().parent.parent / "resources" / "prompt_bank.json"
RGBFrame = NDArray[np.uint8]
EmbeddingMatrix = NDArray[np.float32]
Sample = tuple[float, RGBFrame]
Item = TypeVar("Item")


class ClipEmbeddingModel(Protocol):
    @property
    def logit_scale(self) -> float:
        """Checkpoint similarity multiplier before softmax."""

    def encode_images(self, frames: Sequence[RGBFrame]) -> EmbeddingMatrix:
        """Return one unit-normalized embedding for each RGB image."""

    def encode_text(self, prompts: Sequence[str]) -> EmbeddingMatrix:
        """Return one unit-normalized embedding for each prompt."""


@dataclass(frozen=True)
class ClipPredictionSettings:
    batch_size: int = 16
    action_window_s: float = 2.0
    action_min_samples: int = 2
    action_min_probability: float = 0.12
    action_min_margin: float = 0.015

    def __post_init__(self) -> None:
        for name in ("batch_size", "action_min_samples"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not math.isfinite(self.action_window_s) or self.action_window_s <= 0:
            raise ValueError("action_window_s must be finite and positive")
        if not 0.0 <= self.action_min_probability <= 1.0:
            raise ValueError("action_min_probability must be in [0, 1]")
        if not 0.0 < self.action_min_margin <= 2.0:
            raise ValueError("action_min_margin must be in (0, 2]")


@dataclass(frozen=True)
class ActionPrompt:
    verb: str
    noun: str
    prompt: str


@dataclass(frozen=True)
class PromptBank:
    labels: dict[str, tuple[str, ...]]
    actions: tuple[ActionPrompt, ...]
    background: tuple[str, ...]


def _is_prompt(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _prompts(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(_is_prompt(item) for item in value):
        raise ValueError(f"{field} must contain at least one non-empty prompt")
    return tuple(value)


def load_prompt_bank(path: Path, taxonomy: Taxonomy) -> PromptBank:
    """Validate prompt coverage and verify that every joint action is canonical."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"cannot load CLIP prompt bank {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("CLIP prompt bank must be a JSON object")
    labels = data.get("labels")
    if not isinstance(labels, dict) or set(labels) != taxonomy.label_set:
        raise ValueError("CLIP label prompts must cover exactly the canonical activity labels")
    label_prompts = {label: _prompts(labels[label], f"labels.{label}") for label in taxonomy.labels}

    actions = data.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("CLIP prompt bank requires at least one joint action prompt")
    pairs: set[tuple[str, str]] = set()
    action_prompts: list[ActionPrompt] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError(f"actions[{index}] must be an object")
        verb, noun, prompt = action.get("verb"), action.get("noun"), action.get("prompt")
        if not taxonomy.has_verb(verb) or not taxonomy.has_noun(noun):
            raise ValueError(f"actions[{index}] has noncanonical pair ({verb!r}, {noun!r})")
        pair = (verb, noun)
        if pair in pairs or not _is_prompt(prompt):
            raise ValueError(f"actions[{index}] duplicates a pair or lacks a prompt")
        pairs.add(pair)
        action_prompts.append(ActionPrompt(verb, noun, prompt))
    background = _prompts(data.get("background"), "background")
    return PromptBank(label_prompts, tuple(action_prompts), background)


def _batches(items: Iterable[Item], size: int) -> Iterator[list[Item]]:
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def _softmax(similarities: NDArray[np.floating], scale: float) -> NDArray[np.floating]:
    # Subtract the maximum first so large scales cannot overflow the exponent.
    weights = np.exp((similarities - similarities.max(axis=-1, keepdims=True)) * scale)
    return weights / weights.sum(axis=-1, keepdims=True)


def _embeddings(value: EmbeddingMatrix, count: int) -> EmbeddingMatrix:
    if value.ndim != 2 or value.shape[0] != count or not value.shape[1] or not np.isfinite(value).all():
        raise ValueError("CLIP encoder returned invalid embeddings")
    return value


class ClipPredictor:
    """Pair sampled frame evidence with a replaceable CLIP embedding backend."""

    def __init__(
        self,
        encoder: ClipEmbeddingModel,
        taxonomy: Taxonomy,
        *,
        settings: ClipPredictionSettings = ClipPredictionSettings(),
        prompt_path: Path = DEFAULT_PROMPT_BANK,
    ) -> None:
        if not math.isfinite(encoder.logit_scale) or encoder.logit_scale <= 0:
            raise ValueError("CLIP logit scale must be finite and positive")
        self.encoder = encoder
        self.settings = settings
        self.prompts = load_prompt_bank(prompt_path, taxonomy)
        self._prompt_embeddings: tuple[EmbeddingMatrix, EmbeddingMatrix] | None = None

    def _encode_prompts(self) -> tuple[EmbeddingMatrix, EmbeddingMatrix]:
        if self._prompt_embeddings is None:
            counts = [len(prompts) for prompts in self.prompts.labels.values()]
            texts = [prompt for prompts in self.prompts.labels.values() for prompt in prompts]
            texts.extend(item.prompt for item in self.prompts.actions)
            texts.extend(self.prompts.background)
            vectors = np.concatenate([
                _embeddings(self.encoder.encode_text(batch), len(batch))
                for batch in _batches(texts, self.settings.batch_size)
            ])
            breakpoints = np.cumsum(counts)
            label_groups = np.split(vectors[:breakpoints[-1]], breakpoints[:-1])
            prototypes = np.stack([group.mean(axis=0) for group in label_groups])
            norms = np.linalg.norm(prototypes, axis=1, keepdims=True)
            if np.any(norms <= 0):
                raise ValueError("CLIP label prompt ensemble produced a zero embedding")
            self._prompt_embeddings = (prototypes / norms, vectors[breakpoints[-1]:])
        return self._prompt_embeddings

    def _action(
        self, index: int, scores: NDArray[np.floating], count: int, duration: float,
    ) -> ActionSegment | None:
        if count < self.settings.action_min_samples:
            return None
        average = scores / count
        winner = int(average.argmax())
        if winner >= len(self.prompts.actions):
            return None  # An explicit background description ranked first.
        runner_up = np.partition(average, -2)[-2]
        if average[winner] - runner_up < self.settings.action_min_margin:
            return None
        confidence = float(_softmax(average, self.encoder.logit_scale)[winner])
        if confidence < self.settings.action_min_probability:
            return None
        pair = self.prompts.actions[winner]
        window = self.settings.action_window_s
        return ActionSegment(pair.verb, pair.noun, index * window, min((index + 1) * window, duration), confidence)

    @staticmethod
    def _append_action(actions: list[ActionSegment], action: ActionSegment | None) -> None:
        if action is None:
            return
        if actions:
            previous = actions[-1]
            if (previous.verb, previous.noun, previous.end) == (action.verb, action.noun, action.start):
                previous_weight = previous.end - previous.start
                weight = action.end - action.start
                confidence = (previous.confidence * previous_weight + action.confidence * weight) / (
                    previous_weight + weight
                )
                actions[-1] = ActionSegment(action.verb, action.noun, previous.start, action.end, confidence)
                return
        actions.append(action)

    def predict(
        self, samples: Iterable[Sample], duration: float,
    ) -> tuple[Label, list[ActionSegment], list[FrameEvidence]]:
        """Predict from bounded frame batches and preserve source-video timestamps."""
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("duration must be finite and positive")
        label_vectors, action_vectors = self._encode_prompts()
        labels = tuple(self.prompts.labels)
        visual_evidence = VisualEvidence()
        actions: list[ActionSegment] = []
        timestamps: list[float] = []
        visual_values: list[tuple[float, float, float]] = []
        label_similarities: list[EmbeddingMatrix] = []
        active_window = 0
        window_sample_count = 0
        window_score_sum = np.zeros(len(action_vectors), dtype=np.float64)
        previous_time = -1.0

        for batch in _batches(samples, self.settings.batch_size):
            frames: list[RGBFrame] = []
            for timestamp, frame in batch:
                if not math.isfinite(timestamp) or not 0 <= timestamp < duration or timestamp <= previous_time:
                    raise ValueError("sample timestamps must increase within the source video")
                previous_time = timestamp
                timestamps.append(timestamp)
                visual_values.append(visual_evidence.update(frame))
                frames.append(frame)

            images = _embeddings(self.encoder.encode_images(frames), len(frames))
            label_similarities.append(images @ label_vectors.T)
            for (timestamp, _), scores in zip(batch, images @ action_vectors.T, strict=True):
                window_index = int(timestamp / self.settings.action_window_s)
                if window_index != active_window:
                    self._append_action(actions, self._action(
                        active_window, window_score_sum, window_sample_count, duration,
                    ))
                    active_window = window_index
                    window_sample_count = 0
                    window_score_sum.fill(0.0)
                window_score_sum += scores
                window_sample_count += 1

        if not timestamps:
            raise ValueError("video provided no sampled frames")
        self._append_action(actions, self._action(active_window, window_score_sum, window_sample_count, duration))

        similarities = np.concatenate(label_similarities)
        video_scores = _softmax(similarities.mean(axis=0, dtype=np.float64), self.encoder.logit_scale)
        label_index = int(video_scores.argmax())
        label = Label(labels[label_index], float(video_scores[label_index]))
        relevance = _softmax(similarities, self.encoder.logit_scale)[:, label_index]
        evidence = [
            FrameEvidence(timestamp, motion, novelty, float(score), transition)
            for timestamp, (motion, novelty, transition), score in zip(timestamps, visual_values, relevance, strict=True)
        ]
        return label, actions, evidence
