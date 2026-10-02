# Shop-agent

A daily agent that searches Marktplaats, checks listing prices against your limit,
uses an AI model to evaluate your car criteria, and emails matching listings.

## Configure the search

Fill in `agent_config.json`:

```json
{
	"search_url": "https://www.marktplaats.nl/l/...",
	"max_price": 4250,
	"currency": "EUR",
	"criteria": "Required condition, model, location, or other requirements",
	"alert_email": "you@example.com",
	"timezone": "Europe/Amsterdam",
	"run_hour": 9,
	"max_results": 40
}
```

Only listings priced at or below `max_price` are considered. The AI evaluates
the descriptive criteria; the price limit is checked in code.

## Configure GitHub and Gmail

The daily schedule runs at 09:00 in the configured timezone. Since GitHub
scheduled workflows use UTC, the workflow triggers at 07:00 and 08:00 UTC and
the script runs only during the local 09:00 window, accounting for daylight
saving time. Push this repository to GitHub and enable Actions. Add these
repository Actions secrets under
**Settings > Secrets and variables > Actions**:

- `OPENAI_API_KEY`
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
export OPENAI_API_KEY="..."
export GMAIL_ADDRESS="..."
export GMAIL_APP_PASSWORD="..."
python daily_agent.py
```

The separate `price_agent.py` command remains available for checking one product
page directly.