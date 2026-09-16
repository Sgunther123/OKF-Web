# Distribution plan — the open toolchain

**Status:** plan, 2026-08-17 · Companion to [ROADMAP.md](ROADMAP.md)
(release readiness shipped in Phase 2), [FIDELITY.md](FIDELITY.md),
and [USER-GUIDE.md](USER-GUIDE.md).

## 1. Three different things distribute three different ways

- **The knowledge (bundles)** distributes itself. A bundle lives at
  the merchant's own origin (`/.well-known/okf/`, or delegated per
  GEO-PROFILE §8) and engines fetch it. No channel, no gatekeeper —
  and **no registry, ever**: a central index is the named
  anti-pattern; if one emerges it must be free and open, like
  sitemaps.
- **The tool (this repo)** distributes through package channels —
  this document.
- **Operation at scale** is the hosted edition's concern (publicly
  linked from `[project.urls]`); its channels are documented there.
  What this repo owes those channels is an open core that stays
  embeddable: stdlib-first, no forced dependencies, a stable CLI.

## 2. Audiences and the channel that reaches each

| Audience | Channel | Note |
| --- | --- | --- |
| Python developers, agencies | PyPI (`pip install okf-web`) | The front door; extras opt into LLM/signing/embeddings |
| CI pipelines | PyPI, pinned (`okf-web==X.Y.Z`) | The free dry-run gate on every push is the adoption loop |
| DIY merchants with a terminal | `pipx install okf-web` + USER-GUIDE + `--llm claude-code` (BYOS) | The long-tail wedge: no API console required |
| AI assistants | `okf-web mcp` after any install | The fast consumption loop — §4 |
| Generative engines | None — they read bundles at store origins | The point of the design; nothing to install |
| Auditors | PyPI + `[sign]` extra | The same open tooling the methodology mandates |
| Non-developer merchants | **Not this repo's channel** | Platform apps reach them; the open core rides inside |

## 3. PyPI is the primary channel

- **One name, one publisher.** `okf-web` on PyPI belongs to this
  repository alone; no other edition ever publishes a package under
  it (the hosted edition is operated, not installed). Registration
  and release tags are maintainer-only actions.
- **Trusted Publishing.** `.github/workflows/release.yml` publishes
  on a `v*` tag via PyPI's OIDC flow — no long-lived secrets — with
  the version-match guard refusing a tag that disagrees with
  `pyproject.toml`/`okf_web.__init__`. The tool that signs bundles
  keyless ships through a keyless pipeline; the trust story is one
  story.
- **The wheel carries data.** The surveyor/evaluator prompt contracts
  and all eight question packs are package data; a wheel that
  silently drops them breaks `survey`, `questions`, and `evaluate`
  for every pip user while repo-rooted CI stays green. Proving the
  wheel is why the rehearsal gate below exists.
- **The base install stays stdlib-only, permanently.** Zero hard
  dependencies is an adoption feature (nothing to conflict), a
  supply-chain feature (nothing to audit transitively), and a
  maintenance feature (nothing to break). Extras (`[llm]`, `[sign]`,
  `[embed]`, `[dev]`) carry every third-party want.

## 4. The assistant channel: MCP is the fast loop

Engine adoption is the slow loop — engines integrate on their own
schedule, and no channel of ours accelerates them. The MCP bridge is
the **fast loop**: any MCP-capable assistant can consume a bundle
**today** (`okf-web mcp` — search, retrieval, and GET-only capability
execution over the published view). That changes what publishing a
bundle is worth on day one: the merchant's own assistant stack
answers from their own verified knowledge before a single engine
arrives, which is the strongest retention hook the free tier has —
and every assistant answer grounded in a bundle is a live
demonstration of the format to whoever reads it.

What the plan does with that:

- **Ship the one-block setup.** README and USER-GUIDE carry a
  copy-paste assistant configuration snippet (the standard MCP
  server-config JSON) so "add your store to your assistant" is one
  paste after any install. The bridge is the demo; make the demo
  zero-thought.
