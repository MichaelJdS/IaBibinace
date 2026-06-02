"""
Database Engine — SQLite persistência completa
Trades, métricas, logs de AI, estados de sessão
"""
import sqlite3
import json
import time
import os
import threading
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger

log = get_logger("Database")

DB_PATH = os.path.join("data", "bot.db")

class DatabaseEngine:
    def __init__(self):
        os.makedirs("data", exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()
        log.info(f"Database inicializado: {DB_PATH}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self):
        with self._lock:
            conn = self._conn()
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol        TEXT    NOT NULL,
                side          TEXT    NOT NULL,
                entry_price   REAL    NOT NULL,
                exit_price    REAL,
                quantity      REAL    NOT NULL,
                pnl_usd       REAL,
                pnl_pct       REAL,
                stop_loss     REAL,
                take_profit   REAL,
                reason_entry  TEXT,
                reason_exit   TEXT,
                confidence    INTEGER,
                regime        TEXT,
                duration_sec  INTEGER,
                indicators    TEXT,
                entry_time    INTEGER,
                exit_time     INTEGER,
                mode          TEXT    DEFAULT 'demo',
                win           INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS ai_decisions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          INTEGER NOT NULL,
                symbol      TEXT,
                action      TEXT,
                confidence  INTEGER,
                regime      TEXT,
                bias        TEXT,
                veto        INTEGER DEFAULT 0,
                veto_reason TEXT,
                explanation TEXT,
                indicators  TEXT,
                strategy    TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                date        TEXT PRIMARY KEY,
                symbol      TEXT,
                trades      INTEGER DEFAULT 0,
                wins        INTEGER DEFAULT 0,
                losses      INTEGER DEFAULT 0,
                pnl_usd     REAL    DEFAULT 0.0,
                max_drawdown REAL   DEFAULT 0.0,
                start_bal   REAL,
                end_bal     REAL,
                winrate     REAL    DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS market_snapshots (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       INTEGER NOT NULL,
                symbol   TEXT,
                price    REAL,
                rsi      REAL,
                macd     REAL,
                bb_width REAL,
                trend    TEXT,
                volume   REAL,
                sentiment REAL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time INTEGER,
                end_time   INTEGER,
                mode       TEXT,
                trades     INTEGER DEFAULT 0,
                pnl_usd    REAL    DEFAULT 0.0,
                notes      TEXT
            );

            CREATE TABLE IF NOT EXISTS parameter_history (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        INTEGER NOT NULL,
                param     TEXT    NOT NULL,
                old_value TEXT,
                new_value TEXT,
                reason    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_trades_ts     ON trades(entry_time);
            CREATE INDEX IF NOT EXISTS idx_ai_ts         ON ai_decisions(ts);
            CREATE INDEX IF NOT EXISTS idx_snapshots_ts  ON market_snapshots(ts);
            """)
            conn.commit()
            conn.close()

    # ── TRADES ────────────────────────────────────────────────

    def save_trade_open(self, trade: dict) -> int:
        with self._lock:
            conn = self._conn()
            cur  = conn.execute("""
                INSERT INTO trades
                (symbol, side, entry_price, quantity, stop_loss, take_profit,
                 reason_entry, confidence, regime, indicators, entry_time, mode)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                trade.get("symbol"), trade.get("side"), trade.get("entry_price"),
                trade.get("quantity"), trade.get("stop_loss"), trade.get("take_profit"),
                trade.get("reason_entry"), trade.get("confidence"),
                trade.get("regime"), json.dumps(trade.get("indicators", {})),
                trade.get("entry_time", int(time.time())),
                trade.get("mode", "demo")
            ))
            conn.commit()
            row_id = cur.lastrowid
            conn.close()
        log.debug(f"Trade aberto salvo: id={row_id}")
        return row_id

    def save_trade_close(self, trade_id: int, exit_data: dict):
        with self._lock:
            conn = self._conn()
            conn.execute("""
                UPDATE trades SET
                    exit_price  = ?,
                    pnl_usd     = ?,
                    pnl_pct     = ?,
                    reason_exit = ?,
                    duration_sec= ?,
                    exit_time   = ?,
                    win         = ?
                WHERE id = ?
            """, (
                exit_data.get("exit_price"),
                exit_data.get("pnl_usd"),
                exit_data.get("pnl_pct"),
                exit_data.get("reason"),
                exit_data.get("duration_sec"),
                int(time.time()),
                1 if exit_data.get("pnl_usd", 0) > 0 else 0,
                trade_id
            ))
            conn.commit()
            conn.close()
        log.debug(f"Trade fechado salvo: id={trade_id}")
        self._update_daily_stats()

    def get_trades(self, symbol: str = None, limit: int = 100,
                   since: int = None) -> list:
        with self._lock:
            conn  = self._conn()
            query = "SELECT * FROM trades WHERE exit_price IS NOT NULL"
            args  = []
            if symbol:
                query += " AND symbol = ?"
                args.append(symbol)
            if since:
                query += " AND entry_time >= ?"
                args.append(since)
            query += f" ORDER BY entry_time DESC LIMIT {limit}"
            rows  = conn.execute(query, args).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def get_today_trades(self, symbol: str = None) -> list:
        today = int(time.mktime(time.strptime(
            time.strftime("%Y-%m-%d"), "%Y-%m-%d"
        )))
        return self.get_trades(symbol=symbol, limit=500, since=today)

    # ── AI DECISIONS ─────────────────────────────────────────

    def save_ai_decision(self, decision: dict):
        with self._lock:
            conn = self._conn()
            conn.execute("""
                INSERT INTO ai_decisions
                (ts, symbol, action, confidence, regime, bias,
                 veto, veto_reason, explanation, indicators, strategy)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                int(time.time()),
                decision.get("symbol"),
                decision.get("action"),
                decision.get("confidence"),
                decision.get("regime"),
                decision.get("bias"),
                1 if decision.get("veto") else 0,
                decision.get("veto_reason"),
                decision.get("explanation"),
                json.dumps(decision.get("indicators", {})),
                decision.get("strategy")
            ))
            conn.commit()
            conn.close()

    # ── MARKET SNAPSHOTS ──────────────────────────────────────

    def save_snapshot(self, snap: dict):
        with self._lock:
            conn = self._conn()
            conn.execute("""
                INSERT INTO market_snapshots
                (ts, symbol, price, rsi, macd, bb_width, trend, volume, sentiment)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                int(time.time()),
                snap.get("symbol"), snap.get("price"),
                snap.get("rsi"), snap.get("macd"),
                snap.get("bb_width"), snap.get("trend"),
                snap.get("volume"), snap.get("sentiment")
            ))
            conn.commit()
            conn.close()

    def get_snapshots(self, symbol: str, limit: int = 500) -> list:
        with self._lock:
            conn = self._conn()
            rows = conn.execute("""
                SELECT * FROM market_snapshots
                WHERE symbol = ?
                ORDER BY ts DESC LIMIT ?
            """, (symbol, limit)).fetchall()
            conn.close()
        return [dict(r) for r in reversed(rows)]

    # ── DAILY STATS ───────────────────────────────────────────

    def _update_daily_stats(self):
        today  = time.strftime("%Y-%m-%d")
        trades = self.get_today_trades()
        if not trades:
            return

        wins    = [t for t in trades if t["win"]]
        losses  = [t for t in trades if not t["win"]]
        pnl     = sum(t["pnl_usd"] or 0 for t in trades)
        winrate = len(wins) / len(trades) * 100 if trades else 0

        # Drawdown
        cumulative = 0
        peak       = 0
        max_dd     = 0
        for t in sorted(trades, key=lambda x: x["entry_time"]):
            cumulative += (t["pnl_usd"] or 0)
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        with self._lock:
            conn = self._conn()
            conn.execute("""
                INSERT INTO daily_stats (date, trades, wins, losses, pnl_usd, max_drawdown, winrate)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(date) DO UPDATE SET
                    trades=excluded.trades,   wins=excluded.wins,
                    losses=excluded.losses,   pnl_usd=excluded.pnl_usd,
                    max_drawdown=excluded.max_drawdown,
                    winrate=excluded.winrate
            """, (today, len(trades), len(wins), len(losses), pnl, max_dd, winrate))
            conn.commit()
            conn.close()

    def get_daily_stats(self, days: int = 30) -> list:
        with self._lock:
            conn = self._conn()
            rows = conn.execute("""
                SELECT * FROM daily_stats
                ORDER BY date DESC LIMIT ?
            """, (days,)).fetchall()
            conn.close()
        return [dict(r) for r in reversed(rows)]

    # ── PARAMETER HISTORY ─────────────────────────────────────

    def log_param_change(self, param: str, old_val, new_val, reason: str = ""):
        with self._lock:
            conn = self._conn()
            conn.execute("""
                INSERT INTO parameter_history (ts, param, old_value, new_value, reason)
                VALUES (?,?,?,?,?)
            """, (int(time.time()), param, str(old_val), str(new_val), reason))
            conn.commit()
            conn.close()

    def get_param_history(self, param: str = None, limit: int = 50) -> list:
        with self._lock:
            conn  = self._conn()
            query = "SELECT * FROM parameter_history"
            args  = []
            if param:
                query += " WHERE param = ?"
                args.append(param)
            query += f" ORDER BY ts DESC LIMIT {limit}"
            rows  = conn.execute(query, args).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    # ── SESSIONS ──────────────────────────────────────────────

    def start_session(self, mode: str = "demo") -> int:
        with self._lock:
            conn = self._conn()
            cur  = conn.execute("""
                INSERT INTO sessions (start_time, mode) VALUES (?,?)
            """, (int(time.time()), mode))
            conn.commit()
            sid = cur.lastrowid
            conn.close()
        log.info(f"Sessão iniciada: id={sid} modo={mode}")
        return sid

    def end_session(self, session_id: int, trades: int, pnl: float):
        with self._lock:
            conn = self._conn()
            conn.execute("""
                UPDATE sessions SET
                    end_time = ?, trades = ?, pnl_usd = ?
                WHERE id = ?
            """, (int(time.time()), trades, pnl, session_id))
            conn.commit()
            conn.close()
        log.info(f"Sessão encerrada: id={session_id} trades={trades} pnl=${pnl:+.4f}")