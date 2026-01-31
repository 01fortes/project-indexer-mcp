"""Analyzes project context before indexing individual files."""

import json
from pathlib import Path
from typing import Dict, List, Optional

from ..providers.base import LLMProvider, ChatMessage
from ..storage.models import ProjectContext
from ..utils.logger import get_logger

logger = get_logger(__name__)


# Configuration file names by language/tool
CONFIG_FILES = {
    "python": ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile", "setup.cfg"],
    "nodejs": ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
    "rust": ["Cargo.toml", "Cargo.lock"],
    "go": ["go.mod", "go.sum"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "ruby": ["Gemfile", "Gemfile.lock", "gemspec"],
    "php": ["composer.json", "composer.lock"],
    "dotnet": ["*.csproj", "*.sln", "packages.config"],
}

# Framework detection patterns
FRAMEWORK_PATTERNS = {
    "fastapi": ["fastapi", "FastAPI"],
    "django": ["django", "Django"],
    "flask": ["flask", "Flask"],
    "react": ["react", "React"],
    "vue": ["vue", "Vue"],
    "angular": ["@angular"],
    "express": ["express"],
    "nextjs": ["next"],
    "nuxt": ["nuxt"],
    "spring": ["spring-boot", "springframework"],
    "rails": ["rails"],
}


async def analyze_project_context(
    project_path: Path,
    llm_provider: LLMProvider
) -> ProjectContext:
    """
    Analyze project to understand overall context.

    This function:
    1. Scans project structure (max depth 3)
    2. Finds and reads configuration files
    3. Detects tech stack and frameworks
    4. Reads README and documentation
    5. Sends to LLM for contextual understanding
    6. Returns ProjectContext object

    Args:
        project_path: Path to project root.
        llm_provider: LLM provider for analysis.

    Returns:
        ProjectContext with project information.
    """
    logger.info(f"Analyzing project context for: {project_path}")

    # Step 1: Build file tree summary
    file_tree = await build_file_tree_summary(project_path, max_depth=3)

    # Step 2: Detect tech stack
    tech_info = await detect_tech_stack(project_path)

    # Step 3: Read key documentation files
    docs = await read_key_files(project_path)

    # Step 4: Prepare prompt
    prompt = _build_context_prompt(project_path, file_tree, tech_info, docs)

    # Step 5: Define JSON schema for response
    schema = {
        "name": "project_context",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "project_description": {"type": "string"},
                "tech_stack": {"type": "array", "items": {"type": "string"}},
                "frameworks": {"type": "array", "items": {"type": "string"}},
                "dependencies": {"type": "array", "items": {"type": "string"}},
                "architecture_type": {"type": "string"},
                "project_structure": {"type": "string"},
                "key_entry_points": {"type": "array", "items": {"type": "string"}},
                "build_system": {"type": "string"},
                "purpose": {"type": "string"}
            },
            "required": ["project_name", "project_description", "tech_stack", "frameworks",
                        "dependencies", "architecture_type", "project_structure",
                        "key_entry_points", "build_system", "purpose"],
            "additionalProperties": False
        }
    }

    # Step 6: Call LLM provider
    try:
        response = await llm_provider.chat_completion(
            messages=[
                ChatMessage(
                    role="system",
                    content="You are a code analysis expert. Analyze project structure and provide JSON output."
                ),
                ChatMessage(
                    role="user",
                    content=prompt
                )
            ],
            response_format={"type": "json_schema", "json_schema": schema},
            use_reasoning=True  # Для анализа проекта используем reasoning
        )

        # Parse response
        result = json.loads(response.content)

        context = ProjectContext(
            project_name=result.get("project_name", project_path.name),
            project_description=result.get("project_description", ""),
            tech_stack=result.get("tech_stack", []),
            frameworks=result.get("frameworks", []),
            dependencies=result.get("dependencies", []),
            architecture_type=result.get("architecture_type", "unknown"),
            project_structure=result.get("project_structure", ""),
            key_entry_points=result.get("key_entry_points", []),
            build_system=result.get("build_system", "unknown"),
            purpose=result.get("purpose", "")
        )

        logger.info(f"Project context analyzed: {context.project_name} ({', '.join(context.tech_stack)})")
        return context

    except Exception as e:
        logger.error(f"Failed to analyze project context: {e}")
        # Return minimal context
        return ProjectContext(
            project_name=project_path.name,
            project_description="Failed to analyze project context",
            tech_stack=tech_info.get("languages", []),
            frameworks=tech_info.get("frameworks", []),
            dependencies=tech_info.get("dependencies", [])[:10],  # First 10
        )


