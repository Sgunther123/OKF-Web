# OKF-Web User Guide

*A plain-English guide for store owners and their teams. No
programming background needed — if you can copy and paste a command,
you can follow along.*

---

## What this is, in one minute

Shoppers increasingly ask AI assistants — ChatGPT, Claude, Gemini,
Perplexity — the questions they used to type into Google: *"Is this
store legit?"*, *"Can I return an opened tent?"*, *"Do they ship to
Canada?"* Those assistants answer with whatever they can find, and
when they can't find something, they guess. A wrong guess about your
return policy costs you a sale or a support ticket.

OKF-Web builds a **fact folder** for your store — think of it as a
press kit written for machines. Each fact sheet inside it covers one
thing (a product, your return policy, your shipping rules) in a
simple format any AI can read, with a note about where each fact came
from and who approved it. You publish the folder on your own website
at a standard address, and AI assistants can read your facts instead
of guessing.

Three things make it trustworthy:

1. **An AI drafts, a human approves.** The tool reads your website
   and drafts the fact sheets, but anything involving money, legal
   terms, or safety **cannot be published until a named person
   approves it**. The tool physically refuses. This is not a policy
   suggestion — it's built in.
2. **Every fact cites its source.** Each claim points back to the
   page on your site it came from, so reviewing takes minutes, not
   hours.
3. **It never stores prices or stock.** Those change too fast to
   write down. Instead, the folder teaches AI assistants how to ask
   your website for the live number.

---

## The five words you'll see everywhere

| Word | What it means in plain English |
| --- | --- |
| **Bundle** | The fact folder itself — a folder of small text files |
| **Concept** | One fact sheet inside it (one product, one policy, one FAQ) |
| **Survey** | The step where the AI reads your website and drafts fact sheets |
| **Review** | The step where a person approves or sends back drafts |
| **Scorecard** | A report card measuring how well an AI can answer shopper questions using your folder |

---

## What you'll need

- A computer with **Python** installed (version 3.10 or newer — a
  free download from python.org; many computers already have it).
- The ability to open a **command line**: the app called *Terminal*
  on a Mac, *PowerShell* on Windows.
- One of three ways to give the tool AI access (explained in the
  walkthrough — if you already pay for a Claude subscription, you
  likely need nothing new).
- For the final "put it on your website" step: whoever manages your
  website, for about fifteen minutes. Everything before that, you can
  do yourself.

---

## Walkthrough

### Step 0 — Install

Download this project (green **Code** button on GitHub → *Download
ZIP* → unzip it), open your command line, go into the project folder,
and type:

```
pip install -e .
```

That installs the `okf-web` command. To check it worked:

```
okf-web --help
```

### Step 1 — Play with the example store first

The project includes a complete fact folder for a fictional camping
store, so you can try everything with zero risk. Three commands to
try:

```
okf-web lint bundle-example
```

*Lint* means "check everything." You should see `0 error(s), 0
warning(s)` — a healthy folder.

```
okf-web review list bundle-example
```

This shows what's waiting for human approval. You'll see one item:
the store's warranty policy, drafted by the AI but **not yet
approved by a person** — so the tool will refuse to publish it. Try
approving it, playing the role of the store's lawyer:

```
okf-web review approve bundle-example policies/warranty.md --by you@yourstore.com
```

That's the whole trust system in one command: your name is now
stamped on that policy, permanently, and it's cleared for publishing.

```
okf-web evaluate bundle-example --dry-run
```

This is the free half of the report card — it checks whether the
right fact sheets get found for typical shopper questions.

### Step 2 — Set up AI access (for your own store)

Reading the example needs no AI. Drafting fact sheets for *your*
store does. Pick whichever fits you:

