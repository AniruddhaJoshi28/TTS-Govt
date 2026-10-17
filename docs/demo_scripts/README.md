# Demo videos

[scenes.yaml](scenes.yaml) is the script for all three regional videos and the input to `scripts/demo/make_demo_video.py`.

| Video | Document shown (official source) | Narration |
| --- | --- | --- |
| Marathi, Maharashtra | Public Health Department circular, 16-10-2026: private hospitals must display their rates | AI voice, labelled |
| Hindi, Madhya Pradesh | Labour Commissioner notification, 30-09-2026: minimum wages with VDA, 01.10.2026–31.03.2027 | AI voice, labelled |
| Odia, Odisha | Labour Commissioner notification 8393, 08-10-2026: minimum wages with VDA | AI voice, labelled |

Each video follows plan §9:
1. introduction;
2. the official document and how its text was obtained;
3. the summary with page citations;
4. a question, typed or spoken by a real person;
5. the answer spoken in a second AI voice;
6. opening the cited source page;
7. a question the document cannot answer, which the system declines;
8. closing.

## Rules the pipeline enforces

- Only real product footage and real model output. It refuses stub models; `--allow-test-model` produces files stamped "NOT FOR DISTRIBUTION".
- If an answer's status contradicts the narration, recording stops.
- The narration voice and the product voice are different speakers, both labelled as AI on screen. The closing line also says so aloud.
- `evidence.json` records the document checksum, model, answers shown and voices used.

## Before client delivery

- [ ] A native speaker reviews each language's narration in `scenes.yaml` and the UI strings.
- [ ] The MP wage-table transcription is signed in `data/review/` (otherwise MP wage figures stay withheld).
- [ ] Every number and date on screen is checked against the official PDF.
- [ ] Each finished video is watched end to end with a native speaker, and sign-off is recorded.

See [docs/operations/gpu-server.md](../operations/gpu-server.md) to run it.
