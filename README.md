# Shop-agent

A daily rule-based agent that searches Marktplaats, checks listing prices against
your limit, and emails matching listings. No OpenAI API key or API credits are
needed.

## Configure the search

Fill in `agent_config.json`:

```json
{
	"search_url": "https://www.marktplaats.nl/l/...",
	"max_price": 4250,
	"currency": "EUR",
	"alert_email": "you@example.com",
	"timezone": "Europe/Amsterdam",
	"run_hour": 9,
	"max_results": 40
}
```

The Marktplaats search URL applies the category, location, year, mileage, and
price filters. The script also checks each listing's displayed price against
`max_price` before emailing it.

## Configure GitHub and Gmail

The daily schedule runs at 09:00 in the configured timezone. Since GitHub
scheduled workflows use UTC, the workflow triggers at 07:00 and 08:00 UTC and
the script runs only during the local 09:00 window, accounting for daylight
saving time. Push this repository to GitHub and enable Actions. Add these
repository Actions secrets under
**Settings > Secrets and variables > Actions**:

- `GMAIL_ADDRESS` (the Gmail account that sends the alert)
- `GMAIL_APP_PASSWORD` (a Google app password, not your normal Gmail password)

The recipient address is configured in `agent_config.json`. The workflow also
supports manual runs from the GitHub Actions tab. It checks the first
`max_results` listings returned by Marktplaats. Automated access can be limited
by the site, and scheduled GitHub Actions runs may start a little after their
scheduled time.

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