"""Recovery helpers for simulations whose web runtime was restarted.

The OASIS worker is a child process of the Flask runtime. A Render/container
restart removes the in-memory Popen/monitor handles, while durable run_state
metadata can remain in Postgres. This module detects that orphaned condition
without attempting unsafe PID reuse or automatic replay of simulation actions.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from ..config import Config
from ..utils.logger import get_logger
from .simulation_repository import SimulationRepository

logger = get_logger("mirofish.simulation_runtime_recovery")

_ACTIVE_RUNNER_STATUSES = {"starting", "running", "paused", "stopping"}
_GRACE_PERIOD_SECONDS = 60


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def _is_recent(run_state: dict[str, Any]) -> bool:
    started_at = _parse_timestamp(run_state.get("started_at"))
    if started_at is None:
        return False
    return (datetime.now(timezone.utc) - started_at).total_seconds() < _GRACE_PERIOD_SECONDS


def _write_local_run_state(simulation_id: str, run_state: dict[str, Any]) -> None:
    sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
    os.makedirs(sim_dir, exist_ok=True)
    state_file = os.path.join(sim_dir, "run_state.json")
    with open(state_file, "w", encoding="utf-8") as handle:
        json.dump(run_state, handle, ensure_ascii=False, indent=2)


def recover_orphaned_run(simulation_id: str) -> Optional[dict[str, Any]]:
    """Mark an active run as interrupted when its runtime process is gone.

    Returns the recovered run_state when a run was marked interrupted, or None
    when there is nothing to recover. We deliberately never reuse a persisted
    PID or restart a simulation automatically because replaying OASIS actions
    after a web-runtime restart could duplicate side effects.
    """
    repository = SimulationRepository()
    if not repository.enabled:
        return None

    record = repository.get(simulation_id)
    if not record or not record.run_state:
        return None

    run_state = dict(record.run_state)
    runner_status = str(run_state.get("runner_status", "idle")).lower()
    if runner_status not in _ACTIVE_RUNNER_STATUSES:
        return None

    # Import lazily to avoid a module cycle at application startup.
    from .simulation_runner import SimulationRunner

    process = SimulationRunner._processes.get(simulation_id)
    if process is not None:
        # A Popen handle belongs to the current runtime. Let its monitor own
        # normal completion/failure finalization, even if poll() is non-zero.
        return None

    # A run that was just claimed may still be between STARTING and publishing
    # its process handle. Do not race that startup window.
    if _is_recent(run_state):
        return None

    now = datetime.now(timezone.utc).isoformat()
    error = (
        "Simulation interrupted because the backend runtime restarted while "
        "the simulation process was running. The previous process cannot be "
        "safely resumed; start a new run."
    )
    run_state["runner_status"] = "failed"
    run_state["error"] = error
    run_state["completed_at"] = now
    run_state["updated_at"] = now
    run_state["process_pid"] = None
    run_state["twitter_running"] = False
    run_state["reddit_running"] = False

    state = dict(record.state or {})
    state["status"] = "failed"
    state["error"] = error
    state["updated_at"] = now

    repository.update_status(
        simulation_id,
        status="failed",
        state=state,
        run_state=run_state,
    )
    _write_local_run_state(simulation_id, run_state)

    # Keep the in-memory runner cache aligned for this runtime.
    SimulationRunner._run_states[simulation_id] = SimulationRunner._load_run_state(simulation_id) or SimulationRunner._run_states.get(simulation_id)

    logger.error(
        "Recovered orphaned simulation after runtime restart: simulation_id=%s",
        simulation_id,
    )
    return run_state