- **List the server in the assistant directories** once `okf-web` is
  pip-installable — MCP registries and client catalogs are a
  discovery channel with no gatekeeper and no fee, reaching exactly
  the people who already live in assistants (release gate 6, §6).
- **Planned: remote-bundle mode** — `okf-web mcp --url
  https://store.example/.well-known/okf` — consume any *published*
  bundle without cloning anything: the zero-install demo of the whole
  ecosystem, and the natural tool for engines' own engineers to
  evaluate bundles with. (Plan item; lands as a normal feature commit
  when scheduled.)
- **Stay GET-only, stay free.** The bridge's safety posture (GET-only
  execution, no undeclared arguments, and since EDGE-CASES E2 the
  shared fetch boundary: private, loopback and link-local hosts refused
  on every resolved address and every literal spelling, redirects
  re-checked, a 1 MiB response cap under a deadline, `http`/`https`
  only, with `--allow-private-hosts` as the one explicit opt-out for a
  local dev host) is what makes "point your assistant at any store" a
  responsible instruction; consuming a bundle over MCP is free from
  every publisher, always — consumers never pay. Hosted per-tenant MCP
  endpoints are the hosted edition's channel and follow the same rule.
  The subscription LLM path (`--llm claude-code`) is held to the same
  standard from the other side: the agent CLI runs with all tools
  disabled, the rules as its system prompt and an empty working
  directory, and a CLI without those flags is refused, so a surveyed
  page cannot steer an agent that could touch the operator's machine.

## 5. Versioning and support policy

- `0.x` minor bumps are additive, mirroring the profile's additivity
  rule; the version lives in two guarded places and the release
  workflow enforces agreement.
- The change record is layered: GEO-PROFILE §10 for the profile,
  GitHub Release notes per release for the tool. A CHANGELOG file is
  added when the first post-1.0 deprecation makes one necessary, not
  before.
- **Patch forward, never reuse.** A published version number is
  burned on PyPI; remediation is yank-plus-new-version, and a yanked
  release is documented in its GitHub Release notes.

## 6. Release gates, in order

1. **Verification loop green** — the standing pre-commit loop (suite
   twice, lint 0/0, dry-run at the reference numbers).
2. **TestPyPI rehearsal** — publish to test.pypi.org via the same
   Trusted Publishing mechanics, then in a clean virtualenv:
   `pip install` from TestPyPI, `okf-web lint bundle-example
   --strict`, `okf-web questions --list-packs`, `okf-web evaluate
   --dry-run` — all **from the installed wheel**, proving the
   packaged data. Extras install with the documented two-index
   fallback. TestPyPI reserves nothing and prunes periodically; it is
   a rehearsal stage, never a channel.
3. **Real PyPI** — register the project once, promptly after the
   first clean rehearsal (registration is also name protection for a
   trust product), then push the version tag; Trusted Publishing does
   the rest.
4. **GitHub Release** — notes plus the sdist/wheel attached: the
   mirror channel for clone-first users and an audit trail of exactly
   what shipped.
5. **Post-release smoke** — `pip install okf-web==X.Y.Z` in a clean
   venv, one lint of the example bundle. Then announce.
6. **Assistant-directory listings** — with the server one command
   away (`pipx run okf-web mcp …`), list it in the MCP registries and
   client catalogs (§4). First release only; later releases update
   the listings.

## 7. Deliberate non-goals (until demand is demonstrated)

- No conda, Homebrew, or Docker images yet — each is a standing
  maintenance tax, and stdlib-first makes pip/pipx sufficient.
  Revisit on real requests, not speculatively.
- No bundle registry, ever (§1).
- No installer for the no-terminal audience — that is the platform
  apps' job, by design; this repo's contribution is remaining the
  embeddable core those apps pin.

## 8. What success is measured by

Not download counts — PyPI numbers are inflated by mirrors and CI and
say nothing about the goal. The honest meters are the project's own:
published bundles discovered and consumed at store origins
(`okf-web logscan`, discovery checks). Distribution has succeeded
when engines are reading bundles, not when developers are installing
tools.
