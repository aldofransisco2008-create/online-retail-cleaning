"""Before/after charts for the README. Run after clean.py."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPORTS = Path("reports")
INK, MUTED, ACCENT, WARN, GRID = "#16201d", "#5d6965", "#1f6b58", "#b5651d", "#e3e7e5"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11,
    "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED,
    "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 150,
})

summary = json.loads((REPORTS / "cleaning_summary.json").read_text())

# 1. Where the removed rows went -------------------------------------------
labels = {
    "exact_duplicates_removed": "Exact duplicate rows",
    "cancellation_lines": "Cancellation lines (invoice 'C...')",
    "sales_netted_against_cancellation": "Sales later cancelled in full",
    "removed: non-product line (fee/postage/adjustment)": "Postage, fees, manual adjustments",
    "removed: stock adjustment (quantity <= 0)": "Stock write-offs (quantity <= 0)",
    "removed: zero or negative price": "Zero or negative price",
    "removed: gift voucher": "Gift vouchers",
    "removed: bad debt adjustment": "Bad debt adjustments",
}
items = sorted(((labels[k], summary[k]) for k in labels if k in summary), key=lambda x: x[1])
fig, ax = plt.subplots(figsize=(8, 4.2))
names, vals = zip(*items)
bars = ax.barh(names, vals, color=ACCENT, height=0.6)
for b, v in zip(bars, vals):
    ax.text(b.get_width() + max(vals) * 0.01, b.get_y() + b.get_height() / 2,
            f"{v:,}", va="center", color=INK, fontsize=10)
ax.set_xlim(0, max(vals) * 1.15)
ax.xaxis.grid(True, color=GRID)
ax.set_axisbelow(True)
ax.tick_params(axis="y", length=0)
ax.set_title(f"{summary['raw_rows'] - summary['clean_sales_rows']:,} of "
             f"{summary['raw_rows']:,} rows set aside, each with a reason",
             loc="left", color=INK, fontsize=13, pad=12)
fig.tight_layout()
fig.savefig(REPORTS / "rows_set_aside.png")
plt.close(fig)

# 2. Top products: naive filter vs full cleaning ---------------------------
# "Naive" = the common shortcut of only dropping invoices that start with C.
raw = pd.read_csv("data/raw/online_retail_raw.csv", dtype={"InvoiceNo": str},
                  usecols=["InvoiceNo", "Description", "Quantity", "UnitPrice"])
naive = raw[~raw["InvoiceNo"].str.startswith("C")]
naive_top = ((naive["Quantity"] * naive["UnitPrice"]).groupby(naive["Description"].str.strip())
             .sum().nlargest(5) / 1000)
clean = pd.read_csv("data/clean/sales_clean.csv", usecols=["Description", "Revenue"])
clean_top = clean.groupby("Description")["Revenue"].sum().nlargest(5) / 1000

wrong = {"DOTCOM POSTAGE": "postage, not a product",
         "PAPER CRAFT , LITTLE BIRDIE": "one 80,995-unit order, cancelled"}

fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharex=True)
for ax, top, title in [(axes[0], naive_top, "Naive: only drop 'C' invoices"),
                       (axes[1], clean_top, "After full cleaning")]:
    s = top.iloc[::-1]
    colors = [WARN if d in wrong else ACCENT for d in s.index]
    bars = ax.barh(range(len(s)), s.values, color=colors, height=0.6)
    ax.set_yticks(range(len(s)))
    ax.set_yticklabels([d.title() if len(d) < 30 else d.title()[:28] + "…" for d in s.index])
    for b, (d, v) in zip(bars, s.items()):
        note = f"£{v:,.0f}k" + (f"  ← {wrong[d]}" if d in wrong else "")
        ax.text(v + 3, b.get_y() + b.get_height() / 2, note, va="center",
                fontsize=9, color=WARN if d in wrong else INK)
    ax.set_title(title, loc="left", color=INK, fontsize=12, pad=10)
    ax.xaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)
axes[0].set_xlim(0, 330)
axes[0].set_xlabel("Revenue (£ thousand)")
axes[1].set_xlabel("Revenue (£ thousand)")
fig.suptitle("Top 5 products by revenue", x=0.01, ha="left", color=INK, fontsize=14)
fig.tight_layout()
fig.savefig(REPORTS / "top_products_naive_vs_clean.png")
plt.close(fig)

naive_total = (naive["Quantity"] * naive["UnitPrice"]).sum()
print(f"naive total £{naive_total:,.0f}  clean total £{summary['clean_revenue_gbp']:,.0f}  "
      f"overstated by £{naive_total - summary['clean_revenue_gbp']:,.0f} "
      f"({(naive_total / summary['clean_revenue_gbp'] - 1) * 100:.1f}%)")
