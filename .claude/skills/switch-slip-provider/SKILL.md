---
name: switch-slip-provider
description: "สลับ provider ตรวจสลิประหว่าง EasySlip กับ Slip2Go — แก้บรรทัดเดียว + วิธี rollback"
---

# Switch Slip Provider Skill

สลับระบบตรวจสลิประหว่าง **EasySlip** ↔ **Slip2Go**

---

## สถานะปัจจุบัน (อัปเดต 1 ก.ย. 2569)

**ตัวหลักเป็นแหล่งเดียว** — ย้ายโค้ด Slip2Go เข้าตัวหลักแล้ว เลิกใช้วิธี 2 โปรเจกต์

| | |
|--|--|
| Path | `...OneDrive\เดสก์ท็อป\btc\BattleCats` |
| Provider | **slip2go** (โค้ด EasySlip ยังอยู่ครบ สลับได้) |
| ตัวโคลน `C:\btc-test\BattleCats` | เหลือไว้เป็น sandbox ทดสอบเท่านั้น **ไม่ใช่ deploy path แล้ว** |

> เหตุผลที่รวม: ต้องแก้ `ITEM_PRICE` บ่อย (เพิ่มสินค้า/แพ็ค) การมี 2 ไฟล์เสี่ยงลืมแก้ฝั่งเดียวแล้วราคาหาย

## คำสั่งที่ใช้

```powershell
cd "c:\Users\modpo\OneDrive\เดสก์ท็อป\btc\BattleCats"

.\deploy-payment.ps1              # deploy payment.py (รันเทส 22 เคสก่อนอัตโนมัติ)
.\switch-provider.ps1 easyslip    # สลับไป EasySlip แล้ว deploy ทันที
.\switch-provider.ps1 slip2go     # สลับกลับ Slip2Go แล้ว deploy
```

`deploy-payment.ps1` จะ **หยุดไม่ deploy ถ้าเทสไม่ผ่าน**

## เครื่องมือ (อยู่ในตัวหลักแล้ว)

| ไฟล์ | ใช้ทำอะไร |
|------|-----------|
| `test_slip_security.py` | เทสด่าน security 22 เคส — ไม่กินโควตา ไม่แตะ DB |
| `check_slip.py <รูป>` | สลิปใบนี้ใครใช้ไปแล้ว + ประวัติคนนั้น |
| `decode_qr.py "<สตริง QR>"` | ถอด transRef + ธนาคาร จาก QR ที่สแกนมา |
| `monitor_slip2go.py` | เก็บ uptime ทุก 30 วิ (ยิงเปล่า ไม่กินโควตา) |
| `stats_slip2go.py` | สรุปสถิติจาก CSV |

**รัน `test_slip_security.py` ทุกครั้งหลังแก้โค้ดสลิป** (deploy script รันให้อยู่แล้ว)

---

## โครงสร้างโค้ด (payment.py)

```
_call_easyslip(image_bytes) → normalized dict
_call_slip2go(image_bytes)  → normalized dict
                ↓
        verify_slip()      ← เช็ค security เหมือนกันทั้ง 2 ค่าย
        verify_cr_slip()
```

**Normalized dict** (ทั้ง 2 provider return หน้าตานี้):
```python
{"ok": bool, "reason": str,
 "recv_name_th": str, "recv_name_en": str,
 "recv_proxy_type": str, "recv_proxy_acct": str, "recv_bank_acct": str,
 "amount": float, "trans_ref": str, "is_duplicate": bool}
```

การเช็ค security (BILLERID / digit groups / ชื่อผู้รับ / ยอด / สลิปซ้ำ) อยู่ใน `verify_slip()`
ใช้ร่วมกันทั้ง 2 provider — **เปลี่ยน provider ไม่กระทบ security**

---

## ข้อมูล provider

### EasySlip
| | |
|--|--|
| Endpoint | `POST https://api.easyslip.com/v2/verify/bank` |
| Auth | `Authorization: Bearer {EASYSLIP_API_KEY}` |
| Key | `1c49e3f0-85f9-4718-b3f6-de74ec35fe30` |
| Field รูป | `image` (+ `data={"matchAccount":"true"}`) |
| สำเร็จ | `data.success == true` |
| ยอด | `data.rawSlip.amount.amount` |
| ชื่อผู้รับ | `data.rawSlip.receiver.account.name.{th,en}` — แยก th/en |
| transRef | `data.rawSlip.transRef` |
| ซ้ำ | `data.isDuplicate` ✅ มี |

