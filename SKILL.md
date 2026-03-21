---
name: auto-podcast-skill
description: Generate an Arsenal podcast episode from fresh football news, validate environment and OpenClaw connectivity, and run the podcast pipeline manually on a VPS or local machine. Use when the user wants to run, check, or troubleshoot the auto-podcast pipeline as a Codex skill.
---

# Auto Podcast Skill

Use this skill when the user wants to run or troubleshoot the Arsenal auto-podcast pipeline.

## Workflow

1. Ensure the project environment file exists at `project/.env` in skill layout, or `.env` in repo layout.
2. Run `scripts/check_env.sh` first.
3. If checks pass, run `scripts/run.sh --dry-run`.
4. For a real episode, run `scripts/run.sh`.
5. For retries, pass through `--run-id` and `--step`.

## Commands

Environment check:

```bash
scripts/check_env.sh
```

Dry run:

```bash
scripts/run.sh --dry-run
```

Resume from upload with an existing run id:

```bash
scripts/run.sh --run-id 20260322_080000 --step upload
```

## Notes

- The scripts support two layouts automatically:
  - skill layout: `SKILL.md`, `scripts/`, `project/`
  - repo layout: project files at the repository root
- Secrets must stay in `.env`. Do not paste tokens into commands or logs.
- The OpenClaw gateway is expected at `http://127.0.0.1:18789` unless `config.yaml` says otherwise.
