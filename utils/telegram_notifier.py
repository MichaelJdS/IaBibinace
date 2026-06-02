"""
Telegram Notifier — Alertas em tempo real no celular
Notifica: BUY, SELL, SL, TP, Trailing, Erros, Status diário
"""
import requests
import time
import threading
import re
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger

log = get_logger("Telegram")

# ── Configure aqui ────────────────────────────────────────────────────
BOT_TOKEN = "6674179143:AAEUv9Yzu0LCqAsg05tUEcptDm8bRXBih50"
CHAT_ID   = "5662495395"
# BOT_TOKEN deve estar no formato correto do BotFather:
# 123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# ─────────────────────────────────────────────────────────────────────


def _valid_bot_token(token: str) -> bool:
    return bool(re.match(r"^[0-9]+:[A-Za-z0-9_-]+$", token))

VALID_TOKEN = _valid_bot_token(BOT_TOKEN)
ENABLED     = bool(BOT_TOKEN and BOT_TOKEN != "SEU_TOKEN_AQUI" and VALID_TOKEN)
BASE_URL    = f"https://api.telegram.org/bot{BOT_TOKEN}" if ENABLED else ""

# Fila de mensagens para não bloquear o bot
_queue    = []
_lock     = threading.Lock()
_running  = False
_thread   = None


def start():
    global _running, _thread
    if not ENABLED:
        if not BOT_TOKEN or BOT_TOKEN == "SEU_TOKEN_AQUI":
            log.info("Telegram desabilitado — configure BOT_TOKEN e CHAT_ID")
        else:
            log.warning("Telegram desabilitado — BOT_TOKEN inválido. Deve estar no formato 123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        return
    _running = True
    _thread  = threading.Thread(target=_sender_loop, daemon=True, name="Telegram")
    _thread.start()
    log.info("Telegram Notifier iniciado ✅")
    _enqueue("🤖 <b>CRYPTO IA BOT v2 iniciado!</b>\nModo: DEMO | Par: BTCUSDT")


def stop():
    global _running
    _running = False


def _sender_loop():
    while _running:
        msgs = []
        with _lock:
            if _queue:
                msgs = _queue.copy()
                _queue.clear()
        for msg in msgs:
            _send(msg)
            time.sleep(0.3)  # evita flood
        time.sleep(1)


def _enqueue(msg: str):
    if not ENABLED:
        return
    with _lock:
        _queue.append(msg)


def _send(text: str) -> bool:
    try:
        r = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id"   : CHAT_ID,
                "text"      : text,
                "parse_mode": "HTML"
            },
            timeout=8
        )
        if r.status_code != 200:
            log.warning(f"Telegram erro {r.status_code}: {r.text[:100]}")
            return False
        return True
    except Exception as e:
        log.debug(f"Telegram falhou: {e}")
        return False


def fetch_updates(offset: int = None, timeout: int = 5) -> dict:
    """Retorna os updates do bot para ajudar a descobrir o chat_id."""
    if not ENABLED:
        return {"ok": False, "error": "Telegram disabled"}

    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset

    try:
        r = requests.get(f"{BASE_URL}/getUpdates", params=params, timeout=timeout + 2)
        return r.json() if r.status_code == 200 else {"ok": False, "status_code": r.status_code, "text": r.text}
    except Exception as e:
        log.debug(f"Telegram getUpdates falhou: {e}")
        return {"ok": False, "error": str(e)}


def print_updates():
    updates = fetch_updates()
    if not updates.get("ok"):
        print("Telegram getUpdates falhou:", updates)
        return
    for update in updates.get("result", []):
        print(update)


# ── Notificações específicas ──────────────────────────────────

