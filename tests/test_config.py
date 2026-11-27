from pathlib import Path

import pytest

from c3s_data_pool.cli import main
from c3s_data_pool.config import load_config


def test_toml_relative_paths_and_selection(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        '[collections.example]\ncatalog = "catalog.csv"\nsource = "source"\ntarget = "target"\n'
        '[collections.other]\ncatalog = "other.csv.gz"\nsource = "source"\ntarget = "other"\n'
    )
    collections = load_config(config, ["example"], build=True)
    assert collections == [
        (
            "example",
            {
                "catalog": tmp_path / "catalog.csv",
                "source": tmp_path / "source",
                "target": tmp_path / "target",
            },
        )
    ]


def test_toml_verify_without_source(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('[collections.example]\ncatalog = "catalog.csv"\ntarget = "target"\n')
    assert "source" not in load_config(config, None, build=False)[0][1]


@pytest.mark.parametrize("contents", ["[collections", "collections = []", "[collections]"])
def test_invalid_toml_returns_config_error(tmp_path, contents):
    config = tmp_path / "config.toml"
    config.write_text(contents)
    assert main(["build", "--config", str(config)]) == 2


@pytest.mark.parametrize("suffix", [".yml", ".yaml", ".json"])
def test_non_toml_config_rejected(tmp_path, caplog, suffix):
    config = tmp_path / f"config{suffix}"
    config.write_text("collections: {}\n")
    assert main(["build", "--config", str(config)]) == 2
    assert "config must be a .toml file" in caplog.text


def test_example_toml_config():
    config = Path(__file__).parents[1] / "config/dkrz.toml"
    collections = dict(load_config(config, None, build=True))
    assert set(collections) == {"c3s-cmip6", "c3s-cmip6-decadal"}
    prefix = "/work/"
    assert all(str(paths["source"]).startswith(prefix) for paths in collections.values())
    assert all(str(paths["target"]).startswith(prefix) for paths in collections.values())
