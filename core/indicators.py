"""Computação de indicadores técnicos multi-mercado."""
import pandas as pd
import numpy as np
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


class TechnicalIndicators:
    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or len(df) < 50:
            return df

        c = df["close"].astype(float)
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        v = df["volume"].astype(float)

        delta = c.diff()
        gain = delta.clip(lower=0).ewm(com=config.RSI_PERIOD - 1, min_periods=config.RSI_PERIOD).mean()
        loss = (-delta.clip(upper=0)).ewm(com=config.RSI_PERIOD - 1, min_periods=config.RSI_PERIOD).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))

        ema_f = c.ewm(span=config.MACD_FAST, adjust=False).mean()
        ema_s = c.ewm(span=config.MACD_SLOW, adjust=False).mean()
        macd_line = ema_f - ema_s
        signal_line = macd_line.ewm(span=config.MACD_SIGNAL, adjust=False).mean()
        df["macd"] = macd_line
        df["macd_signal"] = signal_line
        df["macd_hist"] = macd_line - signal_line

        sma = c.rolling(config.BB_PERIOD).mean()
        std = c.rolling(config.BB_PERIOD).std()
        df["bb_upper"] = sma + std * config.BB_STD
        df["bb_middle"] = sma
        df["bb_lower"] = sma - std * config.BB_STD
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / sma.replace(0, np.nan)

        tr = pd.concat([
            h - l,
            (h - c.shift()).abs(),
            (l - c.shift()).abs()
        ], axis=1).max(axis=1)
        df["atr"] = tr.ewm(span=config.ATR_PERIOD, adjust=False).mean()

        df["ema9"] = c.ewm(span=9, adjust=False).mean()
        df["ema21"] = c.ewm(span=21, adjust=False).mean()
        df["ema50"] = c.ewm(span=50, adjust=False).mean()
        df["ema200"] = c.ewm(span=200, adjust=False).mean()

        plus_dm = h.diff()
        minus_dm = -l.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
        atr_smooth = tr.rolling(config.ADX_PERIOD).mean()
        plus_di = 100 * (plus_dm.rolling(config.ADX_PERIOD).mean() / atr_smooth.replace(0, np.nan))
        minus_di = 100 * (minus_dm.rolling(config.ADX_PERIOD).mean() / atr_smooth.replace(0, np.nan))
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
        df["adx"] = dx.rolling(config.ADX_PERIOD).mean()
        df["plus_di"] = plus_di
        df["minus_di"] = minus_di

        df["trend"] = np.where(
            (df["ema9"] > df["ema21"]) & (df["ema21"] > df["ema50"]) & (df["adx"] >= 22),
            "strong_up",
            np.where(
                (df["ema9"] < df["ema21"]) & (df["ema21"] < df["ema50"]) & (df["adx"] >= 22),
                "strong_down",
                np.where(
                    df["ema9"] > df["ema21"],
                    "up",
                    np.where(df["ema9"] < df["ema21"], "down", "sideways")
                )
            )
        )

        pv = (c * v).cumsum()
        cv = v.cumsum()
        df["vwap"] = pv / cv.replace(0, np.nan)

        df["vol_sma"] = v.rolling(20).mean()
        df["vol_ratio"] = v / df["vol_sma"].replace(0, np.nan)

        rsi_s = df["rsi"]
        rsi_min = rsi_s.rolling(config.STOCH_RSI_PERIOD).min()
        rsi_max = rsi_s.rolling(config.STOCH_RSI_PERIOD).max()
        rng = (rsi_max - rsi_min).replace(0, np.nan)
        df["stoch_rsi"] = (rsi_s - rsi_min) / rng

        df["returns_1"] = c.pct_change(1)
        df["returns_5"] = c.pct_change(5)
        df["returns_15"] = c.pct_change(15)
        df["volatility_20"] = c.pct_change().rolling(20).std()

        return df