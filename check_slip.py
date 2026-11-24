"""
ตรวจสลิป: รูปสลิป -> transRef -> ใครใช้ไปแล้ว

ใช้ตอนสงสัยว่าสลิปใบนี้ถูกใช้ไปหรือยัง / ใครเอาไปใช้

รัน:  .venv/Scripts/python.exe -X utf8 check_slip.py "C:/path/to/slip.jpg"
"""
import asyncio, sys, httpx
import payment as P

if len(sys.argv) < 2:
    print("ใช้: check_slip.py <path รูปสลิป>")
    raise SystemExit(1)

path = sys.argv[1]
img = open(path, "rb").read()
print(f"ไฟล์: {path}  ({len(img):,} bytes)")
print()

r = asyncio.run(P._call_slip2go(img))
if not r["ok"]:
    print(f"อ่านสลิปไม่ได้: {r['reason']}")
    raise SystemExit(1)

tx = r["trans_ref"]
print("=" * 74)
print(f"  transRef (ID ที่ระบบใช้) : {tx}")
print(f"  ยอด                      : {r['amount']}")
print(f"  ผู้รับ                    : {r['recv_name_th']}")
print("=" * 74)
print()

h = {"apikey": P.SUPABASE_KEY, "Authorization": f"Bearer {P.SUPABASE_KEY}"}
res = httpx.get(f"{P.SUPABASE_URL}/rest/v1/orders",
                params={"transaction_id": f"eq.{tx}",
                        "select": "order_id,amount,status,paid_at,username"},
                headers=h, timeout=20).json()

if not res:
    print("ยังไม่มีใครใช้สลิปนี้")
else:
    for o in res:
        print("!! สลิปนี้ถูกใช้ไปแล้ว")
        print(f"   order    : {o.get('order_id')}")
        print(f"   ยอด      : B{o.get('amount')}")
        print(f"   สถานะ    : {o.get('status')}")
        print(f"   ใช้เมื่อ  : {(o.get('paid_at') or '')[:19].replace('T',' ')}")
        print(f"   username : {o.get('username')}")
        u = o.get("username")
        if u:
            hist = httpx.get(f"{P.SUPABASE_URL}/rest/v1/orders",
                             params={"username": f"eq.{u}", "status": "eq.done",
                                     "select": "paid_at,amount,transaction_id",
                                     "order": "paid_at.desc", "limit": "8"},
                             headers=h, timeout=20).json()
            print()
            print(f"   ประวัติ 8 รายการล่าสุดของ {u}:")
            for x in hist:
                mark = "  <-- ใบนี้" if x.get("transaction_id") == tx else ""
                print(f"     {(x.get('paid_at') or '')[:19].replace('T',' ')}  B{str(x.get('amount')):<5} {x.get('transaction_id')}{mark}")
