# EIM V2 — Equity Intelligence Model

EIM V2 is a Flask web app for real-source ticker search and daily-price technical analysis. It supports Bursa Malaysia symbols (for example `1155.KL`, `1295.KL`, and `4243.KL`) and US symbols such as `NVDA`.

## What the backend does

- Requests search and daily chart history from a Yahoo-compatible public market-data endpoint.
- Calculates 20/50/200-day simple moving averages, RSI(14), MACD, 52-week high/low, and evidence-labelled nearby support/resistance pivots locally from the returned price history.
- Never synthesises a price or technical result. When the upstream source has no usable history, the API and UI state that data is unavailable.

The source is public and unofficial; it can change or throttle requests. For a regulated/production research workflow, replace it with a licensed provider.

## Local run

```text
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8765`.

## Render deployment

This repository includes `render.yaml`. In Render, create a new Blueprint or Web Service from the GitHub repository. Render will install `requirements.txt`, run Gunicorn, expose `/health`, and provide an HTTPS `onrender.com` URL.

No market-data key is stored in the repository. The app is ready for Safari Add to Home Screen: it includes a responsive mobile layout, a web manifest, an app title, theme metadata, and an icon.
