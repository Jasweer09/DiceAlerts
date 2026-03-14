#!/usr/bin/env python3
"""
Health Monitor - Automated monitoring and alerting

Run this as a separate cron job or GitHub Action to monitor the main workflow.
Checks for failures, stale runs, and other issues, then sends alerts.

Usage:
    python health_monitor.py                    # Check health and alert if needed
    python health_monitor.py --check-github     # Also check GitHub Actions status
    python health_monitor.py --force-alert      # Send test alert
"""

import argparse
import logging
import os
import sys
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('health_monitor.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Import modules
try:
    from metrics import MetricsStore, check_health
    from alerting import (
        check_and_alert_health,
        check_github_actions_status,
        alert_github_actions_failure,
        send_alert,
        AlertSeverity
    )
    import config
except ImportError as e:
    logger.error(f"Failed to import required modules: {e}")
    logger.error("Make sure you're running from the project root directory")
    sys.exit(1)


def run_health_check():
    """Run comprehensive health check."""
    logger.info("=" * 70)
    logger.info("Starting health check...")
    logger.info("=" * 70)

    results = {
        'timestamp': datetime.utcnow().isoformat(),
        'metrics_check': None,
        'github_check': None,
        'alerts_sent': []
    }

    try:
        metrics_store = MetricsStore(config.METRICS_FILE)
        health = check_health(metrics_store)
        summary = metrics_store.get_summary()
        recent_stats = metrics_store.get_hourly_stats(24)

        results['metrics_check'] = {
            'status': health['status'],
            'issues': health.get('issues', []),
            'warnings': health.get('warnings', []),
            'total_runs': summary['total_runs'],
            'success_rate': summary['success_rate'],
            'jobs_scraped_24h': recent_stats['jobs_scraped'],
            'new_jobs_24h': recent_stats['new_jobs']
        }

        logger.info(f"Health Status: {health['status'].upper()}")
        logger.info(f"Success Rate: {summary['success_rate']:.1f}%")
        logger.info(f"Jobs (24h): {recent_stats['jobs_scraped']} scraped, {recent_stats['new_jobs']} new")

        check_and_alert_health(metrics_store)

    except Exception as e:
        logger.exception(f"Error during metrics health check: {e}")
        results['metrics_check'] = {'error': str(e)}

        send_alert(
            title="Health Monitor Failed",
            message=f"The health monitoring system encountered an error:\n\n{str(e)}",
            severity=AlertSeverity.CRITICAL
        )

    return results


def check_github_actions(
    repo_owner: str,
    repo_name: str,
    github_token: str = None
):
    """Check GitHub Actions workflow status."""
    logger.info("Checking GitHub Actions workflow status...")

    workflow_status = check_github_actions_status(
        repo_owner=repo_owner,
        repo_name=repo_name,
        github_token=github_token
    )

    logger.info(f"Workflow Status: {workflow_status.get('status', 'unknown').upper()}")

    if workflow_status.get('last_run'):
        logger.info(f"Last Run: {workflow_status['last_run']}")
        logger.info(f"Hours Ago: {workflow_status.get('hours_since_run', 0):.1f}h")

    alert_github_actions_failure(workflow_status)

    return workflow_status


def send_test_alert() -> None:
    """Send a test alert to verify alerting system works."""
    logger.info("Sending test alert...")

    from alerting import AlertConfig

    logger.info(f"Discord Alerts: {'Enabled' if AlertConfig.DISCORD_ALERT_ENABLED else 'Disabled'}")
    logger.info(f"Email Alerts: {'Enabled' if AlertConfig.EMAIL_ALERT_ENABLED else 'Disabled'}")
    logger.info(f"Custom Webhook: {'Enabled' if AlertConfig.CUSTOM_WEBHOOK_ENABLED else 'Disabled'}")

    results = send_alert(
        title="Test Alert - Dice Job Monitor",
        message=(
            "This is a test alert to verify the monitoring system is working correctly.\n\n"
            f"Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
            "If you received this alert, your alerting system is configured properly!"
        ),
        severity=AlertSeverity.INFO,
        fields=[
            {"name": "Test Type", "value": "System Test", "inline": True},
            {"name": "Status", "value": "SUCCESS", "inline": True},
            {"name": "Source", "value": "health_monitor.py", "inline": True}
        ]
    )

    sent_channels = [channel for channel, success in results.items() if success]
    failed_channels = [channel for channel, success in results.items() if not success]

    if sent_channels:
        logger.info(f"Test alert sent successfully to: {', '.join(sent_channels)}")
    else:
        logger.warning("No test alerts were sent - check your configuration!")

    if failed_channels:
        logger.warning(f"Failed to send to: {', '.join(failed_channels)}")


def main():
    """Main entry point for health monitor."""
    parser = argparse.ArgumentParser(
        description="Dice Job Monitor - Health Check & Alerting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python health_monitor.py                     # Run health check
  python health_monitor.py --check-github      # Include GitHub Actions check
  python health_monitor.py --force-alert       # Send test alert

Environment Variables (optional):
  GITHUB_REPOSITORY=owner/repo                 # GitHub repo for Actions monitoring
  GITHUB_TOKEN=ghp_xxx                         # GitHub token for API access

Alert Configuration:
  ALERT_MIN_SUCCESS_RATE=50.0                  # Alert if success rate < 50%
  ALERT_MAX_FAILURES=5                         # Alert after 5 consecutive failures
  ALERT_HOURS_NO_JOBS=24                       # Alert if no jobs for 24h
  ALERT_HOURS_NO_RUNS=1                        # Alert if no runs for 1h

  DISCORD_ALERT_ROLE_ID=123456                 # Discord role to tag on alerts

  EMAIL_ALERT_ENABLED=true                     # Enable email alerts
  SMTP_SERVER=smtp.gmail.com
  SMTP_PORT=587
  SMTP_USERNAME=your-email@gmail.com
  SMTP_PASSWORD=your-app-password
  ALERT_EMAIL_TO=admin@example.com,dev@example.com
        """
    )

    parser.add_argument(
        '--check-github',
        action='store_true',
        help='Check GitHub Actions workflow status'
    )

    parser.add_argument(
        '--force-alert',
        action='store_true',
        help='Send test alert to verify alerting system'
    )

    parser.add_argument(
        '--repo',
        type=str,
        default=os.getenv('GITHUB_REPOSITORY', ''),
        help='GitHub repository (owner/repo format)'
    )

    parser.add_argument(
        '--token',
        type=str,
        default=os.getenv('GITHUB_TOKEN', ''),
        help='GitHub token for API access'
    )

    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("Dice Job Monitor - Health Check Starting")
    logger.info("=" * 70)

    if args.force_alert:
        send_test_alert()
        logger.info("=" * 70)
        logger.info("Test alert complete")
        logger.info("=" * 70)
        return

    results = run_health_check()

    if args.check_github:
        if not args.repo:
            logger.warning(
                "GitHub Actions check requested but no repository specified. "
                "Set GITHUB_REPOSITORY environment variable or use --repo flag"
            )
        else:
            try:
                parts = args.repo.split('/')
                if len(parts) != 2:
                    logger.error(f"Invalid repository format: {args.repo}. Expected: owner/repo")
                else:
                    owner, repo = parts
                    results['github_check'] = check_github_actions(
                        repo_owner=owner,
                        repo_name=repo,
                        github_token=args.token or None
                    )
            except Exception as e:
                logger.exception(f"Error checking GitHub Actions: {e}")
                results['github_check'] = {'error': str(e)}

    logger.info("=" * 70)
    logger.info("Health Check Summary")
    logger.info("=" * 70)

    if results.get('metrics_check'):
        mc = results['metrics_check']
        if 'error' in mc:
            logger.error(f"Metrics Check: FAILED - {mc['error']}")
        else:
            logger.info(f"System Status: {mc['status'].upper()}")
            logger.info(f"   Success Rate: {mc['success_rate']:.1f}%")
            logger.info(f"   Total Runs: {mc['total_runs']}")
            logger.info(f"   Jobs (24h): {mc['jobs_scraped_24h']} scraped, {mc['new_jobs_24h']} new")

            if mc.get('issues'):
                logger.warning(f"   Issues: {', '.join(mc['issues'])}")
            if mc.get('warnings'):
                logger.warning(f"   Warnings: {', '.join(mc['warnings'])}")

    if results.get('github_check'):
        gc = results['github_check']
        if 'error' in gc:
            logger.error(f"GitHub Check: FAILED - {gc['error']}")
        else:
            logger.info(f"   Last Run: {gc.get('last_run', 'Unknown')}")
            logger.info(f"   Status: {gc.get('status', 'unknown').upper()}")

    logger.info("=" * 70)
    logger.info("Health check complete")
    logger.info("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nHealth check interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fatal error in health monitor: {e}")
        sys.exit(1)
