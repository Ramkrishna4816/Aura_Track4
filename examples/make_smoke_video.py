"""Generate a 36-second test video with motion and scene changes."""
from __future__ import annotations

import argparse
from pathlib import Path


def make_smoke_video(output: Path) -> None:
    import cv2
    import numpy as np

    fps = 12
    width, height = 320, 180
    seconds_per_scene = 12
    scenes = ((95, 53, 22), (60, 106, 23), (42, 72, 111))
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise OSError(f"OpenCV could not create {output}")
    try:
        for scene, color in enumerate(scenes):
            for index in range(fps * seconds_per_scene):
                frame = np.full((height, width, 3), color, dtype=np.uint8)
                x = 35 + (index * (scene + 3)) % (width - 70)
                y = height // 2 + round(30 * np.sin(index / (scene + 7)))
                cv2.circle(frame, (x, y), 25, (235, 215, 165), -1)
                writer.write(frame)
    finally:
        writer.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="path to the MP4 to create")
    args = parser.parse_args()
    make_smoke_video(args.output)
