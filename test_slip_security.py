"""
ชุดทดสอบด่าน security ของ verify_slip()

จำลอง response จาก provider (ไม่ยิง API จริง) เพื่อ:
  - ไม่กินโควตา Slip2Go
  - ไม่เขียน Supabase / ไม่สร้าง order จริง
  - เทสเคสที่หาสลิปจริงมาเทสไม่ได้ (เช่น BILLERID, ยอดไม่พอ)

รัน: .venv/Scripts/python.exe -X utf8 test_slip_security.py
"""
import asyncio
import payment as P

# ---- ปิดทุกอย่างที่เขียนข้อมูลจริง ----
_orders = {}
P.get_order = lambda oid: _orders.get(oid)
P.update_order_status = lambda *a, **k: None
P._is_transaction_used = lambda tx: tx in _USED_SUPABASE
P._load_slips = lambda: _USED_LOCAL

_USED_SUPABASE = set()
_USED_LOCAL = set()

OK_RECV = {
    "recv_name_th": "นาย สรวิชญ์ ท", "recv_name_en": "นาย สรวิชญ์ ท",
    "recv_proxy_type": "", "recv_proxy_acct": "", "recv_bank_acct": "xxxxx1629x",
}

def resp(**over):
    r = {"ok": True, "amount": 100.0, "trans_ref": "TX-TEST-1",
         "is_duplicate": False, **OK_RECV}
    r.update(over)
    return r

async def run(name, provider_resp, order_amount=100, expect_ok=True, used_local=(), used_sup=()):
    global _USED_LOCAL, _USED_SUPABASE
    _USED_LOCAL, _USED_SUPABASE = set(used_local), set(used_sup)
    _orders["T1"] = {"order_id": "T1", "amount": order_amount, "status": "pending",
                     "expires_at": "2099-01-01T00:00:00+07:00"}
    P._call_slip2go = lambda img: _ret(provider_resp)
    P.SLIP_PROVIDER = "slip2go"
    r = await P.verify_slip(b"fake", "T1")
    got = r["success"]
    mark = "PASS" if got == expect_ok else "**FAIL**"
    want = "ผ่าน" if expect_ok else "ปฏิเสธ"
    detail = "" if got == expect_ok else f"   <-- คาดว่า{want} แต่ได้ {got}"
    reason = r.get("reason", "")[:52]
    print(f"  [{mark}] {name:<42} {'ผ่าน' if got else 'ปฏิเสธ':<7} {reason}{detail}")
    return got == expect_ok

async def _ret(v):
    return v

async def main():
    print("=" * 104)
    print("ทดสอบด่าน security ของ verify_slip()  (จำลอง response ไม่ยิง API)")
    print("=" * 104)
    results = []

    print("\n--- ต้องผ่าน ---")
    results.append(await run("สลิปถูกต้อง ชื่อไทย", resp(), 100, True))
    results.append(await run("ชื่ออังกฤษ (PromptPay)", resp(
        recv_name_th="Mr. Sorawit T", recv_name_en="Mr. Sorawit T",
        recv_proxy_type="EWALLETID", recv_proxy_acct="XXXXXXXXXXX6637", recv_bank_acct=""), 100, True))
    results.append(await run("เลขบัญชีเต็ม ไม่ mask", resp(
        recv_proxy_type="EWALLETID", recv_proxy_acct="004999236376637", recv_bank_acct=""), 100, True))
    results.append(await run("ชื่อเต็ม สรวิชญ์ ทองอินทร์", resp(
        recv_name_th="นาย สรวิชญ์ ทองอินทร์", recv_name_en="นาย สรวิชญ์ ทองอินทร์"), 100, True))
    results.append(await run("จ่ายเกิน (ส่วนเกินเข้า wallet)", resp(amount=150.0), 100, True))

    print("\n--- ต้องปฏิเสธ (ถ้าผ่าน = เสียเงินจริง) ---")
    results.append(await run("โอนเข้าบัญชีคนอื่น", resp(recv_bank_acct="xxxxx9999x",
        recv_name_th="บจก. อ", recv_name_en="บจก. อ"), 100, False))
    results.append(await run("ชื่อผู้รับผิด (เลขบัญชีถูก)", resp(
        recv_name_th="นาย สมชาย ใจดี", recv_name_en="นาย สมชาย ใจดี"), 100, False))
    results.append(await run("BILLERID (จ่ายบิล/ร้านค้า)", resp(
        recv_proxy_type="BILLERID", recv_proxy_acct="xxxxx1629x",
        recv_name_th="บจก. ไลน์แมน", recv_name_en="LINEMAN"), 100, False))
    results.append(await run("ยอดไม่พอ (จ่าย 50 ต้อง 100)", resp(amount=50.0), 100, False))
    results.append(await run("สลิปซ้ำ (local used_slips)", resp(), 100, False, used_local=["TX-TEST-1"]))
    results.append(await run("สลิปซ้ำ (Supabase)", resp(), 100, False, used_sup=["TX-TEST-1"]))
    results.append(await run("provider ตอบ isDuplicate", resp(is_duplicate=True), 100, False))
    results.append(await run("ไม่มีข้อมูลผู้รับเลย", resp(
        recv_name_th="", recv_name_en="", recv_proxy_type="",
        recv_proxy_acct="", recv_bank_acct=""), 100, False))
    results.append(await run("provider error (502/ล่ม)", {"ok": False,
        "reason": "ระบบเช็คสลิปขัดข้องชั่วคราว"}, 100, False))

    print("\n" + "=" * 104)
    n, ok = len(results), sum(results)
    print(f"ผลรวม: {ok}/{n} ผ่าน" + ("   ✅ ปลอดภัย ทุกด่านทำงานถูกต้อง" if ok == n else f"   ❌ มี {n-ok} เคสที่ผิดพลาด!"))
    print("=" * 104)

