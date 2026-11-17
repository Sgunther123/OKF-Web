# OKF-Web Answers, a WordPress plugin

`publish` writes a bundle's verified concepts as plain text under
`answers/`, listed by the page each is about (DESIGN §8). This plugin
is a reader of that folder for a store that runs WordPress, with or
without WooCommerce: when it is switched on, a page shows the answers
listed for its own address, after its own content.

It only prints. It creates, edits and deletes no post, page, product
or price; it keeps its three settings and, for fifteen minutes, a copy
of what it read. A test reads its source for any call that would do
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
- it has not passed its `expires` instant, checked each time it is
  printed, so an answer that lapses while a copy is kept stops showing;
- its own `page` is the page being viewed (scheme, a trailing slash,
  the query and the host's case are ignored).

Every string is escaped where it is printed. At most five answers a
page, twelve sections an answer.

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
open Settings, OKF-Web Answers; tick "Show answers".

## Testing it

```bash
php integrations/wordpress/tests/reader-test.php [dist]   # the reader's decisions; with a dist, that dist's answers
php integrations/wordpress/tests/plugin-test.php          # the WordPress side, against stand-ins
python -m pytest -q tests/test_wordpress_plugin.py        # both, and the static checks
```

`reader-test.php` needs no WordPress: the reader is plain PHP.
`plugin-test.php` defines stand-ins for the WordPress functions the
plugin calls and checks what it asks of them and what it prints.

**Not yet done: a run inside WordPress.** The stand-ins say what the
plugin does with WordPress's answers, not what a real WordPress, theme
or WooCommerce version answers. Until it has been activated on a real
site and seen printing on a page, a post and a product, treat it as
untried there. When it has, record the WordPress, WooCommerce and PHP
versions here.
