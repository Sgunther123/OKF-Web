<?php
/**
 * Removing the plugin removes everything it kept: its settings and the
 * short-lived copies of what it read. It never wrote anything else.
 *
 * @package OKF_Web_Answers
 */

defined( 'WP_UNINSTALL_PLUGIN' ) || exit;

delete_option( 'okf_web_answers' );

global $wpdb;
// phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching
$wpdb->query(
	$wpdb->prepare(
		"DELETE FROM {$wpdb->options} WHERE option_name LIKE %s OR option_name LIKE %s",
		$wpdb->esc_like( '_transient_okf_web_answers_' ) . '%',
		$wpdb->esc_like( '_transient_timeout_okf_web_answers_' ) . '%'
	)
);
