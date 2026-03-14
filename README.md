# DiceAlerts - Dice.com Job Monitor v1.0

Automated Dice.com job monitor for **Data Analyst, Data Engineer, CRM, and Automation** roles. Scrapes Dice.com search results, filters for relevance using a 280+ term dictionary, deduplicates, and sends real-time Discord notifications with salary info.

## Features

- **Dice.com scraper** with Next.js RSC payload parser
- **24 search keywords** covering Data/BI/CRM/Automation roles
- **280+ term relevance filter** to catch irrelevant results
- **Salary display** in Discord notifications (Dice includes salary data)
- **Async concurrent scraping** with aiohttp
- **Rate limiting** with exponential backoff and circuit breaker
- **Search strategy permutations** (workplace type variants)
- **Deduplication** with persistent JSON storage
- **Metrics tracking** and health monitoring
- **Discord alerts** for system failures
- **GitHub Actions CI/CD** with state caching
- **Windows Task Scheduler** and **Oracle Cloud** deployment

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/DiceAlerts.git
cd DiceAlerts

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure .env
# Edit .env and set DISCORD_WEBHOOK_URL

# 4. Run once
python monitor.py --once

# 5. Run continuously
python monitor.py
```

## Configuration

All settings are in `.env`:

| Variable | Default | Description |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | (required) | Discord webhook URL |
| `SEARCH_KEYWORDS` | 24 keywords | Comma-separated search terms |
| `SEARCH_LOCATION` | United States | Location filter |
| `SEARCH_POSTED_DATE` | ONE | ONE/THREE/SEVEN/ANY |
| `SEARCH_PAGE_SIZE` | 20 | Results per page (max 100) |
| `SEARCH_WORKPLACE_TYPES` | Remote,On-Site,Hybrid | Workplace filters |
| `TITLE_EXCLUDE` | intern,internship | Title exclusion words |

## Deployment

### Windows Task Scheduler
```powershell
powershell -ExecutionPolicy Bypass -File deploy\setup_windows_task.ps1
```

### Oracle Cloud (cron)
```bash
chmod +x deploy/setup.sh && ./deploy/setup.sh <git-repo-url>
```

### GitHub Actions
1. Add `DISCORD_WEBHOOK_URL` as a repository secret
2. The workflow runs every 5 minutes automatically

## Architecture

```
monitor.py          # Main pipeline orchestrator
scraper.py          # DiceScraper + Next.js RSC parser + DiceSearchStrategy
filters.py          # Relevance filter (280+ terms) + deduplication
notifier.py         # Discord webhook notifications (Dice red embeds)
config.py           # Environment-based configuration
metrics.py          # Run statistics and dashboard
alerting.py         # Multi-channel alerting system
health_monitor.py   # Automated health checks
```

## How It Works

1. **Search Strategy** generates queries: 24 keywords x 4 variants (base + 3 workplace types) = 96 queries
2. **DiceScraper** fetches Dice.com search pages and extracts job data from Next.js RSC payloads
3. **Relevance Filter** validates job titles against 280+ Data/Analytics terms
4. **User Filters** apply title exclusions, company filters, location filters
5. **Deduplication** checks against persistent `seen_jobs.json`
6. **Discord Notifier** sends rich embeds with salary info in Dice red
