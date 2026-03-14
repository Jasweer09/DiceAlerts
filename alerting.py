"""
Alerting System for Dice Job Monitor

Sends alerts when:
- GitHub Actions workflow fails
- No jobs scraped for extended period
- Success rate drops below threshold
- System health degraded
- Rate limiting detected repeatedly

Supports:
- Discord alerts (using existing webhook)
- Email alerts (SMTP)
- Custom webhook alerts
"""

import logging
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List
import requests

logger = logging.getLogger(__name__)


# ============================================================
#  ALERT CONFIGURATION
# ============================================================

class AlertConfig:
    """Alert configuration from environment variables."""

    MIN_SUCCESS_RATE = float(os.getenv('ALERT_MIN_SUCCESS_RATE', '50.0'))
    MAX_CONSECUTIVE_FAILURES = int(os.getenv('ALERT_MAX_FAILURES', '5'))
    HOURS_WITHOUT_JOBS = int(os.getenv('ALERT_HOURS_NO_JOBS', '24'))
    HOURS_WITHOUT_RUNS = int(os.getenv('ALERT_HOURS_NO_RUNS', '1'))

    DISCORD_ALERT_ENABLED = os.getenv('DISCORD_ENABLED', 'false').lower() in ('true', '1', 'yes')
    DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')
    DISCORD_ALERT_ROLE_ID = os.getenv('DISCORD_ALERT_ROLE_ID', '')

    EMAIL_ALERT_ENABLED = os.getenv('EMAIL_ALERT_ENABLED', 'false').lower() in ('true', '1', 'yes')
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
    ALERT_EMAIL_TO = os.getenv('ALERT_EMAIL_TO', '')
    ALERT_EMAIL_FROM = os.getenv('ALERT_EMAIL_FROM', SMTP_USERNAME)

    CUSTOM_WEBHOOK_ENABLED = os.getenv('CUSTOM_WEBHOOK_ENABLED', 'false').lower() in ('true', '1', 'yes')
    CUSTOM_WEBHOOK_URL = os.getenv('CUSTOM_WEBHOOK_URL', '')


# ============================================================
#  ALERT SEVERITY LEVELS
# ============================================================

class AlertSeverity:
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ============================================================
#  DISCORD ALERTS
# ============================================================

def send_discord_alert(
    title: str,
    message: str,
    severity: str = AlertSeverity.WARNING,
    fields: Optional[List[Dict[str, Any]]] = None
) -> bool:
    """Send alert to Discord using webhook."""
    if not AlertConfig.DISCORD_ALERT_ENABLED:
        logger.debug("Discord alerts disabled")
        return False

    if not AlertConfig.DISCORD_WEBHOOK_URL:
        logger.error("Discord alerts enabled but webhook URL not set")
        return False

    colors = {
        AlertSeverity.INFO: 0x3498DB,
        AlertSeverity.WARNING: 0xF39C12,
        AlertSeverity.ERROR: 0xE74C3C,
        AlertSeverity.CRITICAL: 0x992D22
    }
    color = colors.get(severity, 0xF39C12)

    embed = {
        "title": f"{title}",
        "description": message,
        "color": color,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {
            "text": f"Dice Job Monitor • Severity: {severity.upper()}"
        }
    }

    if fields:
        embed["fields"] = fields

    payload = {"embeds": [embed]}

    if severity == AlertSeverity.CRITICAL and AlertConfig.DISCORD_ALERT_ROLE_ID:
        payload["content"] = f"<@&{AlertConfig.DISCORD_ALERT_ROLE_ID}> **CRITICAL ALERT**"

    try:
        response = requests.post(
            AlertConfig.DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=15
        )

        if response.status_code in (200, 204):
            logger.info(f"Discord alert sent: {title}")
            return True
        else:
            logger.error(f"Discord alert failed: HTTP {response.status_code}")
            return False

    except Exception as e:
        logger.error(f"Failed to send Discord alert: {e}")
        return False


# ============================================================
#  EMAIL ALERTS
# ============================================================

def send_email_alert(
    subject: str,
    body: str,
    severity: str = AlertSeverity.WARNING
) -> bool:
    """Send alert via email using SMTP."""
    if not AlertConfig.EMAIL_ALERT_ENABLED:
        logger.debug("Email alerts disabled")
        return False

    if not AlertConfig.SMTP_USERNAME or not AlertConfig.SMTP_PASSWORD:
        logger.error("Email alerts enabled but SMTP credentials not set")
        return False

    if not AlertConfig.ALERT_EMAIL_TO:
        logger.error("Email alerts enabled but ALERT_EMAIL_TO not set")
        return False

    try:
        recipients = [email.strip() for email in AlertConfig.ALERT_EMAIL_TO.split(',')]

        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[{severity.upper()}] {subject}"
        msg['From'] = AlertConfig.ALERT_EMAIL_FROM
        msg['To'] = ', '.join(recipients)

        severity_colors = {
            AlertSeverity.INFO: "#3498DB",
            AlertSeverity.WARNING: "#F39C12",
            AlertSeverity.ERROR: "#E74C3C",
            AlertSeverity.CRITICAL: "#992D22"
        }

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="background-color: {severity_colors.get(severity, '#F39C12')};
                        color: white; padding: 15px; border-radius: 5px;">
                <h2>Dice Job Monitor Alert</h2>
            </div>
            <div style="padding: 20px;">
                <p>{body.replace(chr(10), '<br>')}</p>
            </div>
            <div style="color: #666; font-size: 12px; padding: 15px; border-top: 1px solid #ddd;">
                <p>Severity: <strong>{severity.upper()}</strong></p>
                <p>Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
                <p>This is an automated alert from Dice Job Monitor</p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(AlertConfig.SMTP_SERVER, AlertConfig.SMTP_PORT) as server:
            server.starttls()
            server.login(AlertConfig.SMTP_USERNAME, AlertConfig.SMTP_PASSWORD)
            server.send_message(msg)

        logger.info(f"Email alert sent to {len(recipients)} recipient(s): {subject}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email alert: {e}")
        return False


