<?php
/**
 * Plugin Name:       OKF-Web Answers
 * Plugin URI:        https://github.com/sgunther123/okf-web
 * Description:       Shows the answers a person approved for your store on the pages they are about, read from your store's published OKF-Web bundle. It never changes your products, prices or pages.
 * Version:           0.1.0
 * Requires at least: 5.8
 * Requires PHP:      7.2
 * Author:            OKF-Web contributors
 * License:           Apache-2.0
 * License URI:       https://www.apache.org/licenses/LICENSE-2.0
 * Text Domain:       okf-web-answers
 *
 * What it does, in full: when it is switched on, it reads
 * `answers/index.json` from the address in its settings, finds the
 * answers listed for the page being shown, checks each one, and prints
 * them after the page's own content. It writes nothing to your posts,
 * products or prices, and stores only its own settings and a short-lived
 * copy of what it read.
 *
 * @package OKF_Web_Answers
 */

defined( 'ABSPATH' ) || exit;

define( 'OKF_WEB_ANSWERS_VERSION', '0.1.0' );

require_once __DIR__ . '/includes/class-okf-web-answers-reader.php';

/**
 * The plugin's WordPress side: settings, reading, and the three places
 * an answer can be printed.
 */
final class OKF_Web_Answers {

	const OPTION       = 'okf_web_answers';
	const CACHE_PREFIX = 'okf_web_answers_';
	/** How long what was read is kept before it is read again. */
	const CACHE_SECONDS = 900;
	/** How long a failed read is remembered, so a page never waits twice. */
	const MISS_SECONDS = 300;
	const INDEX_BYTES  = 4194304;
	const ANSWER_BYTES = 131072;
	const TIMEOUT      = 4;

	/**
	 * Posts whose answers were already printed in this request.
	 *
	 * @var array<int,bool>
	 */
	private static $printed = array();

	/**
	 * Hooks.
	 */
	public static function init() {
		add_action( 'admin_init', array( __CLASS__, 'register_settings' ) );
		add_action( 'admin_menu', array( __CLASS__, 'add_settings_page' ) );
		add_action( 'update_option_' . self::OPTION, array( __CLASS__, 'forget_index' ) );
		add_filter( 'plugin_action_links_' . plugin_basename( __FILE__ ), array( __CLASS__, 'action_links' ) );
		add_filter( 'the_content', array( __CLASS__, 'append_to_content' ), 20 );
		add_action( 'woocommerce_after_single_product_summary', array( __CLASS__, 'print_for_product' ), 12 );
		add_shortcode( 'okf_web_answers', array( __CLASS__, 'shortcode' ) );
	}

	/**
	 * The settings, with every key present. Off until switched on.
	 *
	 * @return array{enabled:bool,source:string,heading:string}
	 */
	public static function settings() {
		$saved = get_option( self::OPTION, array() );
		$saved = is_array( $saved ) ? $saved : array();
		return array(
			'enabled' => ! empty( $saved['enabled'] ),
			'source'  => isset( $saved['source'] ) && is_string( $saved['source'] ) ? $saved['source'] : '',
			'heading' => isset( $saved['heading'] ) && is_string( $saved['heading'] ) ? $saved['heading'] : __( 'Verified answers', 'okf-web-answers' ),
		);
	}

	/**
	 * The site's own host.
	 *
	 * @return string
	 */
	private static function site_host() {
		return (string) wp_parse_url( home_url(), PHP_URL_HOST );
	}

	/**
	 * Where answers are read from: the address in the settings, or the
	 * site's own bundle when none is set. '' when it is not an address
	 * this plugin reads.
	 *
	 * @return string
	 */
	public static function source() {
		$settings = self::settings();
		$source   = '' !== $settings['source'] ? $settings['source'] : home_url( '/.well-known/okf' );
		return OKF_Web_Answers_Reader::clean_source( $source, self::site_host() );
	}

