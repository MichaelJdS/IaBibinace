"""Computação de todos os indicadores técnicos sobre um DataFrame OHLCV."""
import pandas as pd
import numpy as np
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

class TechnicalIndicators:

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Adiciona todas as colunas de indicadores ao DataFrame."""
        if df.empty or len(df) < 30:
            return df

        c = df["close"]
        h = df["high"]
        l = df["low"]
        v = df["volume"]

        # ── RSI ───────────────────────────────────────────────
        delta  = c.diff()
        gain   = delta.clip(lower=0).ewm(com=config.RSI_PERIOD-1, min_periods=config.RSI_PERIOD).mean()
        loss   = (-delta.clip(upper=0)).ewm(com=config.RSI_PERIOD-1, min_periods=config.RSI_PERIOD).mean()
        rs     = gain / loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))

        # ── MACD ──────────────────────────────────────────────
        ema_f         = c.ewm(span=config.MACD_FAST, adjust=False).mean()
        ema_s         = c.ewm(span=config.MACD_SLOW, adjust=False).mean()
        macd_line     = ema_f - ema_s
        signal_line   = macd_line.ewm(span=config.MACD_SIGNAL, adjust=False).mean()
        df["macd"]        = macd_line
        df["macd_signal"] = signal_line
        df["macd_hist"]   = macd_line - signal_line

        # ── Bollinger Bands ───────────────────────────────────
        sma            = c.rolling(config.BB_PERIOD).mean()
        std            = c.rolling(config.BB_PERIOD).std()
        df["bb_upper"] = sma + std * config.BB_STD
        df["bb_middle"]= sma
        df["bb_lower"] = sma - std * config.BB_STD
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / sma

        # ── ATR ───────────────────────────────────────────────
        tr             = pd.concat([
            h - l,
            (h - c.shift()).abs(),
            (l - c.shift()).abs()
        ], axis=1).max(axis=1)
        df["atr"]      = tr.ewm(span=config.ATR_PERIOD, adjust=False).mean()

        # ── EMAs ──────────────────────────────────────────────
        df["ema9"]  = c.ewm(span=9,  adjust=False).mean()
        df["ema21"] = c.ewm(span=21, adjust=False).mean()
        df["ema50"] = c.ewm(span=50, adjust=False).mean()
        df["ema200"]= c.ewm(span=200,adjust=False).mean()

        # ── Tendência (EMA ribbon) ────────────────────────────
        df["trend"] = np.where(
            df["ema9"] > df["ema21"],
            np.where(df["ema21"] > df["ema50"], "strong_up", "up"),
            np.where(df["ema9"] < df["ema21"],
                np.where(df["ema21"] < df["ema50"], "strong_down", "down"),
                "sideways"
            )
        )

        # ── VWAP (session) ────────────────────────────────────
        pv          = (c * v).cumsum()
        cv          = v.cumsum()
        df["vwap"]  = pv / cv.replace(0, np.nan)

        # ── Volume SMA ───────────────────────────────────────
        df["vol_sma"] = v.rolling(20).mean()
        df["vol_ratio"] = v / df["vol_sma"].replace(0, np.nan)

        # ── Stochastic RSI ───────────────────────────────────
        rsi_s      = df["rsi"]
        rsi_min    = rsi_s.rolling(14).min()
        rsi_max    = rsi_s.rolling(14).max()
        rng        = (rsi_max - rsi_min).replace(0, np.nan)
        df["stoch_rsi"] = (rsi_s - rsi_min) / rng

        return df