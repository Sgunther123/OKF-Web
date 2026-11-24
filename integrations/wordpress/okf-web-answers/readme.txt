=== OKF-Web Answers ===
Contributors: okfweb
Tags: answers, faq, ai, woocommerce, knowledge
Requires at least: 5.8
Tested up to: 7.1
Requires PHP: 7.2
Stable tag: 0.2.1
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Shows the answers a person approved for your store on the pages they are about. It never changes your products, prices or pages.

== Description ==

AI assistants answer shoppers' questions about your store from what your pages say. This plugin puts answers a person has checked where both shoppers and assistants read: on the page each answer is about.

The answers come from your store's OKF-Web bundle, a set of fact sheets about your store (returns, shipping, products, sizing and so on) in which each fact sheet records who approved it and when. When a bundle is published it includes an `answers/` folder; this plugin reads that folder and prints the answers for the page being viewed, after the page's own content.

What it shows, and what it never shows:

* Only answers a named person approved. A draft, or a fact only a machine checked, is never shown.
* Nothing past its expiry date. Each answer says when it stops being current, and the plugin stops showing it then.
* Only answers about the page being viewed.
* No prices, stock levels or delivery estimates. Those change by the hour and are never part of an answer.

Each answer shows its title, its summary and the line saying who approved it and when. Tick "The whole fact sheet" in its settings to show every part of it too.

What it does to your site: nothing but print. It does not create, edit or delete posts, pages, products or prices. It keeps its own settings and a copy of what it read for fifteen minutes. Removing the plugin removes both.

It is off until you switch it on, under Settings, OKF-Web Answers.

== Installation ==

1. Upload the plugin and activate it.
2. Open Settings, OKF-Web Answers.
3. If your bundle is not served by this site at `/.well-known/okf/`, enter the address it is published at.
4. Tick "Show answers" and save. The page tells you how many pages have answers.

On pages and posts the answers follow the content. On WooCommerce product pages they follow the product summary. To place them yourself, use the shortcode `[okf_web_answers]`.

== Frequently Asked Questions ==

= Why does an answer show only its summary? =

A fact sheet is often written from the very page it is printed on, so the whole of it would repeat what the page already says. The summary and the date a person approved it are what the page did not say. Tick "The whole fact sheet" in the settings to show every part.

= Where do the answers come from? =

From the `answers/` folder of a bundle published with the open-source OKF-Web toolchain (`okf-web publish`), or by a service that runs it for you.

= A page shows no answers. Why? =

Either the plugin is switched off, the bundle has no approved answer about that page, the answer has expired, or the address in the settings could not be read. The settings page says which pages can be read right now. If an answer was approved a moment ago, save the settings: saving reads everything again.

= Does it slow my pages down? =

What it reads is kept for fifteen minutes, and a failed read is remembered for five, so a page waits for the source at most once in that time, and never longer than four seconds.

== External services ==

This plugin reads JSON files from the address in its settings: your own site by default, or the address you enter. It makes these requests from your server, not from your visitors' browsers, when a page is viewed and its copy is older than fifteen minutes. It sends nothing about your visitors. Like every request WordPress makes, it carries your site's address in its User-Agent. If you enter the address of a service that hosts your bundle, that service's terms and privacy policy apply to those requests.

== Changelog ==

= 0.2.1 =
* Licensed GPLv2 or later, the license WordPress itself uses, so that the plugin can be offered in the WordPress.org directory. Nothing it does has changed.

= 0.2.0 =
* Each answer shows its title, its summary and who approved it and when; the whole fact sheet only when that is ticked in the settings. On the page a fact sheet was written from, the whole of it repeated the page.
* Saving the settings reads everything again, even when nothing in them changed.
* In the whole form, a summary the first part already begins with is printed once.

= 0.1.0 =
* First version.
