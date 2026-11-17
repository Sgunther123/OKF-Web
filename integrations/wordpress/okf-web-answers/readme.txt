=== OKF-Web Answers ===
Contributors: okfweb
Tags: answers, faq, ai, woocommerce, knowledge
Requires at least: 5.8
Tested up to: 6.8
Requires PHP: 7.2
Stable tag: 0.1.0
License: Apache-2.0
License URI: https://www.apache.org/licenses/LICENSE-2.0

Shows the answers a person approved for your store on the pages they are about. It never changes your products, prices or pages.

== Description ==

AI assistants answer shoppers' questions about your store from what your pages say. This plugin puts answers a person has checked where both shoppers and assistants read: on the page each answer is about.

The answers come from your store's OKF-Web bundle, a set of fact sheets about your store (returns, shipping, products, sizing and so on) in which each fact sheet records who approved it and when. When a bundle is published it includes an `answers/` folder; this plugin reads that folder and prints the answers for the page being viewed, after the page's own content.

What it shows, and what it never shows:

* Only answers a named person approved. A draft, or a fact only a machine checked, is never shown.
* Nothing past its expiry date. Each answer says when it stops being current, and the plugin stops showing it then.
* Only answers about the page being viewed.
* No prices, stock levels or delivery estimates. Those change by the hour and are never part of an answer.

What it does to your site: nothing but print. It does not create, edit or delete posts, pages, products or prices. It keeps its own three settings and a copy of what it read for fifteen minutes. Removing the plugin removes both.

It is off until you switch it on, under Settings, OKF-Web Answers.

== Installation ==

1. Upload the plugin and activate it.
2. Open Settings, OKF-Web Answers.
3. If your bundle is not served by this site at `/.well-known/okf/`, enter the address it is published at.
4. Tick "Show answers" and save. The page tells you how many pages have answers.

On pages and posts the answers follow the content. On WooCommerce product pages they follow the product summary. To place them yourself, use the shortcode `[okf_web_answers]`.

== Frequently Asked Questions ==

= Where do the answers come from? =

From the `answers/` folder of a bundle published with the open-source OKF-Web toolchain (`okf-web publish`), or by a service that runs it for you.

= A page shows no answers. Why? =

Either the plugin is switched off, the bundle has no approved answer about that page, the answer has expired, or the address in the settings could not be read. The settings page says which pages can be read right now.

= Does it slow my pages down? =

What it reads is kept for fifteen minutes, and a failed read is remembered for five, so a page waits for the source at most once in that time, and never longer than four seconds.

== External services ==

This plugin reads JSON files from the address in its settings: your own site by default, or the address you enter. It makes these requests from your server, not from your visitors' browsers, when a page is viewed and its copy is older than fifteen minutes. It sends nothing about your visitors. Like every request WordPress makes, it carries your site's address in its User-Agent. If you enter the address of a service that hosts your bundle, that service's terms and privacy policy apply to those requests.

== Changelog ==

= 0.1.0 =
* First version.
