<?php
/**
 * The reader: everything the plugin decides, with no WordPress in it.
 *
 * An OKF-Web bundle is published with an `answers/` folder: one JSON
 * file per fact sheet a named person approved, and `answers/index.json`
 * listing them by the page each is about. This class matches a page to
 * its answers, checks each answer before it is shown, and turns it into
 * HTML. It never trusts the source: an answer that is not in the shape
 * it knows, that no person approved, that has expired, or that is about
 * another page is not shown, and every string is escaped where it is
 * printed.
 *
 * @package OKF_Web_Answers
 */

if ( ! defined( 'ABSPATH' ) && ! defined( 'OKF_WEB_ANSWERS_TESTING' ) ) {
	exit;
}

/**
 * Pure functions over the published answers.
 */
final class OKF_Web_Answers_Reader {

	const ANSWER_SCHEMA = 'okf-web/answer/1';
	const INDEX_SCHEMA  = 'okf-web/answers-index/1';

	/** The most answers one page shows. */
	const MAX_ANSWERS = 5;
	/** The most sections one answer shows. */
	const MAX_SECTIONS = 12;
	const MAX_TITLE    = 200;
	const MAX_SUMMARY  = 1000;
	const MAX_HEADING  = 200;
	const MAX_TEXT     = 4000;
	/**
	 * How far ahead of this server's clock an approval may be dated: a
	 * store's clock that runs slow must not hide an answer approved a
	 * minute ago, and a date further ahead than this is not a date.
	 */
	const CLOCK_SLACK = 86400;

	/**
	 * A page address in the one form two spellings of it share: host in
	 * lower case, no scheme, no port a scheme implies, no query or
	 * fragment, no trailing slash. '' when it is not an http(s) address.
	 *
	 * @param mixed $url An address.
	 * @return string
	 */
	public static function normalize_url( $url ) {
		if ( ! is_string( $url ) || '' === $url ) {
			return '';
		}
		$parts = parse_url( trim( $url ) );
		if ( ! is_array( $parts ) || empty( $parts['host'] ) || empty( $parts['scheme'] ) ) {
			return '';
		}
		$scheme = strtolower( $parts['scheme'] );
		if ( 'http' !== $scheme && 'https' !== $scheme ) {
			return '';
		}
		$host = strtolower( $parts['host'] );
		if ( isset( $parts['port'] ) ) {
			$port    = (int) $parts['port'];
			$implied = ( 'http' === $scheme && 80 === $port ) || ( 'https' === $scheme && 443 === $port );
			if ( ! $implied ) {
				$host .= ':' . $port;
			}
		}
		$path = isset( $parts['path'] ) ? rtrim( $parts['path'], '/' ) : '';
		return $host . $path;
	}

	/**
	 * The address answers are read from, or '' when it is not one this
	 * plugin reads: https anywhere, plain http only on the site's own
	 * host. No query, no fragment, no credentials.
	 *
	 * @param mixed  $source    What the settings hold.
	 * @param string $site_host The site's own host.
	 * @return string
	 */
	public static function clean_source( $source, $site_host = '' ) {
		if ( ! is_string( $source ) ) {
			return '';
		}
		$source = trim( $source );
		$parts  = parse_url( $source );
		if ( ! is_array( $parts ) || empty( $parts['host'] ) || empty( $parts['scheme'] ) ) {
			return '';
		}
		if ( isset( $parts['user'] ) || isset( $parts['pass'] ) || isset( $parts['query'] ) || isset( $parts['fragment'] ) ) {
			return '';
		}
		$scheme = strtolower( $parts['scheme'] );
		$host   = strtolower( $parts['host'] );
		$own    = '' !== $site_host && strtolower( $site_host ) === $host;
		if ( 'https' !== $scheme && ! ( 'http' === $scheme && $own ) ) {
			return '';
		}
		$port = isset( $parts['port'] ) ? ':' . (int) $parts['port'] : '';
		$path = isset( $parts['path'] ) ? rtrim( $parts['path'], '/' ) : '';
		return $scheme . '://' . $host . $port . $path;
	}

	/**
	 * Whether a path from the index is one this plugin will fetch: a
	 * JSON file under answers/, with nothing that climbs out of it.
	 *
	 * @param mixed $path A path from the index.
	 * @return bool
	 */
	public static function safe_path( $path ) {
		if ( ! is_string( $path ) || strlen( $path ) > 300 ) {
			return false;
		}
		if ( 1 !== preg_match( '#^answers/[A-Za-z0-9][A-Za-z0-9._/-]*\.json$#', $path ) ) {
			return false;
		}
		return false === strpos( $path, '..' ) && false === strpos( $path, '//' ) && 'answers/index.json' !== $path;
	}

