# src/session_utils.py
def session_filter(df, start="09:30", end="16:00"):
    df = df[df.index.dayofweek < 5]
    return df.between_time(start, end)