	/**
	 * One JSON document from the source, or null. A reply that reached
	 * the size limit was cut, so it is not used.
	 *
	 * @param string $url   The address.
	 * @param int    $bytes The most bytes read.
	 * @return array|null
	 */
	private static function fetch( $url, $bytes ) {
		$response = wp_safe_remote_get(
			$url,
			array(
				'timeout'             => self::TIMEOUT,
				'redirection'         => 2,
				'limit_response_size' => $bytes,
				'headers'             => array( 'Accept' => 'application/json' ),
			)
		);
		if ( is_wp_error( $response ) || 200 !== (int) wp_remote_retrieve_response_code( $response ) ) {
			return null;
		}
		$body = (string) wp_remote_retrieve_body( $response );
		if ( strlen( $body ) >= $bytes ) {
			return null;
		}
		$data = json_decode( $body, true );
		return is_array( $data ) ? $data : null;
	}

	/**
	 * The cache name for an address. Keyed by the address, so a changed
	 * source never shows the old source's answers.
	 *
	 * @param string $url The address.
	 * @return string
	 */
	private static function cache_name( $url ) {
		return self::CACHE_PREFIX . md5( $url );
	}

	/**
	 * A document through the short-lived cache; a failed read is
	 * remembered for a few minutes too.
	 *
	 * @param string $url   The address.
	 * @param int    $bytes The most bytes read.
	 * @return array|null
	 */
	private static function read( $url, $bytes ) {
		$name = self::cache_name( $url );
		$kept = get_transient( $name );
		if ( is_array( $kept ) && array_key_exists( 'data', $kept ) ) {
			return is_array( $kept['data'] ) ? $kept['data'] : null;
		}
		$data = self::fetch( $url, $bytes );
		set_transient( $name, array( 'data' => $data ), null === $data ? self::MISS_SECONDS : self::CACHE_SECONDS );
		return $data;
	}

	/**
	 * The index, or null.
	 *
	 * @return array|null
	 */
	private static function index() {
		$source = self::source();
		return '' === $source ? null : self::read( $source . '/answers/index.json', self::INDEX_BYTES );
	}

	/**
	 * Drop the kept index, so a change of settings is read at once.
	 */
	public static function forget_index() {
		$source = self::source();
		if ( '' !== $source ) {
			delete_transient( self::cache_name( $source . '/answers/index.json' ) );
		}
	}

	/**
	 * The words printed around an answer.
	 *
	 * @return array<string,string>
	 */
	private static function labels() {
		$settings = self::settings();
		return array(
			'heading'  => $settings['heading'],
			/* translators: %s: the date a person approved the answer. */
			'reviewed' => __( 'Checked and approved by a named person on %s.', 'okf-web-answers' ),
			/* translators: %s: the date a person approved the answer. */
			'attested' => __( 'Approved by a named person on %s, as part of a batch.', 'okf-web-answers' ),
			'record'   => __( 'See the record', 'okf-web-answers' ),
		);
	}

	/**
	 * A date as the site writes dates.
	 *
	 * @param int $timestamp A Unix timestamp.
	 * @return string
	 */
	public static function format_date( $timestamp ) {
		return (string) wp_date( get_option( 'date_format', 'j F Y' ), (int) $timestamp, new DateTimeZone( 'UTC' ) );
	}

	/**
	 * The answers for one page as HTML, already escaped; '' when the
	 * plugin is off, the source cannot be read, or the page has none.
	 *
	 * @param string $page_url The page's address.
	 * @return string
	 */
	public static function answers_html( $page_url ) {
		$settings = self::settings();
		if ( ! $settings['enabled'] || ! is_string( $page_url ) || '' === $page_url ) {
			return '';
		}
		$source = self::source();
		$paths  = OKF_Web_Answers_Reader::paths_for_page( self::index(), $page_url );
		$now    = time();
		$shown  = array();
		foreach ( $paths as $path ) {
			$answer = OKF_Web_Answers_Reader::clean_answer( self::read( $source . '/' . $path, self::ANSWER_BYTES ), $page_url, $now );
			if ( null !== $answer ) {
				$shown[] = $answer;
			}
		}
		return OKF_Web_Answers_Reader::render( $shown, self::labels(), array( __CLASS__, 'format_date' ) );
	}

