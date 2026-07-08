# mashpad

Local-first mashup compatibility workbench (prototype). Not a DJ app.

The first product question this repo answers: **can two local songs be
analyzed well enough to suggest plausible mashup pairings**, before any
real editing UI exists?

## Quickstart

```bash
uv sync
uv run mashcheck path/to/song_a.mp3 path/to/song_b.mp3
```

## Status

Tempo/key/section detection are deterministic placeholders (see
`docs/decision-log.md`). Scoring, ranking, and report generation are real.
See `CLAUDE.md` for repo instructions and guardrails.
