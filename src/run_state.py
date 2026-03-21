from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunContext:
    run_id: str
    root_dir: Path
    run_dir: Path
    state_path: Path
    created_at: datetime

    @property
    def script_path(self) -> Path:
        return self.run_dir / "script.txt"

    @property
    def audio_path(self) -> Path:
        return self.run_dir / "podcast.mp3"

    @property
    def articles_path(self) -> Path:
        return self.run_dir / "articles.json"

    @property
    def log_path(self) -> Path:
        return self.root_dir / "logs" / f"{self.created_at.strftime('%Y%m%d')}_{self.run_id}.log"


def create_run_context(output_dir: Path, run_id: str | None = None) -> RunContext:
    created_at = datetime.now()
    resolved_run_id = run_id or created_at.strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / "runs" / resolved_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(
        run_id=resolved_run_id,
        root_dir=output_dir,
        run_dir=run_dir,
        state_path=run_dir / "state.json",
        created_at=created_at,
    )


def load_state(context: RunContext) -> dict[str, Any]:
    if not context.state_path.exists():
        return {"run_id": context.run_id, "steps": {}, "artifacts": {}, "metrics": {}}
    with open(context.state_path, encoding="utf-8") as handle:
        return json.load(handle)


def save_state(context: RunContext, state: dict[str, Any]) -> None:
    context.run_dir.mkdir(parents=True, exist_ok=True)
    with open(context.state_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)


def mark_step(
    context: RunContext,
    state: dict[str, Any],
    step: str,
    status: str,
    *,
    detail: str | None = None,
    artifacts: dict[str, str] | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    entry = {
        "status": status,
        "updated_at": datetime.now().isoformat(),
    }
    if detail:
        entry["detail"] = detail
    state.setdefault("steps", {})[step] = entry
    if artifacts:
        state.setdefault("artifacts", {}).update(artifacts)
    if metrics:
        state.setdefault("metrics", {}).update(metrics)
    save_state(context, state)
