"""The WordPress plugin that prints a bundle's answers on a store's pages
(`integrations/wordpress/okf-web-answers/`).

Two kinds of check. The static ones read the plugin's source: it says
what it is, it agrees with the toolchain on the shape it reads, and it
calls nothing that writes a post, a product or a price, or that
fetches by another door than WordPress's guarded one. The others run
its PHP tests, against the example as `publish` writes it, when a PHP
interpreter is at hand. Neither is a run inside WordPress.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from okf_web.publisher import publish
from okf_web.structured import ANSWER_SCHEMA, ANSWERS_INDEX

REPO = Path(__file__).resolve().parents[1]
WORDPRESS = REPO / "integrations" / "wordpress"
PLUGIN = WORDPRESS / "okf-web-answers"
MAIN = PLUGIN / "okf-web-answers.php"
READER = PLUGIN / "includes" / "class-okf-web-answers-reader.php"
SHIPPED = sorted(PLUGIN.rglob("*.php"))
PHP = shutil.which("php")

#: What a plugin that only prints has no reason to call: anything that
#: writes a post, a product, a price or an option of its own accord, any
#: fetch but the guarded one, and anything that runs text as code.
FORBIDDEN_CALLS = (
    r"wp_insert_post", r"wp_update_post", r"wp_delete_post", r"wp_trash_post",
    r"(?:add|update|delete)_post_meta", r"(?:add|update)_option\s*\(",
    r"wc_(?:update|create|delete)_", r"->set_(?:price|regular_price|sale_price|stock)",
    r"->save\s*\(", r"wp_remote_(?:get|post|request|head)\s*\(", r"wp_safe_remote_(?:post|request)\s*\(",
    r"curl_\w+\s*\(", r"file_get_contents\s*\(", r"fopen\s*\(", r"fsockopen\s*\(",
    r"\beval\s*\(", r"base64_decode\s*\(", r"\bexec\s*\(", r"shell_exec", r"\bsystem\s*\(",
    r"passthru", r"proc_open", r"unserialize\s*\(", r"\$_(?:GET|POST|REQUEST|COOKIE|SERVER)\b",
    r"setcookie", r"wp_mail\s*\(",
)


def _php_or_skip():
    if PHP is None:
        if os.environ.get("CI"):
            pytest.fail("no php on this runner: the plugin's tests did not run")
        pytest.skip("no php interpreter here")
    return PHP


def _run(*args, **kwargs):
    return subprocess.run([_php_or_skip(), "-d", "memory_limit=256M", *map(str, args)],
                          capture_output=True, text=True, timeout=120, **kwargs)


# --- what the source says --------------------------------------------------

def test_the_plugin_ships_these_files_and_no_others():
    shipped = sorted(str(p.relative_to(PLUGIN)) for p in PLUGIN.rglob("*") if p.is_file())
    assert shipped == ["LICENSE", "includes/class-okf-web-answers-reader.php",
                       "okf-web-answers.php", "readme.txt", "uninstall.php"]


def test_it_is_licensed_as_wordpress_is_and_says_so_everywhere():
    """GPLv2 or later, the license WordPress uses and its directory
    strongly recommends; the folder carries the license's text. The
    rest of the repository stays Apache-2.0."""
    gpl = ("GPLv2 or later", "https://www.gnu.org/licenses/gpl-2.0.html")
    main = MAIN.read_text(encoding="utf-8")
    assert (re.search(r"^ \* License:\s+(.+)$", main, re.MULTILINE).group(1),
            re.search(r"^ \* License URI:\s+(\S+)$", main, re.MULTILINE).group(1)) == gpl
    readme = (PLUGIN / "readme.txt").read_text(encoding="utf-8")
    assert (re.search(r"^License: (.+)$", readme, re.MULTILINE).group(1),
            re.search(r"^License URI: (\S+)$", readme, re.MULTILINE).group(1)) == gpl
    text = (PLUGIN / "LICENSE").read_text(encoding="utf-8")
    assert text.split("\n")[:2] == ["                    GNU GENERAL PUBLIC LICENSE",
                                    "                       Version 2, June 1991"]
    assert text.rstrip().endswith("Public License instead of this License.")
    assert (REPO / "LICENSE").read_text(encoding="utf-8").lstrip().startswith("Apache License")


def test_its_readme_keeps_the_directory_rules():
    """What the WordPress.org directory reads from the readme's header:
    the fields it requires, at most five tags, a short description of
    150 characters or fewer, and versions written as numbers."""
    readme = (PLUGIN / "readme.txt").read_text(encoding="utf-8")
    head, _, rest = readme.partition("\n\n")
    assert head.splitlines()[0] == "=== OKF-Web Answers ==="
    fields = dict(line.split(": ", 1) for line in head.splitlines()[1:])
    assert {"Contributors", "Tags", "Requires at least", "Tested up to", "Requires PHP",
            "Stable tag", "License", "License URI"} <= set(fields)
    assert 1 <= len([tag for tag in fields["Tags"].split(",") if tag.strip()]) <= 5
    assert re.fullmatch(r"\d+\.\d+", fields["Tested up to"])
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", fields["Requires at least"])
    short = rest.split("\n\n", 1)[0]
    assert "\n" not in short and 0 < len(short) <= 150 and "<" not in short
    assert "== Description ==" in readme and "== External services ==" in readme
    main = MAIN.read_text(encoding="utf-8")
    for field in ("Requires at least", "Requires PHP"):
        stated = re.search(rf"^ \* {field}:\s+(\S+)$", main, re.MULTILINE).group(1)
        assert stated == fields[field], field


def test_its_version_is_stated_once_in_three_places():
    main = MAIN.read_text(encoding="utf-8")
    header = re.search(r"^ \* Version:\s+(\S+)$", main, re.MULTILINE).group(1)
    constant = re.search(r"define\( 'OKF_WEB_ANSWERS_VERSION', '([^']+)' \)", main).group(1)
    stable = re.search(r"^Stable tag: (\S+)$", (PLUGIN / "readme.txt").read_text(encoding="utf-8"),
                       re.MULTILINE).group(1)
    assert header == constant == stable
    assert re.fullmatch(r"\d+\.\d+\.\d+", header)


def test_it_reads_the_shape_the_toolchain_writes(example_bundle, tmp_path):
    reader = READER.read_text(encoding="utf-8")
    assert f"const ANSWER_SCHEMA = '{ANSWER_SCHEMA}';" in reader
    publish(example_bundle, tmp_path / "dist")
    index = json.loads((tmp_path / "dist" / ANSWERS_INDEX).read_text(encoding="utf-8"))
    assert f"const INDEX_SCHEMA  = '{index['schema']}';" in reader
    # And it asks for the index where the toolchain puts it.
    assert f"'/{ANSWERS_INDEX}'" in MAIN.read_text(encoding="utf-8")


def test_it_is_off_until_switched_on_and_says_what_it_does():
    main = MAIN.read_text(encoding="utf-8")
    assert "'enabled' => ! empty( $saved['enabled'] )," in main
    # An answer is short until the whole fact sheet is asked for (0.2.0).
    assert "'whole'   => ! empty( $saved['whole'] )," in main
    readme = (PLUGIN / "readme.txt").read_text(encoding="utf-8")
    for promise in ("It never changes your products, prices or pages.",
                    "It is off until you switch it on",
                    "== External services =="):
        assert promise in readme
    assert "It never changes your products, prices or pages." in main


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_it_calls_nothing_that_writes_or_fetches_another_way(path):
    source = path.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = "\n".join(line for line in code.splitlines() if not line.strip().startswith("//"))
    for pattern in FORBIDDEN_CALLS:
        assert not re.search(pattern, code), (path.name, pattern)
    # The database is touched in one place: removing its own leftovers.
    assert ("$wpdb" in code) == (path.name == "uninstall.php")


def test_its_one_fetch_is_the_guarded_one_with_limits():
    main = MAIN.read_text(encoding="utf-8")
    assert main.count("wp_safe_remote_get(") == 1
    for limit in ("'timeout'", "'redirection'", "'limit_response_size'"):
        assert limit in main
    assert "strlen( $body ) >= $bytes" in main  # a reply at the limit was cut: not used


def test_everything_it_prints_is_escaped_where_it_is_printed():
    main = MAIN.read_text(encoding="utf-8")
    for line in main.splitlines():
        if re.search(r"\becho\b", line):
            assert re.search(r"echo (esc_html|esc_attr|esc_url|wp_kses_post)\(", line), line.strip()
    reader = READER.read_text(encoding="utf-8")
    render = reader[reader.index("public static function render("):reader.index("public static function instant(")]
    for line in render.splitlines():
        # Every value joined into the HTML passes through an escaper on its own line.
        for value in re.findall(r"\. ([a-z_]*)\(? ?\$(?:answer|section|labels|when|label)\b", line):
            assert value in ("esc_html", "esc_url"), line.strip()
    assert render.count("esc_html(") >= 6 and render.count("esc_url(") == 1


def test_no_file_of_the_plugin_names_a_host():
    """It reads from the store's own site unless the owner types an
    address; no service is built into it."""
    for path in SHIPPED:
        hosts = set(re.findall(r"https?://([A-Za-z0-9.-]+)", path.read_text(encoding="utf-8")))
        assert hosts <= {"github.com", "www.gnu.org"}, (path.name, hosts)


# --- the plugin's own tests, run -------------------------------------------

@pytest.mark.parametrize("path", sorted(WORDPRESS.rglob("*.php")), ids=lambda p: p.name)
def test_every_php_file_parses(path):
    done = _run("-l", path)
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_reader_reads_what_publish_writes(example_bundle, tmp_path):
    result = publish(example_bundle, tmp_path / "dist",
                     site="https://www.alpinepeakoutfitters.example")
    answers = [rel for rel in result.structured
               if rel.startswith("answers/") and rel != ANSWERS_INDEX]
    done = _run(WORDPRESS / "tests" / "reader-test.php", tmp_path / "dist")
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"dist: {len(answers)} answers on {len(answers)} pages" in done.stdout
    assert re.search(r"^ok: \d+ checks$", done.stdout, re.MULTILINE)


def test_the_wordpress_side_against_stand_ins():
    done = _run(WORDPRESS / "tests" / "plugin-test.php")
    assert done.returncode == 0, done.stdout + done.stderr
    assert re.search(r"^ok: \d+ checks$", done.stdout, re.MULTILINE)