### Slip2Go
| | |
|--|--|
| Endpoint | `POST https://connect.slip2go.com/api/verify-slip/qr-image/info` |
| Auth | `Authorization: Bearer {SLIP2GO_API_KEY}` |
| Key | `yO1I5a+lTFR3j8WcEmS8t8A1IHyEXnv7hC0FgdZaNjs=` |
| Field รูป | `file` |
| สำเร็จ | `code == "200000"` |
| ยอด | `data.amount` |
| ชื่อผู้รับ | `data.receiver.account.name` — **string เดียว สลับภาษาได้** ดูด้านล่าง ⚠️ |
| transRef | `data.transRef` |
| ซ้ำ | ❌ ไม่มี — ใช้ `used_slips.json` + Supabase แทน |

> ⚠️ **host คือ `connect.slip2go.com` ไม่ใช่ `api.slip2go.com`**
> `api.slip2go.com` ตอบ 404 ทุก path (เสียเวลาไปแล้วรอบนึง)

### ⚠️ กับดัก: ชื่อผู้รับของ Slip2Go สลับภาษาได้

Slip2Go มีช่องชื่อ **ช่องเดียว** และเปลี่ยนภาษาตามประเภทการโอน:

| ประเภทโอน | ชื่อที่ได้ | proxy.type |
|-----------|-----------|------------|
| PromptPay / e-wallet | `Mr. Sorawit T` (**อังกฤษ**) | `EWALLETID` |
| โอนเข้าบัญชีธนาคาร | `นาย สรวิชญ์ ท` (**ไทย**) | `null` |

→ ใน `_call_slip2go()` ต้องใส่ชื่อลง **ทั้ง** `recv_name_th` และ `recv_name_en`
ไม่งั้นสลิป PromptPay ที่ถูกต้องจะโดน reject ว่า "โอนเข้าบัญชีอื่น"

**ชื่อถูกตัดสั้นด้วย** (`สรวิชญ์ ทองอินทร์` → `สรวิชญ์ ท`) — logic เช็คชื่อจึงหาแค่
คำว่า "สรวิชญ์" / "sorawit" ไม่ใช่ชื่อเต็ม

**เลขบัญชีถูก mask** เหลือ 4 ตัว (`XXXXXXXXXXX6637`) — ใช้ได้กับ logic digit-group เดิม
เพราะเช็คแค่ว่าเลขที่เห็นอยู่ใน `PROMPTPAY_ID` / `KBANK_ACCOUNT` หรือไม่

**Endpoint อื่นของ Slip2Go:**
- `/api/verify-slip/qr-code/info` — ส่ง QR string (ต้อง decode เอง)
- `/api/verify-slip/qr-image/info` — ส่งรูป ✅ **ที่เราใช้**

**Response codes:**
| Code | ความหมาย |
|------|----------|
| `200000` | สำเร็จ |
| `200404` | Slip not found — **อ่าน QR ได้ แต่ธนาคารไม่มีรายการ** (สลิปเก่าเกิน / สลิปปลอม) |
| `200502` | Bank error — ธนาคารขัดข้องชั่วคราว (HTTP ยัง 200 อยู่!) |
| `400002` | File is Incorrect (ไฟล์ผิด/ไม่แนบ) |
| `200500` | Slip is fraud — ไม่ใช่รูปสลิป/อ่าน QR ไม่ได้ (เจอตอนส่งไฟล์ขยะ) |
| `401001` | Authentication Token Mismatch (ไม่ใส่ key) |
| `401002` | Shop not found (key ผิด) |

> ⚠️ Slip2Go ตอบ **HTTP 200/201 เสมอ** แม้ตอน error — ต้องเช็ค `code` ใน body
> ไม่ใช่ status code (ต่างจาก EasySlip ที่ใช้ HTTP status)

### ⚠️ Slip2Go ไม่เสถียร — ต้องมี retry (ยืนยันแล้ว 31 ส.ค. 2569)

เก็บ log ได้จริง 3 request ติดกันใน 5 วินาที สลิปใบเดียวกัน:

```
[20:31:16] attempt 1/3  HTTP 200  {"message":"Bank error, Please try again.","code":"200502"}
[20:31:18] attempt 2/3  HTTP 502  <html>...502 Bad Gateway...nginx/1.30.4
[20:31:21] attempt 3/3  HTTP 502  (เหมือนเดิม)
```

