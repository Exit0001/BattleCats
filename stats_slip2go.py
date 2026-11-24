import csv, io
from pathlib import Path

rows = list(csv.DictReader(io.open(Path("logs") / "slip2go_health.csv", encoding="utf-8")))

print(f"{'เวลา':<10} {'HTTP':<5} {'ms':<6} response")
print("-" * 92)
for r in rows:
    t = r["time"][11:]                       # เอาเฉพาะ HH:MM:SS
    note = " ".join(r["note"].split())[:58]  # ยุบบรรทัดให้เหลือบรรทัดเดียว
    mark = "OK  " if r["healthy"] == "1" else "DOWN"
    print(f"{t:<10} {r['status']:<5} {r['ms']:<6} {mark}  {note}")

n = len(rows); ok = sum(1 for r in rows if r["healthy"] == "1")
print("-" * 92)
print(f"รวม {n} ครั้ง | สำเร็จ {ok} | ล้มเหลว {n-ok} | uptime {ok/n*100:.1f}%")
