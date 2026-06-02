#!/usr/bin/env python3
"""
CRYPTO IA BOT v2 — Entry point com Painel PyQt6
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

os.makedirs("data",  exist_ok=True)
os.makedirs("logs",  exist_ok=True)
os.makedirs("gui",   exist_ok=True)

from PyQt6.QtWidgets import QApplication
from agents.brain_agent import BrainAgent
from gui.main_window    import MainWindow
from utils.logger       import get_logger

log = get_logger("Main")

if __name__ == "__main__":
    log.info("Iniciando CRYPTO IA BOT v2 com painel PyQt6...")

    # Instancia o brain (não chama .start() aqui — GUI controla)
    brain = BrainAgent.__new__(BrainAgent)
    BrainAgent.__init__(brain)

    app    = QApplication(sys.argv)
    app.setApplicationName("Crypto IA Bot v2")
    window = MainWindow(brain=brain)
    window.show()

    log.info("Painel aberto. Pressione START para iniciar o bot.")
    sys.exit(app.exec())