	/**
	 * After a page's or a post's own content.
	 *
	 * @param string $content The content.
	 * @return string
	 */
	public static function append_to_content( $content ) {
		if ( ! is_singular() || ! in_the_loop() || ! is_main_query() ) {
			return $content;
		}
		$post = get_post();
		if ( ! $post || get_queried_object_id() !== $post->ID || isset( self::$printed[ $post->ID ] ) ) {
			return $content;
		}
		if ( function_exists( 'is_product' ) && is_product() ) {
			return $content;
		}
		if ( has_shortcode( (string) $post->post_content, 'okf_web_answers' ) ) {
			return $content;
		}
		self::$printed[ $post->ID ] = true;
		return $content . self::answers_html( (string) get_permalink( $post ) );
	}

	/**
	 * On a WooCommerce product page, after the product's summary: a
	 * product with no long description has no content to follow.
	 */
	public static function print_for_product() {
		if ( ! function_exists( 'is_product' ) || ! is_product() ) {
			return;
		}
		$id = get_queried_object_id();
		if ( ! $id || isset( self::$printed[ $id ] ) ) {
			return;
		}
		$post = get_post( $id );
		if ( $post && has_shortcode( (string) $post->post_content, 'okf_web_answers' ) ) {
			return;
		}
		self::$printed[ $id ] = true;
		echo wp_kses_post( self::answers_html( (string) get_permalink( $id ) ) );
	}

	/**
	 * [okf_web_answers]: the page's answers where the shortcode stands.
	 *
	 * @return string
	 */
	public static function shortcode() {
		$id = get_queried_object_id();
		if ( ! is_singular() || ! $id ) {
			return '';
		}
		self::$printed[ $id ] = true;
		return self::answers_html( (string) get_permalink( $id ) );
	}

	/**
	 * Settings.
	 */
	public static function register_settings() {
		register_setting(
			'okf_web_answers',
			self::OPTION,
			array(
				'type'              => 'array',
				'sanitize_callback' => array( __CLASS__, 'sanitize' ),
				'default'           => array(),
			)
		);
	}

	/**
	 * What may be saved: a switch, an address this plugin reads, a heading.
	 *
	 * @param mixed $input What the form sent.
	 * @return array
	 */
	public static function sanitize( $input ) {
		$input   = is_array( $input ) ? $input : array();
		$typed   = isset( $input['source'] ) ? trim( (string) wp_unslash( $input['source'] ) ) : '';
		$source  = '' === $typed ? '' : OKF_Web_Answers_Reader::clean_source( esc_url_raw( $typed ), self::site_host() );
		$heading = isset( $input['heading'] ) ? sanitize_text_field( wp_unslash( $input['heading'] ) ) : '';
		if ( '' !== $typed && '' === $source ) {
			add_settings_error(
				self::OPTION,
				'okf_web_answers_source',
				__( 'That address was not saved: answers are read over https only, from an address with no question mark in it.', 'okf-web-answers' )
			);
		}
		return array(
			'enabled' => ! empty( $input['enabled'] ),
			'source'  => $source,
			'heading' => function_exists( 'mb_substr' ) ? mb_substr( $heading, 0, 120 ) : substr( $heading, 0, 120 ),
		);
	}

	/**
	 * The page under Settings.
	 */
	public static function add_settings_page() {
		add_options_page(
			__( 'OKF-Web Answers', 'okf-web-answers' ),
			__( 'OKF-Web Answers', 'okf-web-answers' ),
			'manage_options',
			'okf-web-answers',
			array( __CLASS__, 'render_settings_page' )
		);
	}

	/**
	 * A link to the settings beside the plugin's name.
	 *
	 * @param string[] $links The links so far.
	 * @return string[]
	 */
	public static function action_links( $links ) {
		$links[] = '<a href="' . esc_url( admin_url( 'options-general.php?page=okf-web-answers' ) ) . '">' . esc_html__( 'Settings', 'okf-web-answers' ) . '</a>';
		return $links;
	}

