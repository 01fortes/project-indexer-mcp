"""Data models for call graph and data flow analysis."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class CallGraphRelation:
    """
    Represents a relationship between two functions in the call graph.

    This will be stored as a separate document in ChromaDB for semantic search.
    """
    # Caller info
    caller_file: str
    caller_function: str
    caller_line: int

    # Callee info
    callee_name: str
    callee_file: Optional[str]  # If we can resolve it
    callee_module: Optional[str]  # For imported functions

    # Data flow
    arguments: List[str]  # What's passed
    argument_types: List[str]  # Types if available

    # Context
    project_root: str
    description: str  # LLM-generated description of what this call does

    def to_embedding_text(self) -> str:
        """
        Generate text for embedding that describes this relationship.

        This allows semantic search like:
        - "how is user_id passed from API to database"
        - "what functions are called during login"
        """
        parts = [
            f"Function call relationship:",
            f"From: {self.caller_file}::{self.caller_function}",
            f"To: {self.callee_name}",
        ]

        if self.callee_module:
            parts.append(f"Module: {self.callee_module}")

        if self.arguments:
            args_str = ", ".join(self.arguments[:5])  # Limit to 5
            parts.append(f"Arguments: {args_str}")

        if self.argument_types:
            types_str = ", ".join(self.argument_types[:5])
            parts.append(f"Types: {types_str}")

        if self.description:
            parts.append(f"Purpose: {self.description}")

        return "\n".join(parts)

    def to_metadata(self) -> dict:
        """Convert to ChromaDB metadata format."""
        return {
            "type": "call_relation",
            "caller_file": self.caller_file,
            "caller_function": self.caller_function,
            "caller_line": self.caller_line,
            "callee_name": self.callee_name,
            "callee_file": self.callee_file or "",
            "callee_module": self.callee_module or "",
            "arguments": ", ".join(self.arguments) if self.arguments else "",
            "argument_types": ", ".join(self.argument_types) if self.argument_types else "",
            "project_root": self.project_root,
            "description": self.description
        }


@dataclass
class DataFlowPath:
    """
    Represents how data flows through multiple functions.

    Example: user_id flows from API -> UserService -> UserRepository -> Database
    """
    variable_name: str
    start_function: str
    end_function: str
    path: List[str]  # List of functions in order
    transformations: List[str]  # How data is transformed at each step

    def to_embedding_text(self) -> str:
        """Generate text for semantic search."""
        path_str = " -> ".join(self.path)
        return f"""
Data flow: {self.variable_name}
Path: {path_str}
Transformations: {', '.join(self.transformations)}
"""


@dataclass
class EnhancedCodeAnalysis:
    """
    Extended analysis that includes call graph information.

    This replaces the basic CodeAnalysis with AST-powered insights.
    """
    # Original fields
    purpose: str
    dependencies: List[str]
    exported_symbols: List[str]

    # NEW: Call graph fields
    function_calls: List[CallGraphRelation]  # All calls made by this file
    called_by: List[str]  # Functions that call into this file (cross-file)
    data_flows: List[DataFlowPath]  # How data moves through this file

    # NEW: Type information
    type_definitions: List[str]  # Classes, interfaces, types defined
    type_usage: List[str]  # Types used in parameters/returns

    def get_call_chain_summary(self) -> str:
        """
        Generate a human-readable summary of call chains.

        Example output:
        - main() calls process_request()
        - process_request() calls validate() -> authenticate() -> handle()
        """
        if not self.function_calls:
            return "No function calls found"

        lines = []
        # Group by caller
        by_caller = {}
        for call in self.function_calls:
            if call.caller_function not in by_caller:
                by_caller[call.caller_function] = []
            by_caller[call.caller_function].append(call.callee_name)

        for caller, callees in by_caller.items():
            callees_str = " -> ".join(callees[:5])  # Limit to 5
            if len(callees) > 5:
                callees_str += f" ... (+{len(callees) - 5} more)"
            lines.append(f"- {caller}() calls: {callees_str}")

        return "\n".join(lines)
