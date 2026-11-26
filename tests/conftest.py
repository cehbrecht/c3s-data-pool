import json

import pytest


@pytest.fixture(autouse=True)
def local_log_directory(tmp_path_factory, monkeypatch):
    state = tmp_path_factory.mktemp("log-state")
    (state / "c3s-data-pool/logs").mkdir(parents=True)
    monkeypatch.setenv("XDG_STATE_HOME", str(state))


@pytest.fixture
def write_config():
    """Write test collection mappings as TOML without a serializer dependency."""

    def write(path, config):
        path.write_text(
            "\n".join(
                f"[collections.{json.dumps(name)}]\n"
                + "\n".join(f"{key} = {json.dumps(value)}" for key, value in paths.items())
                for name, paths in config["collections"].items()
            ),
            encoding="utf-8",
        )

    return write
