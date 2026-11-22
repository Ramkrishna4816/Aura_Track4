"""Convert selected EPIC-KITCHENS-100 validation rows to the AURA evaluation format."""
from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path

TAXONOMY = Path(__file__).resolve().parents[1] / "TEAM_ID/code/resources/supported_classes.json"


def seconds(timestamp: str) -> float:
    hours, minutes, seconds = timestamp.split(":")
    return float(int(hours) * 3600 + int(minutes) * 60 + Decimal(seconds))


def prepare_reference(
    annotations: Path, video_info: Path, verb_classes: Path, noun_classes: Path, video_ids: list[str],
) -> dict:
    """Use official class IDs, retaining unsupported pairs in the denominator."""
    if len(video_ids) != len(set(video_ids)):
        raise ValueError("duplicate video ID")
    taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    verbs, nouns = set(taxonomy["verbs"]), set(taxonomy["nouns"])
    with verb_classes.open(newline="", encoding="utf-8-sig") as handle:
        verb_keys = {row["id"]: row["key"] for row in csv.DictReader(handle)}
    with noun_classes.open(newline="", encoding="utf-8-sig") as handle:
        noun_keys = {row["id"]: row["key"] for row in csv.DictReader(handle)}
    with video_info.open(newline="", encoding="utf-8-sig") as handle:
        durations = {row["video_id"]: float(row["duration"]) for row in csv.DictReader(handle)}
    videos = {
        video_id: {"video_id": video_id, "duration_sec": durations[video_id], "actions": []}
        for video_id in video_ids
    }
    seen = dict.fromkeys(video_ids, 0)
    noncanonical = dict.fromkeys(video_ids, 0)
    with annotations.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            video_id = row["video_id"]
            if video_id not in videos:
                continue
            seen[video_id] += 1
            verb, noun = verb_keys[row["verb_class"]], noun_keys[row["noun_class"]]
            if verb not in verbs or noun not in nouns:
                noncanonical[video_id] += 1
            start, stop = seconds(row["start_timestamp"]), seconds(row["stop_timestamp"])
            duration = durations[video_id]
            if not 0 <= start < stop <= duration + 0.1:
                raise ValueError(f"{video_id}: invalid EPIC interval {[start, stop]}")
            videos[video_id]["actions"].append(
                {"verb": verb, "noun": noun, "segment": [start, min(stop, duration)]}
            )
    missing = [video_id for video_id, count in seen.items() if not count]
    if missing:
        raise ValueError(f"no source annotations for {', '.join(missing)}")
    return {"videos": list(videos.values()), "source_action_counts": seen, "noncanonical_counts": noncanonical}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--video-info", type=Path, required=True)
    parser.add_argument("--verb-classes", type=Path, required=True)
    parser.add_argument("--noun-classes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("video_ids", nargs="+")
    args = parser.parse_args()
    report = prepare_reference(args.annotations, args.video_info, args.verb_classes, args.noun_classes, args.video_ids)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    noncanonical = sum(report["noncanonical_counts"].values())
    print(f"Wrote {len(report['videos'])} videos. References outside the output taxonomy: {noncanonical}.")


if __name__ == "__main__":
    main()
