# BZU Signal Bot — Огляд коду та покращення

## ✅ Що хорошо

1. **Компактна структура** — логіка добре організована за функціями
2. **One-shot дизайн** — ідеально для GitHub Actions без нескінченного loop
3. **Правильна обробка часових поясів** — використовує UTC
4. **Налаштовуваність** — всі параметри винесені в константи
5. **Чистий Telegram формат** — красивий Markdown вивід

---

## ⚠️ Критичні проблеми та рекомендації

### 1. **Обробка помилок — КРИТИЧНО ВАЖЛИВО**

**Проблема:** Якщо OKX API не відповість або Telegram недоступний, скрипт впаде без логування.

**Рекомендація:**
```python
def get_candles():
    try:
        url = "https://www.okx.com/api/v5/market/candles"
        params = {"instId": INSTRUMENT, "bar": BAR, "limit": "50"}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()  # Піднімає HTTPError для поганих статус-кодів
        data = r.json().get("data", [])
        if not data:
            raise ValueError("No candle data received from OKX API")
        candles = sorted(data, key=lambda x: int(x[0]))
        closes  = [float(c[4]) for c in candles]
        volumes = [float(c[5]) for c in candles]
        return closes, volumes
    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch candles: {e}")
        raise
    except (ValueError, IndexError) as e:
        print(f"[ERROR] Invalid candle data format: {e}")
        raise
```

### 2. **Обробка Telegram помилок**

**Проблема:** Якщо Telegram недоступний, скрипт не поінформує про помилку.

**Рекомендація:**
```python
def send_signal(signal, meta):
    # ... підготовка повідомлення ...
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown"
        }, timeout=10)
        response.raise_for_status()
        print(f"[SENT] {signal} @ ${price}")
    except requests.RequestException as e:
        print(f"[ERROR] Failed to send Telegram message: {e}")
        raise
```

### 3. **Недостатність даних для RSI/EMA**

**Проблема:** Якщо отримаємо менше 50 свічок, EMA або RSI можуть дати неправильні результати.

**Рекомендація:**
```python
def analyze(closes, volumes):
    min_required = max(EMA_SLOW, RSI_PERIOD) + 10
    if len(closes) < min_required:
        print(f"[WARNING] Not enough data: {len(closes)} < {min_required}")
        return None, {"price": closes[-1] if closes else 0, "ema9": 0, "ema21": 0, "rsi": 0, "vol_ratio": 1}
    # ... решта коду ...
```

### 4. **Ділення на нуль у vol_avg**

**Проблема:** Якщо `vol_avg == 0`, буде помилка.

**Рекомендація:**
```python
def analyze(closes, volumes):
    # ...
    vol_avg = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1
    # Уникаємо ділення на нуль
    if vol_avg == 0:
        vol_avg = 1
    # ... решта коду ...
```

---

## 🔍 Інші питання

### 5. **Логування**

Поточно використовується простий `print()`. Для GitHub Actions рекомендується:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Замість print() використовувати:
logger.info(f"[SENT] {signal} @ ${price}")
logger.error(f"Failed to fetch candles: {e}")
```

### 6. **Безпека — не露ення токена у помилках**

Хоча токен передається як env var, в помилках він може з'явитися в логах GitHub Actions.

**Рекомендація:** Обережно обробляти винятки без деталей токена:
```python
except requests.RequestException as e:
    logger.error(f"Failed to send message: {e}")  # Без деталей токена
```

### 7. **Валідація мінімальної довжини свічок**

Функція `get_candles()` може повернути порожній список.

```python
def get_candles():
    # ... кодекс отримання ...
    if not closes or not volumes:
        raise ValueError("No candles data available")
    return closes, volumes
```

---

## 📋 Setup Checklist для GitHub Actions

### 1. Додайте Secrets у репозиторії

**Перейдіть:** Settings → Secrets and variables → Actions → New repository secret

Додайте ці secrets:

| Secret Name | Value | Обов'язково |
|------------|-------|-----------|
| `TELEGRAM_TOKEN` | Токен вашого Telegram бота | ✅ Так |
| `TELEGRAM_CHAT_ID` | ID чату для повідомлень | ✅ Так |
| `BALANCE` | Початковий баланс (за замовчуванням 5) | ❌ Опційно |
| `LEVERAGE` | Кратність плеча (за замовчуванням 20) | ❌ Опційно |

### 2. Переконайтеся, що `.github/workflows/signal-bot.yml` створений

Workflow файл повинен містити:
- Cron schedule `*/15 * * * *` (кожні 15 хвилин)
- Python 3.11+ environment
- Installation of `requests` library
- Передача environment variables для скрипту

---

## 📝 Рекомендовані покращення коду

### Модульність — винести Telegram клієнт у окремий клас:

```python
class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
    
    def send(self, message):
        """Надіслати повідомлення в Telegram з обробкою помилок"""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            response = requests.post(url, json={
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }, timeout=10)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"[ERROR] Failed to send Telegram: {e}")
            return False
```

### Добавити логування сигналів у файл:

```python
import json
from pathlib import Path

def log_signal(signal, meta):
    log_file = Path("signal_history.jsonl")
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signal": signal,
        "meta": meta
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")
```

---

## 🎯 Приоритет виправлень

| Рівень | Завдання | Вплив |
|--------|---------|--------|
| **🔴 Критичні** | Обробка помилок API та Telegram | Без цього скрипт буде критично падати |
| **🟡 Високі** | Валідація даних, логування | Поліпшує надійність та debug |
| **🟢 Низькі** | Класифікація коду, history logging | Nice-to-have for production |

---

## 📖 Статус implementation

- ✅ `signal_bot.py` — основний скрипт
- ✅ `requirements.txt` — залежності
- ❌ `.github/workflows/signal-bot.yml` — потребує ручного створення (проблема з правами доступу)
- ❌ `CODE_REVIEW.md` — документація

### Як вручну створити workflow:

1. На GitHub перейдіть до: **Actions** → **New workflow** → **set up a workflow yourself**
2. Назвіть файл: `signal-bot.yml`
3. Вставте YAML конфіг з розділу нижче

---

## 🔧 GitHub Actions Workflow YAML

```yaml
name: BZU Signal Bot

on:
  schedule:
    # Запускається кожні 15 хвилин
    - cron: '*/15 * * * *'
  # Також можна запустити вручну для тестування
  workflow_dispatch:

jobs:
  signal-bot:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      
      - name: Run BZU Signal Bot
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          BALANCE: ${{ secrets.BALANCE || '5' }}
          LEVERAGE: ${{ secrets.LEVERAGE || '20' }}
        run: python signal_bot.py
```

Дайте знати, якщо потрібна допомога з реалізацією!
