#!/usr/bin/env python3
"""Deterministic attester for `runtime: http` capabilities — no LLM.

Per OKF SPEC §10.2, an attester is code that takes a receipt and
returns a verdict. An http capability has no job id to re-read, so
what attestation certifies here is receipt fidelity: the declared
receipt fields, re-read from the same endpoint, agree with what the
agent displayed. Compare the attest-stable fields (identity and echo
fields such as `sku` or `order_id`) — a live value like `price` may
legitimately move between run and attest, which is exactly why it is
a capability and not a static claim.

Usage:
    python http_refetch.py --receipt receipt.json --fields sku,status \
        (--url https://…  |  --fresh fresh.json)

Exit 0: attested (fields agree). Exit 1: mismatch, verdict on stdout.
Stdlib only, runs consumer-side.
"""

import argparse
import json
import sys
import urllib.request


def verdict(receipt: dict, fresh: dict, fields: list) -> dict:
    mismatches = {
        name: {"receipt": receipt.get(name), "fresh": fresh.get(name)}
        for name in fields
        if receipt.get(name) != fresh.get(name)
    }
    return {
        "attested": not mismatches,
        "checked_fields": fields,
        "mismatches": mismatches,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, help="receipt JSON file")
    parser.add_argument(
        "--fields", required=True,
        help="comma-separated receipt fields to compare (attest-stable ones)",
    )
    parser.add_argument("--url", help="endpoint to re-fetch for the fresh read")
    parser.add_argument("--fresh", help="fresh-read JSON file (offline mode)")
    args = parser.parse_args(argv)

    with open(args.receipt, encoding="utf-8") as fh:
        receipt = json.load(fh)
    if args.fresh:
        with open(args.fresh, encoding="utf-8") as fh:
            fresh = json.load(fh)
    elif args.url:
        with urllib.request.urlopen(args.url, timeout=15) as resp:
            fresh = json.load(resp)
    else:
        parser.error("pass --url or --fresh for the fresh read")

    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    result = verdict(receipt, fresh, fields)
    print(json.dumps(result, indent=2))
    return 0 if result["attested"] else 1


if __name__ == "__main__":
    sys.exit(main())
