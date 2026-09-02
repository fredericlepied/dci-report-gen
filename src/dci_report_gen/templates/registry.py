from __future__ import annotations

import re
from pathlib import Path

import yaml

TEMPLATES_DIR = Path(__file__).parent


def _find_template(name: str) -> Path | None:
    path = TEMPLATES_DIR / f"{name}.yaml"
    if path.exists():
        return path
    return None


def expand_template(name: str, params: dict) -> tuple[dict, dict]:
    """Load a YAML template, substitute params, return (parsed_yaml, vars).

    Substitution happens on the raw YAML text before parsing so that
    numeric fields like `limit: "{{limit}}"` become `limit: 50`.
    """
    path = _find_template(name)
    if path is None:
        available = [p.stem for p in TEMPLATES_DIR.glob("*.yaml")]
        raise ValueError(
            f"Unknown template: {name}. Available: {', '.join(available) or 'none'}"
        )

    with open(path) as f:
        text = f.read()

    pre_raw = yaml.safe_load(text)
    declared_params = pre_raw.get("params", {})
    template_vars = {}
    for key, spec in declared_params.items():
        if isinstance(spec, dict):
            if key in params:
                template_vars[key] = str(params[key])
            elif "default" in spec:
                template_vars[key] = str(spec["default"])
            elif spec.get("required", False):
                raise ValueError(f"Template '{name}' requires param: {key}")
        else:
            template_vars[key] = str(spec)

    for key, value in params.items():
        if key not in template_vars:
            template_vars[key] = str(value)

    def replacer(match):
        key = match.group(1)
        return template_vars.get(key, match.group(0))

    substituted = re.sub(r"\{\{(\w+)\}\}", replacer, text)
    raw = yaml.safe_load(substituted)

    return raw, template_vars


def list_templates() -> list[tuple[str, str]]:
    templates = []
    for path in sorted(TEMPLATES_DIR.glob("*.yaml")):
        with open(path) as f:
            raw = yaml.safe_load(f)
        description = raw.get("description", "")
        templates.append((path.stem, description))
    return templates
