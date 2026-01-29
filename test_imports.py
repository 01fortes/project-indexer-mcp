#!/usr/bin/env python3
"""Test that all imports work correctly."""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("Testing imports...")

try:
    print("✓ Importing mcp...")
    import mcp

    print("✓ Importing openai...")
    import openai

    print("✓ Importing chromadb...")
    import chromadb

    print("✓ Importing src.config...")
    from src.config import load_config

    print("✓ Importing src.storage.models...")
    from src.storage.models import ProjectContext

    print("✓ Importing src.server...")
    from src.server import main

    print("\n✅ All imports successful!")
    print("\nTesting config load (will fail if OPENAI_API_KEY not set)...")

    try:
        config = load_config()
        print(f"✓ Config loaded: {config.server.name} v{config.server.version}")
        print(f"✓ OpenAI model: {config.openai.model}")
        print(f"✓ ChromaDB: {config.chroma.persist_directory}")
        print("\n✅ Configuration is valid!")
    except ValueError as e:
        print(f"⚠️  Config error: {e}")
        print("   Please set OPENAI_API_KEY in .env file")

except ImportError as e:
    print(f"\n❌ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"\n❌ Error: {e}")
    sys.exit(1)
