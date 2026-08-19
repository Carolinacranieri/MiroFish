import json
import shutil
from types import SimpleNamespace

import pytest

from app import create_app
from app.services import simulation_manager as simulation_manager_module
from app.services.simulation_config_generator import SimulationParameters
from app.services.simulation_manager import (
    SimulationManager,
    SimulationState,
    SimulationStatus,
)
from app.services.simulation_repository import (
    PersistedSimulation,
    SimulationStorageError,
)
from app.services.zep_entity_reader import FilteredEntities


class FakeSimulationRepository:
    records = {}
    enabled = True

    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def reset(cls):
        cls.records = {}

    def upsert(self, **kwargs):
        existing = self.records.get(kwargs["simulation_id"], {})
        existing.update({k: v for k, v in kwargs.items() if v is not None})
        self.records[kwargs["simulation_id"]] = existing

    def create(self, **kwargs):
        self.upsert(**kwargs)

    def get(self, simulation_id):
        row = self.records.get(simulation_id)
        if not row:
            return None
        return PersistedSimulation(
            simulation_id=row["simulation_id"],
            project_id=row["project_id"],
            graph_id=row.get("graph_id") or "",
            status=row.get("status") or "created",
            state=row.get("state") or {},
            simulation_config=row.get("simulation_config"),
            reddit_profiles=row.get("reddit_profiles"),
            twitter_profiles=row.get("twitter_profiles"),
            project_snapshot=row.get("project_snapshot"),
            run_state=row.get("run_state"),
            metadata=row.get("metadata") or {},
        )

    def list(self, project_id=None):
        records = []
        for simulation_id in self.records:
            record = self.get(simulation_id)
            if project_id is None or record.project_id == project_id:
                records.append(record)
        return records

    def update_status(self, simulation_id, **kwargs):
        if simulation_id not in self.records:
            raise SimulationStorageError(
                f"Simulation not found in persistent storage: {simulation_id}"
            )
        self.records[simulation_id].update(kwargs)

    def delete(self, simulation_id):
        self.records.pop(simulation_id, None)


class FailingSimulationRepository(FakeSimulationRepository):
    def upsert(self, **kwargs):
        raise SimulationStorageError("persistent storage unavailable")


@pytest.fixture
def fake_storage(monkeypatch):
    FakeSimulationRepository.reset()
    monkeypatch.setattr(
        simulation_manager_module,
        "SimulationRepository",
        FakeSimulationRepository,
    )
    return FakeSimulationRepository


def test_create_persists_simulation_metadata(tmp_path, monkeypatch, fake_storage):
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    manager = SimulationManager()

    state = manager.create_simulation(
        project_id="proj_test",
        graph_id="graph_test",
        project_snapshot={
            "project_id": "proj_test",
            "graph_id": "graph_test",
            "simulation_requirement": "requirement",
            "extracted_text": "document",
        },
    )

    assert state.simulation_id in fake_storage.records
    persisted = fake_storage.records[state.simulation_id]
    assert persisted["simulation_id"] == state.simulation_id
    assert persisted["project_id"] == "proj_test"
    assert persisted["status"] == "created"
    assert persisted["project_snapshot"]["simulation_requirement"] == "requirement"


def test_get_after_new_manager_materializes_missing_state_json(
    tmp_path,
    monkeypatch,
    fake_storage,
):
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    manager = SimulationManager()
    state = manager.create_simulation(project_id="proj_test", graph_id="graph_test")
    sim_dir = tmp_path / state.simulation_id
    shutil.rmtree(sim_dir)

    new_manager = SimulationManager()
    loaded = new_manager.get_simulation(state.simulation_id)

    assert loaded is not None
    assert loaded.simulation_id == state.simulation_id
    assert (sim_dir / "state.json").exists()
    assert json.loads((sim_dir / "state.json").read_text())["simulation_id"] == state.simulation_id


def test_prepare_persists_config_profiles_and_ready_state(
    tmp_path,
    monkeypatch,
    fake_storage,
):
    class Reader:
        def filter_defined_entities(self, **kwargs):
            return FilteredEntities(
                entities=[SimpleNamespace(name="Alice")],
                entity_types={"Person"},
                total_count=1,
                filtered_count=1,
            )

    class ProfileGenerator:
        def __init__(self, *args, **kwargs):
            pass

        def generate_profiles_from_entities(self, **kwargs):
            return [{"user_id": 0, "username": "alice", "name": "Alice"}]

        def save_profiles(self, profiles, file_path, platform):
            if platform == "reddit":
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(profiles, f)
            else:
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    f.write("user_id,username,name\n0,alice,Alice\n")

    class ConfigGenerator:
        def generate_config(self, **kwargs):
            return SimulationParameters(
                simulation_id=kwargs["simulation_id"],
                project_id=kwargs["project_id"],
                graph_id=kwargs["graph_id"],
                simulation_requirement=kwargs["simulation_requirement"],
                generation_reasoning="test",
            )

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", Reader)
    monkeypatch.setattr(
        simulation_manager_module,
        "OasisProfileGenerator",
        ProfileGenerator,
    )
    monkeypatch.setattr(
        simulation_manager_module,
        "SimulationConfigGenerator",
        ConfigGenerator,
    )

    manager = SimulationManager()
    state = manager.create_simulation(project_id="proj_test", graph_id="graph_test")

    result = manager.prepare_simulation(
        simulation_id=state.simulation_id,
        simulation_requirement="requirement",
        document_text="document",
    )

    persisted = fake_storage.records[state.simulation_id]
    assert result.status == SimulationStatus.READY
    assert persisted["status"] == "ready"
    assert persisted["simulation_config"]["simulation_id"] == state.simulation_id
    assert persisted["reddit_profiles"][0]["username"] == "alice"
    assert persisted["twitter_profiles"][0]["name"] == "Alice"