**สิ่งที่ support Slip2Go ยืนยัน:**
- `200502` = ธนาคารส่ง error กลับมา สลิปยังไม่ถึงขั้นตอนตรวจ
- ให้รอสักพักแล้วส่งใหม่
- **ไม่หักโทเคน** สำหรับ error นี้ → retry ได้ฟรี

**สิ่งที่ log บอกเพิ่ม (support ยังไม่ได้อธิบาย):**
- `502 Bad Gateway` มาจาก **nginx ของ Slip2Go เอง** ไม่ใช่ธนาคาร
- request ไปไม่ถึง application server ด้วยซ้ำ = ระบบเขาล่มเป็นช่วงๆ

**→ ห้ามเอา retry ออก** และต้อง retry ทั้ง 2 กรณี:

| เจอ | HTTP | retry? |
|-----|------|--------|
| `200502` Bank error | **200** ← หลุด check `status_code >= 500` ต้องเช็ค body ด้วย | ✅ |
| `502/503/504` | 5xx | ✅ |
| สลิปผิด/ซ้ำ/บัญชีผิด | 4xx หรือ 200 | ❌ |

**ค่า retry ที่ใช้ (ปรับจากข้อมูลจริง):**

```python
_ATTEMPTS = 5
_TIMEOUT  = 10                        # วิ/ครั้ง
_BACKOFF  = (2.0, 5.0, 8.0, 15.0)     # รวม 30 วิ
_DEADLINE = 55                        # เพดานรวม กันลูกค้ารอเป็นนาที
```

**ทำไมต้อง backoff กว้าง 30 วิ** — วัดจริงแล้ว 502 หายภายใน ~26-30 วิ
เคสลูกค้า 31 ส.ค.: ล้มเหลว 21:53:03/05/08 (retry เดิมกว้างแค่ 5 วิ ไม่พอ) แล้ว 21:53:34 กดใหม่ผ่านทันที
→ backoff แคบ = retry เสียเปล่า ลูกค้าต้องกดเอง

**`_DEADLINE` สำคัญ** — 502 ตอบเร็ว (~280ms) เวลาส่วนใหญ่คือ backoff
แต่ถ้า Slip2Go *ค้าง* จริง (timeout ทุกรอบ) จะกลายเป็น 10×5 + 30 = 80 วิ → deadline ตัดที่ 55

### 📊 ข้อมูล uptime จริง (31 ส.ค. 2569, 21:04-22:01)

เก็บด้วย `monitor_slip2go.py` — ยิง POST เปล่า (ไม่แนบ payload) ทุก 30 วิ **ไม่กินโควตา**

```
113 ครั้ง | สำเร็จ 97 | 502 = 16 | uptime 85.8% | latency เฉลี่ย 298ms
```

502 กระจายทั่วชั่วโมง ทุก 1-7 นาที ครั้งละสั้นๆ (< 30 วิ)

> **monitor เป็นสคริปต์แยก ไม่แตะโค้ดร้านเลย** — เป็นหลักฐานชัดว่าปัญหาอยู่ฝั่ง Slip2Go ไม่ใช่โค้ดเรา
> ดูสถิติ: `.venv\Scripts\python.exe -X utf8 stats_slip2go.py`

### Log ไฟล์ — หลักฐานส่ง support

ทุก response ถูกบันทึกที่ `logs/slip2go.log` โดย `_slip2go_log()`
เจอปัญหาเมื่อไหร่ส่งไฟล์นี้ให้ support ได้เลย

### ⚠️ ส่ง content-type ให้ตรงชนิดไฟล์จริง

เดิม hardcode `("slip.jpg", bytes, "image/jpeg")` เสมอ — ลูกค้าอัปโหลด PNG มาก็บอกว่าเป็น jpeg
ใช้ `_sniff_image(bytes)` อ่าน magic bytes แล้วคืน `(filename, mime)` ที่ถูกต้อง (jpg/png/webp)

### แยกให้ออก: อ่าน QR ไม่ได้ vs ธนาคารไม่มีข้อมูล

| Code | อ่าน QR | ถามธนาคาร | สาเหตุ |
|------|---------|-----------|--------|
| `400002` | ❌ ไม่ได้ | — | ไฟล์เสีย/ไม่ใช่รูปสลิป/QR ไม่ชัด |
| `200404` | ✅ ได้ | ❌ ไม่มีรายการ | ธนาคารยังไม่บันทึก (เพิ่งโอน) / สลิปปลอม |

