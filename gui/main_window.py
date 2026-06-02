"""
CRYPTO IA BOT v2 — Painel PyQt6 Principal
6 abas: Trading | Market | AI Council | News | Risk | Research
"""
import sys
import time
import threading
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QTextEdit, QTableWidget,
    QTableWidgetItem, QGridLayout, QFrame, QSplitter,
    QHeaderView, QGroupBox, QProgressBar, QComboBox, QSpinBox,
    QCheckBox, QScrollArea
)
from PyQt6.QtCore    import Qt, QTimer, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui     import QColor, QFont, QPalette, QTextCursor

import pyqtgraph as pg
import numpy as np
import config

# ── Paleta de cores (Dark Mode) ───────────────────────────────

DARK_BG    = "#0d0f14"
DARK_SURF  = "#12151c"
DARK_CARD  = "#181c26"
DARK_BORD  = "#252a38"
GREEN      = "#00e676"
RED        = "#ff1744"
YELLOW     = "#ffd600"
CYAN       = "#00e5ff"
PURPLE     = "#d500f9"
ORANGE     = "#ff9100"
TEXT_PRI   = "#e8eaf0"
TEXT_MUT   = "#7b849a"

STYLE_GLOBAL = f"""
QMainWindow, QWidget  {{ background: {DARK_BG}; color: {TEXT_PRI}; font-family: 'Consolas','Courier New',monospace; font-size: 12px; }}
QTabWidget::pane      {{ border: 1px solid {DARK_BORD}; background: {DARK_SURF}; }}
QTabBar::tab          {{ background: {DARK_CARD}; color: {TEXT_MUT}; padding: 8px 18px; border: 1px solid {DARK_BORD}; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {DARK_SURF}; color: {CYAN}; border-bottom: 2px solid {CYAN}; }}
QTabBar::tab:hover    {{ color: {TEXT_PRI}; }}
QGroupBox             {{ border: 1px solid {DARK_BORD}; border-radius: 6px; margin-top: 10px; padding-top: 10px; font-weight: bold; color: {TEXT_MUT}; }}
QGroupBox::title      {{ subcontrol-origin: margin; left: 10px; color: {CYAN}; }}
QPushButton           {{ background: {DARK_CARD}; color: {TEXT_PRI}; border: 1px solid {DARK_BORD}; border-radius: 5px; padding: 6px 16px; font-weight: bold; }}
QPushButton:hover     {{ background: #1e2535; border-color: {CYAN}; color: {CYAN}; }}
QPushButton:pressed   {{ background: #0a0e18; }}
QPushButton#btn_start {{ background: #00301a; color: {GREEN}; border-color: {GREEN}; }}
QPushButton#btn_start:hover {{ background: #00451f; }}
QPushButton#btn_stop  {{ background: #2a0010; color: {RED}; border-color: {RED}; }}
QPushButton#btn_stop:hover  {{ background: #400018; }}
QTextEdit             {{ background: {DARK_CARD}; color: #b0bec5; border: 1px solid {DARK_BORD}; border-radius: 4px; font-size: 11px; }}
QTableWidget          {{ background: {DARK_CARD}; color: {TEXT_PRI}; border: 1px solid {DARK_BORD}; gridline-color: {DARK_BORD}; }}
QTableWidget::item    {{ padding: 4px 8px; }}
QTableWidget::item:selected {{ background: #1a2540; }}
QHeaderView::section  {{ background: {DARK_SURF}; color: {CYAN}; border: 1px solid {DARK_BORD}; padding: 5px; font-weight: bold; }}
QProgressBar          {{ background: {DARK_CARD}; border: 1px solid {DARK_BORD}; border-radius: 4px; text-align: center; color: {TEXT_PRI}; height: 18px; }}
QProgressBar::chunk   {{ background: {CYAN}; border-radius: 3px; }}
QComboBox             {{ background: {DARK_CARD}; color: {TEXT_PRI}; border: 1px solid {DARK_BORD}; border-radius: 4px; padding: 4px 8px; }}
QScrollBar:vertical   {{ background: {DARK_BG}; width: 8px; }}
QScrollBar::handle:vertical {{ background: {DARK_BORD}; border-radius: 4px; min-height: 20px; }}
QLabel#price_big      {{ font-size: 32px; font-weight: bold; color: {GREEN}; }}
QLabel#label_section  {{ color: {CYAN}; font-weight: bold; font-size: 11px; }}
"""

# ── Widget de KPI ─────────────────────────────────────────────

