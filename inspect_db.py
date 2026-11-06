import sqlite3, os
p = r"C:\Users\zhija\.gemini\antigravity\scratch\power-manager\power_history.db"
conn = sqlite3.connect(p)
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", c.fetchall())
c.execute("SELECT COUNT(*), MIN(hour_key), MAX(hour_key) FROM hourly_logs")
print("Hourly stats:", c.fetchone())
conn.close()
