"""Build and serve the AURA dashboard for the six audited public development clips."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from make_rescue_comparison import ROOT, RUN, relative_url, render_page, workspace_path
from prepare_epic_reference import prepare_reference
from rescue_demo_server import serve_demo


CLIPS = ("P06_02", "P06_08", "P09_01", "P09_04", "P14_02", "P14_03")
ARM_NAMES = {"stock": "stock", "refined": "factorized-refined"}
RELEASE = ROOT / "evaluation/final_release"
REFERENCES = RELEASE / "public_development_reference.json"
MEDIA_ROOT = ROOT / "data/EPIC/development/EPIC-KITCHENS"
BENCHMARK = RUN / "live_benchmark.json"
ANNOTATIONS = ROOT / "data/EPIC/annotations/public"
SOURCE = "EPIC-KITCHENS-100 public training annotations"
SOURCE_REVISION = "ea8b40457a400c3fffa1c7f406ef3dc169cc2522"
THRESHOLD = 0.30


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def export_references() -> None:
    receipt = read_json(ROOT / "evaluation/expanded_ranking_run/results.json")
    paths = [ANNOTATIONS / f"EPIC_100_{suffix}.csv" for suffix in ("train", "video_info", "verb_classes", "noun_classes")]
    hashes = {path.name: sha256(path) for path in paths}
    if hashes != receipt["annotations"]:
        raise ValueError("Public annotation SHA-256 differs from the audited development inputs.")
    videos = prepare_reference(*paths, list(CLIPS))["videos"]
    document = {
        "source": SOURCE,
        "revision": SOURCE_REVISION,
        "license": "CC BY-NC 4.0",
        "annotation_sha256": hashes,
        "transformation": "Filter the six development IDs, resolve class IDs, and convert bounds to seconds.",
        "videos": videos,
    }
    write_new_or_identical(REFERENCES, (json.dumps(document, indent=2) + "\n").encode(), replace=False)


def write_new_or_identical(path: Path, content: bytes, *, replace: bool) -> None:
    if path.exists():
        if path.read_bytes() == content:
            return
        if not replace:
            raise ValueError(f"File already exists with different content: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb" if replace else "xb") as destination:
        destination.write(content)


def action_metrics(detection: dict) -> dict:
    keys = ("ground_truth_actions", "predicted_actions", "true_positives", "false_positives",
            "false_negatives", "precision", "recall", "false_positives_per_minute")
    return {key: detection[key] for key in keys}


def threshold(detections: dict) -> dict:
    return next(row for row in detections["thresholds"] if row["tiou_threshold"] == THRESHOLD)


def make_dashboard(output: Path, media_root: Path, *, replace: bool) -> dict[str, Path]:
    if output.suffix.lower() != ".html":
        raise ValueError("The dashboard output must be an .html file.")
    benchmark = read_json(BENCHMARK)
    public = {video["video_id"]: video for video in read_json(REFERENCES)["videos"]}
    if set(public) != set(CLIPS) or any(set(arm["videos"]) != set(CLIPS) for arm in benchmark["arms"].values()):
        raise ValueError("The reference and benchmark must cover exactly the six allowed public videos.")
    routes = {quote("/" + output.relative_to(ROOT).as_posix()): output}
    clips = []
    for video in CLIPS:
        source = (media_root / video.split("_")[0] / "videos" / f"{video}.MP4").resolve()
        reference = public[video]
        media_hash = benchmark["arms"]["stock"]["videos"][video]["source_sha256"]
        if source.is_file() and sha256(source) != media_hash:
            raise ValueError(f"Original source SHA-256 mismatch for {video}: {source}")
        media_url = f"/development-media/{video}.MP4"
        routes[media_url] = source
        clip = {"videoId": video, "videoUrl": media_url, "sourceHash": media_hash,
                "duration": reference["duration_sec"], "references": reference["actions"], "metrics": {}}
        for model, arm in ARM_NAMES.items():
            prediction = RUN / arm / f"{video}.json"
            record = benchmark["arms"][arm]["videos"][video]
            if record["source_sha256"] != media_hash:
                raise ValueError(f"Source hashes disagree for {video}.")
            detection = threshold(record["detections"])
            if detection["ground_truth_actions"] != len(reference["actions"]):
                raise ValueError(f"The public reference count disagrees for {video}.")
            if prediction.is_file() and sha256(prediction) != record["prediction_sha256"]:
                raise ValueError(f"Saved prediction SHA-256 mismatch for {arm}/{video}.")
            clip[f"{model}Url"] = relative_url(prediction, output)
            routes[quote("/" + prediction.relative_to(ROOT).as_posix())] = prediction
            clip["metrics"][model] = {**action_metrics(detection), "highlights": record["highlights"],
                                      "mean_map": record["detections"]["mean_macro_map_across_ious"],
                                      "ap": [row["macro_map"] for row in record["detections"]["thresholds"]],
                                      "runtime_seconds": record["runtime_seconds"]}
        clips.append(clip)
    overview = {}
    for model, arm in ARM_NAMES.items():
        aggregate = benchmark["arms"][arm]
        overview[model] = {
            **action_metrics(threshold(aggregate["detections"])),
            "mean_map": aggregate["detections"]["mean_macro_map_across_ious"],
            "zero_action_videos": sum(row["action_count"] == 0 for row in aggregate["videos"].values()),
            "coverage": aggregate["highlight_capture"]["micro_fraction"],
            "pairs_covered": aggregate["highlight_capture"]["captured_pairs"],
            "pairs_total": aggregate["highlight_capture"]["ground_truth_pairs"],
        }
    page = render_page({"clips": clips, "overview": overview, "referenceSource": SOURCE,
                        "matchThreshold": THRESHOLD}, "Development evaluation dashboard")
    write_new_or_identical(output, page.encode("utf-8"), replace=replace)
    return routes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RELEASE / "MULTI_VIDEO_DASHBOARD.html")
    parser.add_argument("--media-root", type=Path, default=MEDIA_ROOT, help="authorized EPIC-KITCHENS directory")
    parser.add_argument("--export-reference", action="store_true", help="extract the audited public six-video annotations")
    parser.add_argument("--replace", action="store_true", help="regenerate the dashboard HTML")
    parser.add_argument("--serve", action="store_true", help="serve the dashboard and its selected inputs on loopback")
    parser.add_argument("--open", action="store_true", help="open the default browser when serving")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.open and not args.serve:
        parser.error("--open requires --serve")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be in [0, 65535]")
    try:
        if args.export_reference:
            export_references()
        output = workspace_path(args.output)
        routes = make_dashboard(output, args.media_root.resolve(), replace=args.replace)
        print(f"Dashboard HTML: {output.relative_to(ROOT)}", flush=True)
        if args.serve:
            serve_demo(routes=routes, port=args.port, demo_route=quote("/" + output.relative_to(ROOT).as_posix()),
                       open_browser=args.open)
    except (OSError, ValueError, KeyError, StopIteration) as error:
        parser.exit(1, f"Dashboard error: {error}\n")


if __name__ == "__main__":
    main()
