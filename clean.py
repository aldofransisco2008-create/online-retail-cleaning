"""
Online Retail data cleaning pipeline.

Input : data/raw/online_retail_raw.csv  (UCI Online Retail, 541,909 rows)
Output: data/clean/sales_clean.csv      product sales ready for analysis
        data/clean/cancellations.csv    cancelled order lines
        data/clean/removed_rows.csv     every other dropped row, with a reason
        reports/cleaning_summary.json   row counts for every step

Principle: never silently delete. Every row ends up in exactly one output
file, so the row counts always add back up to the raw total.
"""
import json
from pathlib import Path

import pandas as pd

RAW = Path("data/raw/online_retail_raw.csv")
OUT = Path("data/clean")
REPORTS = Path("reports")

# Stock codes that are fees, postage or manual adjustments, not products.
NON_PRODUCT_CODES = {
    "POST": "postage",
    "DOT": "postage (dotcom)",
    "C2": "carriage",
    "M": "manual adjustment",
    "D": "discount",
    "S": "samples",
    "B": "bad debt adjustment",
    "BANK CHARGES": "bank charges",
    "AMAZONFEE": "amazon fee",
    "CRUK": "charity commission",
    "PADS": "pads to match all cushions (price 0.001)",
}

# Country names standardised to their common English name.
COUNTRY_FIX = {
    "EIRE": "Ireland",
    "RSA": "South Africa",
    "USA": "United States",
    "Unspecified": "Unknown",
}


def load(path: Path) -> pd.DataFrame:
    # Read IDs as text so leading zeros and letter suffixes survive.
    return pd.read_csv(
        path, dtype={"InvoiceNo": str, "StockCode": str, "CustomerID": str}
    )


def standardise(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Description"] = (
        df["Description"].str.strip().str.replace(r"\s+", " ", regex=True)
    )
    df["StockCode"] = df["StockCode"].str.strip().str.upper()
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], format="%m/%d/%Y %H:%M")
    # "17850.0" -> "17850"; missing stays missing (guest checkout), never guessed.
    df["CustomerID"] = df["CustomerID"].str.replace(r"\.0$", "", regex=True)
    df["Country"] = df["Country"].str.strip().replace(COUNTRY_FIX)
    return df


def reason_for(df: pd.DataFrame) -> pd.Series:
    """Label each row with why it is NOT a clean product sale ('' = keep)."""
    reason = pd.Series("", index=df.index, dtype=object)
    code = df["StockCode"]

    def mark(mask, text):
        reason.loc[mask & (reason == "")] = text

    mark(df["InvoiceNo"].str.startswith("C"), "cancellation")
    mark(df["InvoiceNo"].str.startswith("A"), "bad debt adjustment")
    mark(code.isin(NON_PRODUCT_CODES.keys()), "non-product line (fee/postage/adjustment)")
    mark(code.str.startswith("GIFT_"), "gift voucher")
    mark(df["Quantity"] <= 0, "stock adjustment (quantity <= 0)")
    mark(df["UnitPrice"] <= 0, "zero or negative price")
    mark(df["Description"].isna(), "missing description")
    return reason


def match_cancellations(sales: pd.DataFrame, cancels: pd.DataFrame) -> pd.Index:
    """
    Find sale lines that were later cancelled in full.

    A sale matches a cancellation when the customer, stock code and quantity
    are identical and the cancellation happens at or after the sale.
    Matching is one-to-one: each cancellation removes at most one sale.
    """
    s = sales[sales["CustomerID"].notna()].reset_index()
    c = cancels[cancels["CustomerID"].notna()].copy()
    c["Quantity"] = -c["Quantity"]
    key = ["CustomerID", "StockCode", "Quantity"]

    s = s.sort_values("InvoiceDate")
    c = c.sort_values("InvoiceDate")
    s["n"] = s.groupby(key).cumcount()
    c["n"] = c.groupby(key).cumcount()

    m = s.merge(c[key + ["n", "InvoiceDate"]], on=key + ["n"], suffixes=("", "_cancel"))
    m = m[m["InvoiceDate_cancel"] >= m["InvoiceDate"]]
    return pd.Index(m["index"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    steps = {}

    raw = load(RAW)
    steps["raw_rows"] = len(raw)

    df = standardise(raw)

    dup_mask = df.duplicated(keep="first")
    duplicates = df[dup_mask].assign(Reason="exact duplicate row")
    df = df[~dup_mask]
    steps["exact_duplicates_removed"] = len(duplicates)

    df["Reason"] = reason_for(df)
    cancels = df[df["Reason"] == "cancellation"]
    other_removed = df[~df["Reason"].isin(["", "cancellation"])]
    sales = df[df["Reason"] == ""].drop(columns="Reason")

    steps["cancellation_lines"] = len(cancels)
    for r, n in other_removed["Reason"].value_counts().items():
        steps[f"removed: {r}"] = int(n)

    cancelled_idx = match_cancellations(sales, cancels)
    netted = sales.loc[cancelled_idx].assign(Reason="sale later cancelled in full")
    sales = sales.drop(cancelled_idx)
    steps["sales_netted_against_cancellation"] = len(netted)

    sales = sales.assign(
        Revenue=(sales["Quantity"] * sales["UnitPrice"]).round(2),
        HasCustomerID=sales["CustomerID"].notna(),
    ).sort_values(["InvoiceDate", "InvoiceNo"])
    steps["clean_sales_rows"] = len(sales)

    removed = pd.concat([duplicates, other_removed, netted])

    # Every raw row must land in exactly one output file.
    total = len(sales) + len(cancels) + len(removed)
    assert total == steps["raw_rows"], (total, steps["raw_rows"])

    steps["clean_sales_without_customer_id"] = int((~sales["HasCustomerID"]).sum())
    steps["date_range"] = [str(sales["InvoiceDate"].min()), str(sales["InvoiceDate"].max())]
    steps["clean_revenue_gbp"] = round(float(sales["Revenue"].sum()), 2)
    steps["raw_revenue_gbp"] = round(float((raw["Quantity"] * raw["UnitPrice"]).sum()), 2)
    steps["countries"] = int(sales["Country"].nunique())
    steps["products"] = int(sales["StockCode"].nunique())
    steps["invoices"] = int(sales["InvoiceNo"].nunique())

    sales.to_csv(OUT / "sales_clean.csv", index=False)
    cancels.drop(columns="Reason").to_csv(OUT / "cancellations.csv", index=False)
    removed.to_csv(OUT / "removed_rows.csv", index=False)
    (REPORTS / "cleaning_summary.json").write_text(json.dumps(steps, indent=2))

    for k, v in steps.items():
        print(f"{k:45s} {v}")


if __name__ == "__main__":
    main()