async def build_file_tree_summary(project_path: Path, max_depth: int = 3) -> str:
    """
    Build a summary of project structure.

    Args:
        project_path: Project root path.
        max_depth: Maximum directory depth to scan.

    Returns:
        String representation of directory tree.
    """

    def walk_directory(path: Path, current_depth: int, prefix: str = "") -> List[str]:
        """Recursively walk directory."""
        if current_depth > max_depth:
            return []

        lines = []
        try:
            items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
            for i, item in enumerate(items):
                # Skip hidden files and common excludes
                if item.name.startswith('.') or item.name in ['node_modules', '__pycache__', 'venv', '.venv']:
                    continue

                is_last = i == len(items) - 1
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{item.name}{'/' if item.is_dir() else ''}")

                if item.is_dir() and current_depth < max_depth:
                    extension = "    " if is_last else "│   "
                    lines.extend(walk_directory(item, current_depth + 1, prefix + extension))

        except PermissionError:
            pass

        return lines

    tree_lines = [f"{project_path.name}/"]
    tree_lines.extend(walk_directory(project_path, 0))
    return "\n".join(tree_lines)


async def detect_tech_stack(project_path: Path) -> Dict[str, any]:
    """
    Detect technologies, frameworks, and dependencies.

    Args:
        project_path: Project root path.

    Returns:
        Dictionary with tech_stack info.
    """
    info = {
        "languages": [],
        "frameworks": [],
        "dependencies": [],
        "config_files": {}
    }

    # Check for configuration files
    for lang, files in CONFIG_FILES.items():
        for filename in files:
            if "*" in filename:
                # Handle wildcards
                matches = list(project_path.glob(filename))
                if matches:
                    info["config_files"][lang] = [str(m.relative_to(project_path)) for m in matches]
                    if lang not in info["languages"]:
                        info["languages"].append(lang)
            else:
                config_file = project_path / filename
                if config_file.exists():
                    info["config_files"][lang] = [filename]
                    if lang not in info["languages"]:
                        info["languages"].append(lang)

                    # Parse dependencies
                    try:
                        deps = await _parse_dependencies(config_file, lang)
                        info["dependencies"].extend(deps)

                        # Detect frameworks
                        for framework, patterns in FRAMEWORK_PATTERNS.items():
                            if any(pattern in dep for dep in deps for pattern in patterns):
                                if framework not in info["frameworks"]:
                                    info["frameworks"].append(framework)
                    except Exception as e:
                        logger.warning(f"Failed to parse {config_file}: {e}")

    return info


async def read_key_files(project_path: Path) -> Dict[str, str]:
    """
    Read README and other key documentation files.

    Args:
        project_path: Project root path.

    Returns:
        Dictionary mapping filename to content (truncated if needed).
    """
    docs = {}

    # List of documentation files to look for
    doc_files = [
        "README.md", "README.rst", "README.txt", "README",
        "CONTRIBUTING.md", "ARCHITECTURE.md",
        "docs/index.md", "docs/README.md"
    ]

    for filename in doc_files:
        file_path = project_path / filename
        if file_path.exists() and file_path.is_file():
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                # Truncate to first 2000 characters
                docs[filename] = content[:2000] if len(content) > 2000 else content
            except Exception as e:
                logger.warning(f"Failed to read {filename}: {e}")

    return docs


