<?php
/**
 * The plugin's WordPress side, run against stand-ins for the WordPress
 * functions it calls. This checks what the plugin asks of WordPress and
 * what it does with the answers; it is not a run inside WordPress.
 *
 *   php integrations/wordpress/tests/plugin-test.php
 */

define( 'ABSPATH', __DIR__ . '/' );

// --- the stand-ins ----------------------------------------------------------
$GLOBALS['t'] = array(
	'options'    => array(),
	'transients' => array(),
	'hooks'      => array(),
	'shortcodes' => array(),
	'requests'   => array(),
	'web'        => array(),   // url => body string, or an int status, or 'error'.
	'errors'     => array(),
	'clock'      => 1000,
	'view'       => array(),
	'posts'      => array(),
);

class WP_Error {}
function add_action( $hook, $callback, $priority = 10 ) { $GLOBALS['t']['hooks'][ $hook ][] = array( $callback, $priority ); }
function add_filter( $hook, $callback, $priority = 10 ) { add_action( $hook, $callback, $priority ); }
function add_shortcode( $tag, $callback ) { $GLOBALS['t']['shortcodes'][ $tag ] = $callback; }
function plugin_basename( $file ) { return 'okf-web-answers/' . basename( $file ); }
function get_option( $name, $default = false ) { return array_key_exists( $name, $GLOBALS['t']['options'] ) ? $GLOBALS['t']['options'][ $name ] : $default; }
function __( $text, $domain = '' ) { return $text; }
function home_url( $path = '' ) { return 'https://shop.example' . $path; }
function wp_parse_url( $url, $component = -1 ) { return parse_url( $url, $component ); }
function is_wp_error( $thing ) { return $thing instanceof WP_Error; }
function wp_remote_retrieve_response_code( $response ) { return $response['code']; }
function wp_remote_retrieve_body( $response ) { return $response['body']; }
function wp_safe_remote_get( $url, $args = array() ) {
	$GLOBALS['t']['requests'][] = array( $url, $args );
	$web = $GLOBALS['t']['web'];
	if ( ! array_key_exists( $url, $web ) ) {
		return array( 'code' => 404, 'body' => 'not found' );
	}
	if ( 'error' === $web[ $url ] ) {
		return new WP_Error();
	}
	if ( is_int( $web[ $url ] ) ) {
		return array( 'code' => $web[ $url ], 'body' => '{}' );
	}
	return array( 'code' => 200, 'body' => $web[ $url ] );
}
function get_transient( $name ) {
	$kept = isset( $GLOBALS['t']['transients'][ $name ] ) ? $GLOBALS['t']['transients'][ $name ] : null;
	return ( $kept && $kept[1] > $GLOBALS['t']['clock'] ) ? $kept[0] : false;
}
function set_transient( $name, $value, $seconds ) { $GLOBALS['t']['transients'][ $name ] = array( $value, $GLOBALS['t']['clock'] + $seconds ); return true; }
function delete_transient( $name ) { unset( $GLOBALS['t']['transients'][ $name ] ); return true; }
function wp_date( $format, $timestamp, $zone = null ) { return gmdate( 'j F Y', $timestamp ); }
function is_singular() { return ! empty( $GLOBALS['t']['view']['singular'] ); }
function in_the_loop() { return ! empty( $GLOBALS['t']['view']['loop'] ); }
function is_main_query() { return ! empty( $GLOBALS['t']['view']['main'] ); }
function is_product() { return ! empty( $GLOBALS['t']['view']['product'] ); }
function get_queried_object_id() { return isset( $GLOBALS['t']['view']['id'] ) ? $GLOBALS['t']['view']['id'] : 0; }
function get_post( $id = null ) {
	$id = null === $id ? ( isset( $GLOBALS['t']['view']['current'] ) ? $GLOBALS['t']['view']['current'] : get_queried_object_id() ) : $id;
	return isset( $GLOBALS['t']['posts'][ $id ] ) ? (object) array( 'ID' => $id, 'post_content' => $GLOBALS['t']['posts'][ $id ]['content'] ) : null;
}
function get_permalink( $post = 0 ) {
	$id = is_object( $post ) ? $post->ID : $post;
	return isset( $GLOBALS['t']['posts'][ $id ] ) ? $GLOBALS['t']['posts'][ $id ]['url'] : false;
}
function has_shortcode( $content, $tag ) { return false !== strpos( $content, '[' . $tag . ']' ); }
function wp_kses_post( $html ) { return $html; }
function esc_html( $text ) { return htmlspecialchars( (string) $text, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8' ); }
function esc_url( $url ) { return htmlspecialchars( (string) $url, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8' ); }
function esc_url_raw( $url ) { return (string) $url; }
function wp_unslash( $value ) { return $value; }
function sanitize_text_field( $text ) { return trim( preg_replace( '/\s+/', ' ', strip_tags( (string) $text ) ) ); }
function add_settings_error( $setting, $code, $message ) { $GLOBALS['t']['errors'][] = $code; }

require dirname( __DIR__ ) . '/okf-web-answers/okf-web-answers.php';

// --- helpers ----------------------------------------------------------------
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
function answer( $page, $title, $extra = array() ) {
	return $extra + array(
		'schema'    => 'okf-web/answer/1',
		'type'      => 'Policy',
		'title'     => $title,
		'summary'   => "Summary of $title.",
		'sections'  => array( array( 'heading' => 'Detail', 'text' => "Text of $title." ) ),
		'verified'  => array( 'tier' => 'human-reviewed', 'at' => '2026-08-05T15:11:38Z' ),
		'subjectOf' => 'https://shop.example/.well-known/okf/x.md',
		'page'      => $page,
	);
}
/** Serve a bundle's answers at a base address. */
function serve( $base, $pages ) {
	$index = array( 'schema' => 'okf-web/answers-index/1', 'answers' => array(), 'pages' => array() );
	foreach ( $pages as $page => $answers ) {
		foreach ( $answers as $path => $answer ) {
			$GLOBALS['t']['web'][ "$base/$path" ]  = is_array( $answer ) ? json_encode( $answer ) : $answer;
			$index['pages'][ $page ][]             = $path;
			$index['answers'][]                    = $path;
		}
	}
	$GLOBALS['t']['web'][ "$base/answers/index.json" ] = json_encode( $index );
}
/** A fresh request: nothing printed yet, no requests counted. */
function view( $view ) {
	$GLOBALS['t']['view']     = $view;
	$GLOBALS['t']['requests'] = array();
	$printed                  = new ReflectionProperty( 'OKF_Web_Answers', 'printed' );
	$printed->setAccessible( true );
	$printed->setValue( null, array() );
}
function requested() {
	return array_map( function ( $r ) { return $r[0]; }, $GLOBALS['t']['requests'] );
}
function reset_world() {
	$GLOBALS['t']['options']    = array();
	$GLOBALS['t']['transients'] = array();
	$GLOBALS['t']['web']        = array();
	$GLOBALS['t']['errors']     = array();
}

$OWN     = 'https://shop.example/.well-known/okf';
$RETURNS = array( 'singular' => true, 'loop' => true, 'main' => true, 'id' => 7 );
$GLOBALS['t']['posts'] = array(
	7  => array( 'url' => 'https://shop.example/returns/', 'content' => 'Our returns page.' ),
	8  => array( 'url' => 'https://shop.example/shipping/', 'content' => 'Our shipping page.' ),
	9  => array( 'url' => 'https://shop.example/product/tent/', 'content' => '' ),
	10 => array( 'url' => 'https://shop.example/placed/', 'content' => 'Before [okf_web_answers] after.' ),
	11 => array( 'url' => 'https://shop.example/about/', 'content' => 'About us.' ),
);
$world = array(
	'https://shop.example/returns'      => array(
		'answers/faq/returns.json'      => answer( 'https://shop.example/returns', 'Returns FAQ' ),
		'answers/policies/returns.json' => answer( 'https://shop.example/returns', 'Return Policy' ),
	),
	'https://shop.example/shipping'     => array(
		'answers/policies/shipping.json' => answer( 'https://shop.example/shipping', 'Shipping Policy' ),
	),
	'https://shop.example/product/tent' => array(
		'answers/catalog/tent.json' => answer( 'https://shop.example/product/tent', 'Alpine Tent' ),
	),
	'https://shop.example/placed'       => array(
		'answers/placed.json' => answer( 'https://shop.example/placed', 'Placed Answer' ),
	),
);

// --- the hooks it registers ---------------------------------------------------
$hooks = $GLOBALS['t']['hooks'];
check( 'it filters the content', isset( $hooks['the_content'] ) );
check( 'it prints after a product summary', isset( $hooks['woocommerce_after_single_product_summary'] ) );
check( 'it registers its shortcode', isset( $GLOBALS['t']['shortcodes']['okf_web_answers'] ) );
same( 'and hooks nothing that saves a post or a product', array_values( array_filter( array_keys( $hooks ), function ( $h ) {
	return 1 === preg_match( '/save_post|insert_post|woocommerce_.*(update|save|price)|pre_post_update/', $h );
} ) ), array() );

// --- off until switched on ------------------------------------------------------
reset_world();
serve( $OWN, $world );
view( $RETURNS );
same( 'off: the content is untouched', OKF_Web_Answers::append_to_content( 'Our returns page.' ), 'Our returns page.' );
same( 'off: nothing is requested', requested(), array() );

// --- on: the page's answers follow its content -----------------------------------
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true );
view( $RETURNS );
$out = OKF_Web_Answers::append_to_content( 'Our returns page.' );
check( 'the content comes first', 0 === strpos( $out, 'Our returns page.<section class="okf-web-answers">' ) );
check( 'both answers, in the index\'s order', strpos( $out, 'Returns FAQ' ) < strpos( $out, 'Return Policy' ) && false !== strpos( $out, 'Returns FAQ' ) );
check( 'no answer of another page', false === strpos( $out, 'Shipping Policy' ) );
check( 'the default heading', false !== strpos( $out, '>Verified answers</h2>' ) );
same( 'it read the index and the two answers', requested(), array( "$OWN/answers/index.json", "$OWN/answers/faq/returns.json", "$OWN/answers/policies/returns.json" ) );
foreach ( $GLOBALS['t']['requests'] as $request ) {
	check( 'a short timeout', $request[1]['timeout'] <= 5 );
	check( 'a size limit', $request[1]['limit_response_size'] > 0 && $request[1]['limit_response_size'] <= 4194304 );
	check( 'few redirects', $request[1]['redirection'] <= 3 );
}
same( 'a second pass over the same post adds nothing', OKF_Web_Answers::append_to_content( 'Our returns page.' ), 'Our returns page.' );

view( $RETURNS );
OKF_Web_Answers::append_to_content( 'Our returns page.' );
same( 'the next view reads nothing: it is kept', requested(), array() );

view( array( 'id' => 8 ) + $RETURNS );
$out = OKF_Web_Answers::append_to_content( 'Our shipping page.' );
check( 'another page gets its own answer', false !== strpos( $out, 'Shipping Policy' ) && false === strpos( $out, 'Return Policy' ) );
same( 'and reads only that answer', requested(), array( "$OWN/answers/policies/shipping.json" ) );

view( array( 'id' => 11 ) + $RETURNS );
same( 'a page with no answer is untouched', OKF_Web_Answers::append_to_content( 'About us.' ), 'About us.' );
same( 'and costs no request', requested(), array() );

// --- where it does not print -------------------------------------------------------
foreach ( array( 'singular', 'loop', 'main' ) as $missing ) {
	view( array( $missing => false ) + $RETURNS );
	same( "not $missing: untouched", OKF_Web_Answers::append_to_content( 'x' ), 'x' );
}
view( array( 'current' => 8 ) + $RETURNS );
same( 'another post inside the page (a widget, a related post): untouched', OKF_Web_Answers::append_to_content( 'x' ), 'x' );

// --- a product page ------------------------------------------------------------------
view( array( 'id' => 9, 'product' => true ) + $RETURNS );
same( 'a product\'s description is left alone', OKF_Web_Answers::append_to_content( 'Tent description.' ), 'Tent description.' );
ob_start();
OKF_Web_Answers::print_for_product();
$out = ob_get_clean();
check( 'the answers follow the product summary', false !== strpos( $out, 'Alpine Tent' ) );
ob_start();
OKF_Web_Answers::print_for_product();
same( 'once', ob_get_clean(), '' );
view( $RETURNS );
ob_start();
OKF_Web_Answers::print_for_product();
same( 'the product hook prints nothing on a page that is no product', ob_get_clean(), '' );

// --- the shortcode ---------------------------------------------------------------------
view( array( 'id' => 10 ) + $RETURNS );
same( 'content with the shortcode gets nothing appended', OKF_Web_Answers::append_to_content( 'Before [okf_web_answers] after.' ), 'Before [okf_web_answers] after.' );
check( 'the shortcode prints the page\'s answers', false !== strpos( OKF_Web_Answers::shortcode(), 'Placed Answer' ) );
view( array( 'singular' => false ) + $RETURNS );
same( 'the shortcode prints nothing on a list of posts', OKF_Web_Answers::shortcode(), '' );

// --- an answer that expired while it was kept -------------------------------------------
reset_world();
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true );
serve( $OWN, array( 'https://shop.example/returns' => array(
	'answers/a.json' => answer( 'https://shop.example/returns', 'Fresh One' ),
	'answers/b.json' => answer( 'https://shop.example/returns', 'Lapsed One', array( 'expires' => gmdate( 'Y-m-d\TH:i:s\Z', time() - 60 ) ) ),
) ) );
view( $RETURNS );
$out = OKF_Web_Answers::append_to_content( 'c' );
check( 'the current answer is shown', false !== strpos( $out, 'Fresh One' ) );
check( 'the lapsed one is not, though the source still lists it', false === strpos( $out, 'Lapsed One' ) );

// --- a source that cannot be read ---------------------------------------------------------
foreach ( array( 'error', 500, 404, 'not json', '"a string"', 'cut' ) as $reply ) {
	reset_world();
	$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true );
	serve( $OWN, $world );
	if ( 'cut' === $reply ) {
		// A whole, valid index that fills the size limit exactly: it may
		// have been cut there, so it is not used.
		$reply = str_pad( $GLOBALS['t']['web'][ "$OWN/answers/index.json" ], 4194304 );
	}
	$GLOBALS['t']['web'][ "$OWN/answers/index.json" ] = $reply;
	view( $RETURNS );
	$label = is_string( $reply ) && strlen( $reply ) > 40 ? 'a reply at the size limit' : json_encode( $reply );
	same( "index $label: the page is untouched", OKF_Web_Answers::append_to_content( 'c' ), 'c' );
	same( "index $label: one request", count( requested() ), 1 );
	view( $RETURNS );
	OKF_Web_Answers::append_to_content( 'c' );
	same( "index $label: the failure is remembered", requested(), array() );
	$GLOBALS['t']['clock'] += 301;
	view( $RETURNS );
	OKF_Web_Answers::append_to_content( 'c' );
	same( "index $label: and tried again after five minutes", count( requested() ), 1 );
}
reset_world();
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true );
serve( $OWN, $world );
$GLOBALS['t']['web'][ "$OWN/answers/faq/returns.json" ] = 'error';
view( $RETURNS );
$out = OKF_Web_Answers::append_to_content( 'c' );
check( 'one unreadable answer does not hide the other', false !== strpos( $out, 'Return Policy' ) && false === strpos( $out, 'Returns FAQ' ) );
reset_world();
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true );
serve( $OWN, $world );
$GLOBALS['t']['web'][ "$OWN/answers/faq/returns.json" ] = str_pad( $GLOBALS['t']['web'][ "$OWN/answers/faq/returns.json" ], 131072 );
view( $RETURNS );
$out = OKF_Web_Answers::append_to_content( 'c' );
check( 'an answer that fills its size limit is not used', false !== strpos( $out, 'Return Policy' ) && false === strpos( $out, 'Returns FAQ' ) );

