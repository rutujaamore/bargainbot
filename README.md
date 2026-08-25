# BargainBot — Setup & Run

## What's in this build

Your original working project (Selenium scraping, RapidFuzz matching, the
trained Deal Score model, Groq LLM explanations) is unchanged. Added on top:

- **Expanded festival calendar** — 21 sale events instead of 9, still using
  honest low–high discount ranges (`festivals.py`)
- **Price alerts** — anyone can set a target price + email; a background
  job re-checks it every 6 hours and emails when the price drops there
  (`database.py` alerts table, `emailer.py`, `alert_checker.py`, `scheduler.py`)
- **Real price-history provenance badge** — shows how many *actual* scraped
  observations exist for a product ("Based on 3 real price records" /
  "Limited data" / "No history yet") instead of faking a chart

Nothing from mayurpatil's `requests`-based scraper or 90-day Prophet
forecast was carried over — see the earlier explanation for why.

## 1. Install dependencies

```bash
cd bargainbot
pip install -r requirements.txt
```

You also need **Google Chrome** installed on the machine (Selenium drives
real Chrome via `webdriver-manager`, which downloads the matching
chromedriver automatically on first run).

## 2. Train the Deal Score model (only needed once, or if you change the CSVs)

```bash
python train_deal_model.py
```

This reads `data/amazon_raw.csv`, `data/mobiles_raw.csv`, `data/laptop_raw.csv`
and writes `deal_model.json`. A `deal_model.json` is already included, so
you can skip this step unless you want to retrain.

## 3. (Optional) Set up email alerts

Open `email_config.py` and replace the two placeholder values:

```python
SENDER_EMAIL = "your_email@gmail.com"
SENDER_APP_PASSWORD = "your_16_char_app_password"
```

To get an App Password (Gmail no longer accepts your normal password for
this):
1. Go to https://myaccount.google.com/security
2. Turn on 2-Step Verification if it isn't already on
3. Search "App Passwords" in that same settings page
4. Create one for "Mail" → paste the 16-character code above

**If you skip this step**, the app still runs fine — alerts still save to
the database, `emailer.py` just detects the placeholder and skips sending
(prints a message to the terminal instead of crashing).

## 4. Run the app

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

On startup you'll see in the terminal:
```
[Scheduler] Started - checking pending alerts every 6 hour(s).
```
That confirms the background alert-checker thread is alive. It runs
silently every 6 hours from here on — no separate process to start.

## 5. Using it

- **Search a product** in the main search bar — works exactly as before.
- **Set a price alert** in the new card near the bottom of the page —
  enter a product name, your email, and a target price. You'll see a
  green confirmation banner once it's saved.
- To **test the alert flow quickly** without waiting 6 hours, temporarily
  lower `CHECK_INTERVAL_HOURS` in `scheduler.py` to something small (e.g.
  `0.02` for ~1 minute) while demoing, then set it back to `6` afterward.

## For your viva/demo

- Show a search working end-to-end (Amazon + Flipkart + Deal Score +
  Buy/Wait verdict) — this hasn't changed.
- Point out the **provenance badge** under the winning price — explain
  it's honest about real vs. limited data, no fabricated history.
- Set a price alert live, then (if you lowered the interval) show the
  terminal log firing `[AlertChecker]` and the email arriving.
- If asked "why not a 90-day forecast?" — you now have a ready, honest
  answer (see the explanation earlier in this conversation).

## File map (what's new vs. what's original)

| File | Status |
|---|---|
| `app.py` | modified — added `/set-alert` route, scheduler startup, history provenance |
| `database.py` | modified — added `alerts` table + related functions |
| `festivals.py` | modified — 9 → 21 events |
| `templates/index.html` | modified — alert form, provenance badge, banners |
| `emailer.py` | **new** |
| `alert_checker.py` | **new** |
| `scheduler.py` | **new** |
| `email_config.py` | **new** — fill in your Gmail App Password |
| everything else | unchanged from your original project |
