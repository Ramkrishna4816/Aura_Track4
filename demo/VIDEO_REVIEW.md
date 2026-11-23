# AURA silent demonstration

[Play or download the silent MP4](AURA_Track4_Demo_Silent.mp4)

This cut uses the AURA presentation architecture and genuine captures from the six-clip development dashboard. The captures conceal original video frames and detailed reference overlays. The 23 on-screen captions describe the same measured development results as the evaluator portal.

| Property | Verified result |
|---|---|
| Filename | `AURA_Track4_Demo_Silent.mp4` |
| Duration | 2 min 49.53 s |
| Frame size and rate | 1920 × 1080 at 30 fps |
| Video codec | H.264 High, YUV 4:2:0 |
| Decoded frames | 5,086 |
| Audio streams | 0 |
| File size | 3,334,313 bytes |
| SHA-256 | `a5877f9e349805c710433cf3e34e52fbbfb0d6fe7707bc153866f8522b7d6f2a` |

FFmpeg 7.1 copied the existing video stream without re-encoding. Its encoded packet hash matched the review render, which preserves the original masking and captions. The MP4 contains only the video stream. A full FFmpeg decode completed without errors. Edge played the file and resumed playback after seeking to 36, 92, 124 and 166 seconds.
