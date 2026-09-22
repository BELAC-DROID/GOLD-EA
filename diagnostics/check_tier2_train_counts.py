import sys
sys.path.insert(0, r"C:\Users\opc\gold_ea\models")

import duckdb
from level_reaction_core import TIERS, build_classified_all_tiers

con = duckdb.connect(r"C:\Users\opc\gold_ea\data\analytics.duckdb")
build_classified_all_tiers(con)

for train_end in ["2022-12-31", "2023-12-31", "2024-12-31"]:
    print(f"\nTrain period ending {train_end}:")
    print(con.execute(f"""
        SELECT tier_name, count(*) FROM classified_all
        WHERE day <= '{train_end}' GROUP BY tier_name
    """).fetchdf())