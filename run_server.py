#!/usr/bin/env python3
"""
Launcher script for MCP server.
This adds project root to Python path and runs the server.
"""
import sys
from pathlib import Path

# Add project root to Python path (not src!)
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Now import and run server using package path
from src.server import main

if __name__ == "__main__":
    main()
