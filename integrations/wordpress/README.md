# OKF-Web Answers, a WordPress plugin

`publish` writes a bundle's verified concepts as plain text under
`answers/`, listed by the page each is about (DESIGN §8). This plugin
is a reader of that folder for a store that runs WordPress, with or
without WooCommerce: when it is switched on, a page shows the answers
listed for its own address, after its own content.

It only prints. It creates, edits and deletes no post, page, product
or price; it keeps its settings and, for fifteen minutes, a copy of
what it read. A test reads its source for any call that would do
otherwise.

## What it shows

An answer is printed only when all of these hold; otherwise the page
is left as it is:

- the file is in the shape `okf-web/answer/1`, listed in an index in
  the shape `okf-web/answers-index/1`;
- its tier is `human-reviewed` or `human-attested` (a named person
  approved it), and the line under it says which: "checked and
  approved" for a review, "approved as part of a batch" for a
  wholesale sign-off;
- its approval is dated, and not more than a day ahead of the
  store's own clock (a clock that runs slow must not hide an answer
  approved a minute ago);
- it has not passed its `expires` instant, checked each time it is
  printed, so an answer that lapses while a copy is kept stops showing;
- its own `page` is the page being viewed (scheme, a trailing slash,
  the query and the host's case are ignored).

Every string is escaped where it is printed. At most five answers a
page, twelve sections an answer.

What an answer shows: its title, its summary and the line saying who
approved it and when. Its sections follow only when the owner ticks
"The whole fact sheet" in the settings, and then a summary the first
section already begins with is printed once. The short form is the
default because a fact sheet is often written from the page it is
printed on, and the whole of it repeats that page: the first run
inside WordPress (below) printed a refund page's whole policy again
under itself.

## Where it reads from

By default the site's own `/.well-known/okf`. Under Settings, OKF-Web
Answers, an owner can enter another address, for a bundle published
somewhere else: `https` only, or plain `http` on the site's own host;
no query string, no credentials. The plugin names no host of its own.

Reads go through WordPress's guarded fetch (`wp_safe_remote_get`) with
a four-second timeout and a size limit; a reply that reaches the limit
is treated as cut and not used. A failed read is remembered for five
minutes, so a page waits for an unreachable source once, not on every
view.

## Where the answers appear

- Pages and posts: after the content.
- WooCommerce product pages: after the product summary (a product
  with no long description has no content to follow).
- Anywhere else an owner chooses: the shortcode `[okf_web_answers]`.
  A page that carries it gets nothing appended.

Lists of posts, the shop page and archives show nothing.

## Installing it

```bash
cd integrations/wordpress
zip -r okf-web-answers.zip okf-web-answers
```

Upload the zip under Plugins, Add New, Upload Plugin; activate it;
open Settings, OKF-Web Answers (WordPress's own Settings menu, not
WooCommerce's); tick "Show answers". A new WooCommerce store starts
in "Coming soon" mode: until it is switched to Live (WooCommerce,
Settings, Site visibility), visitors, and the assistants that read
its pages, see neither the store nor its answers.

What the plugin has read is kept for fifteen minutes. Saving its
settings reads everything again, changed or not: the saved settings
count the saves, and what was read is kept under that count.

## Testing it

```bash
php integrations/wordpress/tests/reader-test.php [dist]   # the reader's decisions; with a dist, that dist's answers
php integrations/wordpress/tests/plugin-test.php          # the WordPress side, against stand-ins
python -m pytest -q tests/test_wordpress_plugin.py        # both, and the static checks
```

`reader-test.php` needs no WordPress: the reader is plain PHP.
`plugin-test.php` defines stand-ins for the WordPress functions the
plugin calls and checks what it asks of them and what it prints.

**Run inside WordPress, 2026-11-20.** On a temporary test site
running WordPress 7.1.5, WooCommerce 11.3.1 and PHP 8.5.12 with the
Twenty Twenty-Three block theme, and reading its answers from another
host, the plugin was uploaded as the zip above and activated. A
product's answer printed below the product's Description and Reviews
tabs: WooCommerce's block template for a product still ran the hook
the plugin uses. A page's answer printed after the page's own text.
Unticking "Show answers" took both away and left the rest of each
page as it was. All of it was read from outside, as a visitor sees
it. Not yet seen: a post, a classic theme, and any other WordPress,
WooCommerce or PHP version. The stand-ins remain the suite's test,
so a change to where the plugin hooks into a page is seen on a real
site again before it is believed.

What it printed decided 0.2.0. An answer on the page it was drafted
from repeated that page (the refund page's answer repeated the whole
policy under itself), so an answer now shows its title, its summary
and who approved it, and its sections only when asked for. Within one
answer the summary repeated the start of its first section, so the
whole form prints it once. And saving the settings unchanged did not
make the plugin read again; now every save does. 0.2.0 changes what is
printed, not where: it is tried against the stand-ins, and goes onto
the same site to be seen there before it is believed.
