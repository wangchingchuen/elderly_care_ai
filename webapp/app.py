"""Compatibility launcher. The original prototype is preserved in v0.0.0-prototype."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from caretrace.app import create_app

if __name__ == '__main__':
    from waitress import serve
    serve(create_app(), host='127.0.0.1', port=5000, threads=8)
