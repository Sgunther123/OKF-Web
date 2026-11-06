# Security

## Reporting a vulnerability

Please report a vulnerability privately to **info@okf-web.com**, not in
a public issue. Include the version you ran (the installed package
version or the commit), the command or module involved, and the steps
that reproduce the problem. You will get an acknowledgement, and a fix
lands as a normal commit on `main` behind the usual tests; the release
notes credit reporters who want to be named.

## What the design defends

The threat model is in [docs/DESIGN.md](docs/DESIGN.md) and the standing
register of edge cases, with what each fix guarantees, in
[docs/EDGE-CASES.md](docs/EDGE-CASES.md). In short: every outbound
fetch goes through one door that refuses private, local and link-local
hosts and caps every body under a deadline; the MCP bridge executes
capabilities GET-only and never splices undeclared arguments into a
URL; derived and rendered text is inert; a high-risk claim never
publishes without a named human verifier; working-state caches are
JSON, never pickle; and the subscription LLM path runs the agent CLI
with its tools disabled, in an empty working directory.
