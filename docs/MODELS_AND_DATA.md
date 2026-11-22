# Models and data

## 1. Model and weights

AURA uses **OpenAI CLIP ViT-B/32** with the Xenova ONNX conversion pinned to revision `6b7c523703ae26e39be4b03774966f8571c7f523`. ONNX Runtime uses the CPU execution provider. The unsigned 8-bit vision and text graphs are 88,648,915 and 64,070,835 bytes respectively. The tokenizer brings the download to roughly 155 MB (148 MiB). Setup checks SHA-256 against the bundled artifact manifest. Weights are fetched once and inference is local.

```bash
python TEAM_ID/code/fetch_weights.py
python TEAM_ID/code/fetch_weights.py --weights-dir /path/to/weights
```

Set `AURA_WEIGHTS_DIR` to the same location for the second form. The project ZIP contains the fetcher and manifest. To prepare for an offline run, fetch and verify these files in advance.

CLIP's image-text alignment makes zero-shot comparison against a small custom vocabulary practical with CPU inference. Video classifiers trained on generic fixed categories need an additional mapping to the organizer labels. A supervised EPIC-specific action model could cover many more actions with stronger temporal cues, but brings a dedicated checkpoint, larger runtime requirements, and a separate integration and validation job. AURA uses one image encoder for both recognition tasks and requires no training.

The video reader samples at 2 fps by default and downscales large frames to a longest side of 320 pixels before converting to RGB. The model processes frames in batches of up to 16. The image processor resizes the shortest side to 224 pixels using Pillow bicubic interpolation, then center crops to 224×224, scales to [0, 1], standardizes channels with CLIP's original means and standard deviations, and returns float32 NCHW tensors. The tokenizer uses the model's CLIP BPE vocabulary and 77-token context. ONNX output embeddings are L2-normalized and compared with cosine similarity. Logits use the checkpoint's scale of 100.

The runtime compares each frame embedding against text prototypes. Each of the 16 activity categories has two natural-language prompts. The video label is selected from the softmax of video-wide averaged similarities. Per-frame support for the selected label also feeds highlight ranking. The action module pools frame similarities over fixed two-second windows, compares 79 joint verb–noun prompts with seven background alternatives, and abstains unless a pair wins with a softmax score of at least 0.12 and a cosine margin of at least 0.015. At least two sampled frames must support the window. Adjacent windows with the same winning pair can merge. These scores depend on the prompt sets and are uncalibrated. The fixed windows provide coarse localization.

