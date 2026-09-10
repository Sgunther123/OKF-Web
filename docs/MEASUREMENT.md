# Measuring Consumption

Publishing a bundle is one-way: static files go out, nothing comes
back. This page closes the loop — how a merchant sees whether
generative engines actually fetch the bundle, using data the serving
infrastructure already records.

## The short version

```bash
okf-web logscan access.log            # or: zcat access.log.*.gz | okf-web logscan -
```

reports bundle fetches by known AI agents (the same
`AI_USER_AGENTS` roster the robots checker uses), the files they
read, and the time window. Works on Combined Log Format (Apache,
nginx, most CDN exports) and JSON-lines logs, auto-detected.

For a page instead of a terminal, the bundle viewer carries a
read-activity panel drawn from the same scan:

```bash
okf-web view my-bundle --access-log access.log     # agents, files, fetches per day
```

Without a log the panel says so and explains what evidence would look
like; with a log and no AI-agent fetches it says that too (zero is a
finding, see below) and names the checks to run.

No tool at hand? The one-liner version:

```bash
grep '/.well-known/okf/' access.log | grep -iE 'gptbot|oai-searchbot|claudebot|claude-user|google-extended|perplexitybot|ccbot'
```

## Where the logs live

| Serving setup | Log source |
| --- | --- |
| nginx/Apache on your own box | `access.log` — works as-is |
| Cloudflare | Logpush (Enterprise) or GraphQL analytics filtered by path + user agent |
| Fastly / CloudFront | Log streaming to S3/GCS; both emit CLF-compatible or JSON lines |
| Static hosts (Netlify, Pages) | Varies; most paid tiers export access logs |

## Reading the numbers honestly

- **A lone `manifest.json` fetch is good news.** Delta sync working
  as designed: the engine checked freshness and needed nothing else.
  Don't read low file counts as low interest.
- **User agents are self-declared.** An unlisted scraper can wear any
  name; treat counts as a floor for named engines, not a census.
- **CDN logs are often sampled** — check your provider's sampling
  rate before comparing absolute numbers across months.
- **Zero is a finding.** `okf-web logscan --fail-empty` exits 1 when
  no AI agent touched the bundle — wire it into a monthly CI job as
  the "nobody is reading this" alarm, then check reachability
  (`okf-web publish --check-robots`) and discovery (llms.txt entry,
  `<link rel="okf-bundle">` tag) before concluding demand is absent.

## What to watch over time

1. **Breadth**: distinct AI agents per month — adoption.
2. **Depth**: files fetched beyond `index.md`/`manifest.json` —
   engagement past the front door.
3. **Freshness response**: fetches shortly after a publish —
   engines tracking your manifest.
4. **Capability traffic**: hits on your live endpoints attributable
   to declared capabilities (check *those* services' logs) — the
   deepest form of adoption, agents executing your store.

Scorecard history (git) says how answerable the bundle is;
`logscan` says who is drinking from it. The two together are the
GEO reporting story.
