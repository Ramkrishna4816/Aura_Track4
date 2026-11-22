"""Single source of truth for AURA configuration constants.

Nothing in this module depends on the organizer's starter kit. Values that are
engineering assumptions (not organizer-specified) are marked ASSUMPTION so they
can be revisited once the official kit is inspected.
"""
from __future__ import annotations

# --- Highlight selection -----------------------------------------------------
# Initial highlight budget target as a fraction of video duration. Selection
# never exceeds it. ASSUMPTION: confirm the organizer's tolerance in the kit.
HIGHLIGHT_BUDGET_RATIO: float = 0.15

# Candidates shorter than this are not eligible as highlights (they stay in the
# action list). There is deliberately NO maximum: long actions are never dropped
# for being long. ASSUMPTION: the 1.0 s minimum is inherited, not organizer-set.
MIN_HIGHLIGHT_SEGMENT_S: float = 1.0

# If True, a candidate that does not fit the remaining budget is trimmed to a
# centered window instead of being skipped. Off until measured with the official
# evaluator.
TRIM_TO_FIT: bool = False

# --- Time handling -----------------------------------------------------------
TIME_PRECISION_DECIMALS: int = 3     # timestamps are rounded to milliseconds
TIME_EPSILON: float = 1e-6           # tolerance used by output validation
BUDGET_EPSILON: float = 1e-9         # tolerance used inside selection (stricter)
# Predictions that overshoot [0, duration] by at most this many seconds are
# clipped (frame_count/fps rounding); larger overshoots are rejected and
# reported, since they usually indicate an upstream unit/timebase bug.
BOUNDARY_TOLERANCE_S: float = 0.5
SAMPLE_FPS: float = 2.0
SAMPLE_MAX_SIDE_PX: int = 320

# --- Output ------------------------------------------------------------------
JSON_INDENT: int = 2

# --- Process exit codes (CLI contract: non-zero means no valid output) --------
EXIT_OK: int = 0
EXIT_UNEXPECTED: int = 1
EXIT_USAGE: int = 2
EXIT_INPUT_ERROR: int = 3        # video missing/unreadable
EXIT_INFERENCE_ERROR: int = 4    # recognizer or labeler failed / not configured
EXIT_VALIDATION_ERROR: int = 5   # predictions or output failed validation
EXIT_OUTPUT_ERROR: int = 6       # could not write the output file

# --- Serialization profiles --------------------------------------------------
# Exactly one profile is active; there is no code path that emits both.
# Provisional default: the six-key student-README schema. The four-key slide
# schema ("slide4") stays available but inactive until the organizers confirm
# which schema is authoritative.
ACTIVE_PROFILE: str = "readme6"
SHORT_HIGHLIGHT_POLICY: str = "minimum"

# Rules stated by the student README (TEAM_README.md sections 3-4). The official
# validate.py was not supplied, so these are the documented rules, not verified
# validator behavior.
README6_TIME_DECIMALS: int = 2                 # "up to 2 decimal places"
README6_MIN_HIGHLIGHT_SEGMENT_S: float = 4.0   # at least one highlight segment >= 4.0 s
README6_MAX_ACTIONS: int = 2000                # "0-2000 items"
README6_SEGMENT_END_TOLERANCE_S: float = 0.5   # end <= duration_sec + 0.5

# The slide 22 example states no timestamp precision. Reusing 2 decimals is a
# conservative local choice, not a slide requirement.
SLIDE4_TIME_DECIMALS: int = 2