→ เจอ `200404` **ไม่ได้แปลว่าธนาคารนั้นไม่รองรับ** — เคยเจอกับสลิป MAKE ที่โอนเสร็จแล้ว
ยิงเช็คทันที พอลองใหม่อีกรอบผ่านปกติ ให้ลองซ้ำก่อนสรุปเสมอ

### ธนาคาร/แอปที่ทดสอบแล้วใช้ได้กับ Slip2Go

| แอป/ธนาคาร | ผล | หมายเหตุ |
|------------|-----|----------|
| PromptPay / e-wallet | ✅ | proxy type `EWALLETID`, ชื่ออังกฤษ |
| กสิกรไทย (K PLUS) | ✅ | proxy `null`, ใช้ `bank.account` แทน |
| **MAKE by KBank** | ✅ | อ่านได้ปกติ (เคยเข้าใจผิดว่าไม่รองรับ) |
| กรุงไทย | ✅ | |
| กรุงศรีอยุธยา | ✅ | |

### วิธี A/B test สลิปใบเดียวกันกับ 2 ค่าย

```python
cd C:\btc-test\BattleCats
./.venv/Scripts/python.exe -c "
import asyncio, json, payment as P
img = open(r'PATH\TO\slip.jpg','rb').read()
async def m():
    print('SLIP2GO :', json.dumps(await P._call_slip2go(img), ensure_ascii=False))
    print('EASYSLIP:', json.dumps(await P._call_easyslip(img), ensure_ascii=False))
asyncio.run(m())
"
```

> ใช้ตอนสงสัยว่าปัญหาอยู่ที่ provider หรือที่ตัวสลิป — ตอบได้ชัดในคำสั่งเดียว

---

## จุดที่ใช้ตรวจสลิป (main.py) — ครบ 4 จุด

| Line | Endpoint | ใช้ฟังก์ชัน |
|------|----------|-------------|
| ~866 | `payment_verify` — ร้านหลัก | `verify_slip()` |
| ~2613 | `api_code_shop_verify` — ซื้อรหัส | `verify_slip()` |
| ~3263 | `api_wallet_verify` — เติมเงิน | `verify_slip()` |
| ~2924 | `api_cr_verify` — Cookie Run | `verify_cr_slip()` |

ทุกจุดผ่าน switch หมด — เปลี่ยนที่เดียวมีผลทั้งระบบ

---

## วิธีทดสอบว่า key ใช้ได้ (ไม่เปลือง quota)

```python
import httpx
KEY = "..."
r = httpx.post("https://connect.slip2go.com/api/verify-slip/qr-code/info",
               headers={"Authorization": f"Bearer {KEY}"}, timeout=15)
print(r.status_code, r.text)
```

| ผลลัพธ์ | แปลว่า |
|---------|--------|
| `400 payload should not be empty` | ✅ key ใช้ได้ |
| `401002 Shop not found` | ❌ key ผิด |
| `401001 Authentication Token Mismatch` | ❌ ไม่ได้ส่ง key |

---

## Deploy ขึ้น VPS (ตัวหลักเท่านั้น — ห้าม deploy จากตัวโคลน)

```powershell
$pass = ConvertTo-SecureString "SZ/(-6p-x/(yXXQW" -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential("root", $pass)
$base = "c:\Users\modpo\OneDrive\เดสก์ท็อป\btc\BattleCats"
Set-SCPItem -ComputerName "187.77.156.253" -Credential $cred -Path "$base\payment.py" -Destination "/battlecats/" -Force -AcceptKey
$s = New-SSHSession -ComputerName "187.77.156.253" -Credential $cred -AcceptKey -Force
Invoke-SSHCommand -SSHSession $s -Command "systemctl restart battlecats && echo OK"
Remove-SSHSession $s
```

---

## หมายเหตุ

- EasySlip ล่มบ่อย (ส.ค. 2569 ล่ม 7-8 รอบ) — เจอ 404/500 ให้แจ้ง support พร้อม status code + เวลา
- ระหว่าง provider ล่ม → เช็คสลิปมือใน K PLUS แล้ว process ผ่าน admin panel
- ห้ามลบโค้ด provider เก่า — เก็บไว้ทั้ง 2 ตัวเสมอเพื่อ rollback ได้ทันที
