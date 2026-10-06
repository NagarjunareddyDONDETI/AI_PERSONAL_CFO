"""Financial Skills Registry for AI Personal CFO.

Discovers, parses, and provides standardized financial skills inspired by
Hermes Agent's skill architecture. Every skill specifies:
- Frontmatter metadata (name, description, category, required_tools, safety_constraints).
- Detailed procedures grounded in deterministic tools.
- Strict safety bounds prohibiting LLM calculation hallucinations.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("skills.registry")

_SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass
class FinancialSkill:
    name: str
    description: str
    version: str
    author: str
    category: str
    required_tools: list[str] = field(default_factory=list)
    required_data: list[str] = field(default_factory=list)
    safety_constraints: list[str] = field(default_factory=list)
    content: str = ""
    file_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "category": self.category,
            "required_tools": self.required_tools,
            "required_data": self.required_data,
            "safety_constraints": self.safety_constraints,
        }

    def get_prompt_instructions(self) -> str:
        """Format skill for injection into agent context."""
        tools_str = ", ".join(self.required_tools) if self.required_tools else "None"
        safety_str = "\n".join(f"- {sc}" for sc in self.safety_constraints) if self.safety_constraints else "Standard safety rules apply."
        return f"""### Active Financial Skill: {self.name}
**Category**: {self.category} | **Required Tools**: `{tools_str}`
**Goal**: {self.description}

**Safety Constraints**:
{safety_str}

**Execution Instructions**:
{self.content}
"""


class SkillRegistry:
    """Registry that indexes and manages all available financial skills."""

    def __init__(self, skills_dir: Optional[str] = None) -> None:
        self._skills_dir = skills_dir or _SKILLS_DIR
        self._skills: dict[str, FinancialSkill] = {}
        self.reload_skills()

    def reload_skills(self) -> None:
        """Scan skills directory and parse all SKILL.md files."""
        self._skills.clear()
        if not os.path.exists(self._skills_dir):
            return

        for root, _dirs, files in os.walk(self._skills_dir):
            for file in files:
                if file.lower() == "skill.md":
                    full_path = os.path.join(root, file)
                    try:
                        skill = self._parse_skill_file(full_path)
                        if skill:
                            self._skills[skill.name] = skill
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to parse skill at %s: %s", full_path, exc)

        logger.info("Loaded %d financial skills from %s", len(self._skills), self._skills_dir)

    def _parse_skill_file(self, file_path: str) -> Optional[FinancialSkill]:
        """Parse frontmatter and markdown body of a SKILL.md file."""
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
        if not fm_match:
            logger.warning("No YAML frontmatter found in %s", file_path)
            return None

        fm_text = fm_match.group(1)
        body = fm_match.group(2).strip()

        # Parse frontmatter key-values
        meta: dict[str, Any] = {}
        current_list_key = None
        for line in fm_text.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue

            if line_str.startswith("- ") and current_list_key:
                meta[current_list_key].append(line_str[2:].strip().strip('"').strip("'"))
            elif ":" in line_str:
                parts = line_str.split(":", 1)
                k = parts[0].strip()
                v = parts[1].strip().strip('"').strip("'")
                if not v:
                    meta[k] = []
                    current_list_key = k
                else:
                    meta[k] = v
                    current_list_key = None

        name = meta.get("name") or os.path.basename(os.path.dirname(file_path))
        description = meta.get("description", "")
        version = meta.get("version", "1.0.0")
        author = meta.get("author", "AI Personal CFO")
        category = meta.get("category", "general")
        required_tools = meta.get("required_tools", [])
        required_data = meta.get("required_data", [])
        safety_constraints = meta.get("safety_constraints", [])

        if isinstance(required_tools, str):
            required_tools = [required_tools]
        if isinstance(required_data, str):
            required_data = [required_data]
        if isinstance(safety_constraints, str):
            safety_constraints = [safety_constraints]

        return FinancialSkill(
            name=name,
            description=description,
            version=version,
            author=author,
            category=category,
            required_tools=required_tools,
            required_data=required_data,
            safety_constraints=safety_constraints,
            content=body,
            file_path=file_path,
        )

    def get_skill(self, name: str) -> Optional[FinancialSkill]:
        return self._skills.get(name)

    def list_skills(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._skills.values()]

    def match_skill(self, query: str) -> Optional[FinancialSkill]:
        """Match user query to the most relevant skill using semantic keyword heuristics."""
        q = (query or "").lower()
        if not q:
            return None

        # Keyword mapping to skills
        mapping = [
            (r"\b(health|score|rating|checkup|how am i doing|scorecard)\b", "financial-health-assessment"),
            (r"\b(budget|50/30/20|spending breakdown|needs wants|expenses balance)\b", "budget-analysis"),
            (r"\b(emergency|runway|safety net|rainy day|reserve fund)\b", "emergency-fund-audit"),
            (r"\b(debt|loan|emi|credit card|avalanche|snowball|payoff|interest paid)\b", "debt-payoff-optimizer"),
            (r"\b(invest|compound|returns|growth|stocks|portfolio|wealth in \d+ years)\b", "investment-risk-allocation"),
            (r"\b(forecast|liquidity|next month|run out of money|cashflow future|future cash)\b", "cashflow-forecast"),
            (r"\b(goal|milestone|save for|buy a house|vacation fund|retirement target)\b", "goal-feasibility-planner"),
            (r"\b(creep|discretionary spike|spending more|luxury|leakage)\b", "lifestyle-creep-detector"),
            (r"\b(tax|deduction|tax saving|80c|exemptions|tax liability)\b", "tax-optimization-strategy"),
        ]

        for pattern, skill_name in mapping:
            if re.search(pattern, q):
                skill = self._skills.get(skill_name)
                if skill:
                    return skill

        return None


# Singleton skill registry
skill_registry = SkillRegistry()
