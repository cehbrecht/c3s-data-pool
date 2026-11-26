"""Load and validate collection configuration and local roots."""

from pathlib import Path
from urllib.parse import urlsplit

import yaml


def catalog_location(value, directory):
    """Preserve HTTPS URLs; resolve local catalog paths relative to the config."""
    url = urlsplit(value)
    if url.scheme:
        if url.scheme != "https" or not url.hostname:
            raise ValueError("catalog URL must use HTTPS and include a hostname")
        if not url.path.endswith(".csv.gz"):
            raise ValueError("catalog URL must point to a .csv.gz file")
        return url.geturl()
    path = directory / Path(value).expanduser()
    if not path.name.endswith((".csv", ".csv.gz")):
        raise ValueError("catalog must be a local .csv or .csv.gz file or HTTPS .csv.gz URL")
    return path.absolute()


def load_config(filename, selected, build):
    config_path = Path(filename).resolve()
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    collections = config.get("collections") if isinstance(config, dict) else None
    if not isinstance(collections, dict) or not collections:
        raise ValueError("configuration requires a non-empty collections mapping")
    if selected:
        unknown = set(selected) - collections.keys()
        if unknown:
            raise ValueError(f"unknown collections: {', '.join(sorted(unknown))}")
    result = []
    for name, values in collections.items():
        if selected and name not in selected:
            continue
        if not isinstance(name, str) or not isinstance(values, dict):
            raise ValueError("each collection must have a string name and a mapping")
        paths = {}
        for key in ("catalog", "target", "source") if build else ("catalog", "target"):
            value = values.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name}: {key} must be a non-empty string")
            if key == "catalog":
                paths[key] = catalog_location(value, config_path.parent)
            else:
                paths[key] = (config_path.parent / Path(value).expanduser()).resolve()
        if build and paths["source"] == paths["target"]:
            raise ValueError(f"{name}: source and target must be different directories")
        result.append((name, paths))
    return result
