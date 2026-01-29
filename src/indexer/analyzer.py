"""Code analysis using OpenAI with project context."""

import json
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from ..storage.models import CodeAnalysis, FunctionInfo, ProjectContext
from ..utils.logger import get_logger

logger = get_logger(__name__)


async def analyze_code(
    code: str,
    file_path: Path,
    language: str,
    file_type: str,
    project_context: Optional[ProjectContext],
    client: AsyncOpenAI
) -> CodeAnalysis:
    """
    Analyze code file using OpenAI with project context.

    Args:
        code: Code content.
        file_path: Path to file.
        language: Programming language.
        file_type: File type (code|documentation|config|test).
        project_context: Project context for better analysis.
        client: OpenAI async client.

    Returns:
        CodeAnalysis object.
    """
    # Build prompt based on file type
    if file_type == "code":
        prompt = _build_code_analysis_prompt(code, file_path, language, project_context)
    elif file_type == "documentation":
        prompt = _build_doc_analysis_prompt(code, file_path, project_context)
    elif file_type == "config":
        prompt = _build_config_analysis_prompt(code, file_path, project_context)
    else:
        prompt = _build_code_analysis_prompt(code, file_path, language, project_context)

    try:
        # Using Responses API with gpt-5.2-codex for better code analysis
        response = await client.responses.create(
            model="gpt-5.2-codex",
            input=prompt,
            instructions="You are a code analysis expert. Analyze code and provide structured JSON output.",
            text={
                "format": {"type": "json_object"}
            },
            reasoning={
                "effort": "medium"  # Balanced reasoning for code analysis
            }
        )

        # Parse response - handle both string and dict
        output_text = response.output_text

        if isinstance(output_text, str):
            result = json.loads(output_text)
        else:
            result = output_text

        # Validate that result is a dict
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict, got {type(result).__name__}: {result}")

        # Parse functions with safe access
        functions = []
        key_functions = result.get("key_functions", [])
        if isinstance(key_functions, list):
            for func in key_functions:
                if isinstance(func, dict):
                    functions.append(FunctionInfo(
                        name=func.get("name", ""),
                        description=func.get("description", ""),
                        parameters=func.get("parameters", []),
                        return_type=func.get("return_type", "unknown")
                    ))

        analysis = CodeAnalysis(
            purpose=result.get("purpose", ""),
            dependencies=result.get("dependencies", []),
            exported_symbols=result.get("exported_symbols", []),
            key_functions=functions,
            architectural_notes=result.get("architectural_notes", "")
        )

        return analysis

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from {file_path}: {e}. Response: {response.output_text[:200]}")
    except Exception as e:
        logger.error(f"Failed to analyze {file_path}: {e}")
        # Return minimal analysis
        return CodeAnalysis(
            purpose=f"Failed to analyze: {str(e)}",
            dependencies=[],
            exported_symbols=[],
            key_functions=[],
            architectural_notes=""
        )


def _build_code_analysis_prompt(
    code: str,
    file_path: Path,
    language: str,
    project_context: Optional[ProjectContext]
) -> str:
    """Build prompt for code analysis."""

    context_section = ""
    if project_context:
        context_section = f"""PROJECT CONTEXT:
- Project: {project_context.project_name}
- Description: {project_context.project_description}
- Tech Stack: {', '.join(project_context.tech_stack)}
- Architecture: {project_context.architecture_type}
- Frameworks: {', '.join(project_context.frameworks)}
"""

    prompt = f"""{context_section}

FILE TO ANALYZE:
File: {file_path}
Language: {language}

Code:
```{language}
{code[:8000]}
```

Analyze this code file and provide a JSON response with:
{{
  "purpose": "What does this file do? How does it fit into the project? (2-3 sentences)",
  "dependencies": ["list", "of", "imported", "modules", "or", "packages"],
  "exported_symbols": ["list", "of", "public", "functions", "classes", "exports"],
  "key_functions": [
    {{
      "name": "function_name",
      "description": "What this function does in the context of the project",
      "parameters": ["param1", "param2"],
      "return_type": "string|void|etc"
    }}
  ],
  "architectural_notes": "How this file relates to other parts of the project, patterns used, etc"
}}

Focus on semantic understanding in the context of the overall project. Be concise but informative.
"""

    return prompt


def _build_doc_analysis_prompt(
    content: str,
    file_path: Path,
    project_context: Optional[ProjectContext]
) -> str:
    """Build prompt for documentation analysis."""

    context_section = ""
    if project_context:
        context_section = f"PROJECT CONTEXT:\n- Project: {project_context.project_name}\n\n"

    prompt = f"""{context_section}

DOCUMENTATION FILE:
File: {file_path}

Content:
{content[:4000]}

Analyze this documentation and provide JSON:
{{
  "purpose": "What this document explains (1-2 sentences)",
  "topics": ["main", "topics", "covered"],
  "key_concepts": ["important", "concepts"],
  "dependencies": [],
  "exported_symbols": [],
  "key_functions": [],
  "architectural_notes": "Relevance to the project"
}}
"""

    return prompt


def _build_config_analysis_prompt(
    content: str,
    file_path: Path,
    project_context: Optional[ProjectContext]
) -> str:
    """Build prompt for configuration file analysis."""

    context_section = ""
    if project_context:
        context_section = f"PROJECT CONTEXT:\n- Project: {project_context.project_name}\n\n"

    prompt = f"""{context_section}

CONFIGURATION FILE:
File: {file_path}

Content:
{content[:4000]}

Analyze this configuration file and provide JSON:
{{
  "purpose": "What this configuration controls (1-2 sentences)",
  "key_settings": ["important", "settings"],
  "dependencies": ["services", "or", "tools", "configured"],
  "exported_symbols": [],
  "key_functions": [],
  "architectural_notes": "Impact on project architecture"
}}
"""

    return prompt
