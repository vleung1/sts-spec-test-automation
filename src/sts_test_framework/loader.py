"""
Load and parse OpenAPI spec (v2.json).

Provides ``load_spec``, path/schema accessors, and ``normalize_path_for_base`` so
generated request paths align with a base URL that already includes ``/v2``.
"""
import json
from pathlib import Path
from typing import Any

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def load_spec(spec_path: str | Path) -> dict[str, Any]:
    """
    Load OpenAPI spec from file. Accepts .json or .yaml/.yml.
    Returns the full spec dict; paths use keys as in the file (e.g. /v2/..., /).
    """
    path = Path(spec_path)
    if not path.exists():
        raise FileNotFoundError(f"Spec file not found: {spec_path}")

    raw = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    # Try JSON first (works for .json and for .yaml files that contain JSON)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    if suffix == ".json":
        raise RuntimeError("Spec file is not valid JSON.")
    if suffix in (".yaml", ".yml"):
        if not HAS_YAML:
            raise RuntimeError("PyYAML is required to load YAML spec. Install with: pip install PyYAML")
        return yaml.safe_load(raw)

    if HAS_YAML:
        return yaml.safe_load(raw)
    raise RuntimeError("Spec is not valid JSON and PyYAML is not installed.")


def get_paths(spec: dict[str, Any]) -> dict[str, Any]:
    """Return the OpenAPI ``paths`` object: template string -> path item (methods, parameters)."""
    return spec.get("paths") or {}


def get_schemas(spec: dict[str, Any]) -> dict[str, Any]:
    """Return ``components.schemas`` for contract validation and documentation."""
    components = spec.get("components") or {}
    return components.get("schemas") or {}


def get_operations(spec: dict[str, Any], tag_filter: list[str] | None = None) -> list[tuple[str, str, dict]]:
    """
    Yield every HTTP operation under ``paths`` (optional tag filter).

    Yields:
        ``(path_template, lower_case_method, operation_dict)``. The generator module
        uses ``_iter_ops`` instead but behavior is analogous.
    """
    paths = get_paths(spec)
    for path_template, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            if tag_filter:
                op_tags = op.get("tags") or []
                if not set(op_tags) & set(tag_filter):
                    continue
            yield path_template, method, op


def normalize_path_for_base(path_template: str, base_path: str = "/v2") -> str:
    """
    Return path as used for requests. If the spec paths already include /v2 (e.g. /v2/models/),
    and base_url ends with /v2, the path we send should be the part after base (e.g. /models/).
    So we strip a leading base_path from path_template if present.
    """
    if base_path and path_template.startswith(base_path):
        return path_template[len(base_path):] or "/"
    return path_template
