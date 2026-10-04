# Hosting the companion bundle: the matrix and tested recipes

`okf-web publish` turns a bundle into a folder of small static files, and
any web host that can serve files can serve it. This document is the
per-hosting-type recipe book: one row in the matrix for each kind of
host, one recipe per row, and a record of how each recipe was tested. It
complements [DESIGN.md §8](DESIGN.md#8-hosting-and-discovery) (why the
serving rules are what they are) and
[GEO-PROFILE.md §8](GEO-PROFILE.md#8-discovery-and-delegation) (the
discovery and delegation contract every recipe satisfies).

## 0. What you are serving, and the rules every recipe implements

What `publish` writes into `dist/` (the example bundle publishes 33 files):

| Path | What it is | Type to serve |
| --- | --- | --- |
| `index.md`, `<topic>/*.md`, `log.md` | the concepts, the bundle's own map, and its log | `text/markdown; charset=utf-8` |
| `manifest.json` | sha256 and size per file, plus `site` and `bundle_url`; consumers delta-sync from it | `application/json` |
| `linkmap.json` | page URL to concept path, for `<link rel="alternate">` tags on the storefront | `application/json` |
| `llms.txt`, `llms-snippet.txt` | the complete `llms.txt`, and the block plus head tag to paste | `text/plain` |
| `jsonld/**/*.json` | derived schema.org markup, human-verified concepts only | `application/json` |
| `evaluations/` | the scorecard concept and `questions.yaml` | markdown, `text/plain` |
| `attesters/` | attester code artifacts: `index.md` plus `*.py` files, to be read, never run | markdown, `text/plain` |
| `l10n/` | translations | markdown |
| `manifest.json.sigstore.json` | the signature, when you publish with `--sign` | `application/json` |

Three rules, implemented by every recipe below and enforced by the test
suite's own server (`tests/test_hosting.py`):

1. **Content types.** `.md` as `text/markdown; charset=utf-8`; `.json` as
   `application/json`; everything else (`.txt`, `.yaml`, `.py`) as a text
   type such as `text/plain`. What matters for the `.py` attesters is that
   nothing executes them: they are content (lint W036), not scripts.
2. **`Access-Control-Allow-Origin: *`.** The bundle is public knowledge.
   Crawlers do not need the header; browser-based consumers (a viewer, an
   assistant running inside a page) do.
3. **`Cache-Control: public, max-age=300, must-revalidate`.** Five minutes
   is plenty for any CDN, and `must-revalidate` with the per-file ETags
   hosts send anyway makes a re-publish visible within minutes.

Four things to avoid, each of which turns a published bundle into an
unreachable one:

