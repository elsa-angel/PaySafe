"""Feature-set definitions shared by training and by Django inference.

Two XGBoost feature sets are trained with the identical procedure:

  full     every usable IEEE-CIS column (benchmark / dataset ceiling). PaySafe cannot supply
           most of these at prediction time (C*, D*, M*, V*, card1-6, addr*, dist*, id_*).
  aligned  only the six canonical fields that PaySafe can genuinely supply or derive:
           TransactionAmt (USD-equivalent), P_emaildomain, R_emaildomain, device_type,
           browser_family, os_family.

The normalisation functions below are the ONLY place where IEEE-CIS strings and PaySafe
strings are reconciled, so training and inference cannot drift apart.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TARGET = "isFraud"
ID_COL = "TransactionID"
TIME_COL = "TransactionDT"

# Columns never given to the model (identifier / raw clock / label).
EXCLUDED_ALWAYS = {
    ID_COL: "Row identifier, monotonic with time: lets a model memorise position in the data.",
    TIME_COL: "Seconds from an undocumented reference date: raw value is out-of-range for any later "
              "date and cannot be aligned to PaySafe timestamps.",
    TARGET: "Label.",
}

ALIGNED_COLUMNS = [
    "TransactionAmt", "P_emaildomain", "R_emaildomain", "device_type", "browser_family", "os_family",
]
ALIGNED_NUMERIC = ["TransactionAmt"]
ALIGNED_CATEGORICAL = ["P_emaildomain", "R_emaildomain", "device_type", "browser_family", "os_family"]

BROWSER_FAMILIES = ["chrome", "safari", "firefox", "edge", "ie", "samsung", "opera", "other"]
OS_FAMILIES = ["windows", "macos", "ios", "android", "linux", "other"]


# ----------------------------------------------------------------- IEEE-CIS side (training)
def ieee_browser_family(value):
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return np.nan
    s = str(value).strip().lower()
    if "/" in s:                      # device-style user agents e.g. "Samsung/SM-G531H"
        return "other"
    if s == "samsung" or s.startswith("samsung browser"):
        return "samsung"
    if s.startswith("edge"):
        return "edge"
    if s.startswith("opera"):
        return "opera"
    if s.startswith("firefox"):
        return "firefox"
    if s.startswith("chrome") and not s.startswith("chromium"):
        return "chrome"
    if "safari" in s:
        return "safari"
    if s == "ie" or s.startswith("ie "):
        return "ie"
    return "other"


def ieee_os_family(value):
    if pd.isna(value):
        return np.nan
    s = str(value).strip().lower()
    if s.startswith("windows"):
        return "windows"
    if s.startswith("mac"):
        return "macos"
    if s.startswith("ios"):
        return "ios"
    if s.startswith("android"):
        return "android"
    if s.startswith("linux"):
        return "linux"
    return "other"                    # "other", "func"


def ieee_device_type(value):
    return np.nan if pd.isna(value) else str(value).strip().lower()


def _map_categorical(series: pd.Series, fn) -> pd.Series:
    """Applies fn once per distinct category (fast), then maps rows."""
    cats = series.cat.categories if hasattr(series, "cat") else pd.Index(series.dropna().unique())
    table = {c: fn(c) for c in cats}
    return series.astype(object).map(table)


def build_aligned_frame(df: pd.DataFrame) -> pd.DataFrame:
    """IEEE-CIS rows -> the six canonical, PaySafe-compatible columns."""
    out = pd.DataFrame(index=df.index)
    out["TransactionAmt"] = df["TransactionAmt"].astype("float32")
    out["P_emaildomain"] = df["P_emaildomain"].astype(object)
    out["R_emaildomain"] = df["R_emaildomain"].astype(object)
    out["device_type"] = _map_categorical(df["DeviceType"], ieee_device_type)
    out["browser_family"] = _map_categorical(df["id_31"], ieee_browser_family)
    out["os_family"] = _map_categorical(df["id_30"], ieee_os_family)
    return out[ALIGNED_COLUMNS]


# ----------------------------------------------------------------- PaySafe side (inference)
_PAYSAFE_BROWSERS = {
    "chrome": "chrome", "safari": "safari", "firefox": "firefox", "edge": "edge",
    "opera": "opera", "samsung internet": "samsung",
}


def paysafe_browser_family(browser):
    """PaySafe `Transaction.browser`, e.g. 'Chrome 126', 'Safari 17', 'Other', 'Unknown'."""
    if not browser or browser == "Unknown":
        return np.nan
    name = " ".join(p for p in str(browser).split() if not p.replace(".", "").isdigit()).lower()
    return _PAYSAFE_BROWSERS.get(name, "other")


_PAYSAFE_OS = {"windows": "windows", "macos": "macos", "ios": "ios", "android": "android", "linux": "linux"}


def paysafe_os_family(operating_system):
    """PaySafe `Transaction.operating_system`: Windows/Android/iOS/ChromeOS/macOS/Linux/Other/Unknown."""
    if not operating_system or operating_system == "Unknown":
        return np.nan
    return _PAYSAFE_OS.get(str(operating_system).strip().lower(), "other")


def paysafe_device_type(device_type):
    """PaySafe DeviceType MOBILE/TABLET/DESKTOP/UNKNOWN. IEEE-CIS only has mobile/desktop and does not
    say how tablets are labelled, so TABLET and UNKNOWN are left missing rather than guessed."""
    return {"MOBILE": "mobile", "DESKTOP": "desktop"}.get(str(device_type).upper(), np.nan)