- **You already pay for Claude (Pro or Max):** install
  [Claude Code](https://code.claude.com), log in once, and add
  `--llm claude-code` to the commands below. Nothing else to set up,
  no extra cost beyond the subscription you already have. This path
  is for runs you start yourself, by hand — perfect while you're
  getting started.
- **You have (or create) an Anthropic API account:** run
  `pip install -e .[llm]`, then either set an API key
  (`export ANTHROPIC_API_KEY=...`) or log in once with
  `ant auth login`. This is pay-per-use — typically pennies per page
  — and it's the right path later, when runs happen on a schedule
  without you (see the Growth FAQs).

### Step 3 — Survey your store

Start small — ten pages:

```
okf-web survey my-store --sitemap https://www.yourstore.com --limit 10 --llm claude-code
```

The tool reads your site's page list, fetches each page, and drafts
fact sheets into a new folder called `my-store`. Every draft starts
in "unapproved" status, and every fact in it carries a footnote
pointing at the page it came from.

### Step 4 — Review the drafts

```
okf-web review list my-store
```

Prefer reading in your browser? This writes the whole queue as one
nicely formatted page (it even includes the exact approve command to
copy for each item):

```
okf-web review packet my-store
```

Then open the file it names (double-click works). The page is
read-only — approving still happens with the commands below.

Items about money, policies, or safety are listed first. Open each
file in any text editor (they're plain text) and check one thing:
**does each claim match what your website actually says?** The
footnotes tell you exactly which page to compare against. Then:

```
okf-web review approve my-store policies/returns.md --by you@yourstore.com
```

or, if something's wrong:

```
okf-web review reject my-store policies/returns.md --by you@yourstore.com --reason "the window is 30 days, not 60"
```

Rejected drafts stay unpublished, and your reason is saved so the
next drafting pass can react to it.

### Step 5 — Get your report card

```
okf-web questions my-store --llm claude-code
okf-web evaluate my-store --write-scorecard --llm claude-code
```

The first command writes a set of realistic shopper questions. The
second plays the role of an AI shopping assistant, tries to answer
each question *using only your fact folder*, grades itself strictly,
and saves a scorecard. The two numbers to look at:

- **coverage** — what fraction of questions could be answered. 0.9
  means 9 in 10.
- **knowledge gaps** — the exact questions that couldn't be answered.
  This is your to-do list: each gap is usually a page worth surveying
  or a fact sheet worth adding.

### Step 6 — Publish

```
okf-web publish my-store dist
```

This builds the final folder (called `dist`) — and here the safety
net shows itself: anything high-stakes that a person hasn't approved
is **withheld**, and the tool tells you what it held back.

The folder also includes `viewer.html` — a human-readable view of
your published fact sheets, showing who verified what and linking back
to your real pages. That's what a curious shopper sees if they click
an AI's citation. It's deliberately marked so search engines ignore it
(it will never compete with your actual store pages).

Send the `dist` folder to whoever manages your website and ask them
to serve it at:

```
https://www.yourstore.com/.well-known/okf/
```

(That odd-looking address is a web standard — a designated spot where
automated visitors know to look. Your web person will recognize it;
the technical details they need are in
[DESIGN.md, section 8](DESIGN.md#8-hosting-and-discovery).)

### Step 7 — Keep it fresh

When your site changes, run the survey again. Two nice properties:
pages that haven't changed are skipped for free, and if a page
changed *after* a person approved its fact sheet, the tool won't
silently overwrite the approved version — it files a "drift proposal"
for a human to look at. Each fact sheet also carries a freshness
date; when it passes, the tool starts reminding you.

---

## FAQs — The concept

**Q: Is this SEO?**
A: A cousin of it. SEO makes your site rank in search results read
by *people*. This makes your facts legible to *AI assistants* that
answer on your behalf — sometimes called GEO (Generative Engine
Optimization). SEO gets you found; this gets you quoted correctly.

**Q: Why can't AI assistants just read my website?**
A: They try. But a product page is mostly menus, scripts, and design
— the facts are buried, policies hide in collapsible boxes, and
reading it all is slow and expensive for the AI, so it samples and
guesses. Measured on the example store, answering from the fact
folder used about **22 times less** AI reading effort than answering
from raw pages, and answered more questions correctly.

**Q: What is OKF? Am I locking into some vendor?**
A: The Open Knowledge Format is an open, public format (published by
Google Cloud) — just text files in folders. No subscription, no
special software needed to read them. If you stop using OKF-Web
tomorrow, your fact folder remains plain text you fully own.

**Q: Will ChatGPT / Google actually read this?**
A: Honest answer: publishing at the standard address makes your facts
*available* to any AI that looks, and the format is designed so any
of them can use it — but adoption by the big engines is emerging, not
guaranteed. Two reasons it pays off anyway: the same folder makes
*your own* tools better today (a support chatbot or on-site search
grounded in approved facts stops making things up), and being early
costs little — the folder is cheap to keep fresh once built.

**Q: Why does my approval matter? The AI wrote it.**
A: Each fact sheet records *who* verified it. AI assistants reading
your folder can see the difference between "a machine wrote this" and
"a named person at the store confirmed this" — and are built to trust
the second more. Your approval is literally part of the product.

**Q: Why doesn't it just include my prices?**
A: A written-down price is wrong the moment you run a sale. Instead
your folder includes instructions any AI can follow to ask your
website for the *live* price and stock. Your facts stay permanently
honest about the two things stores get misquoted on most.

**Q: What gets published? Is any of it private?**
A: Only facts drafted from your own public website, and only after
your approval gates clear. No customer data, no internals. The
review step is also your chance to catch anything you'd rather not
state.

---

## FAQs — Expectations

**Q: How long does this take?**
A: Playing with the example: ten minutes. A small store end to end:
an afternoon, most of it the review step — and reviewing is fast
because every claim has a footnote telling you exactly what to check
it against. Ongoing upkeep: minutes per site change.

**Q: What does it cost?**
A: The tool is free and open source (Apache-2.0). The AI drafting
costs either nothing extra (your existing Claude subscription) or
pennies per page (API). Hosting is a folder of tiny text files on a
website you already pay for — effectively free.

**Q: Will I see more sales next week?**
A: No — and be wary of anyone promising that. This is plumbing: it
makes AI answers about your store correct and measurable. The
scorecard gives you a number that improves as you close gaps; the
payoff grows as more shopping happens through AI assistants.

**Q: How accurate are the AI's drafts?**
A: Good but not trusted: that's the whole design. Drafts may only
contain claims with a source footnote, high-stakes drafts can't
publish without a human, and the checker refuses folders that break
those rules. The AI does the reading; you do the deciding.

**Q: How often do I have to update it?**
A: When your site changes — after a policy update, new products, a
seasonal change. Unchanged pages are skipped at zero cost, so
re-running is cheap. Freshness dates on each fact sheet nag you if
something sits unreviewed too long.

**Q: Do I need a programmer?**
A: For one step, briefly: putting the published folder on your
website. Everything else is copy-paste commands and reading text
files. (And if even that's more than you want, see the last FAQ
section.)

---

## FAQs — Errors and warnings, translated

**"E010 … is `stable` but has no `human:` verifier"**
Something high-stakes (a policy, pricing language, a safety claim) is
marked as final without a person's approval. This is the safety net
firing, not a malfunction. Fix: `okf-web review approve <folder>
<file> --by you@yourstore.com` after you've actually checked it.

**"E013 … has no `sources`"**
A high-stakes fact sheet has claims but no citations — facts nobody
can check don't get published. Usually means a hand-edited file;
either add the source or re-survey the page.

**"bundle has lint errors; refusing to publish"**
The publish step runs the full check first and stops if anything
fails. Run `okf-web lint <folder>` to see the list, fix the items
(most fixes are an approval or a re-survey), publish again.

**"review queue is empty"**
Good news, not an error. Nothing is waiting on a human.

**"quarantined: 1"** after a survey
The AI's draft for one page didn't meet the format rules, so it was
set aside in a `_quarantine` folder instead of entering your fact
folder. Nothing broke and nothing bad got in. Re-run the survey
later; if the same page keeps quarantining, it's usually a page
layout the extractor struggles with — you can write that fact sheet
by hand.

**"drift proposals (surveyor found changes to human-reviewed concepts)"**
Your website changed *after* a person approved the old fact sheet.
The tool refuses to silently overwrite approved facts, so it filed
the new draft in a `_review/proposed` folder. Compare the two, then
approve the update if it's right.

**"stale: `stale_after` (…) has passed"** (warning W021)
A fact sheet's freshness date expired. It still publishes, but AI
readers can see it's past its date. Re-check the fact against your
site and re-approve to refresh it.

**"the `anthropic` package is required … install with `pip install okf-web[llm]`"**
You ran an AI-backed command on the API path without the extra
installed. Either run that install command, or use your Claude
subscription instead by adding `--llm claude-code`.

**"'claude' not found on PATH; install it and log in"**
You asked for the subscription path but Claude Code isn't installed
(or isn't logged in) on this computer. Install it from
code.claude.com, run it once, log in, then retry.

**A survey stops partway with a limit or rate message**
Subscriptions allow a generous but finite amount of AI use per
window. Nothing is lost: re-run the same command later and it picks
up where it left off — already-drafted pages are skipped for free.

**"fetch failed" on some pages**
Your website (or its firewall) declined the tool's visit, or an
address was mistyped. Check the address; if your site blocks
automated visitors, your web person can allow the tool's name
(`okf-web-surveyor`).

---

## FAQs — Growth, automation, and convenience

**Q: When should I switch from my subscription to an API key?**
A: The subscription path is for runs *you* start by hand — and per
its terms it should stay that way. The moment you want runs to happen
*without you* — a nightly re-survey, an automatic weekly scorecard, a
check on every website deploy — that's automation, and automation
belongs on an API key (or the keyless `ant auth login` setup).
Practically: hobby and setup phase → subscription; operating phase →
API.

**Q: How do I automate it?**
A: With an API key set, any scheduler can run the same commands you
run by hand — your web person can wire `okf-web survey` to run
nightly and `okf-web lint --strict` to run on every site change (this
project's own CI file, `.github/workflows/okf-ci.yml`, is a working
example). Because unchanged pages are free, a nightly run on a quiet
site costs almost nothing.

**Q: My catalog grew from 40 products to 800. Now what?**
A: The design already leans your way: re-surveys only pay for
changed pages, review effort clusters on high-stakes items (product
descriptions can flow with lighter review), and the scorecard scales
its questions with your catalog. The one-time cost of the initial big
build is the main event — do that on the API path, not a
subscription, for throughput.

**Q: Can my team share the review work?**
A: Yes — the fact folder is just files, so it works with the same
tools programmers use to share code (git). Each approver stamps
their own name, so the audit trail shows the lawyer approved the
warranty and the merchandiser approved the product specs. Your web
person can set up the folder on GitHub so approvals happen through
its normal review screens.

**Q: I'm on Shopify / BigCommerce — can it read my catalog directly?**
A: Today the tool reads your public site via its sitemap, which works
on any platform. Direct catalog connectors (reading your product data
straight from the platform, syncing automatically) are on the
roadmap. One platform note: Shopify doesn't allow files at the
`/.well-known/` address — your folder lives at an alternate path like
`/apps/okf/`, which the publish command supports (`--base-path`).

**Q: What if I don't want to run any of this myself?**
A: That's a fair choice — the open tool will always be able to do
everything, but running it is a job. A fully hosted, commercial
edition (managed drafting, scheduled scorecards, drift alerts, and
hosting) is developed as
[www.okf-web.com](https://www.okf-web.com).

**Q: Where do I get help?**
A: Open an issue on this project's GitHub page — include the command
you ran and the message you saw. For the concepts in depth, the
technical docs live alongside this guide:
[DESIGN.md](DESIGN.md) (how it works),
[EVALUATION.md](EVALUATION.md) (how the scorecard is calculated),
[GEO-PROFILE.md](GEO-PROFILE.md) (the format rules).

---

## Command cheat sheet

| You want to… | Type |
| --- | --- |
| Check the folder's health | `okf-web lint my-store` |
| See what needs your approval | `okf-web review list my-store` |
| Read the queue in your browser | `okf-web review packet my-store` |
| Approve a fact sheet | `okf-web review approve my-store <file> --by you@yourstore.com` |
| Send one back | `okf-web review reject my-store <file> --by you@yourstore.com --reason "…"` |
| Draft fact sheets from your site | `okf-web survey my-store --sitemap https://yourstore.com --limit 25 --llm claude-code` |
| Get the report card | `okf-web evaluate my-store --write-scorecard --llm claude-code` |
| Build the publishable folder | `okf-web publish my-store dist` |
