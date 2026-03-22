"""
Live discovery against STS: walk models → nodes → properties → terms to populate test data.

The returned dict keys (``model_handle``, ``node_handle``, ``term_value``, etc.) feed
``generate_cases`` so positive GETs use real handles. Also probes tags and model-PVS.
"""
from urllib.parse import quote

from .client import APIClient


def _is_release_version(version_str: str) -> bool:
    """True if version has no hyphen (e.g. 2.1.0 is release; 2.1.0-0338852 is pre-release)."""
    return "-" not in version_str


def _latest_release_version(versions: list[str]) -> str | None:
    """Return the latest release version (no hyphen), or None if none. Sorts by major.minor.patch."""
    release = [v for v in versions if _is_release_version(v)]
    if not release:
        return None

    def version_key(v: str) -> tuple:
        try:
            parts = v.split(".")[:3]
            return tuple(int(x) if x.isdigit() else 0 for x in parts)
        except (ValueError, AttributeError):
            return (0, 0, 0)

    return max(release, key=version_key)


def get_latest_version(client: APIClient, model_handle: str) -> str | None:
    """
    Prefer latest release version (no hyphen) from ``GET /model/{handle}/versions``;
    fall back to ``GET /model/{handle}/latest-version`` (may return pre-release).
    """
    path = f"/model/{quote(model_handle, safe='')}/versions"
    response = client.get(path)
    if response.status_code != 200:
        return None
    versions = response.json()
    if not isinstance(versions, list):
        return None
    chosen = _latest_release_version(versions)
    if chosen is not None:
        return chosen
    latest_path = f"/model/{quote(model_handle, safe='')}/latest-version"
    latest_res = client.get(latest_path)
    if latest_res.status_code != 200:
        return None
    data = latest_res.json()
    if isinstance(data, dict):
        ver = data.get("version")
        if isinstance(ver, str) and ver.strip():
            return ver.strip()
    return None


def discover(
    client: APIClient,
    base_path: str = "/v2",
    model_handle: str | None = None,
    use_release_version: bool = False,
) -> dict:
    """
    Call the API sequentially to collect handles and sample term/tag values.

    Args:
        client: Configured with base URL ending in ``/v2`` (or matching ``base_path``).
        base_path: Used only to choose relative paths (``/models/`` vs prefixed).
        model_handle: If set, use the first model from /models/ with this handle.
        use_release_version: If True, use latest release version from /model/{handle}/versions
            (version with no hyphen); otherwise use first version in the list.

    Returns:
        Partial dict on failure (e.g. empty if ``GET /models/`` fails). On success
        includes at least ``model_handle``, ``model_version``, and often
        ``node_handle``, ``prop_handle``, ``term_value``, ``tag_key``/``tag_value``.
    """
    data = {}
    models_path = "/models/" if base_path == "/v2" else f"{base_path.rstrip('/')}/models/"
    response = client.get(models_path)
    if response.status_code != 200:
        return data

    models = response.json()
    if not isinstance(models, list) or len(models) == 0:
        return data

    data["models"] = models
    if model_handle:
        model = next((m for m in models if isinstance(m, dict) and m.get("handle") == model_handle), None)
        if not model:
            return data
    else:
        model = models[0]

    data["model_handle"] = model.get("handle")
    data["model_nanoid"] = model.get("nanoid")
    if not data.get("model_handle"):
        return data

    model_handle_resolved = data["model_handle"]
    versions_path = f"/model/{quote(model_handle_resolved, safe='')}/versions"
    response = client.get(versions_path)
    if response.status_code != 200:
        return data
    versions = response.json()
    if not isinstance(versions, list) or len(versions) == 0:
        return data

    if use_release_version:
        chosen = _latest_release_version(versions)
        data["model_version"] = chosen if chosen is not None else versions[0]
    else:
        data["model_version"] = versions[0]

    if not data.get("model_version"):
        return data

    model_version = data["model_version"]
    model_handle = model_handle_resolved
    nodes_path = f"/model/{quote(model_handle, safe='')}/version/{quote(model_version, safe='')}/nodes"
    response = client.get(nodes_path)
    if response.status_code != 200:
        return data

    nodes = response.json()
    if not isinstance(nodes, list) or len(nodes) == 0:
        return data

    for node in nodes[:5]:
        node_handle = node.get("handle")
        if not node_handle:
            continue

        props_path = f"/model/{quote(model_handle, safe='')}/version/{quote(model_version, safe='')}/node/{quote(node_handle, safe='')}/properties"
        response = client.get(props_path)
        if response.status_code != 200:
            continue

        props = response.json()
        if not isinstance(props, list) or len(props) == 0:
            continue

        if not data.get("prop_handle"):
            prop = props[0]
            data["prop_handle"] = prop.get("handle")
            data["prop_nanoid"] = prop.get("nanoid")
            data["node_handle"] = node_handle
            data["node_nanoid"] = node.get("nanoid")

        for prop in props[:10]:
            prop_handle = prop.get("handle")
            if not prop_handle:
                continue

            terms_path = f"/model/{quote(model_handle, safe='')}/version/{quote(model_version, safe='')}/node/{quote(node_handle, safe='')}/property/{quote(prop_handle, safe='')}/terms"
            response = client.get(terms_path)
            if response.status_code != 200:
                continue

            terms = response.json()
            if not isinstance(terms, list) or len(terms) == 0:
                continue

            for term in terms:
                term_obj = term[0] if isinstance(term, list) and len(term) > 0 else term
                if isinstance(term_obj, dict):
                    term_value = term_obj.get("value")
                    if term_value is not None and str(term_value).strip():
                        data["term_value"] = term_value
                        data["prop_handle"] = prop_handle
                        data["prop_nanoid"] = prop.get("nanoid")
                        data["node_handle"] = node_handle
                        data["node_nanoid"] = node.get("nanoid")
                        break
            if data.get("term_value"):
                break
        if data.get("term_value"):
            break

    if not data.get("node_handle") and isinstance(nodes, list) and len(nodes) > 0:
        node = nodes[0]
        data["node_handle"] = node.get("handle")
        data["node_nanoid"] = node.get("nanoid")

    if not data.get("prop_handle") and data.get("node_handle"):
        node_handle = data["node_handle"]
        props_path = f"/model/{quote(model_handle, safe='')}/version/{quote(model_version, safe='')}/node/{quote(node_handle, safe='')}/properties"
        response = client.get(props_path)
        if response.status_code == 200:
            j = response.json()
            if isinstance(j, list) and len(j) > 0:
                prop = j[0]
                data["prop_handle"] = prop.get("handle")
                data["prop_nanoid"] = prop.get("nanoid")

    # Tags
    response = client.get("/tags/")
    if response.status_code == 200:
        tags = response.json()
        if isinstance(tags, list) and len(tags) > 0:
            tag = tags[0]
            data["tag_key"] = tag.get("key")
            data["tag_value"] = tag.get("value")
            data["tag_nanoid"] = tag.get("nanoid")

    # Model PVs availability
    if data.get("model_handle") and data.get("model_version") and data.get("prop_handle"):
        mp_path = f"/terms/model-pvs/{quote(data['model_handle'], safe='')}/{quote(data['prop_handle'], safe='')}"
        response = client.get(mp_path, params={"version": data["model_version"]})
        if response.status_code == 200:
            mp_list = response.json()
            if isinstance(mp_list, list) and len(mp_list) > 0:
                data["model_pvs_available"] = True

    return data