The prompt pairs use canonical organizer keys. Their co-occurrence was cross-checked against the EPIC-KITCHENS-100 training annotations at revision `ea8b40457a400c3fffa1c7f406ef3dc169cc2522`. The deployed model uses the prompt bank and never loads training annotations. The annotation repository is published under CC BY-NC 4.0. [EPIC-KITCHENS-100 training annotations](https://github.com/epic-kitchens/epic-kitchens-100-annotations/blob/ea8b40457a400c3fffa1c7f406ef3dc169cc2522/EPIC_100_train.csv) · [Annotation license](https://github.com/epic-kitchens/epic-kitchens-100-annotations/blob/ea8b40457a400c3fffa1c7f406ef3dc169cc2522/license.txt)

The converted model card lists the MIT license, and OpenAI CLIP publishes an MIT license. The model card and original repository describe intended usage and limitations. Dataset media and annotations have separate terms. [Xenova artifact revision](https://huggingface.co/Xenova/clip-vit-base-patch32/tree/6b7c523703ae26e39be4b03774966f8571c7f523) · [OpenAI CLIP model and preprocessing](https://github.com/openai/CLIP) · [OpenAI CLIP license](https://github.com/openai/CLIP/blob/main/LICENSE)

## 2. Datasets (from the student README and `manifest.csv`)

| Dataset | Videos in manifest | Used for scoring (README only) |
|---|---|---|
| EPIC-KITCHENS-100 validation split (`epic_kitchens_100`) | 138 | Action mAP, Action coverage |
| FPVSum (`fpvsum`) | 49 | Highlight F1, Label accuracy |

**The videos themselves are not part of the kit.** The README says to download them yourself (EPIC is stated as about 184 GB; FPVSum via `yt-dlp`).
The organizer gives the download sources below. They have separate dataset terms. The complete evaluation set was not needed to develop this package.
**Ground-truth evaluation annotations are absent from the supplied kit.**

[EPIC-KITCHENS-100](https://epic-kitchens.github.io/2020) · [EPIC-KITCHENS downloader](https://github.com/epic-kitchens/epic-kitchens-download-scripts) · [FPVSum](https://github.com/azuxmioy/fpvsum)

### Manifest facts (verified)

| Fact | Value |
|---|---|
| Rows / unique IDs | 187 / 187 (no duplicates or blanks) |
| Columns | `video_id,duration_sec,dataset`; CRLF line endings |
| Duration range | 11.13 s (`P03_26`) to 1968.60 s (`P24_09`, 32.8 min); total 15.58 hours |
| EPIC: mean / median | 344.5 s / 216.1 s (range 11.13-1968.60 s) |
| FPVSum: mean / median | 174.7 s / 159.0 s (range 37.34-377.07 s) |
| Inside the "2-10 min" claim | 113 of 187 (120-600 s); 57 shorter, 17 longer |
| Videos where 15% is less than 4 s | 3: `P03_26` (11.13 s), `P26_30` (15.28 s), `P28_23` (25.16 s); the break-even duration is 4 / 0.15 = 26.67 s |
| Videos with a 15% budget under 8 s | 14 |
| EPIC participants | 32 distinct prefixes (`P01`, `P02`, ...) |
| FPVSum per category | Bike 4, BikePolo 4, Boxing 3, Horse 4, Jumping 4, Longboarding 3, Motor 4, Parkour 4, Plane 3, RockClimbing 3, Scuba 3, Skate 2, Ski 4, Surfing 4 (sum 49) |
| Non-standard IDs | `BikePolo_5yf797Lh4Oc_1`, `BikePolo_ccTGFdD18SM_1`, `BikePolo_DHbYfmjX3WQ_1`, `BikePolo_DHbYfmjX3WQ_3` carry a `_1`/`_3` suffix the README does not explain |

The manifest is the source of evaluation IDs and durations. Several videos fall outside the guide's typical range of two to ten minutes.

## 3. Taxonomy (`supported_classes.json`, version `prism2026-theme01-v1`)

| List | Entries | Notes |
|---|---|---|
| `labels` | 16 | 14 FPVSum categories (lowercase), `cooking`, `other` |
| `verbs` | 98 | includes `other` |
| `nouns` | 301 | includes `other`; 33 use a colon form such as `board:chopping` |

The file is **bundled unmodified** at `TEAM_ID/code/resources/supported_classes.json`; its SHA-256 (`e9403017...`) is recorded in `tests/fixtures/SHA256SUMS`
and verified by a test. The 16/98/301 counts are asserted **only in tests**, never in production code (`DECISIONS.md` D-016).
Labels use the order: `bike, bikepolo, boxing, cooking, horse, jumping, longboarding, motor, parkour, plane, rockclimbing, scuba, skate, ski, surfing, other`.

## 4. Sample files and their known issues

| File | Facts | Issues |
|---|---|---|
| `P02_109.json` | `team_id` `T07`, duration 512.3 s, label `cooking` (0.96), 3 actions, 4 highlights | `P02_109` is **not in the manifest** (the manifest has `P02_12`-`P02_15`), so its duration cannot be cross-checked. Otherwise it validates cleanly under the `readme6` profile with the bundled taxonomy. |
| `skiing_03.json` | `team_id` `T07`, duration 258.0 s, label `skiing` (0.91), 2 actions, 3 highlights | **`skiing` is not a taxonomy label** (the taxonomy has `ski`); `skiing_03` is **not in the manifest**. Everything else validates. |

Both samples are stored byte-for-byte in `tests/fixtures/` and are verified against recorded hashes. The slide 22 example uses the ID `P01_01`, which is also not in the manifest
(the manifest has `P01_11`-`P01_15`) and its `"label": "category"` is a placeholder, not a value.

## 5. Data generated by our own tests

Integration tests write a **synthetic MP4** (64x48 pixels, constant-color frames, 10 fps, 1000 frames = 100 s) to a temporary folder and delete it afterwards.
It exists to exercise video-metadata code, **not** to represent real egocentric video.

## 6. Limitations

- CLIP encodes sampled still frames. It can miss short hand–object interactions, distinguish some states more readily than similar motions, and lose relevant content near the edges after the center crop.
- The action prompt set covers a subset of canonical pairs. Background competition, confidence and margin filters can leave `actions` empty. There is no calibrated recall or temporal localization benchmark.
- Highlight importance combines hand-weighted visual and model signals. A flash or camera shake can attract a high motion score, and a quiet but meaningful event can receive a low score.
- The submission kit omits the official validator and evaluation annotations. Duration based on OpenCV metadata can be imprecise on variable-frame-rate media. The full workspace records independent verification in `docs/TESTING.md`.
