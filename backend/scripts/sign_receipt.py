#!/usr/bin/env python3
"""
TRACE Developer Signing CLI Utility.

Signs a canonical receipt JSON file using an EIP-712 domain and a private key
supplied strictly via an environment variable.

SECURITY NOTICE:
- NEVER pass private keys as command-line arguments.
- NEVER write private keys to disk or log files.
- This CLI is intended for local testing and developer workflows. Production key
  management must utilize hardware security modules (HSM) or dedicated KMS providers.
"""
import argparse
import json
import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.app.models.receipt import EIP712Domain, Receipt
from backend.app.services.signatures import recover_signer, sign_receipt


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Sign a canonical receipt using an EIP-712 domain and private key from an env variable."
    )
    parser.add_argument(
        "receipt_file",
        help="Path to JSON file containing canonical receipt fields.",
    )
    parser.add_argument(
        "--env-var",
        default="TRACE_SIGNER_PRIVATE_KEY",
        help="Name of environment variable containing the hex private key (default: TRACE_SIGNER_PRIVATE_KEY).",
    )
    parser.add_argument(
        "--chain-id",
        type=int,
        default=31337,
        help="EIP-712 domain chainId (default: 31337).",
    )
    parser.add_argument(
        "--verifying-contract",
        default="0x1111111111111111111111111111111111111111",
        help="EIP-712 domain verifyingContract address.",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Optional path to output JSON file. If omitted, prints to stdout.",
    )
    return parser.parse_args(argv)


def sign_receipt_cli(argv=None) -> int:
    args = parse_args(argv)

    # 1. Fetch private key strictly from environment variable
    env_var_name = args.env_var.strip()
    private_key = os.environ.get(env_var_name)
    if not private_key or not private_key.strip():
        sys.stderr.write(
            f"ERROR: Private key environment variable '{env_var_name}' is not set or empty.\n"
        )
        return 1

    clean_key = private_key.strip()

    # 2. Load and parse receipt file
    receipt_path = Path(args.receipt_file)
    if not receipt_path.is_file():
        sys.stderr.write(f"ERROR: Receipt file not found: {receipt_path}\n")
        return 1

    try:
        with open(receipt_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as e:
        sys.stderr.write(f"ERROR: Failed to read receipt JSON file: {e}\n")
        return 1

    # 3. Validate domain and receipt models
    try:
        domain = EIP712Domain(
            name="TRACE Receipt Registry",
            version="1",
            chain_id=args.chain_id,
            verifying_contract=args.verifying_contract,
        )
        receipt = Receipt(**raw_data)
    except Exception as e:
        sys.stderr.write(f"ERROR: Model validation failed: {e}\n")
        return 1

    # 4. Sign receipt
    try:
        signature = sign_receipt(receipt, clean_key, domain)
        recovered = recover_signer(receipt, signature, domain)
    except Exception as e:
        sys.stderr.write(f"ERROR: Signing failed: {e}\n")
        return 1

    result = {
        "status": "SIGNED",
        "domain": domain.to_eip712_dict(),
        "receipt": receipt.to_dict(),
        "signature": signature,
        "recovered_signer": recovered,
    }

    output_json = json.dumps(result, indent=2) + "\n"

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_json)
        except Exception as e:
            sys.stderr.write(f"ERROR: Failed to write output file: {e}\n")
            return 1
    else:
        sys.stdout.write(output_json)

    return 0


if __name__ == "__main__":
    sys.exit(sign_receipt_cli())
