# Shop-agent

A daily rule-based agent that searches Marktplaats and AutoScout24, checks car
listings against your filters, and emails matches. No OpenAI API key or API
credits are needed.

## Configure the search

Fill in `agent_config.json`:

```json
{
	"search_urls": {
		"Marktplaats": "https://www.marktplaats.nl/q/ford+fiesta+handgeschakeld/",
		"AutoScout24": "https://www.autoscout24.nl/lst?..."
	},
	"max_price": 4500,
	"min_year": 2012,
	"max_mileage": 131000,
	"make": "Ford",
	"model": "Fiesta",
	"transmission": "manual",
	"currency": "EUR",
	"padel_alert": {
		"search_urls": {
			"Tennis-Point.nl": "https://www.tennis-point.nl/search?q=coello%20motion",
			"Padelshop.com": "https://padelshop.com/search?q=coello%20motion&type=product"
		},
		"max_price": 150,
		"years": [2025, 2026]
	},
	"alert_email": "you@example.com",
	"timezone": "Europe/Amsterdam",
	"run_hour": 9,
	"max_results": 40
}
```

The car search targets manual Ford Fiesta listings first registered in 2012
or later, with no more than 131,000 km and a price no higher than the configured
maximum. Listings must identify the make, model, year, mileage, and manual
transmission in their title or listing details to qualify.

## Configure GitHub and Gmail

The daily schedule targets 09:00 in the configured timezone. Since GitHub
scheduled workflows use UTC, it triggers at 07:17 and 08:17 UTC; the script
selects the trigger matching the configured timezone's daylight-saving offset.
If GitHub starts the selected run late, it still searches instead of silently
skipping it. GitHub Actions schedules are best-effort and may be delayed or
dropped. Push this repository to GitHub and enable Actions. Add these
repository Actions secrets under
**Settings > Secrets and variables > Actions**:

- `GMAIL_ADDRESS` (the Gmail account that sends the alert)
- `GMAIL_APP_PASSWORD` (a Google app password, not your normal Gmail password)

The recipient address is configured in `agent_config.json`. The workflow also
supports manual runs from the GitHub Actions tab. It checks the first
`max_results` listings returned by Marktplaats. Automated access can be limited
by the site, and scheduled GitHub Actions runs may start a little after their
scheduled time. Matching listings are emailed as alerts; if neither search
finds a match, the agent sends a no-match status email instead.

## Run locally

Requires Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
export GMAIL_ADDRESS="..."
export GMAIL_APP_PASSWORD="..."
python daily_agent.py
```

The separate `price_agent.py` command checks one product page without OpenAI,
using structured product data or an unambiguous visible price when available.

The daily workflow also checks HEAD Coello Motion 2025/2026 rackets at
Tennis-Point.nl and Padelshop.com. It emails qualifying offers separately from
the car results when a listed price is strictly below EUR 150. Both retailers
serve the Netherlands; the alert excludes Coello Pro and accessories and only
matches listings whose title identifies model year 2025 or 2026.