// --- what is kept, and for how long ---------------------------------------------------------
$GLOBALS['t']['web'][ "$OWN/answers/policies/returns.json" ] = json_encode( answer( 'https://shop.example/returns', 'Return Policy, revised' ) );
$GLOBALS['t']['clock'] += 899;
view( $RETURNS );
check( 'within fifteen minutes the kept copy is shown', false !== strpos( OKF_Web_Answers::append_to_content( 'c' ), '>Return Policy<' ) );
$GLOBALS['t']['clock'] += 2;
view( $RETURNS );
check( 'after fifteen minutes it is read again', false !== strpos( OKF_Web_Answers::append_to_content( 'c' ), 'Return Policy, revised' ) );

// --- another source ---------------------------------------------------------------------------
$OTHER = 'https://bundles.example/stores/abc';
serve( $OTHER, array( 'https://shop.example/returns' => array( 'answers/r.json' => answer( 'https://shop.example/returns', 'From Elsewhere' ) ) ) );
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true, 'source' => $OTHER, 'heading' => '' );
view( $RETURNS );
$out = OKF_Web_Answers::append_to_content( 'c' );
check( 'a changed source shows its own answers at once', false !== strpos( $out, 'From Elsewhere' ) && false === strpos( $out, 'Return Policy' ) );
check( 'an empty heading prints none', false === strpos( $out, '<h2' ) );
same( 'read from the new address only', requested(), array( "$OTHER/answers/index.json", "$OTHER/answers/r.json" ) );
serve( $OTHER, array( 'https://shop.example/returns' => array( 'answers/r.json' => answer( 'https://other.example/returns', 'About Another Site' ) ) ) );
$GLOBALS['t']['transients'] = array();
view( $RETURNS );
same( 'an answer about another site\'s page is not shown here', OKF_Web_Answers::append_to_content( 'c' ), 'c' );
foreach ( array( 'http://bundles.example/x', 'https://bundles.example/x?y=1', 'ftp://bundles.example/x' ) as $bad ) {
	$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true, 'source' => $bad );
	view( $RETURNS );
	same( "a saved source of $bad is not read", OKF_Web_Answers::append_to_content( 'c' ), 'c' );
	same( "and nothing is requested for $bad", requested(), array() );
}

