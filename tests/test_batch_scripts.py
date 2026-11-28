"""Exercise batch argument handling without Slurm or access to data pools."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def batch_env(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPTS / "levante-build.sh", tmp_path / "scripts")
    cli = tmp_path / ".conda-env/bin/c3s-data-pool"
    cli.parent.mkdir(parents=True)
    cli.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\nexit "${MOCK_EXIT:-0}"\n')
    cli.chmod(0o755)
    return {
        **os.environ,
        "SLURM_SUBMIT_DIR": str(tmp_path),
        "SLURM_JOB_ID": "12345",
    }


@pytest.mark.parametrize("method", ["copy", "hardlink"])
@pytest.mark.parametrize("mode", [None, "--dry-run", "--apply"])
def test_batch_mode_and_log_name(batch_env, method, mode):
    config = "config/custom pool.toml"
    args = ["c3s-cmip6-decadal", "--config", config]
    if mode:
        args.append(mode)
    result = subprocess.run(
        ["bash", str(SCRIPTS / f"levante-{method}.sbatch"), *args],
        env=batch_env,
        capture_output=True,
        text=True,
        check=False,
    )
    selected = mode or "--dry-run"
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "build",
        "--config",
        config,
        "--collection",
        "c3s-cmip6-decadal",
        selected,
        f"--{method}",
        "--batch",
        "--log-file",
        f"logs/c3s-cmip6-decadal-{selected[2:]}-batch-12345.log",
    ]


@pytest.mark.parametrize("method", ["copy", "hardlink"])
def test_batch_defaults_to_cmip6_dry_run(batch_env, method):
    result = subprocess.run(
        ["bash", str(SCRIPTS / f"levante-{method}.sbatch")],
        env=batch_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "c3s-cmip6\n" in result.stdout
    assert "--dry-run\n" in result.stdout
    assert "--apply" not in result.stdout


@pytest.mark.parametrize("method", ["copy", "hardlink"])
@pytest.mark.parametrize(
    "extra", [["--typo"], ["--apply", "--dry-run"], ["--config"], ["a", "b"], ["../escape"]]
)
def test_invalid_batch_arguments_do_not_invoke_cli(batch_env, method, extra):
    result = subprocess.run(
        ["bash", str(SCRIPTS / f"levante-{method}.sbatch"), *extra],
        env=batch_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("method", ["copy", "hardlink"])
def test_batch_preserves_failed_cli_exit_status(batch_env, method):
    result = subprocess.run(
        ["bash", str(SCRIPTS / f"levante-{method}.sbatch"), "--apply"],
        env={**batch_env, "MOCK_EXIT": "1"},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1


@pytest.mark.parametrize("method", ["copy", "hardlink", "verify"])
@pytest.mark.parametrize("console", ["--verbose", "--silent", "--progress"])
def test_batch_passes_console_option_to_cli(batch_env, method, console):
    result = subprocess.run(
        ["bash", str(SCRIPTS / f"levante-{method}.sbatch"), console],
        env=batch_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert console in result.stdout.splitlines()


@pytest.mark.parametrize("custom", [False, True])
def test_verify_batch_command_and_log(batch_env, custom):
    args = ["c3s-cmip6-decadal", "--config", "config/custom pool.toml"] if custom else []
    result = subprocess.run(
        ["bash", str(SCRIPTS / "levante-verify.sbatch"), *args],
        env=batch_env,
        capture_output=True,
        text=True,
        check=False,
    )
    collection = "c3s-cmip6-decadal" if custom else "c3s-cmip6"
    config = "config/custom pool.toml" if custom else "config/dkrz.toml"
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "verify",
        "--config",
        config,
        "--collection",
        collection,
        "--batch",
        "--log-file",
        f"logs/{collection}-verify-batch-12345.log",
    ]


@pytest.mark.parametrize("flag", ["--apply", "--dry-run"])
def test_verify_batch_rejects_build_modes(batch_env, flag):
    result = subprocess.run(
        ["bash", str(SCRIPTS / "levante-verify.sbatch"), flag],
        env=batch_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert result.stdout == ""


def test_verify_batch_preserves_failure_exit_status(batch_env):
    result = subprocess.run(
        ["bash", str(SCRIPTS / "levante-verify.sbatch")],
        env={**batch_env, "MOCK_EXIT": "1"},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1


@pytest.mark.parametrize("exit_code", [0, 1, 2])
@pytest.mark.parametrize("remote", [False, True])
def test_catalog_update_batch_forwards_options_and_exit_status(batch_env, exit_code, remote):
    catalog = "https://example.test/catalog.csv.gz" if remote else "catalogs/input file.csv.gz"
    options = [
        "--catalog",
        catalog,
        "--source",
        "/work/ik1017/C3SCMIP5/data/c3s-cmip5",
        "--output",
        "catalogs/c3s-cmip5_v20240711_v2.csv.gz",
        "--mip-era",
        "CMIP5",
        "--verbose",
    ]
    result = subprocess.run(
        ["bash", str(SCRIPTS / "levante-update-catalog.sbatch"), "c3s-cmip5", *options],
        env={**batch_env, "MOCK_EXIT": str(exit_code)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == exit_code, result.stderr
    assert result.stdout.splitlines() == [
        "update-catalog",
        *options,
        "--batch",
        "--log-file",
        "logs/c3s-cmip5-catalog-update-batch-12345.log",
    ]


@pytest.mark.parametrize("args", [[], ["--catalog"], ["../escape"], [""]])
def test_catalog_update_batch_requires_safe_collection_label(batch_env, args):
    result = subprocess.run(
        ["bash", str(SCRIPTS / "levante-update-catalog.sbatch"), *args],
        env=batch_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert result.stdout == ""
