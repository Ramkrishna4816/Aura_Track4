# AURA completion and public media report

**The public presentation and silent demo are complete. Competition submission remains blocked.** The team approved the redacted presentation and silent cut for public posting. The production pipeline remains on the accepted engineering baseline.

## Media and validation

| Deliverable | Exact Git snapshot | Verified file |
|---|---|---|
| [Silent demo MP4](demo/AURA_Track4_Demo_Silent.mp4) | `0fba091cd01e2738ac4de326e4e1b2f26dd46d80` | 2:49.53, 1920 × 1080 at 30 fps, H.264 High, 5,086 decoded frames and zero audio streams. SHA-256 `a5877f9e349805c710433cf3e34e52fbbfb0d6fe7707bc153866f8522b7d6f2a`. |
| [Public-safe editable PPTX](presentation/AURA_Track4_Presentation_Public.pptx) | `320b299fdd27148e31c7b81508b7fc52e0939652` | Nine editable slides. SHA-256 `35ce267aeed748e72c34e72bf4034dbbd968dfa6f1d6e6af8b63d25cb1c33a5d`. |
| [Matching public-safe PDF](presentation/AURA_Track4_Presentation_Public.pdf) | `320b299fdd27148e31c7b81508b7fc52e0939652` | Nine matching pages. SHA-256 `98ab69bcd520af92100c3ba1eaae4b9169a13fb5830870314210d25b9c531eb2`. |

The silent cut retains identical encoded video packets and preserves the original captions, genuine dashboard captures, and source-footage masking. The entire audio stream was removed. FFmpeg decoded the file without errors, and Edge verified playback and seeking. The 3,334,313-byte MP4 is the largest release file. The three files are within regular Git limits. [Video technical review](demo/VIDEO_REVIEW.md) · [GitHub file size limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)

Privacy checks covered slide text and notes, embedded content, author fields, external links, and extracted PDF text and metadata. The native evaluation table and diagram remain editable. The approved publication export removed the cover review marker. Visual comparisons showed that the change was confined to the marker and that the other eight slides and PDF pages were pixel-identical. The private originals and labelled review copies were preserved separately. [Presentation guide](presentation/README.md)

## Branch and default landing page

The evaluator baseline was `074eb42a4153a3228eff9eda911c7729468a1099`. The engineering tag remains `b16bdb8d4e76cf26f16c8cc1d5c2949cfd490b8f`. Only `final-engineering-release` is in scope for publication. [Evaluator landing page](https://github.com/Ramkrishna4816/Aura_Track4/tree/final-engineering-release)

At release verification, GitHub's default branch was `main` at `2ef8ca1796a7c547fcf9402b4fd6a029535acccf`. Its README still showed the prior media status. The older checklist and demo placeholder were already absent from `main`. An administrator can make the evaluator landing page the default through **Settings → General → Default branch → final-engineering-release → Update** and confirm. This release leaves the setting unchanged. [GitHub default branch instructions](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-branches-in-your-repository/changing-the-default-branch)

## Competition status

Competition output coverage remains zero. The supplied kit lists 187 originals, and the 185-video scope requires written approval of both Scuba exclusions. This release ran no competition inference and made no competition portal submission. The working checklist remains private. [Competition status](docs/SUBMISSION_STATUS.md)
