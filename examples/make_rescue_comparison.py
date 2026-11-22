"""Build and optionally open the local AURA model-comparison demo."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
from pathlib import Path
import re
from string import Template
from urllib.parse import quote

from rescue_demo_server import serve_demo


ROOT = Path(__file__).resolve().parents[1]
ASSETS = Path(__file__).resolve().with_name("rescue_demo")
RUN = ROOT / "evaluation/final_quality_pass"
VIDEO = ROOT / "data/EPIC/development/EPIC-KITCHENS/P06/videos/P06_02.MP4"
P06_02_SHA256 = "683775c69b9ccce5e5585c67ddeaf88db8a50ba42fc866576837f6259668e210"


def public_references(video_id: str) -> list[dict]:
    """Read the audited dishwasher reference from the public EPIC training CSV."""
    if video_id != "P06_02":
        return []
    directory = ROOT / "data/EPIC/annotations/public"
    if not (directory / "EPIC_100_train.csv").is_file():
        subset = ROOT / "evaluation/final_release/public_development_reference.json"
        videos = json.loads(subset.read_text(encoding="utf-8"))["videos"]
        return [item for video in videos if video["video_id"] == video_id for item in video["actions"]
                if item["verb"] == "open" and item["noun"] == "dishwasher" and item["segment"] == [3.14, 4.65]]
    class_ids = []
    for kind, label in (("verb", "open"), ("noun", "dishwasher")):
        with (directory / f"EPIC_100_{kind}_classes.csv").open(encoding="utf-8-sig", newline="") as source:
            class_ids.append(next(row["id"] for row in csv.DictReader(source) if row["key"] == label))

    def seconds(value: str) -> float:
        hours, minutes, seconds_text = value.split(":")
        return 3600 * int(hours) + 60 * int(minutes) + float(seconds_text)

    with (directory / "EPIC_100_train.csv").open(encoding="utf-8-sig", newline="") as source:
        references = [
            {"verb": "open", "noun": "dishwasher", "segment": list(map(seconds, (
                row["start_timestamp"], row["stop_timestamp"],
            )))}
            for row in csv.DictReader(source)
            if row["video_id"] == video_id and [row["verb_class"], row["noun_class"]] == class_ids
        ]
    if [row["segment"] for row in references] != [[3.14, 4.65]]:
        raise ValueError("The public P06_02 reference differs from the audited interval.")
    return references


def relative_url(path: Path, output: Path) -> str:
    return quote(Path(os.path.relpath(path, output.parent)).as_posix())


def workspace_path(path: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"Demo paths must stay in the AURA workspace: {path}")
    return path


def render(video: Path, stock: Path, refined: Path, output: Path) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", video.stem) or video.suffix.lower() != ".mp4":
        raise ValueError("Supply an MP4 named for the prediction video ID.")
    if any(path.suffix.lower() != ".json" for path in (stock, refined)) or output.suffix.lower() != ".html":
        raise ValueError("Use .json for prediction inputs and .html for the demo output.")
    with video.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if video.stem == "P06_02" and digest != P06_02_SHA256:
        raise ValueError("P06_02 source SHA-256 does not match the audited original.")
    config = {
        "videoId": video.stem,
        "videoUrl": relative_url(video, output),
        "stockUrl": relative_url(stock, output),
        "refinedUrl": relative_url(refined, output),
        "references": public_references(video.stem),
        "referenceSource": "EPIC-KITCHENS-100 public training annotations",
        "matchThreshold": 0.3,
        "sourceHash": digest,
    }
    return render_page(config, f"{video.stem} model comparison")


def render_page(config: dict, title: str) -> str:
    template = Template((ASSETS / "comparison.html").read_text(encoding="utf-8"))
    return template.substitute(
        title=html.escape(title),
        config=json.dumps(config, ensure_ascii=True).replace("<", "\\u003c"),
        styles=(ASSETS / "comparison.css").read_text(encoding="utf-8"),
        playback=(ASSETS.parent / "rescue_demo_playback.js").read_text(encoding="utf-8"),
        app=(ASSETS / "comparison.js").read_text(encoding="utf-8"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=VIDEO)
    parser.add_argument("--stock", type=Path, default=RUN / "stock/P06_02.json")
    parser.add_argument("--refined", type=Path, default=RUN / "factorized-refined/P06_02.json")
    parser.add_argument("--output", type=Path, default=RUN / "demo/P06_02.html")
    parser.add_argument("--replace", action="store_true", help="update a previously generated HTML page")
    parser.add_argument("--serve", action="store_true", help="serve the demo and its three inputs on loopback")
    parser.add_argument("--open", action="store_true", help="open the served demo in the default browser")
    parser.add_argument("--port", type=int, default=8765, help="loopback port, or 0 for any free port")
    args = parser.parse_args()
    if args.open and not args.serve:
        parser.error("--open requires --serve")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be in [0, 65535]")
    try:
        video, stock, refined, output = map(workspace_path, (args.video, args.stock, args.refined, args.output))
        page = render(video, stock, refined, output).encode("utf-8")
        if not output.exists() or output.read_bytes() != page:
            if output.exists() and not args.replace:
                raise ValueError("The HTML exists. Use --replace to regenerate it, or choose a new --output path.")
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("wb" if args.replace else "xb") as target:
                target.write(page)
        print(f"Demo HTML: {output.relative_to(ROOT)}", flush=True)
        if args.serve:
            routes = {quote("/" + path.relative_to(ROOT).as_posix()): path
                      for path in (output, video, stock, refined)}
            serve_demo(routes=routes, port=args.port,
                       demo_route=quote("/" + output.relative_to(ROOT).as_posix()), open_browser=args.open)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Demo error: {error}\n")


if __name__ == "__main__":
    main()
