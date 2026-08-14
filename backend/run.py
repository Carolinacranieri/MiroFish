"""
MiroFish Backend startup entry point
"""

import os
import sys

# Ensure UTF-8 output on Windows
if sys.platform == 'win32':
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add backend directory to the import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config import Config


def main():
    """Start the Flask application."""
    errors = Config.validate()
    if errors:
        print("Configuration errors:")
        for err in errors:
            print(f"  - {err}")
        print("\nPlease check the environment configuration")
        sys.exit(1)

    app = create_app()

    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    # Render provides PORT; keep FLASK_PORT as a local-development fallback.
    port = int(os.environ.get('PORT', os.environ.get('FLASK_PORT', 5001)))
    debug = Config.DEBUG

    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    main()
