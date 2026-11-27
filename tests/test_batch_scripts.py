"""Exercise batch argument handling without Slurm or access to data pools."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def batch_env(tmp_path):
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
    config = "config/dkrz.toml" if method == "copy" else "config/custom pool.toml"
    args = ["c3s-cmip6-decadal"] if method == "copy" else [config, "c3s-cmip6-decadal"]
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


def test_copy_batch_defaults_to_cmip6_dry_run(batch_env):
    result = subprocess.run(
        ["bash", str(SCRIPTS / "levante-copy.sbatch")],
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
@pytest.mark.parametrize("extra", [["--typo"], ["--apply", "--dry-run"]])
def test_invalid_batch_arguments_do_not_invoke_cli(batch_env, method, extra):
    args = [] if method == "copy" else ["config/dkrz.toml", "c3s-cmip6"]
    result = subprocess.run(
        ["bash", str(SCRIPTS / f"levante-{method}.sbatch"), *args, *extra],
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
    args = [] if method == "copy" else ["config/dkrz.toml", "c3s-cmip6"]
    result = subprocess.run(
        ["bash", str(SCRIPTS / f"levante-{method}.sbatch"), *args, "--apply"],
        env={**batch_env, "MOCK_EXIT": "1"},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
