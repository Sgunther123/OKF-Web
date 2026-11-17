<?php
/**
 * The reader's decisions, checked without WordPress.
 *
 *   php integrations/wordpress/tests/reader-test.php [dist]
 *
 * With a published dist as the argument it also reads that dist's
 * answers the way the plugin does: every page in the index must yield
 * its answers, checked and rendered.
 */

define( 'OKF_WEB_ANSWERS_TESTING', true );

function esc_html( $text ) {
	return htmlspecialchars( (string) $text, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8' );
}
function esc_url( $url ) {
	return htmlspecialchars( (string) $url, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8' );
}

require dirname( __DIR__ ) . '/okf-web-answers/includes/class-okf-web-answers-reader.php';

$failures = 0;
$checks   = 0;
function check( $what, $ok ) {
	global $failures, $checks;
	$checks++;
	if ( ! $ok ) {
		$failures++;
		echo "FAIL: $what\n";
	}
}
function same( $what, $got, $want ) {
	check( $what . ' (got ' . json_encode( $got ) . ', want ' . json_encode( $want ) . ')', $got === $want );
}

$R    = 'OKF_Web_Answers_Reader';
$PAGE = 'https://shop.example/returns';
$NOW  = gmmktime( 12, 0, 0, 11, 17, 2026 );

// --- addresses -------------------------------------------------------------
same( 'scheme and slash ignored', $R::normalize_url( 'HTTP://Shop.Example/returns/' ), 'shop.example/returns' );
same( 'https the same page', $R::normalize_url( 'https://shop.example/returns' ), 'shop.example/returns' );
same( 'query and fragment dropped', $R::normalize_url( 'https://shop.example/returns?utm=1#top' ), 'shop.example/returns' );
same( 'implied port dropped', $R::normalize_url( 'https://shop.example:443/a' ), 'shop.example/a' );
same( 'other port kept', $R::normalize_url( 'http://shop.example:8080/a' ), 'shop.example:8080/a' );
same( 'home page', $R::normalize_url( 'https://shop.example/' ), 'shop.example' );
same( 'path case kept', $R::normalize_url( 'https://shop.example/Returns' ), 'shop.example/Returns' );
foreach ( array( 'javascript:alert(1)', 'ftp://shop.example/a', '/returns', '', null, 42, array(), 'https://' ) as $bad ) {
	same( 'not a page: ' . json_encode( $bad ), $R::normalize_url( $bad ), '' );
}

// --- the source ------------------------------------------------------------
same( 'https source', $R::clean_source( 'https://cdn.example/okf/', 'shop.example' ), 'https://cdn.example/okf' );
same( 'own host over http', $R::clean_source( 'http://shop.example/.well-known/okf', 'shop.example' ), 'http://shop.example/.well-known/okf' );
same( 'own host with a port', $R::clean_source( 'http://localhost:8089/.well-known/okf', 'localhost' ), 'http://localhost:8089/.well-known/okf' );
same( 'another host over http refused', $R::clean_source( 'http://cdn.example/okf', 'shop.example' ), '' );
same( 'a query refused', $R::clean_source( 'https://cdn.example/okf?x=1', 'shop.example' ), '' );
same( 'a fragment refused', $R::clean_source( 'https://cdn.example/okf#x', 'shop.example' ), '' );
same( 'credentials refused', $R::clean_source( 'https://user:pw@cdn.example/okf', 'shop.example' ), '' );
foreach ( array( 'file:///etc/passwd', 'javascript:alert(1)', 'cdn.example/okf', '', null, array() ) as $bad ) {
	same( 'not a source: ' . json_encode( $bad ), $R::clean_source( $bad, 'shop.example' ), '' );
}

// --- paths from the index --------------------------------------------------
foreach ( array( 'answers/policies/returns.json', 'answers/store.json', 'answers/catalog/products/a-2_tent.v2.json' ) as $good ) {
	check( 'a path it fetches: ' . $good, $R::safe_path( $good ) );
}
foreach ( array(
	'answers/../manifest.json', 'answers/a/../../manifest.json', 'answers/a/..json', 'answers/index.json',
	'/answers/a.json', 'answers//a.json', 'answers/a//b.json', 'jsonld/a.json',
	'answers/a.json?x=1', 'answers/a.md', 'https://evil.example/answers/a.json', 'answers/a b.json',
	'answers/.hidden.json', 'answers/a.json/', '', null, array( 'answers/a.json' ), str_repeat( 'answers/a', 40 ) . '.json',
) as $bad ) {
	check( 'a path it refuses: ' . json_encode( $bad ), ! $R::safe_path( $bad ) );
}

$index = array(
	'schema'  => 'okf-web/answers-index/1',
	'answers' => array(),
	'pages'   => array(
		'https://shop.example/returns'  => array( 'answers/faq/returns.json', 'answers/policies/returns.json' ),
		'http://SHOP.example/returns/'  => array( 'answers/policies/returns.json', 'answers/extra.json', '../secret.json' ),
		'https://shop.example/shipping' => array( 'answers/policies/shipping.json' ),
		'https://shop.example/many'     => array( 'answers/1.json', 'answers/2.json', 'answers/3.json', 'answers/4.json', 'answers/5.json', 'answers/6.json' ),
		'https://shop.example/odd'      => 'answers/odd.json',
	),
);
same( 'both spellings of a page, in order, once each', $R::paths_for_page( $index, $PAGE ), array( 'answers/faq/returns.json', 'answers/policies/returns.json', 'answers/extra.json' ) );
same( 'another page', $R::paths_for_page( $index, 'https://shop.example/shipping/' ), array( 'answers/policies/shipping.json' ) );
same( 'a page with none', $R::paths_for_page( $index, 'https://shop.example/about' ), array() );
same( 'no more than five', count( $R::paths_for_page( $index, 'https://shop.example/many' ) ), 5 );
same( 'a malformed entry', $R::paths_for_page( $index, 'https://shop.example/odd' ), array() );
same( 'an unknown index shape', $R::paths_for_page( array( 'schema' => 'okf-web/answers-index/2' ) + $index, $PAGE ), array() );
foreach ( array( null, 'x', array(), array( 'schema' => 'okf-web/answers-index/1' ), array( 'schema' => 'okf-web/answers-index/1', 'pages' => 'x' ) ) as $bad ) {
	same( 'not an index: ' . json_encode( $bad ), $R::paths_for_page( $bad, $PAGE ), array() );
}
same( 'pages counted', $R::page_count( $index ), 5 );
same( 'no index counted as unreadable', $R::page_count( null ), -1 );
same( 'an index with no pages', $R::page_count( array( 'schema' => 'okf-web/answers-index/1' ) ), 0 );

// --- one answer ------------------------------------------------------------
$answer = array(
	'schema'     => 'okf-web/answer/1',
	'type'       => 'Policy',
	'title'      => 'Return & Exchange Policy',
	'summary'    => 'Items may be returned within 60 days.',
	'sections'   => array(
		array( 'heading' => 'Window', 'text' => 'Sixty days from delivery.' ),
		array( 'heading' => '', 'text' => 'Opening line.' ),
		array( 'heading' => 'Empty', 'text' => '' ),
		'not a section',
	),
	'verified'   => array( 'tier' => 'human-reviewed', 'at' => '2026-08-05T15:11:38Z' ),
	'subjectOf'  => 'https://shop.example/.well-known/okf/policies/returns.md',
	'page'       => 'https://shop.example/returns',
	'inLanguage' => 'en',
	'expires'    => '2028-02-01T00:00:00Z',
);
$clean = $R::clean_answer( $answer, $PAGE, $NOW );
check( 'a good answer is shown', is_array( $clean ) );
same( 'its fields', array_keys( $clean ), array( 'title', 'summary', 'sections', 'tier', 'verified_at', 'expires', 'record' ) );
same( 'its sections, the empty and the malformed dropped', $clean['sections'], array(
	array( 'heading' => 'Window', 'text' => 'Sixty days from delivery.' ),
	array( 'heading' => '', 'text' => 'Opening line.' ),
) );
same( 'verified instant', $clean['verified_at'], gmmktime( 15, 11, 38, 8, 5, 2026 ) );
same( 'the page spelled another way still matches', is_array( $R::clean_answer( $answer, 'http://SHOP.example/returns/?ref=x', $NOW ) ), true );

function without( $a, $key ) { unset( $a[ $key ] ); return $a; }
$refused = array(
	'another shape'             => array( 'schema' => 'okf-web/answer/2' ) + $answer,
	'no shape'                  => without( $answer, 'schema' ),
	'only a machine checked it' => array( 'verified' => array( 'tier' => 'machine-confirmed', 'at' => '2026-08-05T15:11:38Z' ) ) + $answer,
	'nobody checked it'         => array( 'verified' => array( 'tier' => 'unverified', 'at' => '2026-08-05T15:11:38Z' ) ) + $answer,
	'no verification'           => without( $answer, 'verified' ),
	'verification is not a map' => array( 'verified' => 'human-reviewed' ) + $answer,
	'no instant'                => array( 'verified' => array( 'tier' => 'human-reviewed' ) ) + $answer,
	'an instant in the future'  => array( 'verified' => array( 'tier' => 'human-reviewed', 'at' => '2027-01-01T00:00:00Z' ) ) + $answer,
	'an unreadable instant'     => array( 'verified' => array( 'tier' => 'human-reviewed', 'at' => 'yesterday' ) ) + $answer,
	'expired'                   => array( 'expires' => '2026-11-17T12:00:00Z' ) + $answer,
	'expired long ago'          => array( 'expires' => '2026-01-01T00:00:00Z' ) + $answer,
	'an unreadable expiry'      => array( 'expires' => 'never' ) + $answer,
	'an expiry that is no text' => array( 'expires' => 99999999999 ) + $answer,
	'about another page'        => array( 'page' => 'https://shop.example/shipping' ) + $answer,
	'about another site'        => array( 'page' => 'https://other.example/returns' ) + $answer,
	'about no page'             => without( $answer, 'page' ),
	'a page that is no address' => array( 'page' => 'javascript:alert(1)' ) + $answer,
	'no title'                  => array( 'title' => '' ) + $answer,
	'a title that is no text'   => array( 'title' => array( 'x' ) ) + $answer,
	'nothing to say'            => array( 'summary' => '', 'sections' => array() ) + $answer,
);
foreach ( $refused as $why => $raw ) {
	same( 'not shown: ' . $why, $R::clean_answer( $raw, $PAGE, $NOW ), null );
}
foreach ( array( null, 'text', 7, array() ) as $bad ) {
	same( 'not an answer: ' . json_encode( $bad ), $R::clean_answer( $bad, $PAGE, $NOW ), null );
}
check( 'no expiry is allowed', is_array( $R::clean_answer( without( $answer, 'expires' ), $PAGE, $NOW ) ) );
// A store's clock that runs slow: an approval dated a little ahead of it is shown.
check( 'approved an hour ahead of this clock: shown', is_array( $R::clean_answer( array( 'verified' => array( 'tier' => 'human-reviewed', 'at' => '2026-11-17T13:00:00Z' ) ) + $answer, $PAGE, $NOW ) ) );
check( 'approved a day ahead, to the second: shown', is_array( $R::clean_answer( array( 'verified' => array( 'tier' => 'human-reviewed', 'at' => '2026-11-18T12:00:00Z' ) ) + $answer, $PAGE, $NOW ) ) );
same( 'approved more than a day ahead: not a date', $R::clean_answer( array( 'verified' => array( 'tier' => 'human-reviewed', 'at' => '2026-11-18T12:00:01Z' ) ) + $answer, $PAGE, $NOW ), null );
check( 'shown until the instant before expiry', is_array( $R::clean_answer( array( 'expires' => '2026-11-17T12:00:01Z' ) + $answer, $PAGE, $NOW ) ) );
same( 'a batch sign-off keeps its own tier', $R::clean_answer( array( 'verified' => array( 'tier' => 'human-attested', 'at' => '2026-08-05' ) ) + $answer, $PAGE, $NOW )['tier'], 'human-attested' );
same( 'a record that is no web address is dropped', $R::clean_answer( array( 'subjectOf' => 'javascript:alert(1)' ) + $answer, $PAGE, $NOW )['record'], '' );
same( 'a relative record is dropped', $R::clean_answer( array( 'subjectOf' => '/.well-known/okf/policies/returns.md' ) + $answer, $PAGE, $NOW )['record'], '' );

$many = $answer;
$many['sections'] = array();
for ( $i = 0; $i < 30; $i++ ) {
	$many['sections'][] = array( 'heading' => "H$i", 'text' => "T$i" );
}
same( 'no more than twelve sections', count( $R::clean_answer( $many, $PAGE, $NOW )['sections'] ), 12 );
$long = array( 'summary' => str_repeat( 'é', 3000 ) ) + $answer;
same( 'a long summary is cut on a character', mb_strlen( $R::clean_answer( $long, $PAGE, $NOW )['summary'], 'UTF-8' ), 1001 );
same( 'control characters and line breaks become spaces', $R::text( "a\x00b\n\n c\t d\x7F", 100 ), 'a b c d' );
same( 'text that is not text', $R::text( array( 'a' ), 100 ), '' );

// --- instants --------------------------------------------------------------
same( 'an instant', $R::instant( '2026-08-05T15:11:38Z' ), gmmktime( 15, 11, 38, 8, 5, 2026 ) );
same( 'a bare date is midnight UTC', $R::instant( '2028-02-01' ), gmmktime( 0, 0, 0, 2, 1, 2028 ) );
same( 'fractions of a second', $R::instant( '2026-08-05T15:11:38.250Z' ), gmmktime( 15, 11, 38, 8, 5, 2026 ) );
foreach ( array( '2026-02-30', '2026-13-01', '2026-08-05T25:00:00Z', '2026-08-05 15:11:38', '2026-08-05T15:11:38+02:00', '', null, 20260805 ) as $bad ) {
	same( 'not an instant: ' . json_encode( $bad ), $R::instant( $bad ), null );
}

// --- what is printed -------------------------------------------------------
$labels = array( 'heading' => 'Verified answers', 'reviewed' => 'Checked and approved by a named person on %s.', 'attested' => 'Approved by a named person on %s, as part of a batch.', 'record' => 'See the record' );
$date   = function ( $ts ) { return gmdate( 'j F Y', $ts ); };
$html   = $R::render( array( $clean ), $labels, $date );
check( 'a heading', false !== strpos( $html, '<h2 class="okf-web-answers__heading">Verified answers</h2>' ) );
check( 'the title, escaped', false !== strpos( $html, '<h3 class="okf-web-answer__title">Return &amp; Exchange Policy</h3>' ) );
check( 'the summary', false !== strpos( $html, '<p class="okf-web-answer__summary">Items may be returned within 60 days.</p>' ) );
check( 'a section with its heading', false !== strpos( $html, '<h4 class="okf-web-answer__section">Window</h4><p>Sixty days from delivery.</p>' ) );
check( 'a section without one', false !== strpos( $html, '<p>Opening line.</p>' ) && 1 === substr_count( $html, '<h4' ) );
check( 'who and when', false !== strpos( $html, 'Checked and approved by a named person on 5 August 2026.' ) );
check( 'the record, linked', false !== strpos( $html, '<a href="https://shop.example/.well-known/okf/policies/returns.md" rel="nofollow">See the record</a>' ) );
same( 'nothing to show prints nothing', $R::render( array(), $labels, $date ), '' );
$batch = $R::clean_answer( array( 'verified' => array( 'tier' => 'human-attested', 'at' => '2026-08-05' ) ) + $answer, $PAGE, $NOW );
check( 'a batch sign-off says so', false !== strpos( $R::render( array( $batch ), $labels, $date ), 'as part of a batch' ) );
check( 'no heading when none is set', false === strpos( $R::render( array( $clean ), array( 'heading' => '' ) + $labels, $date ), '<h2' ) );

$hostile = '</p><script>alert(1)</script><img src=x onerror=alert(2)> "quoted" \'single\' & more';
$evil    = $R::clean_answer( array(
	'title'     => $hostile,
	'summary'   => $hostile,
	'sections'  => array( array( 'heading' => $hostile, 'text' => $hostile ) ),
	'subjectOf' => 'https://shop.example/x"onmouseover="alert(3)',
) + $answer, $PAGE, $NOW );
$evil_html = $R::render( array( $evil ), array( 'heading' => $hostile, 'record' => $hostile ) + $labels, $date );
check( 'no tag of the source survives', 0 === preg_match( '/<(script|img)\b/i', $evil_html ) );
check( 'no attribute of the source survives', false === strpos( $evil_html, '"onmouseover="' ) && false === strpos( $evil_html, ' onerror=alert(2)>' ) );
$stripped = preg_replace( '#</?(section|article|h2|h3|h4|p|a)\b[^<>]*>#', '', $evil_html );
check( 'only the plugin\'s own tags are in the output', false === strpos( $stripped, '<' ) && false === strpos( $stripped, '>' ) );
check( 'a hostile date is escaped too', false === strpos( $R::render( array( $clean ), $labels, function () { return '<b>x</b>'; } ), '<b>' ) );

// --- a real published dist, read the way the plugin reads it -----------------
// On the real clock, as the plugin does: a dist is published against today.
if ( isset( $argv[1] ) ) {
	$NOW   = time();
	$dist  = rtrim( $argv[1], '/' );
	$index = json_decode( file_get_contents( $dist . '/answers/index.json' ), true );
	check( 'the dist has an index this reader knows', $R::page_count( $index ) > 0 );
	$shown = 0;
	foreach ( array_keys( $index['pages'] ) as $page ) {
		$paths = $R::paths_for_page( $index, $page );
		check( "paths for $page", count( $paths ) > 0 );
		$answers = array();
		foreach ( $paths as $path ) {
			$one = $R::clean_answer( json_decode( file_get_contents( $dist . '/' . $path ), true ), $page, $NOW );
			check( "$path is shown on $page", is_array( $one ) );
			if ( is_array( $one ) ) {
				$answers[] = $one;
			}
		}
		$out = $R::render( $answers, $labels, $date );
		check( "$page renders", '' !== $out && 0 === preg_match( '/<(script|img|iframe)\b/i', $out ) );
		$shown += count( $answers );
	}
	same( 'every answer in the index was shown', $shown, count( $index['answers'] ) );
	echo "dist: $shown answers on " . count( $index['pages'] ) . " pages\n";
}

echo $failures ? "$failures of $checks checks FAILED\n" : "ok: $checks checks\n";
exit( $failures ? 1 : 0 );
