# HypeCheck contributor instructions

Work from the repository containing this file. Do not use directories recorded in
[historical handoffs](docs/HANDOFF-HISTORY.md) as workspace instructions.

## Current scope and contracts

- English Instagram Reels, YouTube Shorts and youtu.be share links; up to 100 seconds,
  three medical claims, and a 100 MB upload fallback. URLs are not a demo allowlist.
- OpenAI is the default live provider. Mock mode is the configuration default and
  must remain visibly labeled. Never publish a mock or incomplete medical video.
- One staged renderer, invoked through Celery using `app.video.render_video` and
  `result.video`. Automatic generation, manual generation and retries share it.
- One selected claim per 45–60-second video: earliest contradicted, otherwise earliest
  assessed. Preserve the saved verdict, exact citations and every limitation.
- OpenAI narration, local audio alignment, labeled source excerpts, caption/source
  downloads, durable stage recovery. Existing version-2 artifacts remain readable.
- GPTZero authorship detection is optional, separate from medical verdicts, and
  non-fatal. Experimental resolver, paper-scanner and crawler tools are not integrated.
- Public deployment, social publishing and experimental research integration are
  outside the current renderer work.

Read [README](README.md), [renderer instructions](backend/app/video/VIDEO.md),
[decisions](backend/app/video/DECISIONS.md), and [verification](docs/VERIFICATION.md).
Historical measurements do not certify the current checkout or its live services.

## Development and verification

Run from the repository root with the documented dependencies installed:

```sh
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q
.venv/bin/ruff check --config ruff.toml backend scripts
npm --prefix frontend run build
npm --prefix frontend test
```

Run meaningful regression checks for changed contracts. Record the tested base commit,
working-tree changes, fixture/live status, cache use, and any unavailable checks.
Do not infer that ignored credentials, databases or media traveled with Git.

Keep `.env`, environments, node_modules, generated media and caches out of Git.
Never print credentials. Preserve existing volumes; `docker compose down -v` deletes
persistent data. Commit source, tests, lockfiles, docs and `.env.example` together.
