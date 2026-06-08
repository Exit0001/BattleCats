import requests, json, sys

tc   = "47d8271b0"
conf = "2788"
base = "http://localhost:8000"

out = open("test_api_result.txt", "w", encoding="utf-8")

def log(*args):
    text = " ".join(str(a) for a in args)
    out.write(text + "\n")
    out.flush()

def test(name, path, body):
    global tc, conf
    log(f"\n{'='*50}")
    log(f"TEST: {name}")
    log(f"{'='*50}")
    log(f"Using TC: {tc} / {conf}")
    try:
        body["transfer_code"] = tc
        body["confirmation_code"] = conf
        r = requests.post(base + path, json=body, timeout=120)
        try:
            data = r.json()
        except:
            log(f"HTTP {r.status_code} — non-JSON: {r.text[:300]}")
            return
        log(f"HTTP {r.status_code}")
        new_tc   = data.get("new_transfer_code", data.get("new_tc"))
        new_conf = data.get("new_confirmation_code")
        log(f"new_tc       : {new_tc or '—'}")
        log(f"new_conf     : {new_conf or '—'}")
        if data.get("error"):
            log(f"error        : {data['error']}")
        else:
            log("status       : OK")
        log_lines = data.get("log", [])
        if log_lines:
            log(f"log ({len(log_lines)} lines):")
            for l in log_lines[:15]:
                log(f"  {l}")
        if data.get("detail"):
            log(f"detail       : {data['detail']}")
        # อัปเดต tc/conf ถ้าได้ใหม่มา
        if new_tc and new_conf:
            tc   = new_tc
            conf = new_conf
            log(f">> TC updated -> {tc} / {conf}")
    except Exception as e:
        log(f"EXCEPTION: {e}")

# 1. Unlock แมว ID 86 (Kamukura)
test("Unlock #86 Kamukura", "/api/unlock/characters",
     {"transfer_code": tc, "confirmation_code": conf, "country": "1",
      "cat_ids": [86]})

# 2. Upgrade แมว ID 86
test("Upgrade #86 Max", "/api/upgrade/characters",
     {"transfer_code": tc, "confirmation_code": conf, "country": "1",
      "cat_ids": [86]})

# 3. True Form #86
test("True Form #86", "/api/trueform/characters",
     {"transfer_code": tc, "confirmation_code": conf, "country": "1",
      "cat_ids": [86]})

# 4. Ultra Form #86
test("Ultra Form #86", "/api/ultraform/characters",
     {"transfer_code": tc, "confirmation_code": conf, "country": "1",
      "cat_ids": [86]})

# 5. Talents #86
test("Talents #86", "/api/talents/characters",
     {"transfer_code": tc, "confirmation_code": conf, "country": "1",
      "cat_ids": [86]})

log("\n\nDONE — Final TC: " + tc + " / " + conf)
out.close()
