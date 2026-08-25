"""
API路由模块
"""

from flask import Blueprint, request


graph_bp = Blueprint('graph', __name__)
simulation_bp = Blueprint('simulation', __name__)
report_bp = Blueprint('report', __name__)


def _recover_orphaned_simulation_run():
    """Fail closed when a previous runtime died with an active simulation."""
    path = request.path.rstrip('/')
    if path.endswith('/run-status/detail'):
        parts = path.split('/')
        simulation_id = parts[-3] if len(parts) >= 3 else None
    elif path.endswith('/run-status'):
        parts = path.split('/')
        simulation_id = parts[-2] if len(parts) >= 2 else None
    else:
        return None

    if not simulation_id or not simulation_id.startswith('sim_'):
        return None

    try:
        from ..services.simulation_runtime_recovery import recover_orphaned_run
        recover_orphaned_run(simulation_id)
    except Exception as error:
        # Status polling must remain available even if persistence recovery
        # itself fails. The normal run-status handler will report its state.
        from ..utils.logger import get_logger
        get_logger('mirofish.api').error(
            "Simulation runtime recovery failed: simulation_id=%s, error=%s",
            simulation_id,
            error,
        )
    return None


simulation_bp.before_request(_recover_orphaned_simulation_run)

from . import graph  # noqa: E402, F401
from . import simulation  # noqa: E402, F401
from . import report  # noqa: E402, F401

