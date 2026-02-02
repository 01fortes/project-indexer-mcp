"""Enhanced code analyzer combining AST (tree-sitter) + LLM analysis.

This module provides the best of both worlds:
- AST: Precise, structured call graph extraction
- LLM: Semantic understanding and natural language descriptions
"""

from pathlib import Path
from typing import List, Optional

from ..providers.base import LLMProvider, ChatMessage
from ..storage.call_graph_models import CallGraphRelation, EnhancedCodeAnalysis
from ..storage.models import ProjectContext
from ..utils.logger import get_logger
from .ast_analyzer import ASTAnalyzer

logger = get_logger(__name__)


class EnhancedCodeAnalyzer:
    """
    Analyzes code using both AST parsing and LLM understanding.

    Pipeline:
    1. AST Parser extracts precise call graph
    2. LLM adds semantic understanding and descriptions
    3. Combined result has both structure and meaning
    """

    def __init__(self, llm_provider: LLMProvider):
        """
        Initialize analyzer.

        Args:
            llm_provider: LLM for semantic analysis
        """
        self.llm_provider = llm_provider
        self.ast_analyzer = ASTAnalyzer()

    async def analyze_file(
        self,
        code: str,
        file_path: Path,
        language: str,
        project_context: Optional[ProjectContext] = None
    ) -> EnhancedCodeAnalysis:
        """
        Perform enhanced analysis with both AST and LLM.

        Args:
            code: Source code content
            file_path: Path to file
            language: Programming language
            project_context: Project context for better understanding

        Returns:
            EnhancedCodeAnalysis with call graph and semantic info
        """
        # Step 1: AST Analysis (precise structure)
        call_graph = self.ast_analyzer.analyze_file(file_path, language, code)

        if not call_graph:
            # Fallback to LLM-only analysis
            logger.debug(f"AST not available for {language}, using LLM only")
            return await self._llm_only_analysis(code, file_path, language, project_context)

        # Step 2: LLM Analysis (semantic understanding)
        # Ask LLM to describe what each function call does
        call_relations = await self._enrich_call_graph_with_llm(
            call_graph,
            code,
            file_path,
            project_context
        )

        # Step 3: Extract data flows (LLM-powered)
        # data_flows = await self._extract_data_flows(call_graph, code, file_path)

        # Step 4: Combine everything
        return EnhancedCodeAnalysis(
            purpose=await self._generate_file_purpose(code, file_path, project_context),
            dependencies=[imp.module for imp in call_graph.imports],
            exported_symbols=call_graph.exports,
            function_calls=call_relations,
            called_by=[],  # Will be populated in cross-file analysis
            data_flows=[],  # TODO: Implement data flow analysis
            type_definitions=[],  # TODO: Extract from AST
            type_usage=[]
        )

    async def _enrich_call_graph_with_llm(
        self,
        call_graph,
        code: str,
        file_path: Path,
        project_context: Optional[ProjectContext]
    ) -> List[CallGraphRelation]:
        """
        Use LLM to add semantic descriptions to call graph.

        For each function call extracted by AST, ask LLM:
        - What is the purpose of this call?
        - What data is being passed?
        - How does it fit in the bigger picture?
        """
        relations = []

        if not call_graph.calls:
            return relations

        # Group calls by function for efficient LLM processing
        calls_by_function = {}
        for call in call_graph.calls:
            if call.caller_function not in calls_by_function:
                calls_by_function[call.caller_function] = []
            calls_by_function[call.caller_function].append(call)

        # Process each function's calls
        for caller_func, calls in calls_by_function.items():
            descriptions = await self._describe_calls_with_llm(
                calls,
                code,
                file_path,
                project_context
            )

            for call, description in zip(calls, descriptions):
                relation = CallGraphRelation(
                    caller_file=str(file_path),
                    caller_function=caller_func,
                    caller_line=call.line_number,
                    callee_name=call.callee_name,
                    callee_file=None,  # TODO: Resolve cross-file
                    callee_module=call.module,
                    arguments=call.arguments,
                    argument_types=[],  # TODO: Extract from AST
                    project_root=str(file_path.parent),
                    description=description
                )
                relations.append(relation)

        return relations

    async def _describe_calls_with_llm(
        self,
        calls: List,
        code: str,
        file_path: Path,
        project_context: Optional[ProjectContext]
    ) -> List[str]:
        """
        Ask LLM to describe what each function call does.

        Returns list of descriptions matching the order of calls.
        """
        if not calls:
            return []

        # Build prompt with call context
        calls_info = "\n".join([
            f"- Line {call.line_number}: {call.callee_name}({', '.join(call.arguments[:3])})"
            for call in calls[:10]  # Limit to 10 calls per batch
        ])

        context_section = ""
        if project_context:
            context_section = f"""
Project Context:
- Name: {project_context.project_name}
- Type: {project_context.architecture_type}
- Stack: {', '.join(project_context.tech_stack)}
"""

        prompt = f"""{context_section}

File: {file_path}

Function calls found:
{calls_info}

Code context:
```
{code[:3000]}
```

For each function call, provide a brief description (1 sentence) of:
1. What is the purpose of this call?
2. What does it contribute to the overall logic?

Return as JSON array: ["description1", "description2", ...]
Limit to {len(calls[:10])} descriptions matching the calls above.
"""

        try:
            response = await self.llm_provider.chat_completion(
                messages=[
                    ChatMessage(role="system", content="You are a code analyst."),
                    ChatMessage(role="user", content=prompt)
                ]
            )

            # Parse response
            import json
            descriptions = json.loads(response.content)

            if not isinstance(descriptions, list):
                descriptions = [str(descriptions)] * len(calls)

            # Pad if needed
            while len(descriptions) < len(calls):
                descriptions.append("Function call")

            return descriptions[:len(calls)]

        except Exception as e:
            logger.warning(f"Failed to get LLM descriptions: {e}")
            return ["Function call" for _ in calls]

    async def _generate_file_purpose(
        self,
        code: str,
        file_path: Path,
        project_context: Optional[ProjectContext]
    ) -> str:
        """Generate high-level file purpose description."""
        # Simplified version - you can reuse existing analyzer logic
        return f"Code file at {file_path.name}"

    async def _llm_only_analysis(
        self,
        code: str,
        file_path: Path,
        language: str,
        project_context: Optional[ProjectContext]
    ) -> EnhancedCodeAnalysis:
        """
        Fallback to LLM-only analysis when AST is not available.
        """
        # Import existing analyzer
        from .analyzer import analyze_code

        basic_analysis = await analyze_code(
            code, file_path, language, "code", project_context, self.llm_provider
        )

        # Convert to enhanced format
        return EnhancedCodeAnalysis(
            purpose=basic_analysis.purpose,
            dependencies=basic_analysis.dependencies,
            exported_symbols=basic_analysis.exported_symbols,
            function_calls=[],  # No precise call graph without AST
            called_by=[],
            data_flows=[],
            type_definitions=[],
            type_usage=[]
        )