async def _parse_dependencies(config_file: Path, lang: str) -> List[str]:
    """
    Parse dependencies from configuration file.

    Args:
        config_file: Path to config file.
        lang: Language/tool type.

    Returns:
        List of dependency names.
    """
    deps = []

    try:
        content = config_file.read_text(encoding='utf-8')

        if lang == "python":
            if config_file.name == "requirements.txt":
                # Parse requirements.txt
                for line in content.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Extract package name (before ==, >=, etc.)
                        pkg = line.split('==')[0].split('>=')[0].split('<=')[0].split('~=')[0].strip()
                        deps.append(pkg)

            elif config_file.name == "pyproject.toml":
                # Simple TOML parsing for dependencies
                import re
                # Find dependencies section
                matches = re.findall(r'"([^"]+)"', content)
                deps.extend([m for m in matches if '=' not in m and '/' not in m])

        elif lang == "nodejs":
            if config_file.name == "package.json":
                import json
                data = json.loads(content)
                if "dependencies" in data:
                    deps.extend(data["dependencies"].keys())
                if "devDependencies" in data:
                    deps.extend(data["devDependencies"].keys())

        elif lang == "rust":
            if config_file.name == "Cargo.toml":
                # Simple TOML parsing
                import re
                # Find dependencies in [dependencies] section
                in_deps = False
                for line in content.split('\n'):
                    if '[dependencies]' in line:
                        in_deps = True
                        continue
                    if in_deps and line.startswith('['):
                        break
                    if in_deps and '=' in line:
                        dep_name = line.split('=')[0].strip()
                        if dep_name:
                            deps.append(dep_name)

    except Exception as e:
        logger.warning(f"Error parsing dependencies from {config_file}: {e}")

    return deps[:50]  # Limit to 50 dependencies


def _build_context_prompt(
    project_path: Path,
    file_tree: str,
    tech_info: Dict[str, any],
    docs: Dict[str, str]
) -> str:
    """Build prompt for OpenAI to analyze project context."""

    # Format configuration files
    config_files_str = "\n".join([
        f"- {lang}: {', '.join(files)}"
        for lang, files in tech_info.get("config_files", {}).items()
    ])

    # Format README content
    readme_content = ""
    if docs:
        readme_content = "\n\n".join([
            f"=== {filename} ===\n{content}"
            for filename, content in docs.items()
        ])

    # Format dependencies
    dependencies_list = "\n".join([f"- {dep}" for dep in tech_info.get("dependencies", [])[:30]])

    prompt = f"""You are analyzing a software project to understand its overall context.

Project Path: {project_path}

Project Structure (key files and directories):
{file_tree}

Configuration Files Found:
{config_files_str if config_files_str else "None found"}

README/Documentation:
{readme_content if readme_content else "No documentation found"}

Package Dependencies:
{dependencies_list if dependencies_list else "No dependencies found"}

Detected Languages: {', '.join(tech_info.get('languages', []))}
Detected Frameworks: {', '.join(tech_info.get('frameworks', []))}

Based on this information, provide a JSON response with:
{{
  "project_name": "Name of the project (from README or directory name)",
  "project_description": "Brief description of what this project does (2-3 sentences)",
  "tech_stack": ["list", "of", "technologies", "like Python, React, etc"],
  "frameworks": ["list", "of", "frameworks", "like Django, FastAPI, Next.js, etc"],
  "dependencies": ["key", "dependencies"],
  "architecture_type": "monolithic|microservices|library|cli-tool|serverless|mobile-app|web-app",
  "project_structure": "Description of how the project is organized (2-3 sentences)",
  "key_entry_points": ["main.py", "src/index.ts", "etc"],
  "build_system": "npm|poetry|cargo|gradle|maven|pip|make|etc",
  "purpose": "What problem does this project solve? What is its main purpose?"
}}

Be concise but informative. Focus on understanding the big picture. If information is missing, make reasonable inferences based on file structure and naming conventions.
"""

    return prompt
