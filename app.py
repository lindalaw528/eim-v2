from flask import Flask, request, jsonify, send_from_directory
import requests
from datetime import datetime, timezone

app=Flask(__name__, static_folder='static')

# Yahoo-compatible symbols: Bursa uses .KL (e.g. 2445.KL for KLSE ticker codes).
# Search endpoint resolves company names and tickers across markets.
H = {'User-Agent': 'Mozilla/5.0'}


class DataUnavailable(Exception):
    """Raised when the upstream market-data source has no usable daily data."""

def get_json(url, params=None):
    response = requests.get(url, params=params, headers=H, timeout=15)
    response.raise_for_status()
    return response.json()

def search(query):
    query = query.strip()
    if not query:
        return []
    data = get_json(
        'https://query1.finance.yahoo.com/v1/finance/search',
        {'q': query, 'quotesCount': 12, 'newsCount': 0},
    )
    output = []
    for quote in data.get('quotes', []):
        if quote.get('quoteType') in ('EQUITY', 'ETF') and quote.get('symbol'):
            output.append({
                'symbol': quote['symbol'],
                'name': quote.get('longname') or quote.get('shortname') or quote['symbol'],
                'exchange': quote.get('exchDisp') or quote.get('exchange'),
                'type': quote['quoteType'],
            })
    return output

def chart(symbol, rng='1y'):
    data = get_json(
        f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}',
        {'range': rng, 'interval': '1d', 'events': 'div,splits', 'includeAdjustedClose': 'true'},
    )
    chart_data = data.get('chart', {})
    result = chart_data.get('result') or []
    if not result:
        raise DataUnavailable(chart_data.get('error', {}).get('description') or 'No chart data returned.')

    result = result[0]
    quote_sets = result.get('indicators', {}).get('quote') or []
    timestamps = result.get('timestamp') or []
    if not quote_sets or not timestamps:
        raise DataUnavailable('No historical daily price data returned.')

    quote = quote_sets[0]
    rows = []
    for index, timestamp in enumerate(timestamps):
        values = {
            key: (quote.get(key) or [None] * len(timestamps))[index]
            if index < len(quote.get(key) or []) else None
            for key in ('open', 'high', 'low', 'close', 'volume')
        }
        if values['close'] is not None:
            rows.append({
                't': timestamp,
                'date': datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat(),
                **values,
            })
    if not rows:
        raise DataUnavailable('No usable daily closing prices returned.')
    return rows, result.get('meta', {})

def sma(values, period):
    return sum(values[-period:]) / period if len(values) >= period else None

def ema_series(values, period):
    if not values:
        return []
    multiplier = 2 / (period + 1)
    current = values[0]
    output = []
    for value in values:
        current = value * multiplier + current * (1 - multiplier)
        output.append(current)
    return output

def rsi(values, period=14):
    if len(values) <= period:
        return None
    gains, losses = [], []
    for index in range(-period, 0):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    average_gain, average_loss = sum(gains) / period, sum(losses) / period
    return 100 if average_loss == 0 else 100 - (100 / (1 + average_gain / average_loss))

def levels(rows):
    closes = [row['close'] for row in rows]
    highs = [row['high'] for row in rows if row['high'] is not None]
    lows = [row['low'] for row in rows if row['low'] is not None]
    price = closes[-1]
    window = rows[-90:]
    # Evidence-based pivot clusters: local extrema then nearest below/above current.
    pivots = []
    for index in range(2, len(window) - 2):
        neighbourhood = window[index - 2:index + 3]
        lows_in_range = [row['low'] for row in neighbourhood if row['low'] is not None]
        highs_in_range = [row['high'] for row in neighbourhood if row['high'] is not None]
        if window[index]['low'] is not None and lows_in_range and window[index]['low'] == min(lows_in_range):
            pivots.append(('S', window[index]['low'], window[index]['date']))
        if window[index]['high'] is not None and highs_in_range and window[index]['high'] == max(highs_in_range):
            pivots.append(('R', window[index]['high'], window[index]['date']))
    support = sorted([pivot for pivot in pivots if pivot[1] < price], key=lambda pivot: price - pivot[1])
    resistance = sorted([pivot for pivot in pivots if pivot[1] > price], key=lambda pivot: pivot[1] - price)
    def distinct(items):
        output = []
        for pivot in items:
            if not output or abs(pivot[1] - output[-1][1]) / price > 0.015:
                output.append(pivot)
            if len(output) == 2:
                break
        return output

    support, resistance = distinct(support), distinct(resistance)
    ema12, ema26 = ema_series(closes, 12), ema_series(closes, 26)
    return {
        'price': price,
        'sma20': sma(closes, 20),
        'sma50': sma(closes, 50),
        'sma200': sma(closes, 200),
        'rsi14': rsi(closes),
        'macd': ema12[-1] - ema26[-1] if ema12 and ema26 else None,
        'support': [
            {'price': pivot[1], 'basis': f'90-day local swing low ({pivot[2]})'}
            for pivot in support
        ],
        'resistance': [
            {'price': pivot[1], 'basis': f'90-day local swing high ({pivot[2]})'}
            for pivot in resistance
        ],
        'high52': max(highs[-252:]) if highs else None,
        'low52': min(lows[-252:]) if lows else None,
    }

@app.get('/')
def home():
    return send_from_directory('static', 'index.html')


@app.get('/health')
def health():
    return jsonify({'status': 'ok'})


@app.get('/api/search')
def api_search():
    try:
        return jsonify(search(request.args.get('q', '')))
    except requests.RequestException:
        return jsonify({'error': 'DATA NOT RELIABLY AVAILABLE — search source could not be reached.'}), 502
    except (ValueError, KeyError, TypeError):
        return jsonify({'error': 'DATA NOT RELIABLY AVAILABLE — search source returned an invalid response.'}), 502


@app.get('/api/stock/<path:symbol>')
def api_stock(symbol):
    try:
        rows, meta = chart(symbol, '2y')
        technical = levels(rows)
        previous_close = rows[-2]['close'] if len(rows) > 1 else None
        price = technical['price']
        change = ((price - previous_close) / previous_close * 100) if previous_close else None
        return jsonify({
            'symbol': symbol,
            'name': meta.get('longName') or meta.get('shortName') or symbol,
            'currency': meta.get('currency'),
            'exchange': meta.get('exchangeName'),
            'marketState': meta.get('marketState'),
            'lastTradingDate': rows[-1]['date'],
            'responseGeneratedAt': datetime.now(timezone.utc).isoformat(),
            'price': price,
            'changePct': change,
            'technical': technical,
            'history': rows[-260:],
        })
    except (DataUnavailable, requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return jsonify({'error': 'DATA NOT RELIABLY AVAILABLE — the source did not return usable daily price history for this symbol.'}), 502


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8765, debug=False)