async def test_enhanced_analysis():
    """Test enhanced analyzer."""
    from ..providers.openai_provider import OpenAIProvider
    from ..config import load_config

    config = load_config()
    llm_provider = OpenAIProvider(
        api_key=config.openai.api_key,
        model=config.openai.model,
        max_retries=3
    )

    analyzer = EnhancedCodeAnalyzer(llm_provider)

    sample_code = """
import os
from typing import List

def process_users(user_ids: List[int]) -> None:
    for user_id in user_ids:
        user = fetch_user(user_id)
        validate_user(user)
        save_to_db(user)

def fetch_user(user_id: int) -> dict:
    return {"id": user_id, "name": "Test"}

def validate_user(user: dict) -> bool:
    return user.get("id") is not None
"""

    result = await analyzer.analyze_file(
        sample_code,
        Path("test.py"),
        "python",
        None
    )

    print("Enhanced Analysis Result:")
    print(f"Purpose: {result.purpose}")
    print(f"Exports: {result.exported_symbols}")
    print(f"Function calls: {len(result.function_calls)}")

    for call in result.function_calls:
        print(f"\n  {call.caller_function} -> {call.callee_name}")
        print(f"    Description: {call.description}")
        print(f"    Arguments: {call.arguments}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_enhanced_analysis())