asyncio.run(main())

# ============================================================
# ส่วนที่ 2 — สลับ provider + ตรวจชนิดไฟล์
# ============================================================
import io as _io

async def part2():
    print()
    print("=" * 104)
    print("ทดสอบการสลับ provider (ทางหนีไฟ) + ตรวจชนิดไฟล์")
    print("=" * 104)
    res = []

    # --- สลับ provider ---
    print("\n--- สลับ SLIP_PROVIDER ต้องเรียกฟังก์ชันถูกตัว ---")
    called = []
    async def fake_s2g(img): called.append("slip2go");  return resp()
    async def fake_esl(img): called.append("easyslip"); return resp()
    P._call_slip2go, P._call_easyslip = fake_s2g, fake_esl
    _orders["T1"] = {"order_id":"T1","amount":100,"status":"pending",
                     "expires_at":"2099-01-01T00:00:00+07:00"}

    for prov, want in [("slip2go","slip2go"), ("easyslip","easyslip")]:
        called.clear()
        globals()['_USED_LOCAL'] = set(); globals()['_USED_SUPABASE'] = set()
        P.SLIP_PROVIDER = prov
        r = await P.verify_slip(b"x", "T1")
        good = called == [want] and r["success"]
        res.append(good)
        print(f"  [{'PASS' if good else '**FAIL**'}] SLIP_PROVIDER='{prov}' -> เรียก {called or ['ไม่มี']}")

    # verify_cr_slip ต้องสลับตามด้วย
    P.get_cr_order = lambda oid: {"order_id":"C1","amount":100,"status":"pending",
                                  "expires_at":"2099-01-01T00:00:00+07:00"}
    P.update_cr_order_status = lambda *a, **k: None
    for prov, want in [("slip2go","slip2go"), ("easyslip","easyslip")]:
        called.clear()
        globals()['_USED_LOCAL'] = set(); globals()['_USED_SUPABASE'] = set()
        P.SLIP_PROVIDER = prov
        r = await P.verify_cr_slip(b"x", "C1")
        good = called == [want] and r["success"]
        res.append(good)
        print(f"  [{'PASS' if good else '**FAIL**'}] verify_cr_slip '{prov}' -> เรียก {called or ['ไม่มี']}")

    # --- ตรวจชนิดไฟล์ ---
    print("\n--- _sniff_image ต้องบอกชนิดไฟล์ถูก ---")
    cases = [
        ("PNG",  bytes([0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A]) + b"x"*20, "image/png"),
        ("JPEG", bytes([0xFF,0xD8,0xFF]) + b"x"*20,                          "image/jpeg"),
        ("WEBP", b"RIFF" + b"\x00"*4 + b"WEBP" + b"x"*20,                     "image/webp"),
        ("ขยะ",  b"notanimage" + b"x"*20,                                     "image/jpeg"),
    ]
    for label, data, want_mime in cases:
        fn, mime = P._sniff_image(data)
        good = mime == want_mime
        res.append(good)
        print(f"  [{'PASS' if good else '**FAIL**'}] {label:<5} -> {fn}, {mime}")

    print()
    print("=" * 104)
    n, ok = len(res), sum(res)
    print(f"ส่วนที่ 2: {ok}/{n} ผ่าน" + ("   ✅ สลับ provider ได้ปลอดภัย" if ok==n else f"   ❌ มี {n-ok} เคสผิด!"))
    print("=" * 104)

asyncio.run(part2())
