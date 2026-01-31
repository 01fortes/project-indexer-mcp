#!/usr/bin/env python3
"""Run web admin portal."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.web.server import run_web_server

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Project Indexer Admin Portal")
    parser.add_argument("--host", default="0.0.0.0", help="Host address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port number (default: 8080)")

    args = parser.parse_args()

    print(f"🚀 Starting admin portal at http://{args.host}:{args.port}")
    print(f"📊 View your indexed projects in the browser")
    print(f"🔍 Search and manage projects through the web interface")
    print()

    run_web_server(host=args.host, port=args.port)
