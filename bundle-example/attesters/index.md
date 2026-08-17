# Attesters

Deterministic verifier code (no LLM) that capability concepts name in
`attester.resource`, per OKF SPEC §10.2. Runs consumer-side against a
receipt.

* [http_refetch.py](http_refetch.py) - Re-fetches the capability's endpoint and compares the attest-stable receipt fields (identity and echo fields) against what the agent displayed.
