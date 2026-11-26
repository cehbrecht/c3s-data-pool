"""Load and validate collection configuration and local roots."""

from pathlib import Path

import yaml


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
        for key in (("catalog", "target", "source") if build else ("catalog", "target")):
            value = values.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name}: {key} must be a non-empty local path")
            path = Path(value).expanduser()
            # Resolve configured roots, but preserve catalog paths lexically.
            paths[key] = (config_path.parent / path).absolute()
            if key != "catalog":
                paths[key] = paths[key].resolve()
        if not str(paths["catalog"]).endswith(".csv.gz"):
            raise ValueError(f"{name}: catalog must be a local .csv.gz file")
        if build and paths["source"] == paths["target"]:
            raise ValueError(f"{name}: source and target must be different directories")
        result.append((name, paths))
    return result