class KPICard(QFrame):
    def __init__(self, title: str, value: str = "---", color: str = CYAN):
        super().__init__()
        self.setStyleSheet(f"""
            QFrame {{ background: {DARK_CARD}; border: 1px solid {DARK_BORD};
                     border-radius: 8px; padding: 8px; }}
        """)
        self.setMinimumWidth(130)
        layout   = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)
        self.lbl_title = QLabel(title.upper())
        self.lbl_title.setStyleSheet(f"color: {TEXT_MUT}; font-size: 10px; letter-spacing: 1px;")
        self.lbl_value = QLabel(value)
        self.lbl_value.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)

    def update_value(self, value: str, color: str = None):
        self.lbl_value.setText(value)
        if color:
            self.lbl_value.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")

# ── Thread do Bot ─────────────────────────────────────────────

class BotThread(QThread):
    log_signal     = pyqtSignal(str)
    update_signal  = pyqtSignal(dict)

    def __init__(self, brain_ref):
        super().__init__()
        self.brain = brain_ref
        self._running = False

    def run(self):
        self._running = True
        self.log_signal.emit("🚀 Bot iniciado!")
        try:
            self.brain.start()
        except Exception as e:
            self.log_signal.emit(f"❌ Erro no bot: {e}")

    def stop(self):
        self._running = False
        if self.brain:
            self.brain.stop()