	/**
	 * The settings page: what the plugin does, its three settings, and
	 * what it can read right now.
	 */
	public static function render_settings_page() {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		$settings = self::settings();
		$source   = self::source();
		$count    = OKF_Web_Answers_Reader::page_count( self::index() );
		?>
		<div class="wrap">
			<h1><?php esc_html_e( 'OKF-Web Answers', 'okf-web-answers' ); ?></h1>
			<p><?php esc_html_e( 'When this is switched on, each page shows the answers a person approved for it, after the page\'s own content. The plugin reads them from the address below. It does not change your products, prices or pages, and it sends nothing about your shoppers anywhere.', 'okf-web-answers' ); ?></p>
			<form method="post" action="options.php">
				<?php settings_fields( 'okf_web_answers' ); ?>
				<table class="form-table" role="presentation">
					<tr>
						<th scope="row"><?php esc_html_e( 'Show answers', 'okf-web-answers' ); ?></th>
						<td><label><input type="checkbox" name="<?php echo esc_attr( self::OPTION ); ?>[enabled]" value="1" <?php checked( $settings['enabled'] ); ?>> <?php esc_html_e( 'Show approved answers on the pages they are about', 'okf-web-answers' ); ?></label></td>
					</tr>
					<tr>
						<th scope="row"><label for="okf-web-answers-source"><?php esc_html_e( 'Where to read them', 'okf-web-answers' ); ?></label></th>
						<td>
							<input type="url" class="regular-text code" id="okf-web-answers-source" name="<?php echo esc_attr( self::OPTION ); ?>[source]" value="<?php echo esc_attr( $settings['source'] ); ?>" placeholder="<?php echo esc_attr( home_url( '/.well-known/okf' ) ); ?>">
							<p class="description"><?php esc_html_e( 'The address of your store\'s published bundle. Leave it empty if the bundle is served by this site.', 'okf-web-answers' ); ?></p>
						</td>
					</tr>
					<tr>
						<th scope="row"><label for="okf-web-answers-heading"><?php esc_html_e( 'Heading', 'okf-web-answers' ); ?></label></th>
						<td>
							<input type="text" class="regular-text" id="okf-web-answers-heading" name="<?php echo esc_attr( self::OPTION ); ?>[heading]" value="<?php echo esc_attr( $settings['heading'] ); ?>" maxlength="120">
							<p class="description"><?php esc_html_e( 'Printed above the answers. Leave it empty for none.', 'okf-web-answers' ); ?></p>
						</td>
					</tr>
				</table>
				<?php submit_button(); ?>
			</form>
			<h2><?php esc_html_e( 'What can be read right now', 'okf-web-answers' ); ?></h2>
			<?php if ( '' === $source ) : ?>
				<p><?php esc_html_e( 'There is no address to read answers from.', 'okf-web-answers' ); ?></p>
			<?php elseif ( $count < 0 ) : ?>
				<p>
					<?php
					/* translators: %s: the address the plugin tried to read. */
					echo esc_html( sprintf( __( 'No answers could be read from %s. Nothing is shown on your pages until they can.', 'okf-web-answers' ), $source . '/answers/index.json' ) );
					?>
				</p>
			<?php else : ?>
				<p>
					<?php
					/* translators: 1: a number of pages, 2: the address read. */
					echo esc_html( sprintf( _n( 'Answers are listed for %1$d page at %2$s.', 'Answers are listed for %1$d pages at %2$s.', $count, 'okf-web-answers' ), $count, $source ) );
					?>
				</p>
			<?php endif; ?>
			<p><?php esc_html_e( 'What is read is kept for fifteen minutes. An answer is shown only if a named person approved it, it has not passed its expiry date, and it is about the page being viewed. To place the answers yourself, put the shortcode [okf_web_answers] where you want them.', 'okf-web-answers' ); ?></p>
		</div>
		<?php
	}
}

OKF_Web_Answers::init();