// --- saving the settings --------------------------------------------------------------------------
$saved = OKF_Web_Answers::sanitize( array( 'enabled' => '1', 'source' => ' https://bundles.example/stores/abc/ ', 'heading' => " <b>Good</b>\n answers " ) );
same( 'what is saved', $saved, array( 'enabled' => true, 'source' => 'https://bundles.example/stores/abc', 'heading' => 'Good answers', 'whole' => false, 'saved' => 1 ) );
same( 'no complaint', $GLOBALS['t']['errors'], array() );
$saved = OKF_Web_Answers::sanitize( array( 'source' => 'http://bundles.example/x' ) );
same( 'an address it will not read is not saved', $saved['source'], '' );
same( 'off unless ticked', $saved['enabled'], false );
same( 'and the page says so', $GLOBALS['t']['errors'], array( 'okf_web_answers_source' ) );
same( 'nonsense in, defaults out', OKF_Web_Answers::sanitize( 'x' ), array( 'enabled' => false, 'source' => '', 'heading' => '', 'whole' => false, 'saved' => 1 ) );
same( 'the whole fact sheet when ticked', OKF_Web_Answers::sanitize( array( 'whole' => '1' ) )['whole'], true );
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true, 'saved' => 4 );
same( 'every save counts, so the settings always change', OKF_Web_Answers::sanitize( array( 'enabled' => '1' ) )['saved'], 5 );
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true, 'saved' => 'x' );
same( 'a count that is not one starts again', OKF_Web_Answers::sanitize( array() )['saved'], 1 );
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true, 'saved' => -3 );
same( 'and so does one below nothing', OKF_Web_Answers::sanitize( array() )['saved'], 1 );
same( 'a long heading is cut', strlen( OKF_Web_Answers::sanitize( array( 'heading' => str_repeat( 'a', 500 ) ) )['heading'] ), 120 );

