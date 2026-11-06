import sqlite3
conn = sqlite3.connect(r"C:\Users\zhija\.gemini\antigravity\scratch\power-manager\power_history.db")
c = conn.cursor()
print("Top Real Apps by Energy Share:")
for row in c.execute("SELECT app_name, category, cpu_seconds, ram_mb, est_wh, share_pct FROM app_energy_logs ORDER BY cpu_seconds DESC"):
    print(f" - {row[0]} ({row[1]}): CPU {row[2]}s | RAM {row[3]}MB | {row[4]} Wh ({row[5]}%)")
print("\nDaily Summaries (Past 7 days):")
for row in c.execute("SELECT date_key, ROUND(SUM(wh)/1000.0, 2) as kwh, ROUND(AVG(avg_watts), 1), ROUND(MAX(peak_watts), 1) FROM hourly_logs GROUP BY date_key ORDER BY date_key DESC LIMIT 7"):
    print(f" - {row[0]}: {row[1]} 度 (kWh) | Avg {row[2]} W | Peak {row[3]} W")
conn.close()
