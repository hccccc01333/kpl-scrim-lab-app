import sqlite3
from pathlib import Path

db = Path("marketing/video/.demo/training.sqlite3")
con = sqlite3.connect(str(db))
cur = con.cursor()
tabs = [r[0] for r in cur.execute("select name from sqlite_master where type='table'")]
print("tables:", tabs)
target = "信则有"
for t in tabs:
    cols = [c[1] for c in cur.execute(f"pragma table_info({t})")]
    for c in cols:
        try:
            n = cur.execute(
                f"select count(*) from {t} where cast({c} as text) like ?", (f"%{target}%",)
            ).fetchone()[0]
        except sqlite3.Error:
            continue
        if n:
            print("HIT", t, c, n)
            sample = cur.execute(
                f"select {c} from {t} where cast({c} as text) like ? limit 1", (f"%{target}%",)
            ).fetchone()[0]
            print("   sample:", str(sample)[:200])
