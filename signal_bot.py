"""
BZU Signal Bot — ONE-SHOT версія для GitHub Actions.
Запускається кожні 15 хв через cron, перевіряє сигнал і виходить.
Не потрібен нескінченний loop — GitHub Actions сам перезапускає.
"""

import requests
import os
from datetime import datetime, timezone

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
INSTRUMENT  = "BZ-USDT-SWAP"
BAR         = "15m"
BALANCE     = float(os.environ.get("BALANCE", "5"))
LEVERAGE    = int(os.environ.get("LEVERAGE", "20"))
RISK_PCT    = 0.20
SL_PCT      = 0.018
TP1_PCT     = 0.030
TP2_PCT     = 0.055
EMA_FAST    = 9
EMA_SLOW    = 21
RSI_PERIOD  = 14
RSI_MIN     = 35
RSI_MAX     = 60
VOLUME_MULT = 1.2
# ─────────────────────────────────────────────────────────────


def get_candles():
    url = "https://www.okx.com/api/v5/market/candles"
    params = {"instId": INSTRUMENT, "bar": BAR, "limit": "50"}
    r = requests.get(url, params=params, timeout=10)
    data = r.json().get("data", [])
    candles = sorted(data, key=lambda x: int(x[0]))
    closes  = [float(c[4]) for c in candles]
    volumes = [float(c[5]) for c in candles]
    return closes, volumes


def ema(values, period):
    k = 2 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def rsi(closes, period=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)


def analyze(closes, volumes):
    ef    = ema(closes, EMA_FAST)[-1]
    es    = ema(closes, EMA_SLOW)[-1]
    price = closes[-1]
    rsi_v = rsi(closes, RSI_PERIOD)
    vol_avg = sum(volumes[-20:]) / 20
    vol_cur = volumes[-1]

    short_ok = (
        ef < es
        and RSI_MIN < rsi_v < RSI_MAX
        and price < es
        and vol_cur > vol_avg * VOLUME_MULT
    )
    long_ok = (
        ef > es
        and RSI_MIN < rsi_v < RSI_MAX
        and price > es
        and vol_cur > vol_avg * VOLUME_MULT
    )

    meta = {
        "price": round(price, 2),
        "ema9":  round(ef, 2),
        "ema21": round(es, 2),
        "rsi":   rsi_v,
        "vol_ratio": round(vol_cur / vol_avg, 2),
    }

    if short_ok:
        return "SHORT", meta
    if long_ok:
        return "LONG", meta
    return None, meta


def send_signal(signal, meta):
    price = meta["price"]
    now   = datetime.now(timezone.utc).strftime("%d.%m %H:%M UTC")

    if signal == "SHORT":
        sl  = round(price * (1 + SL_PCT), 2)
        tp1 = round(price * (1 - TP1_PCT), 2)
        tp2 = round(price * (1 - TP2_PCT), 2)
        emoji = "🔴"
        label = "SHORT · Продавай"
    else:
        sl  = round(price * (1 - SL_PCT), 2)
        tp1 = round(price * (1 + TP1_PCT), 2)
        tp2 = round(price * (1 + TP2_PCT), 2)
        emoji = "🟢"
        label = "LONG · Купуй"

    margin   = round(BALANCE * RISK_PCT, 2)
    position = round(margin * LEVERAGE, 2)

    msg = (
        f"{emoji} *{label}*  |  `{INSTRUMENT}`\n"
        f"🕐 {now}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💵 Вхід:      *${price}*\n"
        f"🛡 Стоп-лос:  *${sl}*\n"
        f"🎯 TP1:       *${tp1}*  _(закрий 50%)_\n"
        f"🎯 TP2:       *${tp2}*  _(решта)_\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"EMA9: {meta['ema9']}  EMA21: {meta['ema21']}\n"
        f"RSI: {meta['rsi']}   Обсяг: ×{meta['vol_ratio']}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Маржа: ${margin}  Позиція: ${position}  (×{LEVERAGE})\n"
        f"⚠️ Виставляй стоп в OKX одразу!"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }, timeout=10)
    print(f"[SENT] {signal} @ ${price}")


def send_status(meta):
    """Коротке щогодинне повідомлення — статус без сигналу."""
    now = datetime.now(timezone.utc)
    # Надсилаємо тільки в "круглі" години (00, 15, 30, 45 хвилин не рахуємо,
    # тобто тільки якщо хвилина < 16 і кожні 4 запуски = 1 год)
    # Простіше: надсилаємо тільки раз на годину (хвилина 0–2)
    if now.minute > 2:
        return

    price = meta.get("price", "—")
    rsi_v = meta.get("rsi", "—")
    msg = (
        f"⏳ *Немає сигналу*  |  {now.strftime('%H:%M UTC')}\n"
        f"BZU: `${price}`   RSI: {rsi_v}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "Markdown"
    }, timeout=10)
    print(f"[STATUS] No signal. Price=${price}")


if __name__ == "__main__":
    closes, volumes = get_candles()
    signal, meta = analyze(closes, volumes)

    if signal:
        send_signal(signal, meta)
    else:
        send_status(meta)
        print(f"[NO SIGNAL] ${meta.get('price')} RSI={meta.get('rsi')}")
