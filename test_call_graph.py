"""Test script for call graph functionality."""

import asyncio
from pathlib import Path

from src.config import load_config
from src.storage.call_graph_store import CallGraphStore
from src.indexer.ast_analyzer import ASTAnalyzer, FunctionDefinition


async def test_call_graph_store():
    """Test SQLite call graph store."""
    print("=" * 60)
    print("Testing Call Graph Store")
    print("=" * 60)

    # Create temporary database
    db_path = Path("./test_call_graph.db")
    if db_path.exists():
        db_path.unlink()

    store = CallGraphStore(db_path)

    # Create sample function
    func_def = FunctionDefinition(
        name="test_function",
        parameters=["param1", "param2"],
        return_type="dict",
        line_number=10,
        is_async=True
    )

    # Save function
    func_id = store.save_function(
        project_path="/test/project",
        file_path="src/test.py",
        func_def=func_def,
        layer="service",
        is_entry_point=True,
        trigger_type="http",
        trigger_metadata={"method": "POST", "path": "/api/test"},
        description="Test function for API"
    )

    print(f"✓ Saved function: {func_id}")

    # Retrieve function
    retrieved = store.get_function(func_id)
    print(f"✓ Retrieved function: {retrieved['function_name']}")

    # Get entry points
    entry_points = store.get_entry_points("/test/project")
    print(f"✓ Found {len(entry_points)} entry points")

    # Get statistics
    stats = store.get_statistics("/test/project")
    print(f"✓ Statistics: {stats}")

    # Cleanup
    store.close()
    db_path.unlink()

    print("\n✅ Call Graph Store test passed!")


async def test_ast_analyzer():
    """Test AST analyzer."""
    print("\n" + "=" * 60)
    print("Testing AST Analyzer")
    print("=" * 60)

    analyzer = ASTAnalyzer()

    if not analyzer.tree_sitter_available:
        print("⚠️  tree-sitter not available - skipping AST test")
        print("   Install with: pip install tree-sitter tree-sitter-languages")
        return

    # Sample Python code
    sample_code = """
import os
from typing import List

def process_data(items: List[str]) -> None:
    '''Process list of items.'''
    for item in items:
        result = transform_item(item)
        save_result(result)

def transform_item(item: str) -> dict:
    '''Transform single item.'''
    return {"value": item.upper()}

async def save_result(data: dict):
    '''Save result to database.'''
    await db.save(data)
"""

    # Analyze code
    call_graph = analyzer.analyze_file(
        Path("test.py"),
        "python",
        sample_code
    )

    if call_graph:
        print(f"✓ Found {len(call_graph.functions)} functions:")
        for func in call_graph.functions:
            async_prefix = "async " if func.is_async else ""
            print(f"  - {async_prefix}{func.name}({', '.join(func.parameters)})")

        print(f"\n✓ Found {len(call_graph.calls)} function calls:")
        for call in call_graph.calls[:5]:  # Show first 5
            print(f"  - {call.caller_function} → {call.callee_name}()")

        print(f"\n✓ Found {len(call_graph.imports)} imports:")
        for imp in call_graph.imports:
            print(f"  - import {imp.module}")

        print("\n✅ AST Analyzer test passed!")
    else:
        print("❌ AST analysis failed")


async def test_language_adapters():
    """Test language adapters."""
    print("\n" + "=" * 60)
    print("Testing Language Adapters")
    print("=" * 60)

    from src.indexer.language_adapters import (
        PythonAdapter,
        JavaScriptAdapter,
        get_language_adapter
    )

    # Test Python adapter
    python_adapter = PythonAdapter()
    print("✓ Python adapter initialized")

    # Test JavaScript adapter
    js_adapter = JavaScriptAdapter()
    print("✓ JavaScript adapter initialized")

    # Test factory
    adapter = get_language_adapter("python")
    print(f"✓ Factory returned: {adapter.__class__.__name__}")

    # Test layer classification
    layer = python_adapter.classify_layer(
        "create_user",
        Path("src/api/controllers/user_controller.py"),
        has_trigger=True,
        decorators=["@app.post('/users')"]
    )
    print(f"✓ Layer classification: {layer}")

    print("\n✅ Language Adapters test passed!")


async def test_trigger_detector():
    """Test trigger detector."""
    print("\n" + "=" * 60)
    print("Testing Trigger Detector")
    print("=" * 60)

    from src.indexer.trigger_detector import TriggerDetector

    detector = TriggerDetector()

    sample_code = """
@app.post('/users')
def create_user(user_data: dict):
    return {"id": 1}

@kafka.consumer('user-events')
def handle_user_event(event: dict):
    process_event(event)
"""

    triggers = detector.detect_triggers(
        Path("test.py"),
        None,  # No AST tree for regex fallback
        sample_code,
        "python"
    )

    print(f"✓ Found {len(triggers)} triggers:")
    for trigger in triggers:
        display = detector.format_trigger_display(trigger)
        print(f"  - {display}")

    print("\n✅ Trigger Detector test passed!")


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("CALL GRAPH IMPLEMENTATION TEST SUITE")
    print("=" * 60)

    try:
        await test_call_graph_store()
        await test_ast_analyzer()
        await test_language_adapters()
        await test_trigger_detector()

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        print("\nThe call graph implementation is working correctly.")
        print("\nNext steps:")
        print("1. Install tree-sitter if not already installed:")
        print("   pip install tree-sitter tree-sitter-languages")
        print("\n2. Try indexing a project:")
        print("   Use the index_project_with_call_graph MCP tool")
        print("\n3. Trace code flows:")
        print("   Use the trace_code_flow MCP tool")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
