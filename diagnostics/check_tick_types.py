import pandas as pd

CSV_PATH = r"C:\Users\opc\Documents\XAUUSDm_202601012305_202609180105new.csv"

chunk = pd.read_csv(CSV_PATH, sep="\t", nrows=500_000)
chunk.columns = [c.strip("<>") for c in chunk.columns]
chunk["BID"] = pd.to_numeric(chunk["BID"], errors="coerce")
chunk["ASK"] = pd.to_numeric(chunk["ASK"], errors="coerce")

both_missing = (chunk["BID"].isna() & chunk["ASK"].isna()).sum()
only_bid_missing = (chunk["BID"].isna() & chunk["ASK"].notna()).sum()
only_ask_missing = (chunk["ASK"].isna() & chunk["BID"].notna()).sum()
both_present = (chunk["BID"].notna() & chunk["ASK"].notna()).sum()

print(f"Rows checked: {len(chunk):,}")
print(f"Both BID and ASK present:     {both_present:,}")
print(f"Only BID missing (ASK only):  {only_ask_missing:,}")
print(f"Only ASK missing (BID only):  {only_bid_missing:,}")
print(f"Both missing (pure trade tick): {both_missing:,}")

print("\nFLAGS value breakdown by row type:")
print("-- Both present --")
print(chunk[chunk["BID"].notna() & chunk["ASK"].notna()]["<FLAGS>" if "<FLAGS>" in chunk.columns else "FLAGS"].value_counts())

print("\n-- Both missing (if any) --")
both_missing_rows = chunk[chunk["BID"].isna() & chunk["ASK"].isna()]
if len(both_missing_rows) > 0:
    print(both_missing_rows.head(10))
else:
    print("(none found in this sample)")

print("\n-- Only one side missing (if any) --")
partial_rows = chunk[chunk["BID"].isna() ^ chunk["ASK"].isna()]
if len(partial_rows) > 0:
    print(partial_rows.head(10))
else:
    print("(none found in this sample)")