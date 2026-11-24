"""
เช็คสุขภาพระบบอั่งเป่า — รันได้ทุกเมื่อ ไม่กินโควตาซอง ไม่แลกซองจริง

ตรวจ 4 อย่างที่อาจทำให้ระบบพัง:
  1. proxy ต่อได้ไหม            (ถ้าไม่ได้ = 407 whitelist หลุด / โควตาหมด)
  2. IP ที่ออกไปเป็นไทยไหม       (ถ้าไม่ใช่ = TrueMoney อาจบล็อก)
  3. TrueMoney ตอบ JSON ไหม     (ถ้าเป็น HTML = โดน Cloudflare อีกแล้ว)
  4. ยิงตรงไม่ผ่าน proxy เป็นไง  (ไว้เทียบว่ายังต้องใช้ proxy อยู่ไหม)

รันบน VPS:  cd /battlecats && venv/bin/python check_angpao.py
"""
import asyncio, json, sys
from curl_cffi.requests import AsyncSession
import payment as P

FAKE = "0000000000000000000000000000000000"   # hash ปลอม แลกอะไรไม่ได้
URL  = f"https://gift.truemoney.com/campaign/vouchers/{FAKE}/redeem"
HDR  = {"Content-Type": "application/json", "Origin": "https://gift.truemoney.com",
        "Referer": f"https://gift.truemoney.com/campaign/?v={FAKE}"}
BODY = {"mobile": P.TRUEMONEY_ID, "voucher_hash": FAKE}

async def redeem(kwargs):
    async with AsyncSession(**kwargs) as c:
        return await c.post(URL, json=BODY, headers=HDR, timeout=40)

async def main():
    problems = []
    print("=" * 62)
    print("ตรวจสุขภาพระบบอั่งเป่า")
    print("=" * 62)
    print(f"ANGPAO_PROXY = {P.ANGPAO_PROXY or '(ไม่ได้ตั้ง — ยิงตรง)'}")
    print()

    kw = P._angpao_session_kwargs()

    # 1+2) proxy + ประเทศ
    if P.ANGPAO_PROXY:
        try:
            async with AsyncSession(**kw) as c:
                d = json.loads((await c.get("https://ipinfo.io/json", timeout=30)).text)
            th = d.get("country") == "TH"
            print(f"[{'OK ' if th else 'เตือน'}] proxy ใช้ได้ | IP {d.get('ip')} {d.get('city')}, {d.get('country')}")
            print(f"       ISP: {d.get('org','')[:50]}")
            if not th:
                problems.append(f"IP ไม่ใช่ไทย (ได้ {d.get('country')}) — เช็คว่า _country-th ยังตั้งอยู่ไหม")
        except Exception as e:
            print(f"[พัง] ต่อ proxy ไม่ได้: {type(e).__name__}: {str(e)[:70]}")
            problems.append("proxy ต่อไม่ได้ — เช็ค whitelist IP 187.77.156.253 และโควตาที่เหลือ")
    print()

    # 3) TrueMoney ผ่าน proxy
    try:
        r = await redeem(kw)
        isjson = r.text.lstrip().startswith("{")
        if isjson:
            print(f"[OK ] TrueMoney ตอบ JSON | HTTP {r.status_code}")
            print(f"       {r.text[:110]}")
        else:
            print(f"[พัง] TrueMoney ตอบ HTML | HTTP {r.status_code} — โดน Cloudflare")
            print(f"       {r.text[:90]}")
            problems.append("โดน Cloudflare บล็อกอีกแล้ว — ลองเปลี่ยน impersonate เป็นเวอร์ชันใหม่กว่า chrome136")
    except Exception as e:
        print(f"[พัง] ยิง TrueMoney ไม่ได้: {type(e).__name__}: {str(e)[:70]}")
        problems.append("ยิง TrueMoney ไม่สำเร็จ")
    print()

    # 4) เทียบ: ไม่ใช้ proxy
    if P.ANGPAO_PROXY:
        try:
            r2 = await redeem({"impersonate": "chrome136"})
            direct_ok = r2.text.lstrip().startswith("{")
            print(f"[i  ] ยิงตรงไม่ผ่าน proxy: HTTP {r2.status_code} "
                  f"{'ผ่านได้แล้ว (เลิกใช้ proxy ก็ได้)' if direct_ok else 'ยังโดนบล็อก (ยังต้องใช้ proxy)'}")
        except Exception as e:
            print(f"[i  ] ยิงตรงไม่ผ่าน proxy: ล้มเหลว ({type(e).__name__})")

    print()
    print("=" * 62)
    if problems:
        print(f"พบปัญหา {len(problems)} อย่าง:")
        for i, p in enumerate(problems, 1):
            print(f"  {i}. {p}")
        sys.exit(1)
    print("ทุกอย่างปกติ — ระบบอั่งเป่าใช้งานได้")
    sys.exit(0)

asyncio.run(main())