	/**
	 * The answer files the index lists for one page, in the index's own
	 * order; none when the index is not in the shape this plugin knows.
	 *
	 * @param mixed  $index    The decoded answers/index.json.
	 * @param string $page_url The page being shown.
	 * @return string[]
	 */
	public static function paths_for_page( $index, $page_url ) {
		$wanted = self::normalize_url( $page_url );
		if ( '' === $wanted || ! is_array( $index ) ) {
			return array();
		}
		if ( ! isset( $index['schema'] ) || self::INDEX_SCHEMA !== $index['schema'] ) {
			return array();
		}
		if ( ! isset( $index['pages'] ) || ! is_array( $index['pages'] ) ) {
			return array();
		}
		$found = array();
		foreach ( $index['pages'] as $page => $paths ) {
			if ( self::normalize_url( $page ) !== $wanted || ! is_array( $paths ) ) {
				continue;
			}
			foreach ( $paths as $path ) {
				if ( self::safe_path( $path ) && ! in_array( $path, $found, true ) ) {
					$found[] = $path;
				}
			}
		}
		return array_slice( $found, 0, self::MAX_ANSWERS );
	}

	/**
	 * How many pages an index lists answers for; -1 when it is not an
	 * index this plugin knows.
	 *
	 * @param mixed $index The decoded answers/index.json.
	 * @return int
	 */
	public static function page_count( $index ) {
		if ( ! is_array( $index ) || ! isset( $index['schema'] ) || self::INDEX_SCHEMA !== $index['schema'] ) {
			return -1;
		}
		return ( isset( $index['pages'] ) && is_array( $index['pages'] ) ) ? count( $index['pages'] ) : 0;
	}

	/**
	 * One answer, checked: the fields this plugin prints and nothing
	 * else, or null when it must not be shown. It must be in the known
	 * shape, approved by a named person, not expired, and about the
	 * page being shown.
	 *
	 * @param mixed  $raw      The decoded answer file.
	 * @param string $page_url The page being shown.
	 * @param int    $now      The time, as a Unix timestamp.
	 * @return array|null
	 */
	public static function clean_answer( $raw, $page_url, $now ) {
		if ( ! is_array( $raw ) || ! isset( $raw['schema'] ) || self::ANSWER_SCHEMA !== $raw['schema'] ) {
			return null;
		}
		$verified = ( isset( $raw['verified'] ) && is_array( $raw['verified'] ) ) ? $raw['verified'] : array();
		$tier     = isset( $verified['tier'] ) ? $verified['tier'] : '';
		if ( 'human-reviewed' !== $tier && 'human-attested' !== $tier ) {
			return null;
		}
		$verified_at = isset( $verified['at'] ) ? self::instant( $verified['at'] ) : null;
		if ( null === $verified_at || $verified_at > $now + self::CLOCK_SLACK ) {
			return null;
		}
		$expires = null;
		if ( isset( $raw['expires'] ) ) {
			$expires = self::instant( $raw['expires'] );
			if ( null === $expires || $expires <= $now ) {
				return null;
			}
		}
		$page = isset( $raw['page'] ) ? self::normalize_url( $raw['page'] ) : '';
		if ( '' === $page || self::normalize_url( $page_url ) !== $page ) {
			return null;
		}
		$title = self::text( isset( $raw['title'] ) ? $raw['title'] : '', self::MAX_TITLE );
		if ( '' === $title ) {
			return null;
		}
		$summary  = self::text( isset( $raw['summary'] ) ? $raw['summary'] : '', self::MAX_SUMMARY );
		$sections = array();
		if ( isset( $raw['sections'] ) && is_array( $raw['sections'] ) ) {
			foreach ( $raw['sections'] as $section ) {
				if ( ! is_array( $section ) ) {
					continue;
				}
				$text = self::text( isset( $section['text'] ) ? $section['text'] : '', self::MAX_TEXT );
				if ( '' === $text ) {
					continue;
				}
				$sections[] = array(
					'heading' => self::text( isset( $section['heading'] ) ? $section['heading'] : '', self::MAX_HEADING ),
					'text'    => $text,
				);
				if ( count( $sections ) >= self::MAX_SECTIONS ) {
					break;
				}
			}
		}
		if ( '' === $summary && ! $sections ) {
			return null;
		}
		$record = '';
		if ( isset( $raw['subjectOf'] ) && is_string( $raw['subjectOf'] ) && 1 === preg_match( '#^https?://#i', $raw['subjectOf'] ) ) {
			$record = $raw['subjectOf'];
		}
		return array(
			'title'       => $title,
			'summary'     => $summary,
			'sections'    => $sections,
			'tier'        => $tier,
			'verified_at' => $verified_at,
			'expires'     => $expires,
			'record'      => $record,
		);
	}