def test_storage_unavailable_fails_create_explicitly(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        simulation_manager_module,
        "SimulationRepository",
        FailingSimulationRepository,
    )

    manager = SimulationManager()
    with pytest.raises(SimulationStorageError, match="persistent storage unavailable"):
        manager.create_simulation(project_id="proj_test", graph_id="graph_test")


def test_old_filesystem_only_simulation_still_loads(tmp_path, monkeypatch):
    from app.config import Config

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "SUPABASE_DATABASE_URL", None)
    sim_dir = tmp_path / "sim_legacy"
    sim_dir.mkdir()
    (sim_dir / "state.json").write_text(
        json.dumps(
            {
                "simulation_id": "sim_legacy",
                "project_id": "proj_legacy",
                "graph_id": "graph_legacy",
                "status": "ready",
                "config_generated": True,
            }
        ),
        encoding="utf-8",
    )

    manager = SimulationManager()

    loaded = manager.get_simulation("sim_legacy")

    assert loaded is not None
    assert loaded.simulation_id == "sim_legacy"
    assert loaded.status == SimulationStatus.READY


def test_start_uses_persisted_metadata_when_local_state_is_missing(
    tmp_path,
    monkeypatch,
    fake_storage,
):
    from app.api import simulation as simulation_api
    from app.config import Config

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "RUN_STATE_DIR",
        str(tmp_path),
    )

    manager = SimulationManager()
    state = manager.create_simulation(
        project_id="proj_test",
        graph_id="graph_test",
        project_snapshot={
            "project_id": "proj_test",
            "graph_id": "graph_test",
            "simulation_requirement": "requirement",
            "extracted_text": "document",
        },
    )
    state.status = SimulationStatus.READY
    state.config_generated = True
    state.profiles_generated = True
    manager._save_simulation_state(state)
    manager.repository.upsert(
        simulation_id=state.simulation_id,
        project_id=state.project_id,
        graph_id=state.graph_id,
        status="ready",
        state=state.to_dict(),
        simulation_config={
            "simulation_id": state.simulation_id,
            "project_id": state.project_id,
            "graph_id": state.graph_id,
            "time_config": {
                "total_simulation_hours": 1,
                "minutes_per_round": 30,
            },
            "agent_configs": [],
            "event_config": {},
        },
        reddit_profiles=[{"user_id": 0, "username": "alice"}],
        twitter_profiles=[{"user_id": 0, "username": "alice"}],
        project_snapshot={
            "project_id": "proj_test",
            "graph_id": "graph_test",
        },
    )
    shutil.rmtree(tmp_path / state.simulation_id)

    started_ids = []

    def fake_start_simulation(**kwargs):
        started_ids.append(kwargs["simulation_id"])
        config_path = tmp_path / kwargs["simulation_id"] / "simulation_config.json"
        assert config_path.exists()
        return SimpleNamespace(
            to_dict=lambda: {
                "simulation_id": kwargs["simulation_id"],
                "runner_status": "running",
            }
        )

    monkeypatch.setattr(
        simulation_api.SimulationRunner,
        "start_simulation",
        fake_start_simulation,
    )

    app = create_app()
    app.config.update(TESTING=True)
    response = app.test_client().post(
        "/api/simulation/start",
        json={
            "simulation_id": state.simulation_id,
            "platform": "parallel",
            "enable_graph_memory_update": True,
        },
    )

    assert response.status_code == 200
    assert response.json["success"] is True
    assert response.json["data"]["simulation_id"] == state.simulation_id
    assert started_ids == [state.simulation_id]


def test_missing_simulation_returns_404_for_get_and_start(tmp_path, monkeypatch, fake_storage):
    from app.config import Config

    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    get_response = client.get("/api/simulation/sim_missing")
    start_response = client.post(
        "/api/simulation/start",
        json={"simulation_id": "sim_missing"},
    )

    assert get_response.status_code == 404
    assert start_response.status_code == 404