def notify_buy(symbol: str, price: float, qty: float,
               sl: float, tp: float, confidence: int,
               regime: str, explanation: str = ""):
    rr = round((tp - price) / (price - sl), 2) if (price - sl) > 0 else 0
    msg = (
        f"🟢 <b>BUY — ENTRADA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Par:        <code>{symbol}</code>\n"
        f"Preço:      <b>${price:,.2f}</b>\n"
        f"Quantidade: <code>{qty:.6f}</code>\n"
        f"Stop Loss:  🔴 ${sl:,.2f}\n"
        f"Take Profit:🎯 ${tp:,.2f}\n"
        f"R:R:        {rr:.1f}x\n"
        f"Confiança:  {confidence}%\n"
        f"Regime:     {regime.replace('_',' ').upper()}\n"
    )
    if explanation:
        msg += f"━━━━━━━━━━━━━━━━━━━\n<i>{explanation[:200]}</i>"
    _enqueue(msg)
    log.info(f"📱 Telegram BUY enviado: {symbol} @ ${price:,.2f}")


def notify_sell(symbol: str, entry: float, exit_p: float,
                qty: float, pnl_usd: float, pnl_pct: float,
                reason: str, duration_sec: int = 0):
    icon    = "✅" if pnl_usd > 0 else "❌"
    result  = "WIN" if pnl_usd > 0 else "LOSS"
    dur_min = round(duration_sec / 60, 1)
    reason_map = {
        "tp"      : "🎯 Take Profit atingido",
        "sl"      : "🛑 Stop Loss atingido",
        "trailing": "📉 Trailing Stop",
        "signal"  : "📊 Sinal de saída",
        "manual"  : "✋ Saída manual"
    }
    reason_text = reason_map.get(reason, reason.upper())
    msg = (
        f"{icon} <b>SELL — {result}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Par:     <code>{symbol}</code>\n"
        f"Entrada: ${entry:,.2f}\n"
        f"Saída:   <b>${exit_p:,.2f}</b>\n"
        f"PnL:     <b>${pnl_usd:+.4f} ({pnl_pct:+.2f}%)</b>\n"
        f"Razão:   {reason_text}\n"
        f"Duração: {dur_min} min\n"
    )
    _enqueue(msg)
    log.info(f"📱 Telegram SELL enviado: PnL ${pnl_usd:+.4f}")


def notify_regime_change(old_regime: str, new_regime: str,
                          price: float, symbol: str):
    icons = {
        "trending_up"  : "🚀",
        "trending_down": "📉",
        "ranging"      : "➡️",
        "volatile"     : "⚡"
    }
    icon = icons.get(new_regime, "🔄")
    msg = (
        f"{icon} <b>MUDANÇA DE REGIME</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Par:    <code>{symbol}</code>\n"
        f"Antes:  {old_regime.replace('_',' ').upper()}\n"
        f"Agora:  <b>{new_regime.replace('_',' ').upper()}</b>\n"
        f"Preço:  ${price:,.2f}"
    )
    _enqueue(msg)


def notify_daily_summary(stats: dict, balance: float):
    wr    = stats.get("winrate", 0)
    pnl   = stats.get("total_pnl", 0)
    icon  = "📈" if pnl >= 0 else "📉"
    msg = (
        f"{icon} <b>RESUMO DIÁRIO</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Trades:  {stats.get('trades', 0)}\n"
        f"Wins:    ✅ {stats.get('wins', 0)}\n"
        f"Losses:  ❌ {stats.get('losses', 0)}\n"
        f"Winrate: <b>{wr:.1f}%</b>\n"
        f"PnL:     <b>${pnl:+.4f}</b>\n"
        f"Saldo:   ${balance:,.2f}"
    )
    _enqueue(msg)


def notify_error(component: str, error: str):
    msg = (
        f"⚠️ <b>ERRO — {component}</b>\n"
        f"<code>{error[:300]}</code>"
    )
    _enqueue(msg)


def notify_daily_loss_limit(pct_used: float, daily_pnl: float):
    msg = (
        f"🚨 <b>LIMITE DE PERDA DIÁRIA</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Utilizado: <b>{pct_used:.1f}%</b> do limite\n"
        f"PnL hoje:  ${daily_pnl:.4f}\n"
        f"Bot pausado até amanhã."
    )
    _enqueue(msg)


def notify_cooldown(reason: str, duration_sec: int):
    msg = (
        f"⏳ <b>COOLDOWN ATIVADO</b>\n"
        f"Razão:    {reason}\n"
        f"Duração:  {duration_sec}s"
    )
    _enqueue(msg)