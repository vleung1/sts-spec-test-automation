"""
Live discovery of STS v2 API: models -> nodes -> properties -> terms, and tags.
Returns a structured dict used to fill path/query parameters when generating tests.
"""
from urllib.parse import quote

from .client import APIClient


def discover(client: APIClient, base_path: str = "/v2") -> dict:
    """
    Discover test data from the API. Base_path is the path prefix (e.g. /v2);
    client.base_url should already end with base_path (e.g. https://sts.cancer.gov/v2).
    Paths used in requests are relative to base_url, so we use /models/, /tags/, etc.
    """
    data = {}
    # Paths are relative to client.base_url which ends with /v2 -> use /models/ not /v2/models/
    models_path = "/models/" if base_path == "/v2" else f"{base_path.rstrip('/')}/models/"
    response = client.get(models_path)
    if response.status_code != 200:
        return data

    models = response.json()
    if not isinstance(models, list) or len(models) == 0:
        return data

    data["models"] = models
    model = models[0]
    data["model_handle"] = model.get("handle")
    data["model_version"] = model.get("version")
    data["model_nanoid"] = model.get("nanoid")

    if not data.get("model_handle") or not data.get("model_version"):
        return data

    model_handle = data["model_handle"]
    model_version = data["model_version"]
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
