# AURA development dashboard

This engineering release adds a six-video local dashboard and browser verification. The 33 production files and the pinned model manifest remain byte-identical to the prior frozen build. The optional scorer and the two-frame experiment remain development-only. The dashboard reads saved stock and refined results and shows annotations separately.

## Inputs

Use Python 3.12 and the team's local engineering handoff. It supplies the six-video benchmark, its attributed public reference subset and 12 saved development JSONs. Place them in the corresponding `evaluation/final_release` and `evaluation/final_quality_pass` directories. Use publisher-authorized original MP4s in the EPIC-KITCHENS directory with its original participant subdirectories. No original footage, annotation payload, model binaries, or internal development predictions are hosted on this release branch.

From the project root, run the following PowerShell command.

~~~powershell
py -3.12 -B examples/make_multi_video_dashboard.py --media-root '<authorized EPIC-KITCHENS directory>' --serve --open
~~~

The browser tests require Node 22+ and a local Edge installation. The six authorized originals belong under `data/EPIC/development/EPIC-KITCHENS` for the tests. The Round 1 test also needs the generated single-clip HTML. Run the launch generator separately from the tests.

~~~powershell
py -3.12 -B examples/make_rescue_comparison.py
node tests/test_rescue_demo.cjs
node tests/test_multi_video_dashboard.cjs
~~~

The six development clips provided 44 public action references. Refined matched one at tIoU 0.30, emitted no actions on five clips and remained opt-in. The clip-level evidence is a local development comparison and does not establish generalization or official performance.

[Production architecture](ARCHITECTURE.md) · [Pinned model assets and SHA-256](MODEL_WEIGHTS.json) · [CLIP terms](../licenses/OpenAI-CLIP-MIT.txt)