# ============================================================
#  CUSTOM WEBHOOK ALERTS
# ============================================================

def send_custom_webhook_alert(
    title: str,
    message: str,
    severity: str = AlertSeverity.WARNING,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """Send alert to custom webhook endpoint."""
    if not AlertConfig.CUSTOM_WEBHOOK_ENABLED:
        logger.debug("Custom webhook alerts disabled")
        return False

    if not AlertConfig.CUSTOM_WEBHOOK_URL:
        logger.error("Custom webhook alerts enabled but URL not set")
        return False

    payload = {
        "title": title,
        "message": message,
        "severity": severity,
        "timestamp": datetime.utcnow().isoformat(),
        "source": "dice-job-monitor",
        "metadata": metadata or {}
    }

    try:
        response = requests.post(
            AlertConfig.CUSTOM_WEBHOOK_URL,
            json=payload,
            timeout=15
        )

        if response.status_code in (200, 201, 204):
            logger.info(f"Custom webhook alert sent: {title}")
            return True
        else:
            logger.error(f"Custom webhook alert failed: HTTP {response.status_code}")
            return False

    except Exception as e:
        logger.error(f"Failed to send custom webhook alert: {e}")
        return False


# ============================================================
#  UNIFIED ALERT DISPATCHER
# ============================================================

def send_alert(
    title: str,
    message: str,
    severity: str = AlertSeverity.WARNING,
    fields: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, bool]:
    """Send alert to all enabled channels."""
    results = {
        'discord': False,
        'email': False,
        'custom': False
    }

    if AlertConfig.DISCORD_ALERT_ENABLED:
        results['discord'] = send_discord_alert(title, message, severity, fields)

    if AlertConfig.EMAIL_ALERT_ENABLED:
        results['email'] = send_email_alert(title, message, severity)

    if AlertConfig.CUSTOM_WEBHOOK_ENABLED:
        results['custom'] = send_custom_webhook_alert(title, message, severity, metadata)

    sent_count = sum(results.values())
    total_count = sum([
        AlertConfig.DISCORD_ALERT_ENABLED,
        AlertConfig.EMAIL_ALERT_ENABLED,
        AlertConfig.CUSTOM_WEBHOOK_ENABLED
    ])

    if sent_count > 0:
        logger.info(f"Alert sent to {sent_count}/{total_count} enabled channels")
    else:
        logger.warning("No alerts sent - check configuration")

    return results


# ============================================================
#  HEALTH CHECK ALERTING
# ============================================================

def check_and_alert_health(metrics_store) -> None:
    """Check system health and send alerts if needed."""
    from metrics import check_health

    health = check_health(metrics_store)
    summary = metrics_store.get_summary()
    recent_stats = metrics_store.get_hourly_stats(24)

    if health['status'] == 'unhealthy':
        fields = [
            {"name": "Status", "value": "UNHEALTHY", "inline": True},
            {"name": "Total Runs", "value": str(summary['total_runs']), "inline": True},
            {"name": "Success Rate", "value": f"{summary['success_rate']:.1f}%", "inline": True}
        ]

        issues_text = "\n".join(f"- {issue}" for issue in health['issues'])

        send_alert(
            title="System Health Critical",
            message=f"The Dice Job Monitor is experiencing critical issues:\n\n{issues_text}",
            severity=AlertSeverity.CRITICAL,
            fields=fields
        )

    elif health['status'] == 'warning' and health['warnings']:
        fields = [
            {"name": "Status", "value": "WARNING", "inline": True},
            {"name": "Success Rate", "value": f"{summary['success_rate']:.1f}%", "inline": True},
            {"name": "Last 24h Runs", "value": str(recent_stats['total_runs']), "inline": True}
        ]

        warnings_text = "\n".join(f"- {warning}" for warning in health['warnings'])

        send_alert(
            title="System Health Warning",
            message=f"The Dice Job Monitor has warnings:\n\n{warnings_text}",
            severity=AlertSeverity.WARNING,
            fields=fields
        )

    hours_since_jobs = AlertConfig.HOURS_WITHOUT_JOBS
    if recent_stats['jobs_scraped'] == 0 and recent_stats['total_runs'] > 0:
        send_alert(
            title=f"No Jobs Scraped in {hours_since_jobs}+ Hours",
            message=(
                f"The monitor has run {recent_stats['total_runs']} times in the last "
                f"{hours_since_jobs} hours but found zero jobs. This could indicate:\n\n"
                "- Dice.com is rate-limiting the scraper\n"
                "- Your search criteria are too restrictive\n"
                "- Network connectivity issues\n"
                "- Dice.com has changed their HTML/RSC structure"
            ),
            severity=AlertSeverity.ERROR,
            fields=[
                {"name": "Runs (24h)", "value": str(recent_stats['total_runs']), "inline": True},
                {"name": "Jobs Found", "value": "0", "inline": True},
                {"name": "Rate Limited", "value": str(recent_stats['rate_limited_runs']), "inline": True}
            ]
        )

    if summary['success_rate'] < AlertConfig.MIN_SUCCESS_RATE and summary['total_runs'] >= 10:
        send_alert(
            title="Low Success Rate Detected",
            message=(
                f"Success rate has dropped to {summary['success_rate']:.1f}% "
                f"(threshold: {AlertConfig.MIN_SUCCESS_RATE}%)\n\n"
                f"Total errors: {summary['total_errors']}\n"
                f"Total runs: {summary['total_runs']}"
            ),
            severity=AlertSeverity.ERROR,
            fields=[
                {"name": "Success Rate", "value": f"{summary['success_rate']:.1f}%", "inline": True},
                {"name": "Errors", "value": str(summary['total_errors']), "inline": True},
                {"name": "Total Runs", "value": str(summary['total_runs']), "inline": True}
            ]
        )


# ============================================================
#  GITHUB ACTIONS MONITORING
# ============================================================

def check_github_actions_status(
    repo_owner: str,
    repo_name: str,
    workflow_name: str = "Dice Job Monitor",
    github_token: Optional[str] = None
) -> Dict[str, Any]:
    """Check GitHub Actions workflow status."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    try:
        url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/runs"
        params = {"per_page": 10, "status": "completed"}

        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()

        data = response.json()
        runs = data.get('workflow_runs', [])

        if not runs:
            return {
                'status': 'unknown',
                'message': 'No workflow runs found',
                'last_run': None
            }

        matching_runs = [r for r in runs if r.get('name') == workflow_name]

        if not matching_runs:
            return {
                'status': 'unknown',
                'message': f'No runs found for workflow: {workflow_name}',
                'last_run': None
            }

        latest_run = matching_runs[0]

        last_run_time = datetime.fromisoformat(latest_run['updated_at'].replace('Z', '+00:00'))
        hours_since_run = (datetime.now(last_run_time.tzinfo) - last_run_time).total_seconds() / 3600

        status_info = {
            'status': latest_run['conclusion'],
            'last_run': latest_run['updated_at'],
            'hours_since_run': hours_since_run,
            'run_number': latest_run['run_number'],
            'url': latest_run['html_url']
        }

        if latest_run['conclusion'] == 'failure':
            status_info['alert'] = 'Last workflow run failed'
        elif hours_since_run > AlertConfig.HOURS_WITHOUT_RUNS:
            status_info['alert'] = f'No runs in {hours_since_run:.1f} hours'

        return status_info

    except Exception as e:
        logger.error(f"Failed to check GitHub Actions status: {e}")
        return {
            'status': 'error',
            'message': str(e),
            'last_run': None
        }


def alert_github_actions_failure(workflow_status: Dict[str, Any]) -> None:
    """Send alert if GitHub Actions workflow has issues."""
    if 'alert' not in workflow_status:
        return

    alert_message = workflow_status['alert']

    if workflow_status['status'] == 'failure':
        send_alert(
            title="GitHub Actions Workflow Failed",
            message=(
                f"The Dice Job Monitor workflow has failed!\n\n"
                f"Run #{workflow_status.get('run_number', 'N/A')}\n"
                f"Time: {workflow_status.get('last_run', 'Unknown')}\n\n"
                f"Check the logs: {workflow_status.get('url', 'N/A')}"
            ),
            severity=AlertSeverity.CRITICAL,
            fields=[
                {"name": "Status", "value": "FAILED", "inline": True},
                {"name": "Run Number", "value": str(workflow_status.get('run_number', 'N/A')), "inline": True},
                {"name": "URL", "value": f"[View Logs]({workflow_status.get('url', '#')})", "inline": False}
            ]
        )

    elif 'No runs in' in alert_message:
        send_alert(
            title="GitHub Actions Not Running",
            message=(
                f"The Dice Job Monitor workflow hasn't run recently!\n\n"
                f"{alert_message}\n\n"
                f"This could mean:\n"
                f"- GitHub Actions are disabled\n"
                f"- The cron schedule is not working\n"
                f"- Repository secrets are misconfigured"
            ),
            severity=AlertSeverity.ERROR,
            fields=[
                {"name": "Last Run", "value": workflow_status.get('last_run', 'Unknown'), "inline": True},
                {"name": "Hours Ago", "value": f"{workflow_status.get('hours_since_run', 0):.1f}h", "inline": True}
            ]
        )
