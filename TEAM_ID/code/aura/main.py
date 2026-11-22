"""Run video inference, select highlights, and atomically publish one JSON document."""
from __future__ import annotations

import logging
import math
import os
import sys
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from . import config
from .action_recognition import Recognizer
from .highlight_selection import SelectionResult, select_highlights_with_report, select_video_highlights
from .importance_scoring import FrameEvidence, ImportanceWeights, VisualEvidence, score_actions
from .io_utils import atomic_write_text
from .labeling import VideoLabeler
from .models import ActionSegment, Label, RecognitionResult, VideoContext, VideoPrediction
from .normalize import NormalizationError, NormalizationReport, as_real, normalize_actions
from .preprocessing import VideoDecodeError, get_video_info, sample_video
from .serialization import ProfileValidationError, ValidationReport, get_profile
from .taxonomy import Taxonomy, load_bundled_taxonomy

if TYPE_CHECKING:
    from numpy import ndarray

logger = logging.getLogger("aura")
TEAM_DIR = Path(__file__).resolve().parents[2]
USAGE = "Usage: python run_aura.py <video.mp4> <out.json>"


class PipelineError(Exception):
    """A stage failed with the given process exit code."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class VideoPredictor(Protocol):
    """Joint inference over timestamped RGB frames in source order."""

    def predict(self, samples: Iterable[tuple[float, ndarray]], duration: float
                ) -> tuple[Label, list[ActionSegment], list[FrameEvidence]]:
        ...


@dataclass(frozen=True)
class PipelineResult:
    output: dict
    normalization: NormalizationReport
    selection: SelectionResult
    output_path: Path
    validation: ValidationReport


def _validate_paths(video_path: str, output_path: str) -> None:
    source, target = Path(video_path), Path(output_path)
    try:
        same_file = source.resolve() == target.resolve()
        if not same_file and target.exists() and source.exists():
            same_file = target.samefile(source)
    except (OSError, RuntimeError) as exc:
        raise PipelineError(f"could not compare input and output paths: {exc}", config.EXIT_OUTPUT_ERROR) from exc
    if same_file:
        raise PipelineError("input video and output path identify the same file", config.EXIT_OUTPUT_ERROR)


def run_pipeline(
    video_path: str,
    output_path: str,
    *,
    predictor: VideoPredictor | None = None,
    recognizer: Recognizer | None = None,
    labeler: VideoLabeler | None = None,
    taxonomy: Taxonomy | None = None,
    profile_name: str | None = None,
    team_id: str | None = None,
    weights_dir: Path | None = None,
    sample_fps: float = config.SAMPLE_FPS,
    action_window_s: float | None = None,
    budget_ratio: float = config.HIGHLIGHT_BUDGET_RATIO,
    min_segment_s: float = config.MIN_HIGHLIGHT_SEGMENT_S,
    trim_to_fit: bool = config.TRIM_TO_FIT,
    short_policy: str = config.SHORT_HIGHLIGHT_POLICY,
    importance_weights: ImportanceWeights = ImportanceWeights(),
    highlight_strategy: str | None = None,
) -> PipelineResult:
    """Summarize a video, with an optional experimental highlight planner."""
    alternate_planner = None
    try:
        profile = get_profile(config.ACTIVE_PROFILE if profile_name is None else profile_name)
        if highlight_strategy is not None:
            from .competition_highlights import STRATEGIES, select_competition_highlights

            if highlight_strategy not in STRATEGIES or recognizer is not None:
                raise ValueError("select a supported highlight strategy with frame-evidence inference")
            alternate_planner = select_competition_highlights
        if not math.isfinite(sample_fps) or sample_fps <= 0:
            raise ValueError("sample FPS must be finite and positive")
        if action_window_s is not None:
            if not math.isfinite(action_window_s) or action_window_s <= 0:
                raise ValueError("action window must be finite and positive")
            if predictor is not None or recognizer is not None:
                raise ValueError("set the action window on the supplied prediction adapter")
        if not math.isfinite(budget_ratio) or not 0 < budget_ratio <= 1:
            raise ValueError("budget ratio must be in (0, 1]")
        if not math.isfinite(min_segment_s) or min_segment_s < 0:
            raise ValueError("minimum highlight duration must be finite and nonnegative")
        if short_policy not in {"minimum", "budget"}:
            raise ValueError("highlight policy must be 'minimum' or 'budget'")
        if (recognizer is None) != (labeler is None) or (predictor is not None and recognizer is not None):
            raise ValueError("supply a joint predictor or both a recognizer and a labeler")
    except (ValueError, KeyError, TypeError) as exc:
        raise PipelineError(f"configuration error: {exc}", config.EXIT_USAGE) from exc

    try:
        info = get_video_info(video_path)
    except (ValueError, OSError) as exc:
        raise PipelineError(f"input video error: {exc}", config.EXIT_INPUT_ERROR) from exc
    except ImportError as exc:
        raise PipelineError(f"OpenCV is required: {exc}", config.EXIT_INFERENCE_ERROR) from exc
    duration = info["duration"]
    _validate_paths(video_path, output_path)

    try:
        taxonomy = load_bundled_taxonomy() if taxonomy is None else taxonomy
    except ValueError as exc:
        raise PipelineError(f"taxonomy error: {exc}", config.EXIT_VALIDATION_ERROR) from exc

    evidence = None
    video_id = Path(video_path).stem
    try:
        if recognizer is not None:
            recognition = recognizer.recognize(video_path)
            if not isinstance(recognition, RecognitionResult):
                raise TypeError(f"expected RecognitionResult, got {type(recognition).__name__}")
            video_id, raw_actions = recognition.video_id, list(recognition.actions)
        else:
            if predictor is None:
                from .clip_backend import ClipEncoder
                from .clip_predictor import ClipPredictionSettings, ClipPredictor

                settings = (ClipPredictionSettings() if action_window_s is None else
                            ClipPredictionSettings(action_window_s=action_window_s))
                predictor = ClipPredictor(ClipEncoder(TEAM_DIR / "weights" if weights_dir is None else weights_dir),
                                          taxonomy, settings=settings)
            with closing(sample_video(video_path, info, sample_fps)) as samples:
                label, predicted_actions, evidence = predictor.predict(samples, duration)
            raw_actions = list(predicted_actions)
    except VideoDecodeError as exc:
        raise PipelineError(f"input video error: {exc}", config.EXIT_INPUT_ERROR) from exc
    except Exception as exc:
        raise PipelineError(f"model inference failed: {exc}", config.EXIT_INFERENCE_ERROR) from exc

    precision = config.README6_TIME_DECIMALS if profile.name == "readme6" else config.SLIDE4_TIME_DECIMALS
    try:
        actions, report = normalize_actions(raw_actions, duration, precision=precision)
    except NormalizationError as exc:
        raise PipelineError(f"normalization failed: {exc}", config.EXIT_VALIDATION_ERROR) from exc
    logger.info("normalize: %s", report.summary())
    for item in report.rejected:
        logger.warning("rejected action #%d: %s (%s)", item.index, item.reason.value, item.detail)
    if raw_actions and not actions:
        raise PipelineError(f"all {len(raw_actions)} predicted actions were invalid ({report.reason_counts()})",
                            config.EXIT_VALIDATION_ERROR)
    if not raw_actions:
        logger.info("model returned no action segments")

    if labeler is not None:
        try:
            label = labeler.label_video(video_id, actions)
        except Exception as exc:
            raise PipelineError(f"video labeling failed: {exc}", config.EXIT_INFERENCE_ERROR) from exc
    score = as_real(label.score) if isinstance(label, Label) else None
    if score is None or not 0 <= score <= 1:
        raise PipelineError("label prediction must contain a finite score between 0 and 1",
                            config.EXIT_VALIDATION_ERROR)

    if evidence is None and profile.name == "slide4":
        # The separate legacy adapters provide action confidence as their sole signal.
        selection = select_highlights_with_report(score_actions(actions), duration, budget_ratio,
                                                  min_segment_s, trim_to_fit)
    else:
        if evidence is None:
            visual = VisualEvidence()
            with closing(sample_video(video_path, info, sample_fps)) as samples:
                try:
                    evidence = []
                    for timestamp, frame in samples:
                        motion, novelty, transition = visual.update(frame)
                        evidence.append(FrameEvidence(timestamp, motion, novelty, 0.0, transition))
                except VideoDecodeError as exc:
                    raise PipelineError(f"input video error: {exc}", config.EXIT_INPUT_ERROR) from exc
        selection_options = {
            "profile": profile.name, "budget_ratio": budget_ratio, "min_segment_s": min_segment_s,
            "short_policy": short_policy, "importance_weights": importance_weights,
        }
        if alternate_planner is None:
            selection = select_video_highlights(evidence, actions, duration, **selection_options)
        else:
            selection = alternate_planner(evidence, actions, duration, strategy=highlight_strategy, **selection_options)
    logger.info("highlights: selected=%d skipped=%d used=%.3fs budget=%.3fs",
                len(selection.highlights), len(selection.skipped), selection.used_s, selection.budget_s)
    for skip in selection.skipped:
        logger.debug("highlight candidate skipped: [%s, %s] %s %s", skip.candidate.start,
                     skip.candidate.end, skip.reason.value, skip.detail)

    if profile.name == "readme6" and len(actions) > config.README6_MAX_ACTIONS:
        # Stable ties prefer chronological order. Keep the remaining items time-sorted.
        ranked = sorted(range(len(actions)), key=lambda index: -actions[index].confidence)
        actions = [actions[index] for index in sorted(ranked[:config.README6_MAX_ACTIONS])]
        logger.warning("retaining %d highest-confidence actions for readme6", len(actions))
    prediction = VideoPrediction(
        VideoContext(TEAM_DIR.name if team_id is None else team_id, video_id, duration),
        Label(label.name, score),
        actions,
        selection.highlights,
    )
    minimum = config.README6_MIN_HIGHLIGHT_SEGMENT_S
    allow_short = profile.name == "readme6" and (
        duration < minimum or (short_policy == "budget" and duration * budget_ratio < minimum)
    )
    try:
        serialized = profile.serialize_with_report(
            prediction, taxonomy=taxonomy, budget_ratio=budget_ratio, allow_short_highlights=allow_short,
        )
    except ProfileValidationError as exc:
        raise PipelineError(f"{profile.name} output validation failed: {exc}", config.EXIT_VALIDATION_ERROR) from exc
    for issue in serialized.report.warnings:
        logger.warning("%s", issue.format())
    try:
        atomic_write_text(output_path, serialized.text)
    except (OSError, ValueError) as exc:
        raise PipelineError(f"could not write output: {exc}", config.EXIT_OUTPUT_ERROR) from exc
    return PipelineResult(serialized.data, report, selection, Path(output_path), serialized.report)


def main(
    argv: Sequence[str] | None = None,
    *,
    predictor: VideoPredictor | None = None,
    recognizer: Recognizer | None = None,
    labeler: VideoLabeler | None = None,
) -> int:
    """Validate CLI settings, run the pipeline, and return its process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print(USAGE, file=sys.stderr)
        return config.EXIT_USAGE
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s aura: %(message)s")
    try:
        weights = os.environ.get("AURA_WEIGHTS_DIR")
        action_window = os.environ.get("AURA_ACTION_WINDOW_SECONDS")
        try:
            sample_fps = float(os.environ.get("AURA_SAMPLE_FPS", config.SAMPLE_FPS))
            budget_ratio = float(os.environ.get("AURA_BUDGET_RATIO", config.HIGHLIGHT_BUDGET_RATIO))
            min_segment_s = float(os.environ.get("AURA_MIN_HIGHLIGHT_SECONDS", config.MIN_HIGHLIGHT_SEGMENT_S))
            action_window_s = None if action_window is None else float(action_window)
        except ValueError as exc:
            raise PipelineError(f"invalid numeric AURA setting: {exc}", config.EXIT_USAGE) from exc
        run_pipeline(
            args[0], args[1], predictor=predictor, recognizer=recognizer, labeler=labeler,
            profile_name=os.environ.get("AURA_PROFILE"),
            team_id=os.environ.get("AURA_TEAM_ID"),
            weights_dir=Path(weights).expanduser() if weights else None,
            short_policy=os.environ.get("AURA_HIGHLIGHT_POLICY", config.SHORT_HIGHLIGHT_POLICY),
            sample_fps=sample_fps, budget_ratio=budget_ratio, min_segment_s=min_segment_s,
            action_window_s=action_window_s,
        )
    except PipelineError as exc:
        logger.error("%s", exc)
        return exc.exit_code
    except Exception:
        logger.exception("unexpected internal error")
        return config.EXIT_UNEXPECTED
    return config.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
