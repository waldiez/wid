"""Tests for crypto utils."""

# pylint: disable=missing-function-docstring
# pylint: disable=import-outside-toplevel
# pylint: disable=unexpected-keyword-arg

# pyright: reportPrivateUsage=false
# flake8: noqa: D102,D103,C901

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

# Define the root directory of the project
REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
CLI_PATH = REPO_ROOT / "python" / "wid" / "cli.py"
CONFORMANCE_CRYPTO_PATH = REPO_ROOT / "spec" / "conformance" / "crypto.json"


@pytest.fixture(name="temp_dir")
def temp_dir_fixture() -> Generator[Path, Any, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(name="ed25519_key_pair")
def ed25519_key_pair_fixture(temp_dir: Path) -> tuple[Path, Path]:
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_key_path = temp_dir / "private_key.pem"
    public_key_path = temp_dir / "public_key.pem"

    private_key_path.write_bytes(private_pem)
    public_key_path.write_bytes(public_pem)

    return private_key_path, public_key_path


@pytest.fixture(name="ed25519_key_pair_alt")
def ed25519_key_pair_alt_fixture(temp_dir: Path) -> tuple[Path, Path]:
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_key_path = temp_dir / "private_key_alt.pem"
    public_key_path = temp_dir / "public_key_alt.pem"

    private_key_path.write_bytes(private_pem)
    public_key_path.write_bytes(public_pem)

    return private_key_path, public_key_path


def run_wid_cli(args: list[str], expected_exit_code: int = 0) -> str:
    cmd = [sys.executable, "-m", "wid.cli", *args]
    env = dict(os.environ)
    local_py = str(REPO_ROOT / "python")
    env["PYTHONPATH"] = (
        f"{local_py}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else local_py
    )
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)

    if result.returncode != expected_exit_code:
        sys.stderr.write(f"Command failed with exit code {result.returncode}\n")
        sys.stderr.write(f"Stdout:\n{result.stdout}\n")
        sys.stderr.write(f"Stderr:\n{result.stderr}\n")
        msg =  f"Expected: {expected_exit_code}, Got: {result.returncode}"
        cmd_str = " ".join(cmd)
        pytest.fail(
            f"CLI command failed with unexpected exit code. Command: {cmd_str}. {msg}"
        )

    return result.stdout.strip()


def load_conformance_tests() -> Any:
    with open(CONFORMANCE_CRYPTO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("test_case", load_conformance_tests())
def test_crypto_conformance(
    test_case: dict[str, Any],
    temp_dir: Path,
    ed25519_key_pair: tuple[Path, Path],
    ed25519_key_pair_alt: tuple[Path, Path],
) -> None:
    private_key_path, public_key_path = ed25519_key_pair
    _private_key_path_alt, public_key_path_alt = ed25519_key_pair_alt

    if test_case["key_type"] != "ed25519":
        pytest.skip(f"Skipping non-Ed25519 test case: {test_case['description']}")

    test_type = test_case["test_type"]

    if test_type == "sign_verify":
        wid_to_sign = test_case["wid"]
        data_path = None
        if "data_content" in test_case:
            data_file_path = temp_dir / "data.txt"
            data_file_path.write_text(test_case["data_content"])
            data_path = str(data_file_path)

        # Sign the WID (and optional data)
        sign_args = [
            "A=sign",
            f"WID={wid_to_sign}",
            f"KEY={private_key_path}",
        ]
        if data_path:
            sign_args.append(f"DATA={data_path}")

        signature = run_wid_cli(sign_args)
        assert signature, "Signature should not be empty"

        # Verify the signature
        verify_args = [
            "A=verify",
            f"WID={wid_to_sign}",
            f"KEY={public_key_path}",
            f"SIG={signature}",
        ]
        if data_path:
            verify_args.append(f"DATA={data_path}")

        run_wid_cli(verify_args, expected_exit_code=0)  # Expect success

    elif test_type == "verify_invalid":
        # First, generate a valid signature using original WID and data
        original_wid = test_case.get("original_wid")
        if original_wid is None:
            original_wid = test_case["wid"]
        original_data_content = test_case.get("original_data_content")

        data_path_for_sign = None
        if original_data_content:
            data_file_path = temp_dir / "original_data.txt"
            data_file_path.write_text(original_data_content)
            data_path_for_sign = str(data_file_path)

        sign_args = [
            "A=sign",
            f"WID={original_wid}",
            f"KEY={private_key_path}",
        ]
        if data_path_for_sign:
            sign_args.append(f"DATA={data_path_for_sign}")

        valid_signature = run_wid_cli(sign_args)

        # Now attempt to verify with a modification
        wid_for_verify = test_case.get("modified_wid", original_wid)
        data_content_for_verify = test_case.get(
            "modified_data_content", original_data_content
        )
        key_path_for_verify = public_key_path

        if test_case.get("use_wrong_key"):
            key_path_for_verify = public_key_path_alt

        data_path_for_verify = None
        if data_content_for_verify:
            data_file_path = temp_dir / "data_for_verify.txt"
            data_file_path.write_text(data_content_for_verify)
            data_path_for_verify = str(data_file_path)

        verify_args = [
            "A=verify",
            f"WID={wid_for_verify}",
            f"KEY={key_path_for_verify}",
            f"SIG={valid_signature}",
        ]
        if data_path_for_verify:
            verify_args.append(f"DATA={data_path_for_verify}")

        # Expect verification to fail (exit code 1)
        run_wid_cli(verify_args, expected_exit_code=1)