- **Hidden dot-directories.** `/.well-known/` starts with a dot, and some
  servers, site generators, and security plugins hide or skip dot-paths
  (the nginx boilerplate `location ~ /\. { deny all; }`, Jekyll on GitHub
  Pages, "protect system files" plugins). Each recipe shows its exception.
  When a host cannot be told to serve the dot-directory at all, the
  bundle can live at a plain path on the same host instead
  ([§2.4](#24-a-host-that-hides-dot-directories)).
- **HTML fallbacks for missing files.** Single-page-app hosting answers
  every unknown path with `index.html` and status 200. A missing file must
  be a real 404: `okf-web discover` requires the signature file to parse
  as JSON precisely because one emulator served a home page in its place,
  and other consumers may be less careful.
- **Bot gates above `robots.txt`.** A WAF or bot-management product can
  refuse AI crawlers whatever `robots.txt` says, and `okf-web publish
  --check-robots` reads only `robots.txt`. Section 6 covers Cloudflare in
  detail because it fronts so many storefronts.
- **Objects stored pre-compressed.** An upload that stamps
  `Content-Encoding: gzip` on the files (a common static-asset
  optimization) serves them compressed to every client, including the
  ones that never asked. Keep the files plain and let the CDN compress
  on the wire. Since 2026-09-30 the toolchain's own fetcher asks for
  identity and decodes a gzip or deflate answer anyway, under its byte
  cap; other consumers may not.

Two routes, one of which you pick before choosing a recipe:

- **Same-origin** (preferred): the bundle lives at
  `https://<store>/.well-known/okf/` on the storefront's own origin. Path
  position is the binding; nothing else is needed. Publish with
  `okf-web publish my-store dist` (`--site` defaults to the bundle's
  `x_geo.site`).
- **Delegated**: the storefront cannot serve root paths (Shopify and most
  hosted platforms), so the bundle lives on any HTTPS origin you control
  and the storefront's `<head>` points at it. Publish with
  `--site https://www.store.example --bundle-url https://<bundle-host>/<path>`
  and paste the emitted `<link rel="okf-bundle" href="…/">` tag. The
  pointer on the store plus `manifest.site` in the bundle form the two-way
  binding (GEO-PROFILE §8). Section 4 walks through it.

Every static-host recipe keeps the same layout for both routes: the dist
sits at `.well-known/okf/` inside the deploy directory, and only the URL
you pass to `--bundle-url` changes.

## 1. The matrix

| Hosting type | Route | Where `dist/` goes | Headers come from | Gate to check first | Recipe |
| --- | --- | --- | --- | --- | --- |
| Own server, nginx | same-origin | `/srv/okf-dist/`, aliased to `/.well-known/okf/` | a `location` block | `robots.txt`; any `location ~ /\.` deny rule | [§2.1](#21-nginx) |
| Own server or shared hosting, Apache (cPanel, WordPress/WooCommerce, Magento, PrestaShop) | same-origin | `<webroot>/.well-known/okf/` | a `.htaccess` shipped with the files | `robots.txt`; security plugins hiding dot-paths or `.py` | [§2.2](#22-apache-shared-hosting-and-cms-hosting) |
| Own server, Caddy | same-origin, or a standalone bundle host | `/srv/okf-dist/` | a `handle_path` block | `robots.txt` | [§2.3](#23-caddy) |
| Any host that hides dot-directories and cannot be configured | same-origin, at a plain path | `<webroot>/okf/` | the host's own defaults | the head tag, written by hand | [§2.4](#24-a-host-that-hides-dot-directories) |
| Cloudflare Pages | same-origin if the storefront is the Pages site, otherwise delegated | `<deploy dir>/.well-known/okf/` | the `_headers` file | Cloudflare's bot settings (§6) | [§3.1](#31-cloudflare-pages) |
| Netlify | same-origin if the storefront is the Netlify site, otherwise delegated | `<publish dir>/.well-known/okf/` | `netlify.toml` or `_headers` | `robots.txt`; no SPA redirect | [§3.2](#32-netlify) |
| Vercel | same-origin or delegated | `public/.well-known/okf/` | `vercel.json` | the firewall's bot rules | [§3.3](#33-vercel) |
| GitHub Pages | delegated (same-origin only for a Pages-hosted storefront) | repository root or `docs/` | none configurable; CORS `*` is the platform default | Jekyll dropping dot-directories | [§3.4](#34-github-pages) |
| Amazon S3 + CloudFront | same-origin when CloudFront fronts the store, otherwise delegated | bucket prefix `.well-known/okf/` | object metadata plus a response headers policy | WAF Bot Control on the distribution | [§3.5](#35-amazon-s3--cloudfront) |
| Hosted commerce platform (Shopify, BigCommerce, Squarespace, Wix, and the like) | delegated | any host above | that host's recipe | the bundle host's gate, and the storefront staying fetchable | [§4](#4-hosted-commerce-platforms-delegated-hosting) |
| A container | standalone bundle host, or a sidecar behind a proxy | an image layer | the Caddyfile inside the image | as for Caddy | [§5.1](#51-a-container-image) |
| CI pipeline (GitHub Actions) | either | wherever the last step ships it | the target host's recipe | none of its own | [§5.2](#52-publishing-from-ci-github-actions) |
| Any CDN or WAF in front of the above (Cloudflare proxy, Fastly, Akamai, AWS WAF) | unchanged | unchanged | the origin (confirm the CDN forwards them) | the product's AI-crawler category | [§6](#6-bot-gates-above-robotstxt) |

How each recipe was tested is in [§8](#8-how-these-recipes-were-tested);
the verification commands to run after any deploy are in
[§7](#7-verify-after-deploying).

## 2. Own server

### 2.1 nginx

Ship the files, then add one `location` block inside the storefront's
`server { … }`:

```bash
rsync -a --delete dist/ deploy@www.store.example:/srv/okf-dist/
```

```nginx
location ^~ /.well-known/okf/ {
    alias /srv/okf-dist/;
    types {
        application/json  json;
        text/plain        txt yaml py;
    }
    default_type "text/markdown; charset=utf-8";
    add_header Access-Control-Allow-Origin "*" always;
    add_header Cache-Control "public, max-age=300, must-revalidate" always;
}
```

Then `nginx -t && systemctl reload nginx`. Why it is shaped this way:

- `^~` makes the prefix win over regex locations, so a boilerplate
  `location ~ /\. { deny all; }` elsewhere in the file cannot hide the
  dot-directory.
- A `types` map inside a location replaces the inherited one, and `.md`
  is deliberately left out of it so Markdown falls through to
  `default_type`, which is where the charset rides along.
- `alias` needs the trailing slash on both the location and the path.
- nginx inherits `add_header` lines from the server level only when a
  location has none of its own. If the site sets headers such as HSTS at
  server level, repeat them here.

### 2.2 Apache, shared hosting, and CMS hosting

This covers cPanel and other shared hosts and the self-hosted commerce
CMSs (WordPress with WooCommerce, Magento, PrestaShop), which all run on
Apache or on nginx configured to honor Apache conventions.

Upload `dist/` to `<webroot>/.well-known/okf/` with SFTP, the panel's file
manager, or `rsync`. The web root is the folder holding `wp-config.php`
for WordPress, `pub/` for Magento, and the site root for PrestaShop. Put
this `.htaccess` inside the uploaded folder, and keep a copy next to the
bundle so every publish ships it again:

```apache
# <webroot>/.well-known/okf/.htaccess
<IfModule mod_mime.c>
    AddType text/markdown .md
    AddType application/json .json
    AddType text/plain .txt .yaml .py
    AddCharset utf-8 .md .txt .yaml .py
    RemoveHandler .py
</IfModule>
<IfModule mod_headers.c>
    Header set Access-Control-Allow-Origin "*"
    Header set Cache-Control "public, max-age=300, must-revalidate"
</IfModule>
# Delete the next line if the host answers 500 (AllowOverride without Options).
Options -Indexes -ExecCGI
```

Notes:

- The CMS's own rewrite rules pass real files straight through
  (`RewriteCond %{REQUEST_FILENAME} !-f`), so nothing in the site's root
  `.htaccess` changes.
- `RemoveHandler .py` and `-ExecCGI` exist because some shared hosts map
  `.py` to CGI globally. The attester files are content, never programs.
- Security plugins (Wordfence, Solid Security, "protect system files"
  toggles) sometimes answer 403 for dot-paths or unfamiliar extensions.
  If `okf-web discover` finds the bundle but `attesters/http_refetch.py`
  is refused, exempt the folder in the plugin rather than deleting the
  attester.
- `mod_headers` is enabled on essentially every shared host. If
  `curl -I` shows no `Access-Control-Allow-Origin`, ask the host to enable
  it; the bundle still works for crawlers without it.

### 2.3 Caddy

Same-origin, inside the storefront's site block:

```caddyfile
www.store.example {
    # ... the storefront ...

    handle_path /.well-known/okf/* {
        root * /srv/okf-dist
        @md path *.md
        header @md >Content-Type "text/markdown; charset=utf-8"
        header Access-Control-Allow-Origin "*"
        header Cache-Control "public, max-age=300, must-revalidate"
        file_server
    }
}
```

A standalone bundle host for the delegated route, where the dist is the
whole site and Caddy obtains the certificate by itself:

```caddyfile
okf.store.example {
    root * /srv/okf-dist
    @md path *.md
    header @md >Content-Type "text/markdown; charset=utf-8"
    header Access-Control-Allow-Origin "*"
    header Cache-Control "public, max-age=300, must-revalidate"
    file_server
}
```

`>Content-Type` defers the header until after `file_server` has chosen
its own type, which is what makes the override stick. `handle_path`
strips the prefix, so `/.well-known/okf/index.md` maps to
`/srv/okf-dist/index.md`. Caddy types the other files from the system
MIME table; observed on the live run: `application/json`,
`text/plain; charset=utf-8`, `application/yaml`, and
`text/x-python; charset=utf-8`, all of which are text and none of which
execute.

### 2.4 A host that hides dot-directories

Some managed hosts hide every dot-path and expose no setting for it. The
bundle can then live at a plain path on the same host, named by the
storefront's head tag, exactly as the delegated route works but without
leaving the origin:

```bash
okf-web publish my-store dist --base-path /okf
rsync -a --delete dist/ deploy@www.store.example:<webroot>/okf/
```

Then add the tag to the storefront's `<head>` by hand (the snippet
carries it only for `--bundle-url`):

```html
<link rel="okf-bundle" href="/okf/">
```

The verifier resolves a relative pointer against the page and binds a
same-host bundle as same-origin, so `okf-web discover` reports
`routes found: link-tag` and `binding: same-origin`. The serving rules
of §0 still apply at the new path: the host's defaults usually type
`.md` as `text/markdown` or `text/plain`, either of which is text, and
the headers come from whatever the host lets you set.

## 3. Static hosts and CDNs

### 3.1 Cloudflare Pages

Layout of the deploy directory (the storefront, or nothing but the bundle):

```
site/
  index.html
  404.html            any content; its presence turns off the SPA fallback
  _headers
  .well-known/okf/    the contents of dist/
```

`_headers`:

```
/.well-known/okf/*
  Access-Control-Allow-Origin: *
  Cache-Control: public, max-age=300, must-revalidate
/.well-known/okf/attesters/*
  Content-Type: text/plain; charset=utf-8
```

Deploy with `npx wrangler pages deploy site --project-name <project>`, or
connect the repository and set the build output directory to `site`.
Pages serves `.md` as `text/markdown; charset=utf-8` on its own; the
second rule keeps the attester code readable as text instead of a
download.

Without `404.html`, Pages answers every unknown path with `index.html`
and status 200 (the single-page-app convention), and a consumer probing
for `manifest.json.sigstore.json` sees a 200 where there is no
signature. With `404.html` present, missing paths return a real 404.

Custom domain: the storefront's own domain makes this same-origin; a
subdomain such as `okf.store.example` makes it delegated, so publish
with `--bundle-url https://okf.store.example/.well-known/okf` and paste
the tag (§4). On a custom domain the zone's bot settings apply to the
bundle path: read [§6](#6-bot-gates-above-robotstxt) before announcing
the bundle. A `*.pages.dev` hostname has no zone settings of yours.

### 3.2 Netlify

`netlify.toml`, or the identical `_headers` file from §3.1 (the format
is Netlify's; Cloudflare adopted it):

```toml
[build]
  publish = "site"

[[headers]]
  for = "/.well-known/okf/*"
  [headers.values]
    Access-Control-Allow-Origin = "*"
    Cache-Control = "public, max-age=300, must-revalidate"
```

Deploy with `netlify deploy --prod --dir site`. Observed in Netlify's
local emulator: `.md` served as `text/markdown; charset=UTF-8`, `.json`
as `application/json; charset=UTF-8`, the CORS header applied from either
form; the emulator kept its own `Cache-Control: public, max-age=0,
must-revalidate` (Netlify's production default, which revalidates on
every request and is fine for a bundle) and did not apply a
`Content-Type` override for `attesters/*`, which it served as
`application/octet-stream` (a download; not executed). Do not add a
`/* /index.html 200` rule to `_redirects` on the site carrying the
bundle: that is the SPA fallback.

### 3.3 Vercel

`vercel.json` at the project root, with the files under
`public/.well-known/okf/` (framework projects) or `.well-known/okf/` (a
plain static project):

```json
{
  "headers": [
    {
      "source": "/.well-known/okf/(.*)",
      "headers": [
        { "key": "Access-Control-Allow-Origin", "value": "*" },
        { "key": "Cache-Control", "value": "public, max-age=300, must-revalidate" }
      ]
    }
  ]
}
```

Not run here (deploys need an account); the file is validated as JSON by
the suite. Vercel types `.md` from its own MIME table; confirm with the
curl check in §7 after the first deploy. Do not add a catch-all
`rewrites` entry to `/index.html` that covers this path. Vercel's
firewall can challenge or block automated traffic, including managed
rules aimed at AI crawlers: check its rules against the bundle path (§6).

### 3.4 GitHub Pages

Free and public, which makes it a natural delegated host at
`https://<user>.github.io/<repo>/`:

1. Put `dist/` in the repository at `.well-known/okf/` (at the root, or
   under `docs/` with Pages set to that folder, or pushed from CI).
2. Add an empty `.nojekyll` file at the top of the published tree.
   Without it Jekyll silently drops the `.well-known` dot-directory
   (`include: [".well-known"]` in `_config.yml` is the alternative).
3. Publish with
   `--site https://www.store.example --bundle-url https://<user>.github.io/<repo>/.well-known/okf`
   and paste the head tag on the storefront (§4).

No headers are configurable. GitHub Pages sends
`Access-Control-Allow-Origin: *` and `Cache-Control: max-age=600` on
everything (probed live on `pages.github.com`), serves `.md` as
`text/markdown` (observed on a Pages-hosted documentation site), and
returns a real 404 for missing files (a custom `404.html` keeps the 404
status). Same-origin is possible only when the storefront itself is the
Pages site under the store's custom domain.

### 3.5 Amazon S3 + CloudFront

Upload with explicit types and cache metadata (two passes, because
`--content-type` applies to every file in a `sync`):

```bash
BUCKET=okf-store-example
aws s3 sync dist/ "s3://$BUCKET/.well-known/okf/" --delete --exclude "*.md" \
    --cache-control "public, max-age=300, must-revalidate"
aws s3 sync dist/ "s3://$BUCKET/.well-known/okf/" --delete --exclude "*" --include "*.md" \
    --content-type "text/markdown; charset=utf-8" \
    --cache-control "public, max-age=300, must-revalidate"
```

Bucket CORS, applied with
`aws s3api put-bucket-cors --bucket "$BUCKET" --cors-configuration file://cors.json`:

```json
{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["GET", "HEAD"],
      "AllowedHeaders": ["*"],
      "MaxAgeSeconds": 3000
    }
  ]
}
```

CloudFront: a distribution (or the store's existing one) with a behavior
for `/.well-known/okf/*` pointing at the bucket, HTTPS only, and a
response headers policy that adds `Access-Control-Allow-Origin: *` and
`Cache-Control: public, max-age=300, must-revalidate` as custom headers
(the object metadata is forwarded too; the policy is belt and braces).
After each publish run
`aws cloudfront create-invalidation --distribution-id <id> --paths "/.well-known/okf/*"`
or wait out the 300 s TTL. CloudFront in front of the store's domain is
same-origin; a bucket with its own hostname is delegated. The S3 website
endpoint is HTTP-only; HTTPS comes from CloudFront. Not run here (needs
an account); the commands follow the AWS CLI reference and the JSON is
validated by the suite. AWS WAF Bot Control on the distribution: §6.
Upload the files plain: an object stored with `Content-Encoding: gzip`
metadata is served compressed to every client (§0, the fourth thing to
avoid); let CloudFront compress on the wire.

## 4. Hosted commerce platforms (delegated hosting)

Shopify, BigCommerce, Squarespace, Wix, and most other hosted platforms
cannot serve a file at `/.well-known/okf/`, but every one of them lets you
edit the storefront's `<head>`. That is all delegation needs.

1. **Pick a bundle host** from §2 or §3: a subdomain of your own domain on
   Cloudflare Pages, Netlify, or S3; a GitHub Pages repository; a Caddy
   box. Use that host's recipe unchanged, so the bundle URL ends in
   `/.well-known/okf`.
2. **Publish with both URLs:**

   ```bash
   okf-web publish my-store dist \
       --site https://www.store.example \
       --bundle-url https://okf.store.example/.well-known/okf
   ```

   The publisher records `site` and `bundle_url` in `manifest.json` and
   writes the head tag into `llms-snippet.txt`.
3. **Ship `dist/`** to the host.
4. **Paste the tag**, exactly as emitted, into the storefront's `<head>`:

   ```html
   <link rel="okf-bundle" href="https://okf.store.example/.well-known/okf/">
   ```

   - Shopify: Online Store → Themes → Edit code → `layout/theme.liquid`,
     inside `<head>`.
   - BigCommerce: Storefront → Script Manager → Create a Script (Location:
     Head, Pages: All pages, Category: Essential, paste the tag as the
     script contents), or Themes → Edit Theme Files →
     `templates/layout/base.html`.
   - Squarespace: Settings → Developer Tools → Code Injection → Header.
   - Wix: Settings → Custom Code → Add Custom Code → Head, all pages
     (paid plans).
   - Any other platform: wherever the theme editor exposes the head. The
     verifier reads the tag anywhere in the page, but the head is the
     convention.
5. **Verify:** `okf-web discover https://www.store.example` must print
   `routes found: link-tag` and `binding: bound` (§7).

Notes:

- Two robots policies now matter. The storefront's must let crawlers read
  the page carrying the tag (every platform allows its home page). The
  bundle host's governs the bundle itself, and `--check-robots` does not
  read it (it reads the store's `robots.txt` for the well-known path):
  check the bundle host's `robots.txt` and bot settings by hand (§6).
- `llms.txt` is a bonus where the platform lets you serve a root file,
  which is rare (Shopify does not). The head tag is the route that works
  everywhere.
- A subdomain is a separate origin. `okf.store.example` is delegated
  hosting, bound by the tag and `manifest.site`, exactly like a
  third-party host.
- Name the origin the storefront actually serves. `https://store.example`
  and `https://www.store.example` are different origins to the binding,
  as they are to browsers: publish `--site` with the host the browser
  lands on, and run the verifier against that URL. Letter case and a
  default port (`:443`, `:80`) are normalized; a `www` is not.
- One pointer per page. If a page carries two `okf-bundle` tags, the
  first is the one consumers follow; remove the other.

## 5. Containers and CI

### 5.1 A container image

```Dockerfile
FROM caddy:2
COPY Caddyfile /etc/caddy/Caddyfile
COPY dist/ /srv/okf-dist/
```

with the standalone Caddyfile from §2.3 as `Caddyfile` (the site name on
its first line; Caddy provisions the certificate when ports 80 and 443
are published). Build and run:

```bash
docker build -t okf-bundle:$(date +%Y%m%d) .
docker run -d --name okf-bundle -p 80:80 -p 443:443 okf-bundle:$(date +%Y%m%d)
```

The image is the deployment: rebuild on every publish, and a tag per
publish gives rollbacks for free. Behind an existing reverse proxy that
already terminates TLS, replace the site name with `http://:8080` and
route `/.well-known/okf/` to the container. Not built here (the test
environment has no container runtime); the Caddyfile the image copies is
the one run live in §8. No official image is published, deliberately
(DISTRIBUTION §7).

### 5.2 Publishing from CI (GitHub Actions)

```yaml
name: publish-okf
on:
  push:
    branches: [main]
    paths: ["my-store/**"]
permissions:
  contents: read
  id-token: write        # sigstore keyless signing uses the workflow's identity
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "okf-web[sign] @ git+https://github.com/Sgunther123/OKF-Web"
      - run: okf-web lint my-store --strict
      - run: okf-web publish my-store dist --site https://www.store.example --sign --check-robots
      - run: >
          okf-web verify dist
          --cert-identity "https://github.com/${{ github.repository }}/.github/workflows/publish-okf.yml@refs/heads/main"
          --cert-oidc-issuer https://token.actions.githubusercontent.com
      # Ship dist/ with the target host's own tool, for example:
      # - run: rsync -a --delete dist/ deploy@www.store.example:/srv/okf-dist/
      # - run: npx wrangler pages deploy site --project-name okf-store
      # - run: aws s3 sync dist/ s3://okf-store-example/.well-known/okf/ --delete
```

The signature's identity is the workflow file's URI at the branch that
ran it, which is what consumers pass to `okf-web verify`. Once the
package is on PyPI the install line becomes `pip install "okf-web[sign]"`.
Not executed here; the workflow is parsed as YAML by the suite.

## 6. Bot gates above `robots.txt`

`robots.txt` is advice that well-behaved crawlers follow. A WAF or
bot-management layer is enforcement: it answers before your origin does,
and it decides by the crawler's verified identity (network ranges plus
user agent), not by what the path is for. `okf-web publish --check-robots`
parses `robots.txt` and nothing else, so a bundle can pass that check and
still be unreachable for every engine it was published for. Cloudflare
is the common case: it fronts a large share of storefronts and, since
mid-2025, blocks AI crawlers on newly created zones by default.

**Cloudflare settings that gate the bundle** (names as of this writing;
if the labels move, look for the function):

- **Block AI Bots** (Security → Bots; also labelled "block AI scrapers
  and crawlers"): one toggle that blocks known AI crawlers on every page.
  On by default for zones created since July 2025; older zones keep what
  was chosen. "Do not block", or blocking only on hostnames with ads,
  lets the bundle be read.
- **AI Crawl Control** (formerly AI Audit): per-crawler Allow/Block, a
  request log per path, pay-per-crawl (a `402` answer instead of the
  file), and a **managed `robots.txt`** that injects directives into the
  file you serve. That last one is the only Cloudflare gate
  `--check-robots` can see.
- **Bot Fight Mode** (free plan) and **Super Bot Fight Mode** (paid
  plans): "definitely automated" traffic is challenged or blocked, and
  verified bots pass only if the "Verified bots" option says so. Bot
  Fight Mode has no path exceptions; Super Bot Fight Mode can be skipped
  for a path by a WAF custom rule.
- **WAF custom or managed rules** matching the AI-crawler category or
  user agents; **Security Level, Under Attack Mode, and managed
  challenges** (a challenge page is HTML with a non-200 status, which a
  consumer reads as "no bundle"); and **AI Labyrinth**, which serves
  decoy pages to crawlers Cloudflare classes as unwanted, so the request
  succeeds and the content is fiction, the worst outcome for a knowledge
  bundle.
- A Pages project on your custom domain inherits all of the above from
  the zone. A `*.pages.dev` hostname has no zone settings of yours.

**What to set.** Allow the crawlers the bundle exists for. Either turn
AI-crawler blocking off for the zone (the bundle's premise is that
engines should read verified facts about the store), or keep it on and
carve out the bundle: in AI Crawl Control set the crawlers you want to
Allow and confirm in its request log that `/.well-known/okf/` answers
200 to them; for Super Bot Fight Mode and custom rules, add a WAF custom
rule with the Skip action for
`starts_with(http.request.uri.path, "/.well-known/okf/")`. The agents
`okf-web`'s robots check watches (`publisher.AI_USER_AGENTS`) are
GPTBot, OAI-SearchBot, ClaudeBot, Claude-User, Google-Extended,
PerplexityBot, and CCBot.

**What counts as evidence.** The dashboard settings; the per-path request
log in AI Crawl Control (or your CDN's equivalent) showing `200` for
`/.well-known/okf/manifest.json` from the crawlers you allowed; and
`okf-web logscan` over origin or Logpush logs
([MEASUREMENT.md](MEASUREMENT.md)). A `curl` with a crawler's user-agent
string from your own machine is not evidence: verified-bot detection
checks the source network, so a spoofed name can be blocked precisely
because it is spoofed, and a plain `curl` can pass precisely because it
is not a crawler.

**Elsewhere.** AWS WAF Bot Control, Akamai Bot Manager, Fastly, Vercel's
firewall, and hosting-panel "bot protection" toggles have equivalent
categories. The rule is the same: find the AI-crawler setting, allow or
exempt the bundle path, and read the product's log rather than trusting
`robots.txt`.

## 7. Verify after deploying

Run the verifier from outside your own network if you can; it does what
an engine does:

```bash
okf-web discover https://www.store.example
```

Against a server on your own machine or network (the transcripts
below were taken on `127.0.0.1`), add `--allow-private-hosts`: the
verifier, like every fetcher in the toolchain, refuses loopback,
private and link-local hosts unless told otherwise (DESIGN §8,
outbound fetches).

Against the Caddy recipe on the test machine (§8), same-origin:

```
store origin: http://127.0.0.1:18080
routes found: well-known
bundle: http://127.0.0.1:18080/.well-known/okf (33 file(s), profile ecommerce-geo/1.12)
signature: absent
binding: same-origin
OK: the bundle is discoverable and speaks for this store
```

and delegated, against a platform-style store page carrying only the
head tag, with the bundle on a second origin:

```
store origin: http://127.0.0.1:18082
routes found: link-tag
bundle: http://127.0.0.1:18081 (33 file(s), profile ecommerce-geo/1.12)
signature: absent
binding: bound
OK: the bundle is discoverable and speaks for this store
```

Anything else is a problem line in plain words, and the command exits 1.
The line names what the well-known location answered, so a bot gate
reads as `answered HTTP 403`, a pay-per-crawl answer as `HTTP 402`, a
single-page-app fallback as `answered 200 with something other than
JSON`, and an absent bundle as `HTTP 404`.

Check the headers on one Markdown file and one JSON file:

```bash
curl -sI https://www.store.example/.well-known/okf/index.md
```

Expected, as returned by the Caddy recipe on the test machine:

```
HTTP/1.1 200 OK
Access-Control-Allow-Origin: *
Cache-Control: public, max-age=300, must-revalidate
Content-Type: text/markdown; charset=utf-8
```

Check `robots.txt` at publish time (same-origin only; for a delegated
bundle read the bundle host's `robots.txt` yourself):

```bash
okf-web publish my-store dist --check-robots
# robots.txt: all checked AI agents may fetch the bundle
```

A missing `robots.txt` (a 404, or any other 4xx) places no restrictions
and is reported as allowed, as the robots standard reads it; a 5xx or an
unreachable host leaves the check inconclusive, and the publish says so.

If you signed, verify the identity, not just the presence:

```bash
okf-web verify dist --cert-identity you@store.example --cert-oidc-issuer <issuer-url>
```

Then read [§6](#6-bot-gates-above-robotstxt) once more if a CDN or WAF
sits in front of the host: none of the commands above can see a bot gate
from the outside.

## 8. How these recipes were tested

All on 2026-09-09, in the project's test environment (Linux, Python
3.11, Node 22). "Live" means the recipe served the published example
bundle over HTTP and `okf-web discover` was run against it.

| Recipe | How | Tools |
| --- | --- | --- |
| nginx (§2.1) | Parsed as a complete nginx configuration. No nginx binary was available, so the header and type semantics are covered by the suite's own HTTP server, which implements the same rules. | crossplane 0.5.8 |
| Apache `.htaccess` (§2.2) | Parsed. No httpd binary was available, so not served live. | apacheconfig 0.3.2 |
| Caddy (§2.3, §5.1) | `caddy validate`, then run live with three sites: a same-origin store, a standalone bundle host, and a platform-style store carrying only the head tag. Headers checked with curl on every file type; `okf-web discover` returned OK on both routes (the transcripts in §7). | Caddy v2.11.4 |
| Cloudflare Pages (§3.1) | Live in wrangler's local Pages emulator with `_headers` and `404.html`: headers, the `Content-Type` override for `attesters/*`, a real 404 for missing files, and `discover` OK. Also observed, and the reason for the `404.html` line: without it, missing paths returned `index.html` with status 200 and `discover` reported a signature that did not exist. | wrangler 3.114.17 |
| Netlify (§3.2) | Live in Netlify Dev, once with `netlify.toml` and once with `_headers`: CORS applied from both, `.md` typed correctly, `discover` OK; the emulator kept its own `Cache-Control` and ignored the `Content-Type` override. | netlify-cli 17.38.1 |
| Vercel (§3.3) | `vercel.json` validated as JSON by the suite. Not deployed. | test suite |
| GitHub Pages (§3.4) | Platform headers probed live on `pages.github.com` (CORS `*`, `max-age=600`); the `.md` type observed on a Pages-hosted documentation site. No deploy run. | curl |
| S3 + CloudFront (§3.5) | Commands checked against the AWS CLI reference; the CORS JSON validated by the suite. Not run. | test suite |
| Delegated route (§4) | Exercised end to end by the suite: a store page carrying the emitted tag on one origin, the dist on another, `discover` binding `bound`; a wrong `--site` yields `mismatch`, a missing one `missing`. Also live under Caddy (above). | test suite, Caddy |
| Container (§5.1) | Not built (no container runtime). The Caddyfile it copies is the live-tested one. | |
| GitHub Actions (§5.2) | Parsed as YAML by the suite. Not executed. | test suite |
| Bot gates (§6) | Vendor documentation, not a run. The `robots.txt` half (`check_robots`) is exercised against a served `robots.txt` in the suite. | test suite |

The durable part is `tests/test_hosting.py`: it publishes the example
bundle, serves it over real HTTP with exactly the header rules of §0,
runs the discovery verifier over both routes, and checks that the
recipes in this file still carry those rules. A change to the serving
rules or the verifier fails a test before it reaches this document.

### Re-run 2026-09-30

The recipes were run again against a freshly published example: Caddy
v2.11.4 on the three localhost sites, wrangler 3.114.17's Pages emulator
with and without `404.html`, and Netlify Dev 17.38.1, each reproducing
the observations above, and GitHub Pages' platform headers re-probed
live. Edge probes against the suite's own server then produced four
changes to the toolchain rather than to the recipes: the fetcher asks
for identity encoding and decodes a gzip or deflate answer under its
byte cap (a pre-compressed manifest used to read as "no bundle found");
a missing `robots.txt` counts as allowed instead of inconclusive; the
verifier's problem lines name the HTTP status the well-known location
answered (a 403 challenge page used to read like an absent bundle); and
origin comparison normalizes default ports. The plain-path route for a
host that hides dot-directories (§2.4) and the one-pointer rule (§4)
were written down at the same time. The tests that pin the four:
`tests/test_net_encoding.py`, and the robots, status and origin cases in
`tests/test_hosting.py`.
