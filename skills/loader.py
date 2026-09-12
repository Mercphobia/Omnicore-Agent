"""Skill loader — discovers, loads, and manages reusable skill modules.
DNA: Hermes Agent (self-improving skills).
"""

import importlib.util
from pathlib import Path
from typing import Optional


class Skill:
    """A reusable skill — prompt template + metadata."""

    def __init__(self, name: str, description: str, prompt: str, triggers: list[str] | None = None):
        self.name = name
        self.description = description
        self.prompt = prompt
        self.triggers = triggers or []

    def matches(self, user_input: str) -> bool:
        """Check if this skill should activate for the given input."""
        if not self.triggers:
            return False
        text = user_input.lower()
        return any(t.lower() in text for t in self.triggers)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "prompt": self.prompt,
            "triggers": self.triggers,
        }


class SkillLoader:
    """Discovers, loads, and activates skills."""

    def __init__(self, skill_dirs: list[Path] | None = None):
        if skill_dirs is None:
            skill_dirs = [
                Path(__file__).parent / "builtin",
                Path.home() / ".omnicore" / "skills",
            ]
        self.skill_dirs = [d for d in skill_dirs if d.exists()]
        self._skills: dict[str, Skill] = {}
        self.load_all()

    def load_all(self) -> None:
        """Discover and load all skills from all directories."""
        for skill_dir in self.skill_dirs:
            if not skill_dir.exists():
                continue
            for f in sorted(skill_dir.rglob("*.py")):
                if f.name.startswith("_"):
                    continue
                try:
                    self._load_python_skill(f)
                except Exception:
                    continue

    def _load_python_skill(self, path: Path) -> None:
        """Load a skill from a Python module.
        
        Expected module structure:
            NAME = "skill_name"
            DESCRIPTION = "..."
            PROMPT = "..."
            TRIGGERS = ["keyword1", "keyword2"]
        """
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        name = getattr(module, "NAME", path.stem)
        desc = getattr(module, "DESCRIPTION", "")
        prompt = getattr(module, "PROMPT", "")
        triggers = getattr(module, "TRIGGERS", [])

        if prompt:
            self._skills[name] = Skill(name, desc, prompt, triggers)

    def register(self, skill: Skill) -> None:
        """Manually register a skill."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def find_matching(self, user_input: str) -> list[Skill]:
        """Find all skills that match the user input."""
        return [s for s in self._skills.values() if s.matches(user_input)]

    def list_all(self) -> list[Skill]:
        return list(self._skills.values())

    def get_active_prompts(self, user_input: str) -> str:
        """Get prompts from all matching skills, combined."""
        matching = self.find_matching(user_input)
        if not matching:
            return ""
        parts = []
        for s in matching:
            parts.append(f"[Skill: {s.name} — {s.description}]\n{s.prompt}")
        return "\n\n".join(parts)

    def save_skill(self, skill: Skill, target_dir: Path | None = None) -> Path:
        """Save a skill as a Python module to the user's skill directory."""
        target = target_dir or (Path.home() / ".omnicore" / "skills")
        target.mkdir(parents=True, exist_ok=True)
        
        filename = skill.name.lower().replace(" ", "_") + ".py"
        filepath = target / filename

        content = f'''"""Auto-generated skill: {skill.name}"""
NAME = "{skill.name}"
DESCRIPTION = "{skill.description}"
TRIGGERS = {skill.triggers}
PROMPT = """{skill.prompt}"""
'''
        filepath.write_text(content)
        return filepath