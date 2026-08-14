"""
MiroFish Backend - Flask application factory
"""

import os
import warnings

warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request, send_from_directory
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


def create_app(config_class=Config):
    """Flask application factory."""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    frontend_dist = os.path.join(project_root, 'frontend', 'dist')

    app = Flask(__name__, static_folder=frontend_dist, static_url_path='/assets')
    app.config.from_object(config_class)

    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    logger = setup_logger('mirofish')
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend starting...")
        logger.info("=" * 50)

    CORS(app, resources={r"/api/*": {"origins": "*"}})

    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("Simulation cleanup registered")

    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"Request: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"Request body: {request.get_json(silent=True)}")

    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"Response: {response.status_code}")
        return response

    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')

    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}

    # Serve the compiled Vue application in production.
    # API routes above take precedence; all other paths fall back to index.html
    # so Vue Router can handle client-side routes.
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def frontend(path):
        if not os.path.isdir(frontend_dist):
            return {'error': 'Frontend build not found'}, 503

        if path:
            requested_file = os.path.join(frontend_dist, path)
            if os.path.isfile(requested_file):
                return send_from_directory(frontend_dist, path)

        return send_from_directory(frontend_dist, 'index.html')

    if should_log_startup:
        logger.info("MiroFish Backend started")

    return app