# ── Janela Principal ──────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, brain=None):
        super().__init__()
        self.brain   = brain
        self.bot_thread = None

        self.setWindowTitle(f"🤖 CRYPTO IA BOT v2  |  {config.PRIMARY_PAIR}  |  {config.TRADING_MODE.upper()}")
        self.setMinimumSize(1400, 860)
        self.setStyleSheet(STYLE_GLOBAL)

        self._build_ui()
        self._start_refresh_timer()

    # ── Construção da UI ──────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root    = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Header
        root.addWidget(self._build_header())
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_trading_tab(),  "📊  TRADING")
        self.tabs.addTab(self._build_market_tab(),   "📈  MARKET")
        self.tabs.addTab(self._build_ai_tab(),       "🧠  AI COUNCIL")
        self.tabs.addTab(self._build_news_tab(),     "📰  NEWS & TRENDS")
        self.tabs.addTab(self._build_risk_tab(),     "🛡️  RISK")
        self.tabs.addTab(self._build_research_tab(), "🔬  RESEARCH")
        root.addWidget(self.tabs)
        # Status bar
        self.status_lbl = QLabel("● Aguardando início...")
        self.status_lbl.setStyleSheet(f"color: {YELLOW}; padding: 4px 10px;")
        root.addWidget(self.status_lbl)

    def _build_header(self) -> QWidget:
        w   = QWidget()
        w.setStyleSheet(f"background: {DARK_SURF}; border-radius: 8px;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(14, 8, 14, 8)

        # Logo / título
        title = QLabel("⚡ CRYPTO IA BOT v2")
        title.setStyleSheet(f"color: {CYAN}; font-size: 18px; font-weight: bold;")
        lay.addWidget(title)

        # Modo
        mode_lbl = QLabel(f"[ {config.TRADING_MODE.upper()} ]")
        mode_color = GREEN if config.TRADING_MODE == "demo" else RED
        mode_lbl.setStyleSheet(f"color: {mode_color}; font-size: 13px; font-weight: bold;")
        lay.addWidget(mode_lbl)
        lay.addStretch()

        # KPIs no header
        self.kpi_price   = KPICard("Preço",    "---",    CYAN)
        self.kpi_pnl     = KPICard("PnL Hoje", "+0.00",  GREEN)
        self.kpi_winrate = KPICard("Winrate",  "0%",     YELLOW)
        self.kpi_trades  = KPICard("Trades",   "0",      TEXT_PRI)
        self.kpi_pos     = KPICard("Posição",  "NONE",   TEXT_MUT)
        self.kpi_groq    = KPICard("Groq",     "ranging",PURPLE)

        for k in [self.kpi_price, self.kpi_pnl, self.kpi_winrate,
                  self.kpi_trades, self.kpi_pos, self.kpi_groq]:
            lay.addWidget(k)

        lay.addStretch()

        # Botões Start / Stop
        self.btn_start = QPushButton("▶  START")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.setFixedSize(110, 40)
        self.btn_start.clicked.connect(self._on_start)

        self.btn_stop  = QPushButton("■  STOP")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setFixedSize(110, 40)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop.setEnabled(False)

        lay.addWidget(self.btn_start)
        lay.addWidget(self.btn_stop)
        return w

    # ────── ABA: TRADING ─────────────────────────────────────

    def _build_trading_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)

        # Gráfico de preço
        grp_chart = QGroupBox("Candles + Indicadores")
        gl        = QVBoxLayout(grp_chart)
        pg.setConfigOption("background", DARK_CARD)
        pg.setConfigOption("foreground", TEXT_PRI)

        self.chart_price = pg.PlotWidget()
        self.chart_price.setMinimumHeight(280)
        self.chart_price.showGrid(x=True, y=True, alpha=0.12)
        self.chart_price.setLabel("left", "Preço (USDT)")
        self.chart_price.addLegend(offset=(10, 10))

        self.curve_close  = self.chart_price.plot(pen=pg.mkPen(CYAN,  width=2), name="Close")
        self.curve_ema9   = self.chart_price.plot(pen=pg.mkPen(GREEN, width=1, style=Qt.PenStyle.DashLine), name="EMA9")
        self.curve_ema21  = self.chart_price.plot(pen=pg.mkPen(ORANGE,width=1, style=Qt.PenStyle.DashLine), name="EMA21")
        self.curve_bb_u   = self.chart_price.plot(pen=pg.mkPen(PURPLE,width=1, style=Qt.PenStyle.DotLine),  name="BB+")
        self.curve_bb_l   = self.chart_price.plot(pen=pg.mkPen(PURPLE,width=1, style=Qt.PenStyle.DotLine),  name="BB-")
        gl.addWidget(self.chart_price)

        # RSI
        self.chart_rsi = pg.PlotWidget()
        self.chart_rsi.setMaximumHeight(110)
        self.chart_rsi.showGrid(x=True, y=True, alpha=0.12)
        self.chart_rsi.setLabel("left", "RSI")
        self.chart_rsi.setYRange(0, 100)
        self.chart_rsi.addLine(y=70, pen=pg.mkPen(RED,   width=1, style=Qt.PenStyle.DashLine))
        self.chart_rsi.addLine(y=30, pen=pg.mkPen(GREEN, width=1, style=Qt.PenStyle.DashLine))
        self.curve_rsi = self.chart_rsi.plot(pen=pg.mkPen(YELLOW, width=2), name="RSI")
        gl.addWidget(self.chart_rsi)

        # MACD
        self.chart_macd = pg.PlotWidget()
        self.chart_macd.setMaximumHeight(110)
        self.chart_macd.showGrid(x=True, y=True, alpha=0.12)
        self.chart_macd.setLabel("left", "MACD")
        self.curve_macd    = self.chart_macd.plot(pen=pg.mkPen(CYAN, width=2), name="MACD")
        self.curve_macd_sig= self.chart_macd.plot(pen=pg.mkPen(ORANGE, width=1), name="Signal")
        gl.addWidget(self.chart_macd)

        lay.addWidget(grp_chart)

        # Tabela de trades
        grp_trades = QGroupBox("Histórico de Operações")
        tl         = QVBoxLayout(grp_trades)
        self.table_trades = QTableWidget(0, 8)
        self.table_trades.setHorizontalHeaderLabels(
            ["Par", "Entrada", "Saída", "Qtde", "PnL $", "PnL %", "Razão", "Duração"]
        )
        self.table_trades.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_trades.setMaximumHeight(180)
        self.table_trades.setSortingEnabled(True)
        tl.addWidget(self.table_trades)
        lay.addWidget(grp_trades)

        return w

    # ────── ABA: MARKET ──────────────────────────────────────

    def _build_market_tab(self) -> QWidget:
        w    = QWidget()
        lay  = QVBoxLayout(w)

        # Ticks ao vivo
        grp_ticks = QGroupBox("Ticks em Tempo Real")
        gl        = QVBoxLayout(grp_ticks)
        self.chart_ticks = pg.PlotWidget()
        self.chart_ticks.setMinimumHeight(200)
        self.chart_ticks.showGrid(x=True, y=True, alpha=0.1)
        self.chart_ticks.setLabel("left", "Preço")
        self.curve_ticks = self.chart_ticks.plot(pen=pg.mkPen(GREEN, width=1))
        gl.addWidget(self.chart_ticks)
        lay.addWidget(grp_ticks)

        # Volume + spread
        bottom = QHBoxLayout()
        grp_vol = QGroupBox("Volume")
        vl      = QVBoxLayout(grp_vol)
        self.chart_vol = pg.PlotWidget()
        self.chart_vol.setMaximumHeight(130)
        self.chart_vol.showGrid(x=False, y=True, alpha=0.1)
        self.chart_vol.setLabel("left", "Volume")
        self.bar_vol = pg.BarGraphItem(x=[0], height=[0], width=0.6,
                                       brush=pg.mkBrush(CYAN+"80"))
        self.chart_vol.addItem(self.bar_vol)
        vl.addWidget(self.chart_vol)
        bottom.addWidget(grp_vol)

        grp_ob = QGroupBox("Order Book Snapshot")
        ol     = QGridLayout(grp_ob)
        self.lbl_bid   = QLabel("BID: ---")
        self.lbl_ask   = QLabel("ASK: ---")
        self.lbl_spread= QLabel("SPREAD: ---")
        self.lbl_vwap  = QLabel("VWAP: ---")
        for lbl in [self.lbl_bid, self.lbl_ask, self.lbl_spread, self.lbl_vwap]:
            lbl.setStyleSheet(f"color: {TEXT_PRI}; font-size: 13px; padding: 6px;")
        self.lbl_bid.setStyleSheet(f"color: {GREEN}; font-size: 14px; font-weight: bold;")
        self.lbl_ask.setStyleSheet(f"color: {RED};   font-size: 14px; font-weight: bold;")
        ol.addWidget(self.lbl_bid,    0, 0)
        ol.addWidget(self.lbl_ask,    0, 1)
        ol.addWidget(self.lbl_spread, 1, 0)
        ol.addWidget(self.lbl_vwap,   1, 1)
        bottom.addWidget(grp_ob)
        lay.addLayout(bottom)

        # Log de mercado
        grp_log = QGroupBox("Log de Mercado")
        ll      = QVBoxLayout(grp_log)
        self.market_log = QTextEdit()
        self.market_log.setReadOnly(True)
        self.market_log.setMaximumHeight(130)
        ll.addWidget(self.market_log)
        lay.addWidget(grp_log)

        return w

    # ────── ABA: AI COUNCIL ──────────────────────────────────

    def _build_ai_tab(self) -> QWidget:
        w   = QWidget()
        lay = QHBoxLayout(w)

        # Coluna esquerda — estado do conselho
        left    = QVBoxLayout()
        grp_gs  = QGroupBox("Groq Council — Estado Atual")
        gsl     = QGridLayout(grp_gs)

        labels = ["Regime", "Bias", "Veto", "Confiança ×", "Threshold adj.", "Última análise"]
        self.ai_labels = {}
        for i, lbl in enumerate(labels):
            gsl.addWidget(QLabel(lbl + ":"), i, 0)
            val = QLabel("---")
            val.setStyleSheet(f"color: {CYAN}; font-weight: bold; font-size: 13px;")
            gsl.addWidget(val, i, 1)
            self.ai_labels[lbl] = val
        left.addWidget(grp_gs)

        # Barra de confiança
        grp_conf = QGroupBox("Confiança do Sistema")
        cl       = QVBoxLayout(grp_conf)
        self.conf_bar = QProgressBar()
        self.conf_bar.setRange(0, 100)
        self.conf_bar.setValue(0)
        cl.addWidget(self.conf_bar)
        left.addWidget(grp_conf)

        # Scores das estratégias
        grp_sc = QGroupBox("Votos por Estratégia")
        scl    = QGridLayout(grp_sc)
        strategies = ["Trend Follow", "Mean Reversion", "Breakout", "News Shock"]
        self.strat_bars = {}
        for i, s in enumerate(strategies):
            scl.addWidget(QLabel(s), i, 0)
            bar = QProgressBar()
            bar.setRange(-10, 10)
            bar.setValue(0)
            bar.setFormat("%v")
            scl.addWidget(bar, i, 1)
            self.strat_bars[s] = bar
        left.addWidget(grp_sc)
        left.addStretch()
        lay.addLayout(left, 1)

        # Coluna direita — explicação + log
        right = QVBoxLayout()
        grp_exp = QGroupBox("Explicação da Última Decisão (Groq)")
        el      = QVBoxLayout(grp_exp)
        self.ai_explanation = QTextEdit()
        self.ai_explanation.setReadOnly(True)
        self.ai_explanation.setMinimumHeight(160)
        self.ai_explanation.setStyleSheet(f"""
            QTextEdit {{ background: {DARK_CARD}; color: {GREEN};
                        border: 1px solid {DARK_BORD}; font-size: 13px; }}
        """)
        el.addWidget(self.ai_explanation)
        right.addWidget(grp_exp)

        grp_alog = QGroupBox("Log de Decisões AI")
        al       = QVBoxLayout(grp_alog)
        self.ai_log = QTextEdit()
        self.ai_log.setReadOnly(True)
        al.addWidget(self.ai_log)
        right.addWidget(grp_alog)
        lay.addLayout(right, 2)

        return w

    # ────── ABA: NEWS & TRENDS ───────────────────────────────

    def _build_news_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)

        # Score de sentimento por símbolo
        grp_sent = QGroupBox("Sentimento de Mercado (Finnhub)")
        sl       = QHBoxLayout(grp_sent)
        self.sent_bars = {}
        for sym, col in [("BTC", ORANGE), ("ETH", CYAN), ("BNB", YELLOW), ("GLOBAL", PURPLE)]:
            vb = QVBoxLayout()
            lbl = QLabel(sym)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"color: {col}; font-weight: bold;")
            bar = QProgressBar()
            bar.setRange(-100, 100)
            bar.setValue(0)
            bar.setOrientation(Qt.Orientation.Vertical)
            bar.setMinimumHeight(100)
            bar.setFixedWidth(50)
            bar.setFormat("%v%")
            bar.setStyleSheet(f"""
                QProgressBar::chunk {{ background: {col}; }}
                QProgressBar {{ background: {DARK_CARD}; border: 1px solid {DARK_BORD}; }}
            """)
            vb.addWidget(lbl)
            vb.addWidget(bar, alignment=Qt.AlignmentFlag.AlignHCenter)
            sl.addLayout(vb)
            self.sent_bars[sym] = bar
        lay.addWidget(grp_sent)

        # Event risk
        grp_ev   = QGroupBox("Risco de Evento")
        evl      = QHBoxLayout(grp_ev)
        self.lbl_event_risk = QLabel("BAIXO")
        self.lbl_event_risk.setStyleSheet(f"color: {GREEN}; font-size: 24px; font-weight: bold;")
        self.lbl_event_risk.setAlignment(Qt.AlignmentFlag.AlignCenter)
        evl.addWidget(self.lbl_event_risk)
        lay.addWidget(grp_ev)

        # Feed de notícias
        grp_feed = QGroupBox("Feed de Notícias — Finnhub")
        fl       = QVBoxLayout(grp_feed)
        self.news_table = QTableWidget(0, 3)
        self.news_table.setHorizontalHeaderLabels(["Hora", "Fonte", "Título"])
        self.news_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.news_table.setColumnWidth(0, 80)
        self.news_table.setColumnWidth(1, 120)
        fl.addWidget(self.news_table)
        lay.addWidget(grp_feed)

        return w

    # ────── ABA: RISK ────────────────────────────────────────

    def _build_risk_tab(self) -> QWidget:
        w   = QWidget()
        lay = QGridLayout(w)
        lay.setSpacing(10)

        def make_stat(title, val="---", col=TEXT_PRI):
            f  = QFrame()
            f.setStyleSheet(f"background: {DARK_CARD}; border-radius: 8px; border: 1px solid {DARK_BORD};")
            vl = QVBoxLayout(f)
            t  = QLabel(title.upper())
            t.setStyleSheet(f"color: {TEXT_MUT}; font-size: 10px;")
            v  = QLabel(val)
            v.setStyleSheet(f"color: {col}; font-size: 22px; font-weight: bold;")
            vl.addWidget(t)
            vl.addWidget(v)
            return f, v

        r = [
            ("Saldo USDT",    "---",   CYAN),
            ("Saldo BTC",     "---",   ORANGE),
            ("PnL Total $",   "---",   GREEN),
            ("Perda Diária",  "0.00",  RED),
            ("Trades Hoje",   "0",     TEXT_PRI),
            ("Win / Loss",    "0/0",   YELLOW),
            ("Winrate",       "0%",    GREEN),
            ("Em Cooldown",   "NÃO",   GREEN),
        ]
        self.risk_labels = {}
        for i, (title, val, col) in enumerate(r):
            f, v = make_stat(title, val, col)
            lay.addWidget(f, i // 4, i % 4)
            self.risk_labels[title] = v

        # Barra de loss diário
        grp_dl = QGroupBox("Utilização do Limite de Perda Diária")
        dl     = QVBoxLayout(grp_dl)
        self.daily_loss_bar = QProgressBar()
        self.daily_loss_bar.setRange(0, 100)
        self.daily_loss_bar.setValue(0)
        self.daily_loss_bar.setFormat("%v%")
        self.daily_loss_bar.setStyleSheet("""
            QProgressBar::chunk { background: #ff1744; }
        """)
        dl.addWidget(self.daily_loss_bar)
        lay.addWidget(grp_dl, 2, 0, 1, 4)

        # Config de risco ao vivo
        grp_cfg = QGroupBox("Parâmetros de Risco")
        cl      = QGridLayout(grp_cfg)
        params  = [
            ("SL %",  "STOP_LOSS_PCT"),
            ("TP %",  "TAKE_PROFIT_PCT"),
            ("Qty",   "TRADE_QUANTITY"),
        ]
        for i, (lbl, attr) in enumerate(params):
            cl.addWidget(QLabel(lbl), 0, i * 2)
            val_lbl = QLabel(str(getattr(config, attr, "---")))
            val_lbl.setStyleSheet(f"color: {CYAN}; font-weight: bold;")
            cl.addWidget(val_lbl, 0, i * 2 + 1)
        lay.addWidget(grp_cfg, 3, 0, 1, 4)

        return w

    # ────── ABA: RESEARCH ────────────────────────────────────

    def _build_research_tab(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)

        grp_bt = QGroupBox("Análise de Performance")
        btl    = QVBoxLayout(grp_bt)

        # Equity curve
        self.chart_equity = pg.PlotWidget()
        self.chart_equity.setMinimumHeight(220)
        self.chart_equity.showGrid(x=True, y=True, alpha=0.1)
        self.chart_equity.setLabel("left", "Equity ($)")
        self.chart_equity.setLabel("bottom", "Trades")
        self.curve_equity = self.chart_equity.plot(
            pen=pg.mkPen(GREEN, width=2), fillLevel=0,
            brush=pg.mkBrush(GREEN + "20")
        )
        btl.addWidget(self.chart_equity)
        lay.addWidget(grp_bt)

        # Stats de performance
        grp_st = QGroupBox("Métricas")
        stl    = QGridLayout(grp_st)
        metrics = [
            "Profit Factor", "Max Drawdown", "Sharpe Ratio",
            "Avg Win", "Avg Loss", "Consecutive Wins",
            "Consecutive Losses", "Best Trade", "Worst Trade"
        ]
        self.perf_labels = {}
        for i, m in enumerate(metrics):
            stl.addWidget(QLabel(m + ":"), i // 3, (i % 3) * 2)
            v = QLabel("---")
            v.setStyleSheet(f"color: {CYAN}; font-weight: bold;")
            stl.addWidget(v, i // 3, (i % 3) * 2 + 1)
            self.perf_labels[m] = v
        lay.addWidget(grp_st)

        # Log geral
        grp_log = QGroupBox("Log Geral do Sistema")
        ll      = QVBoxLayout(grp_log)
        self.main_log = QTextEdit()
        self.main_log.setReadOnly(True)
        self.main_log.setMinimumHeight(140)
        ll.addWidget(self.main_log)
        lay.addWidget(grp_log)

        return w

    # ── Timer de refresh ──────────────────────────────────────

    def _start_refresh_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self._refresh_ui)
        self.timer.start(500)   # 500ms

    def _refresh_ui(self):
        if not self.brain:
            return
        try:
            self._update_kpis()
            self._update_charts()
            self._update_market()
            self._update_ai()
            self._update_news()
            self._update_risk()
            self._update_research()
        except Exception as e:
            pass

    # ── Updates por aba ───────────────────────────────────────

    def _update_kpis(self):
        pair   = config.PRIMARY_PAIR
        price  = self.brain.ws.get_price(pair)
        stats  = self.brain.risk.get_stats()
        pos    = self.brain.executor.open_position
        groq   = self.brain.groq.get_state()

        if price > 0:
            self.kpi_price.update_value(f"${price:,.2f}", CYAN)

        pnl_color = GREEN if stats["total_pnl"] >= 0 else RED
        self.kpi_pnl.update_value(f"${stats['total_pnl']:+.2f}", pnl_color)
        self.kpi_winrate.update_value(f"{stats['winrate']:.1f}%",
                                       GREEN if stats["winrate"] >= 50 else RED)
        self.kpi_trades.update_value(str(stats["trades"]))
        self.kpi_pos.update_value("LONG" if pos else "NONE",
                                   ORANGE if pos else TEXT_MUT)
        self.kpi_groq.update_value(groq["regime"].replace("_"," "), PURPLE)

    def _update_charts(self):
        pair = config.PRIMARY_PAIR
        df   = self.brain.ws.get_candles(pair, "15m")
        if df.empty or len(df) < 10:
            return
        df   = self.brain.indicators.compute_all(df.copy())
        x    = np.arange(len(df))
        close = df["close"].values

        self.curve_close.setData(x, close)
        if "ema9"  in df: self.curve_ema9.setData(x, df["ema9"].values)
        if "ema21" in df: self.curve_ema21.setData(x, df["ema21"].values)
        if "bb_upper" in df:
            self.curve_bb_u.setData(x, df["bb_upper"].values)
            self.curve_bb_l.setData(x, df["bb_lower"].values)
        if "rsi"  in df: self.curve_rsi.setData(x, df["rsi"].values)
        if "macd" in df:
            self.curve_macd.setData(x, df["macd"].values)
            self.curve_macd_sig.setData(x, df["macd_signal"].values)

        # Marca posição aberta
        self.chart_price.removeItem(getattr(self, "_pos_line", None))
        pos = self.brain.executor.open_position
        if pos:
            line = self.chart_price.addLine(
                y=pos["entry_price"],
                pen=pg.mkPen(ORANGE, width=2, style=Qt.PenStyle.DashLine)
            )
            self._pos_line = line

    def _update_market(self):
        pair  = config.PRIMARY_PAIR
        state = self.brain.ws.get_state(pair)
        if not state:
            return
        ticks = state.get_ticks_df()
        if not ticks.empty:
            prices = ticks["price"].values
            self.curve_ticks.setData(np.arange(len(prices)), prices)
            vols   = ticks["qty"].values
            self.bar_vol.setOpts(
                x=np.arange(len(vols)),
                height=vols,
                width=0.8
            )
        if state.bid > 0:
            self.lbl_bid.setText(f"BID: ${state.bid:,.2f}")
            self.lbl_ask.setText(f"ASK: ${state.ask:,.2f}")
            self.lbl_spread.setText(f"SPREAD: ${state.spread:.2f}")
        vwap = self.brain.ws.get_vwap(pair)
        if vwap > 0:
            self.lbl_vwap.setText(f"VWAP: ${vwap:,.2f}")

    def _update_ai(self):
        gs = self.brain.groq.get_state()
        mapping = {
            "Regime"         : gs["regime"].replace("_", " ").upper(),
            "Bias"           : gs["bias"].upper(),
            "Veto"           : ("⛔ SIM — " + (gs["veto_reason"] or "")) if gs["veto"] else "✅ NÃO",
            "Confiança ×"    : f"{gs['confidence_multiplier']:.2f}",
            "Threshold adj." : f"{gs['threshold_adjustment']:+d}",
            "Última análise" : gs["last_updated"] or "---",
        }
        for k, v in mapping.items():
            if k in self.ai_labels:
                col = RED if (k == "Veto" and gs["veto"]) else CYAN
                self.ai_labels[k].setText(v)
                self.ai_labels[k].setStyleSheet(f"color: {col}; font-weight: bold; font-size: 13px;")

        last_analysis = getattr(self.brain, '_last_analysis', {})
        scores = last_analysis.get('scores', {})
        score_map = {
            "Trend Follow"   : scores.get("trend", 0),
            "Mean Reversion" : scores.get("mean_reversion", 0),
            "Breakout"       : scores.get("breakout", 0),
            "News Shock"     : scores.get("momentum", 0),
        }
        for name, val in score_map.items():
            if name in self.strat_bars:
                self.strat_bars[name].setValue(int(val))

        conf_pct = int(gs["confidence_multiplier"] / 1.5 * 100)
        self.conf_bar.setValue(min(100, max(0, conf_pct)))

        if gs["explanation"] and gs["explanation"] != self.ai_explanation.toPlainText():
            self.ai_explanation.setText(gs["explanation"])

    def _update_news(self):
        ne     = self.brain.news
        btc_s  = ne.get_sentiment("BTC")
        eth_s  = ne.get_sentiment("ETH")
        bnb_s  = ne.get_sentiment("BNB")
        gl_s   = ne.get_sentiment("GLOBAL")

        self.sent_bars["BTC"].setValue(int(btc_s * 100))
        self.sent_bars["ETH"].setValue(int(eth_s * 100))
        self.sent_bars["BNB"].setValue(int(bnb_s * 100))
        self.sent_bars["GLOBAL"].setValue(int(gl_s * 100))

        risk = ne.get_event_risk()
        risk_map = {"low": (GREEN, "BAIXO ✅"), "medium": (YELLOW, "MÉDIO ⚠️"), "high": (RED, "ALTO 🚨")}
        rc, rt = risk_map.get(risk, (TEXT_PRI, risk.upper()))
        self.lbl_event_risk.setStyleSheet(f"color: {rc}; font-size: 24px; font-weight: bold;")
        self.lbl_event_risk.setText(rt)

        news = ne.get_news_feed(20)
        self.news_table.setRowCount(len(news))
        for i, n in enumerate(news):
            ts   = n.get("datetime", 0)
            hora = time.strftime("%H:%M", time.localtime(ts)) if ts else "---"
            self.news_table.setItem(i, 0, QTableWidgetItem(hora))
            self.news_table.setItem(i, 1, QTableWidgetItem(n.get("source", "")))
            self.news_table.setItem(i, 2, QTableWidgetItem(n.get("headline", "")))

    def _update_risk(self):
        stats   = self.brain.risk.get_stats()
        bals    = self.brain.executor.get_all_balances()
        max_loss = config.MAX_DAILY_LOSS_PCT * 100
        start   = self.brain.risk.daily_start_bal or 1

        self.risk_labels["Saldo USDT"].setText(f"${bals.get('USDT', 0):,.2f}")
        self.risk_labels["Saldo BTC"].setText(f"{bals.get('BTC', 0):.6f}")
        pnl_c = GREEN if stats["total_pnl"] >= 0 else RED
        self.risk_labels["PnL Total $"].setText(f"${stats['total_pnl']:+.4f}")
        self.risk_labels["PnL Total $"].setStyleSheet(f"color: {pnl_c}; font-size: 22px; font-weight: bold;")
        self.risk_labels["Perda Diária"].setText(f"${stats['daily_loss']:.4f}")
        self.risk_labels["Trades Hoje"].setText(str(stats["trades"]))
        self.risk_labels["Win / Loss"].setText(f"{stats['wins']} / {stats['losses']}")
        self.risk_labels["Winrate"].setText(f"{stats['winrate']:.1f}%")
        cd = stats["in_cooldown"]
        self.risk_labels["Em Cooldown"].setText("⏳ SIM" if cd else "✅ NÃO")
        self.risk_labels["Em Cooldown"].setStyleSheet(
            f"color: {YELLOW if cd else GREEN}; font-size: 22px; font-weight: bold;"
        )
        loss_pct = (stats["daily_loss"] / start * 100) if start > 0 else 0
        self.daily_loss_bar.setValue(int(min(100, loss_pct)))

    def _update_research(self):
        history = self.brain.executor.get_trade_history()
        if not history:
            return

        # Equity curve
        equity = [1000.0]
        for t in history:
            equity.append(equity[-1] + t.get("pnl_usd", 0))
        self.curve_equity.setData(np.arange(len(equity)), np.array(equity))

        # Atualiza tabela de trades
        self.table_trades.setRowCount(len(history))
        for i, t in enumerate(reversed(history)):
            pnl_usd = t.get("pnl_usd", 0)
            pnl_pct = t.get("pnl_pct", 0)
            color   = QColor(GREEN) if pnl_usd >= 0 else QColor(RED)
            cells   = [
                t.get("symbol", ""), f"${t.get('entry',0):,.2f}",
                f"${t.get('exit',0):,.2f}",  f"{t.get('qty',0):.6f}",
                f"${pnl_usd:+.4f}",           f"{pnl_pct:+.2f}%",
                t.get("reason", ""),           f"{int(t.get('duration',0))}s"
            ]
            for j, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if j in (4, 5):
                    item.setForeground(color)
                self.table_trades.setItem(i, j, item)

        # Métricas
        pnls     = [t.get("pnl_usd", 0) for t in history]
        wins_v   = [p for p in pnls if p > 0]
        loss_v   = [p for p in pnls if p < 0]
        avg_win  = sum(wins_v) / len(wins_v)  if wins_v else 0
        avg_loss = sum(loss_v) / len(loss_v)  if loss_v else 0
        pf       = abs(sum(wins_v) / sum(loss_v)) if loss_v else float("inf")
        dd       = min(0, min(np.cumsum(pnls) - np.maximum.accumulate(np.cumsum(pnls))))

        self.perf_labels["Profit Factor"].setText(f"{pf:.2f}")
        self.perf_labels["Max Drawdown"].setText(f"${dd:.2f}")
        self.perf_labels["Avg Win"].setText(f"${avg_win:+.4f}")
        self.perf_labels["Avg Loss"].setText(f"${avg_loss:+.4f}")
        self.perf_labels["Best Trade"].setText(f"${max(pnls):+.4f}" if pnls else "---")
        self.perf_labels["Worst Trade"].setText(f"${min(pnls):+.4f}" if pnls else "---")

    # ── Botões ────────────────────────────────────────────────

    def _on_start(self):
        if not self.brain:
            self._log_main("❌ Brain não inicializado. Configure config.py")
            return
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_lbl.setText("● Bot em execução...")
        self.status_lbl.setStyleSheet(f"color: {GREEN}; padding: 4px 10px;")

        self.bot_thread = BotThread(self.brain)
        self.bot_thread.log_signal.connect(self._log_main)
        self.bot_thread.start()

    def _on_stop(self):
        if self.bot_thread:
            self.bot_thread.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_lbl.setText("● Bot parado")
        self.status_lbl.setStyleSheet(f"color: {RED}; padding: 4px 10px;")

    def _log_main(self, msg: str):
        self.main_log.append(
            f"<span style='color:{TEXT_MUT}'>{time.strftime('%H:%M:%S')}</span> "
            f"<span style='color:{TEXT_PRI}'>{msg}</span>"
        )
        self.main_log.moveCursor(QTextCursor.MoveOperation.End)