	/**
	 * Whether the first section already begins with the summary: a
	 * summary drafted from the text it sums up would be printed twice.
	 *
	 * @param array[] $sections The sections to be printed.
	 * @param string  $summary  The summary.
	 * @return bool
	 */
	public static function begins_with_summary( $sections, $summary ) {
		if ( ! is_array( $sections ) || ! $sections ) {
			return false;
		}
		$lead = rtrim( trim( (string) $summary ), ". \t" );
		$text = trim( (string) $sections[0]['text'] );
		return '' !== $lead && 0 === strncasecmp( $text, $lead, strlen( $lead ) );
	}

	/**
	 * Checked answers as HTML. Every string is escaped here, where it is
	 * printed. Returns '' when there is nothing to show. In the short
	 * form, the default, an answer is its title, its summary and who
	 * approved it when: on the page a fact sheet was written from, its
	 * sections repeat the page. The whole form adds every section, and
	 * leaves the summary out when the first section begins with it.
	 *
	 * @param array[]  $answers Answers from clean_answer().
	 * @param array    $labels  heading, reviewed, attested (each with %s for the date), record.
	 * @param callable $date    Formats a Unix timestamp as a date.
	 * @param bool     $whole   Every section too, not only the summary.
	 * @return string
	 */
	public static function render( $answers, $labels, $date, $whole = false ) {
		if ( ! is_array( $answers ) || ! $answers ) {
			return '';
		}
		$html = '<section class="okf-web-answers">';
		if ( ! empty( $labels['heading'] ) ) {
			$html .= '<h2 class="okf-web-answers__heading">' . esc_html( $labels['heading'] ) . '</h2>';
		}
		foreach ( $answers as $answer ) {
			$sections = $whole ? $answer['sections'] : array();
			$html    .= '<article class="okf-web-answer">';
			$html    .= '<h3 class="okf-web-answer__title">' . esc_html( $answer['title'] ) . '</h3>';
			if ( '' !== $answer['summary'] && ! self::begins_with_summary( $sections, $answer['summary'] ) ) {
				$html .= '<p class="okf-web-answer__summary">' . esc_html( $answer['summary'] ) . '</p>';
			}
			foreach ( $sections as $section ) {
				if ( '' !== $section['heading'] ) {
					$html .= '<h4 class="okf-web-answer__section">' . esc_html( $section['heading'] ) . '</h4>';
				}
				$html .= '<p>' . esc_html( $section['text'] ) . '</p>';
			}
			$label = 'human-reviewed' === $answer['tier'] ? $labels['reviewed'] : $labels['attested'];
			$when  = (string) call_user_func( $date, $answer['verified_at'] );
			$html .= '<p class="okf-web-answer__verified">' . esc_html( sprintf( $label, $when ) );
			if ( '' !== $answer['record'] && ! empty( $labels['record'] ) ) {
				$html .= ' <a href="' . esc_url( $answer['record'] ) . '" rel="nofollow">' . esc_html( $labels['record'] ) . '</a>';
			}
			$html .= '</p></article>';
		}
		return $html . '</section>';
	}

	/**
	 * A UTC instant ("2026-08-05T15:11:38Z", or a bare date) as a Unix
	 * timestamp; null when it is not one.
	 *
	 * @param mixed $value The instant as written.
	 * @return int|null
	 */
	public static function instant( $value ) {
		if ( ! is_string( $value ) ) {
			return null;
		}
		if ( 1 === preg_match( '/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?Z)?$/', $value, $m ) ) {
			if ( ! checkdate( (int) $m[2], (int) $m[3], (int) $m[1] ) ) {
				return null;
			}
			$hour   = isset( $m[4] ) ? (int) $m[4] : 0;
			$minute = isset( $m[5] ) ? (int) $m[5] : 0;
			$second = isset( $m[6] ) ? (int) $m[6] : 0;
			if ( $hour > 23 || $minute > 59 || $second > 60 ) {
				return null;
			}
			return gmmktime( $hour, $minute, $second, (int) $m[2], (int) $m[3], (int) $m[1] );
		}
		return null;
	}

	/**
	 * A string for printing: one line of plain text, no control
	 * characters, cut at a length. '' for anything that is not a string.
	 *
	 * @param mixed $value The value as read.
	 * @param int   $limit The most characters kept.
	 * @return string
	 */
	public static function text( $value, $limit ) {
		if ( ! is_string( $value ) ) {
			return '';
		}
		$value = preg_replace( '/[\x00-\x1F\x7F]+/u', ' ', $value );
		if ( null === $value ) {
			return '';
		}
		$value = trim( preg_replace( '/\s+/u', ' ', $value ) );
		if ( function_exists( 'mb_substr' ) ) {
			return mb_strlen( $value, 'UTF-8' ) > $limit ? rtrim( mb_substr( $value, 0, $limit, 'UTF-8' ) ) . '…' : $value;
		}
		return strlen( $value ) > $limit ? rtrim( substr( $value, 0, $limit ) ) . '…' : $value;
	}
}
