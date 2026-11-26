"""Exercise the CLI with two small catalogs and a temporary DKRZ-style pool."""

import csv
import gzip
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

FIXTURES = Path(__file__).parent / "fixtures"
COLLECTIONS = ("c3s-cmip6", "c3s-cmip6-decadal")


@pytest.fixture(params=[".csv", ".csv.gz"])
def dkrz_pool(tmp_path, request):
    source = tmp_path / "work/ik1017/CMIP6/data/CMIP6"
    targets = {
        "c3s-cmip6": tmp_path / "work/ik1017/C3SCMIP6/data/c3s-cmip6",
        "c3s-cmip6-decadal": tmp_path / "work/ik1017/C3SCMIP6_DECADAL/data/c3s-cmip6-decadal",
    }
    collections = {}
    files = {}
    originals = []
    for name in COLLECTIONS:
        fixture = FIXTURES / f"{name}.csv"
        with fixture.open(newline="", encoding="utf-8") as stream:
            files[name] = list(csv.DictReader(stream))
        catalog = tmp_path / f"{name}{request.param}"
        contents = fixture.read_bytes()
        catalog.write_bytes(gzip.compress(contents) if request.param == ".csv.gz" else contents)
        collections[name] = {
            "catalog": catalog.name,
            "source": str(source.relative_to(tmp_path)),
            "target": str(targets[name].relative_to(tmp_path)),
        }
        for row in files[name]:
            path = source / row["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = row["variable_id"].encode()[:1] * int(row["size"])
            # A published source path may point to a replica elsewhere on Lustre.
            if name == "c3s-cmip6-decadal" and row["member_id"].startswith("s1960-"):
                replica = tmp_path / "replicas" / path.name
                replica.parent.mkdir(parents=True, exist_ok=True)
                replica.write_bytes(payload)
                path.symlink_to(replica)
                originals.append(replica)
            else:
                path.write_bytes(payload)
            originals.append(path)
    config = tmp_path / "dkrz.yml"
    config.write_text(yaml.safe_dump({"collections": collections}))
    return config, source, targets, files, originals


def cli(config, command, *options):
    result = subprocess.run(
        [sys.executable, "-m", "c3s_data_pool", command, "--config", str(config), *options],
        input="yes\n" if "--apply" in options else "",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stderr


def test_both_collections_survive_source_removal(dkrz_pool):
    config, source, targets, files, originals = dkrz_pool

    dry_run = cli(config, "build")
    assert "rows=4 logical_bytes=120 created=0 planned=4" in dry_run
    assert all(not target.exists() for target in targets.values())

    build = cli(config, "build", "--apply")
    assert "rows=4 logical_bytes=120 created=4 planned=0" in build
    identities = {}
    for name, rows in files.items():
        for row in rows:
            target = targets[name] / row["path"]
            assert target.samefile(source / row["path"])
            assert not target.is_symlink()
            assert target.stat().st_size == int(row["size"])
            identities[target] = (target.stat().st_dev, target.stat().st_ino)
        assert {p.relative_to(targets[name]).as_posix() for p in targets[name].rglob("*.nc")} == {
            row["path"] for row in rows
        }

    repeated = cli(config, "build", "--apply")
    assert "rows=4 logical_bytes=120 created=0 planned=0 existing=4" in repeated
    assert all(
        (path.stat().st_dev, path.stat().st_ino) == identity
        for path, identity in identities.items()
    )

    for path in originals:
        path.unlink()
    assert not list(source.rglob("*.nc"))
    verified = cli(config, "verify")
    assert "rows=4 logical_bytes=120 created=0 planned=0 existing=0 verified=4" in verified
    for name, rows in files.items():
        for row in rows:
            assert (targets[name] / row["path"]).read_bytes() == (
                row["variable_id"].encode()[:1] * int(row["size"])
            )


@pytest.mark.parametrize("selected", COLLECTIONS)
def test_select_realistic_collection(dkrz_pool, selected):
    config, _, targets, _, _ = dkrz_pool
    cli(config, "build", "--apply", "--collection", selected)
    cli(config, "verify", "--collection", selected)
    assert targets[selected].is_dir()
    assert all(not target.exists() for name, target in targets.items() if name != selected)
