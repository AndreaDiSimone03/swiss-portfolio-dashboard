"""
Swiss portfolio dashboard
-------------------------
Compares two baskets of SIX-listed stocks (all in CHF, so no currency effects):
  - Blue chips (large SMI companies)
  - Listed Swiss real estate
against the SMI index.

Usage:
    python dashboard.py              # download prices (first run) and build the dashboard
    python dashboard.py --refresh    # force a fresh download
    python dashboard.py --csv my_prices.csv   # use your own price file instead

Outputs (in ./output):
    dashboard.png   one-page dashboard
    metrics.csv     table of risk and return metrics
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Configuration: change these to make the analysis your own
# --------------------------------------------------------------------------
BLUE_CHIPS = {
    "NESN.SW": "Nestle",
    "NOVN.SW": "Novartis",
    "RO.SW": "Roche",
    "UBSG.SW": "UBS",
    "ZURN.SW": "Zurich Insurance",
    "ABBN.SW": "ABB",
}
REAL_ESTATE = {
    "SPSN.SW": "Swiss Prime Site",
    "PSPN.SW": "PSP Swiss Property",
    "MOBN.SW": "Mobimo",
}
BENCHMARK = {"^SSMI": "SMI"}

START = "2019-01-01"
END = None  # None = today
RISK_FREE = 0.0  # annual risk-free rate used in the Sharpe ratio (set your own)
TRADING_DAYS = 252
ROLLING_WINDOW = 252  # one year of trading days

DATA_FILE = Path("data/prices.csv")
OUT_DIR = Path("output")

ALL_NAMES = {**BLUE_CHIPS, **REAL_ESTATE, **BENCHMARK}


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def download_prices() -> pd.DataFrame:
    """Download adjusted close prices from Yahoo Finance."""
    import yfinance as yf

    data = yf.download(
        list(ALL_NAMES),
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
    )["Close"]
    return data.rename(columns=ALL_NAMES)[list(ALL_NAMES.values())]


def load_prices(csv_path=None, refresh=False) -> pd.DataFrame:
    path = Path(csv_path) if csv_path else DATA_FILE
    if path.exists() and not refresh:
        prices = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        prices = download_prices()
        path.parent.mkdir(parents=True, exist_ok=True)
        prices.to_csv(path)
    # Skip any stock Yahoo returned no data for, and say so
    empty = [c for c in prices.columns if prices[c].isna().all()]
    if empty:
        print(f"WARNING: no data for {empty}. Skipped. Check the ticker in the config.")
        prices = prices.drop(columns=empty)
    # Keep only dates where every series has a price, so all stats use the same window
    return prices.dropna().sort_index()


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
def drawdown(prices: pd.DataFrame) -> pd.DataFrame:
    """Percentage drop from the running maximum."""
    return prices / prices.cummax() - 1


def compute_metrics(prices: pd.DataFrame) -> pd.DataFrame:
    returns = prices.pct_change().dropna()
    years = (prices.index[-1] - prices.index[0]).days / 365.25

    total = prices.iloc[-1] / prices.iloc[0]
    ann_return = total ** (1 / years) - 1
    ann_vol = returns.std() * np.sqrt(TRADING_DAYS)
    sharpe = (ann_return - RISK_FREE) / ann_vol
    max_dd = drawdown(prices).min()
    var_95 = returns.quantile(0.05)  # worst daily loss in 95% of days (historical VaR)

    metrics = pd.DataFrame(
        {
            "Ann. return": ann_return,
            "Ann. volatility": ann_vol,
            "Sharpe": sharpe,
            "Max drawdown": max_dd,
            "Daily VaR 95%": var_95,
        }
    )
    return metrics


def basket_series(prices: pd.DataFrame, names: list) -> pd.Series:
    """Equal-weight basket, rebalanced daily."""
    basket_returns = prices[names].pct_change().mean(axis=1)
    return (1 + basket_returns.fillna(0)).cumprod()


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
def build_dashboard(prices: pd.DataFrame, metrics: pd.DataFrame, out_path: Path):
    blue = [n for n in BLUE_CHIPS.values() if n in prices.columns]
    real = [n for n in REAL_ESTATE.values() if n in prices.columns]
    smi = BENCHMARK["^SSMI"]

    baskets = pd.DataFrame(
        {
            "Blue chips (equal weight)": basket_series(prices, blue),
            "Swiss real estate (equal weight)": basket_series(prices, real),
            "SMI": prices[smi] / prices[smi].iloc[0],
        }
    )
    basket_returns = baskets.pct_change().dropna()
    returns = prices.pct_change().dropna()

    colors = {
        "Blue chips (equal weight)": "#1f4e79",
        "Swiss real estate (equal weight)": "#c0504d",
        "SMI": "#7f7f7f",
    }

    fig = plt.figure(figsize=(16, 12.5))
    gs = fig.add_gridspec(3, 3, hspace=0.7, wspace=0.3)
    fig.suptitle(
        f"Swiss blue chips vs listed real estate  |  {prices.index[0]:%b %Y} to "
        f"{prices.index[-1]:%b %Y}  |  all prices in CHF",
        fontsize=15,
        fontweight="bold",
    )

    # 1. Growth of 100 CHF
    ax = fig.add_subplot(gs[0, :2])
    for col in baskets:
        ax.plot(baskets.index, 100 * baskets[col], label=col, color=colors[col], lw=1.6)
    ax.set_title("Growth of CHF 100")
    ax.legend(frameon=False)
    ax.grid(alpha=0.3)

    # 2. Risk vs return
    ax = fig.add_subplot(gs[0, 2])
    for name in metrics.index:
        if name in real:
            c = colors["Swiss real estate (equal weight)"]
        elif name == smi:
            c = colors["SMI"]
        else:
            c = colors["Blue chips (equal weight)"]
        ax.scatter(
            metrics.loc[name, "Ann. volatility"] * 100,
            metrics.loc[name, "Ann. return"] * 100,
            color=c,
            s=50,
        )
        ax.annotate(
            name,
            (metrics.loc[name, "Ann. volatility"] * 100, metrics.loc[name, "Ann. return"] * 100),
            fontsize=7,
            xytext=(4, 3),
            textcoords="offset points",
        )
    ax.set_xlabel("Annualised volatility (%)")
    ax.set_ylabel("Annualised return (%)")
    ax.set_title("Risk vs return")
    ax.grid(alpha=0.3)

    # 3. Drawdowns
    ax = fig.add_subplot(gs[1, :2])
    dd = drawdown(baskets) * 100
    for col in dd:
        ax.plot(dd.index, dd[col], label=col, color=colors[col], lw=1.2)
    ax.fill_between(dd.index, dd["SMI"], 0, color=colors["SMI"], alpha=0.15)
    ax.set_title("Drawdown from previous peak (%)")
    ax.grid(alpha=0.3)

    # 4. Correlation heatmap
    ax = fig.add_subplot(gs[1, 2])
    corr = returns.corr()
    im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)))
    ax.set_yticks(range(len(corr)))
    ax.set_xticklabels(corr.columns, rotation=90, fontsize=7)
    ax.set_yticklabels(corr.columns, fontsize=7)
    ax.set_title("Correlation of daily returns")
    fig.colorbar(im, ax=ax, fraction=0.046)

    # 5. Rolling volatility
    ax = fig.add_subplot(gs[2, :2])
    roll_vol = basket_returns.rolling(ROLLING_WINDOW).std() * np.sqrt(TRADING_DAYS) * 100
    for col in roll_vol:
        ax.plot(roll_vol.index, roll_vol[col], label=col, color=colors[col], lw=1.4)
    ax.set_title("Rolling 1-year volatility (%)")
    ax.grid(alpha=0.3)

    # 6. Metrics table (baskets + benchmark)
    ax = fig.add_subplot(gs[2, 2])
    ax.axis("off")
    basket_metrics = compute_metrics(baskets)
    table = basket_metrics.copy()
    for c in ["Ann. return", "Ann. volatility", "Max drawdown", "Daily VaR 95%"]:
        table[c] = (table[c] * 100).map("{:.1f}%".format)
    table["Sharpe"] = table["Sharpe"].map("{:.2f}".format)
    table.index = ["Blue chips", "Real estate", "SMI"]
    tbl = ax.table(
        cellText=table.values,
        rowLabels=table.index,
        colLabels=["Return", "Vol", "Sharpe", "Max DD", "VaR 95%"],
        loc="center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8)
    tbl.scale(1, 1.6)
    ax.set_title("Basket metrics (annualised)")

    fig.text(
        0.5,
        0.01,
        "Past performance does not predict future results. Equal-weight baskets, daily "
        "rebalancing, dividends included via adjusted prices.",
        ha="center",
        fontsize=8,
        color="gray",
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return basket_metrics


# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="download prices again")
    parser.add_argument("--csv", help="use a custom price CSV (date index, one column per stock)")
    args = parser.parse_args()

    prices = load_prices(args.csv, args.refresh)
    metrics = compute_metrics(prices)
    basket_metrics = build_dashboard(prices, metrics, OUT_DIR / "dashboard.png")

    OUT_DIR.mkdir(exist_ok=True)
    pd.concat([metrics, basket_metrics.rename(index={
        "Blue chips (equal weight)": "BASKET Blue chips",
        "Swiss real estate (equal weight)": "BASKET Real estate",
        "SMI": "SMI (basket calc)",
    })]).round(4).to_csv(OUT_DIR / "metrics.csv")

    print(metrics.round(3).to_string())
    print(f"\nSaved {OUT_DIR / 'dashboard.png'} and {OUT_DIR / 'metrics.csv'}")


if __name__ == "__main__":
    main()
