"""
Monitoring & Metrics System

Tracks job statistics, notification success rates, and system health.
Provides dashboard for monitoring the Dice Job Monitor performance.

Industry Best Practices:
    - Time-series metrics storage
    - Success/failure tracking
    - Performance monitoring
    - Aggregated statistics
    - JSON-based persistence
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
#  METRICS STORAGE
# ============================================================

class MetricsStore:
    """Store and retrieve monitoring metrics.

    Metrics tracked:
        - Total runs
        - Jobs scraped per run
        - New jobs found per run
        - Notification success/failures
        - Errors encountered
        - Execution time
        - Rate limiting events
    """

    def __init__(self, metrics_file: str = "metrics.json"):
        """Initialize metrics store.

        Args:
            metrics_file: Path to metrics JSON file
        """
        self.metrics_file = Path(metrics_file)
        self.data = self._load_metrics()

    def _load_metrics(self) -> Dict[str, Any]:
        """Load metrics from file."""
        if not self.metrics_file.exists():
            return self._create_empty_metrics()

        try:
            with open(self.metrics_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load metrics: {e}")
            return self._create_empty_metrics()

    def _create_empty_metrics(self) -> Dict[str, Any]:
        """Create empty metrics structure."""
        return {
            "version": "1.0",
            "started_at": datetime.utcnow().isoformat(),
            "runs": [],
            "summary": {
                "total_runs": 0,
                "total_jobs_scraped": 0,
                "total_new_jobs": 0,
                "total_notifications_sent": 0,
                "total_errors": 0,
                "success_rate": 100.0,
                "avg_execution_time": 0.0,
                "last_successful_run": None,
                "last_error": None
            }
        }

    def save_metrics(self) -> None:
        """Save metrics to file with atomic write."""
        temp_file = self.metrics_file.with_suffix('.tmp')

        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)

            # Atomic rename
            temp_file.replace(self.metrics_file)
            logger.debug(f"Metrics saved to {self.metrics_file}")

        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")
            if temp_file.exists():
                temp_file.unlink()

    def record_run(
        self,
        jobs_scraped: int,
        new_jobs: int,
        notifications_sent: int,
        execution_time: float,
        success: bool = True,
        error: Optional[str] = None,
        rate_limited: bool = False
    ) -> None:
        """Record a monitoring run."""
        run_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "jobs_scraped": jobs_scraped,
            "new_jobs": new_jobs,
            "notifications_sent": notifications_sent,
            "execution_time": execution_time,
            "success": success,
            "error": error,
            "rate_limited": rate_limited
        }

        self.data["runs"].append(run_data)

        if len(self.data["runs"]) > 1000:
            self.data["runs"] = self.data["runs"][-1000:]

        self._update_summary(run_data)
        self.save_metrics()

        logger.info(
            f"Metrics recorded: {jobs_scraped} scraped, {new_jobs} new, "
            f"{notifications_sent} notified, {execution_time:.2f}s"
        )

    def _update_summary(self, run_data: Dict[str, Any]) -> None:
        """Update summary statistics."""
        summary = self.data["summary"]

        summary["total_runs"] += 1
        summary["total_jobs_scraped"] += run_data["jobs_scraped"]
        summary["total_new_jobs"] += run_data["new_jobs"]
        summary["total_notifications_sent"] += run_data["notifications_sent"]

        if not run_data["success"]:
            summary["total_errors"] += 1

        if summary["total_runs"] > 0:
            successful_runs = summary["total_runs"] - summary["total_errors"]
            summary["success_rate"] = (successful_runs / summary["total_runs"]) * 100

        total_time = sum(r["execution_time"] for r in self.data["runs"])
        summary["avg_execution_time"] = total_time / len(self.data["runs"])

        if run_data["success"]:
            summary["last_successful_run"] = run_data["timestamp"]
        else:
            summary["last_error"] = {
                "timestamp": run_data["timestamp"],
                "error": run_data["error"]
            }

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        return self.data["summary"]

    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent run history."""
        return self.data["runs"][-limit:]

    def get_runs_since(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get runs from the last N hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        recent_runs = []
        for run in reversed(self.data["runs"]):
            run_time = datetime.fromisoformat(run["timestamp"])
            if run_time >= cutoff:
                recent_runs.append(run)
            else:
                break

        return list(reversed(recent_runs))

    def get_hourly_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get statistics for the last N hours."""
        runs = self.get_runs_since(hours)

        if not runs:
            return {
                "period": f"Last {hours} hours",
                "total_runs": 0,
                "jobs_scraped": 0,
                "new_jobs": 0,
                "notifications_sent": 0,
                "success_rate": 0.0,
                "avg_execution_time": 0.0,
                "rate_limited_runs": 0
            }

        total_runs = len(runs)
        successful_runs = sum(1 for r in runs if r["success"])
        jobs_scraped = sum(r["jobs_scraped"] for r in runs)
        new_jobs = sum(r["new_jobs"] for r in runs)
        notifications = sum(r["notifications_sent"] for r in runs)
        exec_times = [r["execution_time"] for r in runs]
        rate_limited = sum(1 for r in runs if r.get("rate_limited", False))

        return {
            "period": f"Last {hours} hours",
            "total_runs": total_runs,
            "jobs_scraped": jobs_scraped,
            "new_jobs": new_jobs,
            "notifications_sent": notifications,
            "success_rate": (successful_runs / total_runs * 100) if total_runs > 0 else 0.0,
            "avg_execution_time": sum(exec_times) / len(exec_times) if exec_times else 0.0,
            "rate_limited_runs": rate_limited,
            "jobs_per_run": jobs_scraped / total_runs if total_runs > 0 else 0.0,
            "new_jobs_per_run": new_jobs / total_runs if total_runs > 0 else 0.0
        }


# ============================================================
#  DASHBOARD DISPLAY
# ============================================================

def print_dashboard(metrics_store: MetricsStore) -> None:
    """Print a formatted dashboard to console."""
    summary = metrics_store.get_summary()
    last_24h = metrics_store.get_hourly_stats(24)
    last_1h = metrics_store.get_hourly_stats(1)
    recent_runs = metrics_store.get_recent_runs(5)

    print("\n" + "=" * 80)
    print("DICE JOB MONITOR - DASHBOARD")
    print("=" * 80)

    print("\nOVERALL STATISTICS")
    print("-" * 80)
    print(f"  Total Runs:              {summary['total_runs']}")
    print(f"  Total Jobs Scraped:      {summary['total_jobs_scraped']:,}")
    print(f"  Total New Jobs Found:    {summary['total_new_jobs']:,}")
    print(f"  Total Notifications:     {summary['total_notifications_sent']:,}")
    print(f"  Success Rate:            {summary['success_rate']:.1f}%")
    print(f"  Avg Execution Time:      {summary['avg_execution_time']:.2f}s")
    print(f"  Total Errors:            {summary['total_errors']}")

    if summary['last_successful_run']:
        last_success = datetime.fromisoformat(summary['last_successful_run'])
        time_ago = datetime.utcnow() - last_success
        print(f"  Last Successful Run:     {time_ago.seconds // 60}m ago")

    print("\nLAST 24 HOURS")
    print("-" * 80)
    print(f"  Runs:                    {last_24h['total_runs']}")
    print(f"  Jobs Scraped:            {last_24h['jobs_scraped']:,} ({last_24h['jobs_per_run']:.1f} per run)")
    print(f"  New Jobs:                {last_24h['new_jobs']:,} ({last_24h['new_jobs_per_run']:.1f} per run)")
    print(f"  Notifications Sent:      {last_24h['notifications_sent']:,}")
    print(f"  Success Rate:            {last_24h['success_rate']:.1f}%")
    print(f"  Avg Execution Time:      {last_24h['avg_execution_time']:.2f}s")
    print(f"  Rate Limited:            {last_24h['rate_limited_runs']} runs")

    print("\nLAST HOUR")
    print("-" * 80)
    print(f"  Runs:                    {last_1h['total_runs']}")
    print(f"  Jobs Scraped:            {last_1h['jobs_scraped']:,}")
    print(f"  New Jobs:                {last_1h['new_jobs']:,}")
    print(f"  Notifications Sent:      {last_1h['notifications_sent']:,}")
    print(f"  Success Rate:            {last_1h['success_rate']:.1f}%")

    if recent_runs:
        print("\nRECENT RUNS (Last 5)")
        print("-" * 80)
        print(f"  {'Time':<20} {'Scraped':<10} {'New':<8} {'Notified':<10} {'Time(s)':<10} {'Status':<10}")
        print("-" * 80)

        for run in reversed(recent_runs):
            timestamp = datetime.fromisoformat(run['timestamp'])
            time_str = timestamp.strftime("%Y-%m-%d %H:%M")
            status = "OK" if run['success'] else "FAIL"

            print(f"  {time_str:<20} {run['jobs_scraped']:<10} {run['new_jobs']:<8} "
                  f"{run['notifications_sent']:<10} {run['execution_time']:<10.2f} {status:<10}")

            if run.get('error'):
                print(f"    ERROR: {run['error'][:60]}...")

    print("\n" + "=" * 80)
    print(f"Dashboard generated at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 80 + "\n")


# ============================================================
#  HEALTH CHECKS
# ============================================================

def check_health(metrics_store: MetricsStore) -> Dict[str, Any]:
    """Perform health check on the monitoring system."""
    recent_runs = metrics_store.get_runs_since(hours=1)

    health = {
        "status": "healthy",
        "issues": [],
        "warnings": []
    }

    if not recent_runs:
        health["status"] = "warning"
        health["warnings"].append("No runs in the last hour")

    if recent_runs:
        failures = sum(1 for r in recent_runs if not r["success"])
        if failures > len(recent_runs) * 0.5:
            health["status"] = "unhealthy"
            health["issues"].append(f"High failure rate: {failures}/{len(recent_runs)} runs failed")

    rate_limited = sum(1 for r in recent_runs if r.get("rate_limited", False))
    if rate_limited > 0:
        health["warnings"].append(f"Rate limiting detected in {rate_limited} runs")

    new_jobs = sum(r["new_jobs"] for r in recent_runs)
    if new_jobs == 0 and len(recent_runs) > 5:
        health["warnings"].append("No new jobs found in recent runs")

    return health
