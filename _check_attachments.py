import pandas as pd
df = pd.read_csv('/home/myrzaarslan/dev/freedom_hack/tickets.csv', dtype=str, keep_default_na=False)
print("Columns:", list(df.columns))
att_col = [c for c in df.columns if 'ложен' in c.lower() or 'attach' in c.lower()]
print("Attachment column:", att_col)
if att_col:
    vals = df[att_col[0]].unique()
    for v in vals:
        if v.strip():
            print(repr(v))
    print("Non-empty count:", sum(1 for v in df[att_col[0]] if v.strip()))
