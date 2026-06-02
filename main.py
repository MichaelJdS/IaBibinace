#!/usr/bin/env python3
"""
CRYPTO IA BOT v2 — Entry point CLI (sem painel)
Para rodar headless / em servidor
"""
import sys
import os
import time
import signal
os.makedirs("data", exist_ok=True)
os.makedirs("logs", exist_ok=True)

from agents.brain_agent import BrainAgent
from utils.logger       import get_logger

log    = get_logger("Main")
brain  = None

def handle_signal(sig, frame):
    log.info(f"Sinal {sig} recebido. Encerrando bot...")
    if brain:
        brain.stop()
    sys.exit(0)

signal.signal(signal.SIGINT,  handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

if __name__ == "__main__":
    log.info("=" * 55)
    log.info("  CRYPTO IA BOT v2 — CLI MODE")
    log.info("=" * 55)

    import config
    log.info(f"Modo      : {config.TRADING_MODE.upper()}")
    log.info(f"Par       : {config.PRIMARY_PAIR}")
    log.info(f"Timeframe : {config.TF_PRIMARY}")
    log.info(f"SL/TP     : {config.STOP_LOSS_PCT*100:.1f}% / {config.TAKE_PROFIT_PCT*100:.1f}%")
    log.info("=" * 55)

    brain = BrainAgent()

    try:
        brain.start()       # Bloqueante — roda até Ctrl+C
    except KeyboardInterrupt:
        log.info("Interrompido pelo usuário")
        brain.stop()