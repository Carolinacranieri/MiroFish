"""Persistent storage for simulation metadata.

The runtime still uses local files for OASIS subprocesses, logs, IPC and SQLite.
This repository stores the durable metadata needed to re-materialize those
critical files after an ephemeral runtime restart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("mirofish.simulation_repository")


class SimulationStorageError(RuntimeError):
    """Raised when configured persistent storage cannot complete an operation."""


@dataclass
class PersistedSimulation:
    simulation_id: str
    project_id: str
    graph_id: str
    status: str
    state: Dict[str, Any]
    simulation_config: Optional[Dict[str, Any]] = None
    reddit_profiles: Optional[list[Dict[str, Any]]] = None
    twitter_profiles: Optional[list[Dict[str, Any]]] = None
    project_snapshot: Optional[Dict[str, Any]] = None
    run_state: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


class SimulationRepository:
    """Postgres-backed repository for durable simulation metadata."""

    TABLE = "mirofish_simulations"

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or Config.SUPABASE_DATABASE_URL

    @property
    def enabled(self) -> bool:
        return bool(self.database_url)

    def _connect(self):
        if not self.database_url:
            raise SimulationStorageError("Persistent simulation storage is not configured")
        try:
            import psycopg
        except ImportError as error:
            raise SimulationStorageError(
                "Persistent simulation storage requires the psycopg package"
            ) from error

        try:
            return psycopg.connect(self.database_url, autocommit=True)
        except Exception as error:
            raise SimulationStorageError(
                f"Persistent simulation storage is unavailable: {error}"
            ) from error

    @staticmethod
    def _coerce_json(value: Any) -> Any:
        if value is None or isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    @classmethod
    def _row_to_record(cls, row: Dict[str, Any]) -> PersistedSimulation:
        return PersistedSimulation(
            simulation_id=row["simulation_id"],
            project_id=row["project_id"],
            graph_id=row.get("graph_id") or "",
            status=row.get("status") or "created",
            state=cls._coerce_json(row.get("state")) or {},
            simulation_config=cls._coerce_json(row.get("simulation_config")),
            reddit_profiles=cls._coerce_json(row.get("reddit_profiles")),
            twitter_profiles=cls._coerce_json(row.get("twitter_profiles")),
            project_snapshot=cls._coerce_json(row.get("project_snapshot")),
            run_state=cls._coerce_json(row.get("run_state")),
            metadata=cls._coerce_json(row.get("metadata")) or {},
            created_at=str(row["created_at"]) if row.get("created_at") else None,
            updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        )

    def create(
        self,
        *,
        simulation_id: str,
        project_id: str,
        graph_id: str,
        status: str,
        state: Dict[str, Any],
        project_snapshot: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        self.upsert(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            status=status,
            state=state,
            project_snapshot=project_snapshot,
            metadata=metadata,
        )

    def upsert(
        self,
        *,
        simulation_id: str,
        project_id: str,
        graph_id: str,
        status: str,
        state: Dict[str, Any],
        simulation_config: Optional[Dict[str, Any]] = None,
        reddit_profiles: Optional[list[Dict[str, Any]]] = None,
        twitter_profiles: Optional[list[Dict[str, Any]]] = None,
        project_snapshot: Optional[Dict[str, Any]] = None,
        run_state: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return

        updates = [
            "project_id = EXCLUDED.project_id",
            "graph_id = EXCLUDED.graph_id",
            "status = EXCLUDED.status",
            "state = EXCLUDED.state",
            "updated_at = now()",
        ]
        columns = ["simulation_id", "project_id", "graph_id", "status", "state"]
        values: list[Any] = [simulation_id, project_id, graph_id, status, _jsonb(state)]

        optional_fields = {
            "simulation_config": simulation_config,
            "reddit_profiles": reddit_profiles,
            "twitter_profiles": twitter_profiles,
            "project_snapshot": project_snapshot,
            "run_state": run_state,
            "metadata": metadata,
        }
        for column, value in optional_fields.items():
            if value is not None:
                columns.append(column)
                values.append(_jsonb(value))
                updates.append(f"{column} = EXCLUDED.{column}")

        placeholders = ", ".join(["%s"] * len(columns))
        sql = f"""
            INSERT INTO {self.TABLE} ({", ".join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (simulation_id) DO UPDATE SET {", ".join(updates)}
        """

        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, values)
        except SimulationStorageError:
            raise
        except Exception as error:
            raise SimulationStorageError(
                f"Failed to persist simulation {simulation_id}: {error}"
            ) from error

    def get(self, simulation_id: str) -> Optional[PersistedSimulation]:
        if not self.enabled:
            return None
        try:
            with self._connect() as conn:
                with conn.cursor(row_factory=dict_row()) as cur:
                    cur.execute(
                        f"""
                        SELECT simulation_id, project_id, graph_id, status, state,
                               simulation_config, reddit_profiles, twitter_profiles,
                               project_snapshot, run_state, metadata,
                               created_at, updated_at
                        FROM {self.TABLE}
                        WHERE simulation_id = %s
                        """,
                        (simulation_id,),
                    )
                    row = cur.fetchone()
        except SimulationStorageError:
            raise
        except Exception as error:
            raise SimulationStorageError(
                f"Failed to load simulation {simulation_id}: {error}"
            ) from error

        return self._row_to_record(row) if row else None

    def list(self, project_id: Optional[str] = None) -> list[PersistedSimulation]:
        if not self.enabled:
            return []
        sql = f"""
            SELECT simulation_id, project_id, graph_id, status, state,
                   simulation_config, reddit_profiles, twitter_profiles,
                   project_snapshot, run_state, metadata,
                   created_at, updated_at
            FROM {self.TABLE}
        """
        params: tuple[Any, ...] = ()
        if project_id:
            sql += " WHERE project_id = %s"
            params = (project_id,)
        sql += " ORDER BY created_at DESC"

        try:
            with self._connect() as conn:
                with conn.cursor(row_factory=dict_row()) as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
        except SimulationStorageError:
            raise
        except Exception as error:
            raise SimulationStorageError(
                f"Failed to list persisted simulations: {error}"
            ) from error

        return [self._row_to_record(row) for row in rows]

    def update_status(
        self,
        simulation_id: str,
        *,
        status: str,
        state: Optional[Dict[str, Any]] = None,
        run_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return

        assignments = ["status = %s", "updated_at = now()"]
        values: list[Any] = [status]
        if state is not None:
            assignments.append("state = %s")
            values.append(_jsonb(state))
        if run_state is not None:
            assignments.append("run_state = %s")
            values.append(_jsonb(run_state))
        values.append(simulation_id)

        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE {self.TABLE}
                        SET {", ".join(assignments)}
                        WHERE simulation_id = %s
                        """,
                        values,
                    )
                    if cur.rowcount == 0:
                        raise SimulationStorageError(
                            f"Simulation not found in persistent storage: {simulation_id}"
                        )
        except SimulationStorageError:
            raise
        except Exception as error:
            raise SimulationStorageError(
                f"Failed to update simulation {simulation_id}: {error}"
            ) from error

    def delete(self, simulation_id: str) -> None:
        if not self.enabled:
            return
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"DELETE FROM {self.TABLE} WHERE simulation_id = %s",
                        (simulation_id,),
                    )
        except SimulationStorageError:
            raise
        except Exception as error:
            raise SimulationStorageError(
                f"Failed to delete persisted simulation {simulation_id}: {error}"
            ) from error


def dict_row():
    from psycopg.rows import dict_row as psycopg_dict_row

    return psycopg_dict_row
