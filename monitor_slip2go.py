"""
Slip2Go health monitor — เก็บสถิติความเสถียร โดยไม่กินโควตาสลิป

ยิง endpoint โดยไม่แนบ payload:
  ระบบปกติ  -> HTTP 400 {"message":"payload should not be empty"}   (nginx + app ทำงาน)
  ระบบล่ม   -> HTTP 502/503/504 จาก nginx                            (app server ตาย)
  key ผิด   -> HTTP 401

ไม่มีการตรวจสลิปจริง = ไม่หักโทเคน

รัน:  .venv/Scripts/python.exe monitor_slip2go.py
หยุด: Ctrl+C
"""
import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

TZ = timezone(timedelta(hours=7))
KEY = "yO1I5a+lTFR3j8WcEmS8t8A1IHyEXnv7hC0FgdZaNjs="
URL = "https://connect.slip2go.com/api/verify-slip/qr-code/info"
OUT = Path("logs") / "slip2go_health.csv"
INTERVAL = 30          # วินาที

OUT.parent.mkdir(exist_ok=True)
new_file = not OUT.exists()
with open(OUT, "a", newline="", encoding="utf-8") as f:
    if new_file:
        csv.writer(f).writerow(["time", "status", "ms", "healthy", "note"])

print(f"เริ่มเก็บข้อมูล -> {OUT}  (ทุก {INTERVAL} วินาที, Ctrl+C เพื่อหยุด)")
n = ok = 0
try:
    while True:
        t0 = time.time()
        try:
            r = httpx.post(URL, headers={"Authorization": f"Bearer {KEY}"}, timeout=15)
            ms = int((time.time() - t0) * 1000)
            status = r.status_code
            healthy = status < 500
            note = r.text[:80].replace("\n", " ")
        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            status = 0
            healthy = False
            note = f"{type(e).__name__}: {e}"[:80]

        n += 1
        ok += 1 if healthy else 0
        ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        with open(OUT, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([ts, status, ms, int(healthy), note])

        mark = "OK " if healthy else "DOWN"
        print(f"[{ts}] {mark} HTTP {status} {ms}ms   ({ok}/{n} = {ok/n*100:.1f}% uptime)")
        time.sleep(INTERVAL)
except KeyboardInterrupt:
    print(f"\nหยุดแล้ว — เก็บได้ {n} ครั้ง, uptime {ok/n*100:.1f}%" if n else "\nหยุดแล้ว")