reset_world();
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true );
serve( $OWN, $world );
view( $RETURNS );
OKF_Web_Answers::append_to_content( 'c' );
OKF_Web_Answers::forget_index();
view( $RETURNS );
OKF_Web_Answers::append_to_content( 'c' );
same( 'saving the settings drops the kept index', requested(), array( "$OWN/answers/index.json" ) );

// --- what an answer shows -------------------------------------------------------------------------
reset_world();
serve( $OWN, $world );
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true );
view( $RETURNS );
$out = OKF_Web_Answers::append_to_content( 'c' );
check( 'by default: the title, the summary and who approved it', false !== strpos( $out, 'Return Policy' ) && false !== strpos( $out, 'Summary of Return Policy.' ) && false !== strpos( $out, 'Checked and approved by a named person on 5 August 2026.' ) );
check( 'by default: no section', false === strpos( $out, 'Text of Return Policy.' ) && false === strpos( $out, '<h4' ) );
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true, 'whole' => true );
view( $RETURNS );
$out = OKF_Web_Answers::append_to_content( 'c' );
check( 'ticked: the whole fact sheet', false !== strpos( $out, '<h4 class="okf-web-answer__section">Detail</h4><p>Text of Return Policy.</p>' ) && false !== strpos( $out, 'Summary of Return Policy.' ) );
view( array( 'singular' => true, 'loop' => true, 'main' => true, 'product' => true, 'id' => 9 ) );
ob_start();
OKF_Web_Answers::print_for_product();
$product = ob_get_clean();
check( 'a product\'s answer in the whole form too', false !== strpos( $product, 'Text of Alpine Tent.' ) );
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true );
view( array( 'singular' => true, 'loop' => true, 'main' => true, 'product' => true, 'id' => 9 ) );
ob_start();
OKF_Web_Answers::print_for_product();
$product = ob_get_clean();
check( 'and in the short one by default', false !== strpos( $product, 'Summary of Alpine Tent.' ) && false === strpos( $product, 'Text of Alpine Tent.' ) );

// --- a save reads everything again ------------------------------------------------------------------
reset_world();
serve( $OWN, $world );
$GLOBALS['t']['options']['okf_web_answers'] = array( 'enabled' => true );
view( $RETURNS );
OKF_Web_Answers::append_to_content( 'c' );
view( $RETURNS );
OKF_Web_Answers::append_to_content( 'c' );
same( 'unsaved, what was read is kept', requested(), array() );
$GLOBALS['t']['options']['okf_web_answers'] = OKF_Web_Answers::sanitize( array( 'enabled' => '1' ) );
view( $RETURNS );
OKF_Web_Answers::append_to_content( 'c' );
same( 'a save of the same settings reads the index and every answer again', requested(), array( "$OWN/answers/index.json", "$OWN/answers/faq/returns.json", "$OWN/answers/policies/returns.json" ) );

echo $failures ? "$failures of $checks checks FAILED\n" : "ok: $checks checks\n";
exit( $failures ? 1 : 0 );
