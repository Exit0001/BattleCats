# Battle Cats Shop — Project Context

## โปรเจกต์คืออะไร
ร้านค้าออนไลน์สำหรับเกม Battle Cats — ลูกค้าสั่งซื้อของ/ปลดล็อคแมว แล้ว admin รัน BCSFE แก้ save file แล้วส่ง Transfer Code ใหม่กลับ

## Stack
- **Frontend**: HTML/CSS/JS vanilla (dark theme, Chakra Petch + Russo One)
- **Backend**: FastAPI (Python) — `main.py`
- **Database**: Supabase (orders, auth)
- **BCSFE**: Python library `bcsfe` 3.4.0 — แก้ save file ผ่าน Transfer Code
- **Payment**: PromptPay QR + SlipOK verification

## ไฟล์หลัก
| ไฟล์ | หน้าที่ |
|------|---------|
| `main.py` | FastAPI server, API routes ทั้งหมด |
| `runner.py` | BCSFERunner — download/edit/upload save |
| `config.py` | ITEM_MAP, AMOUNT_OPTIONS, COUNTRIES |
| `models.py` | Pydantic request/response models |
| `payment.py` | สร้าง order, QR PromptPay, verify slip |
| `test_no_payment.html` | หน้าทดสอบ admin (ไม่ต้องจ่ายเงิน) |
| `assets/characters_data.js` | ข้อมูลแมวทั้งหมด (id, tier, name) |

## API Routes (main.py)
```
POST /api/test/bcsfe               ทดสอบเพิ่มของ
POST /api/unlock/characters        ปลดล็อคแมว
POST /api/upgrade/characters       อัพเกรด max level (by IDs)
POST /api/upgrade/all              อัพเกรด max ทุกตัวใน save
POST /api/trueform/characters      True Form
POST /api/ultraform/characters     Ultra Form (4th form)
POST /api/talents/characters       Max Talents
POST /api/payment/create           สร้าง order + QR
POST /api/payment/verify/{id}      verify สลิป + รัน BCSFE
```

---

## BCSFE Runner — วิธีที่ถูกต้อง

### Upgrade Characters
ใช้ `PowerUpHelper.max_upgrade()` เสมอ ห้าม hardcode `base = 29`

```python
power_up = core.PowerUpHelper(cat, save_file)
power_up.reset_upgrade()   # reset base=0, catseyes_used=0
power_up.max_upgrade()     # อ่าน max_upgrade_level_catseye ต่อแมว
cat.upgrade.plus = 0       # reset plus = 0 เสมอ
```

**Max level ต่อ rarity (with catseyes):**
- Uber Rare → **Lv 60**
- Super Rare / Rare → **Lv 50**
- Normal / Special → **Lv 30**

> ❌ ข้อผิดพลาดเดิม: `cat.upgrade.base = 29` → ได้แค่ Lv30 และ plus ไม่ reset

### Talents Max
ต้องอ่าน max levels จาก `talent_data` (game data) ไม่ใช่ `talent.max_level`

```python
talent_data = save_file.cats.read_talent_data(save_file)
data = talent_data.get_cat_talents(cat)
_names, max_levels, _cur, ids = data
for i, tid in enumerate(ids):
    talent = cat.get_talent_from_id(tid)
    if talent:
        talent.level = max_levels[i]
```

> ❌ ข้อผิดพลาดเดิม: `talent.max_level` ไม่มี attribute นี้ → talents ไม่ขึ้น

### Unlock Characters
```python
cat.unlocked = 1
cat.gatya_seen = 1
if cat.unlocked_forms == 0:
    cat.unlocked_forms = 1
```

### True Form / Ultra Form
```python
cat.true_form(save_file)           # True Form (3rd)
cat.unlock_fourth_form(save_file)  # Ultra Form (4th)
```

### Log Format (ทุก method return log array)
```
✔ #86 — Lv1+0 → Lv50+0
✔ #86 — 8 talents maxed
✔ #86 — True Form applied
✔ #86 — unlocked
✘ #999 — ไม่พบใน save
— #5 — ไม่มี talent data
```

---

## กฎสำคัญ — ขอบเขตของแต่ละคำสั่ง

| คำสั่ง | ทำกับ |
|--------|-------|
| **Unlock** | ตัวละคร**ทุกตัวในเกม** (all cats) |
| **Upgrade** | เฉพาะตัวละครที่ลูกค้า**มีอยู่แล้ว** |
| **True Form** | เฉพาะตัวละครที่ลูกค้า**มีอยู่แล้ว** |
| **Ultra Form** | เฉพาะตัวละครที่ลูกค้า**มีอยู่แล้ว** |
| **Talents Max** | เฉพาะตัวละครที่ลูกค้า**มีอยู่แล้ว** |

---

## BCSFE CLI Workflows (คำสั่ง All)

> ใช้แสดงขั้นตอนเมื่อ user ขอทำแบบ All — เป็นสินค้าราคาเพิ่มให้ลูกค้าซื้อ

### 1. Unlock All Characters (ปลดล็อกทุกตัวในเกม)
1. กด **3** → เมนู Cat / Special Skills
2. กด **2** → Unlock Character
3. กด **1** → ปลดทุกตัว
4. กด **y** → ยืนยัน (finished selecting cats)
5. กด **1** → ยืนยันคำสั่ง unlock
6. กด **1** → Save Management
7. กด **3** → รับ Transfer Code ใหม่

### 2. Upgrade All Max (No +) (อัปเกรดตัวที่มีทุกตัวให้เลเวลตัน)
1. กด **3** → เมนู Cat / Special Skills
2. กด **3** → Upgrade Cats
3. กด **2** → Cat ที่มี (owned cats)
4. กด **y** → ยืนยัน (finished selecting cats)
5. กด **2** → เลือกเวลทุกตัวในครั้งเดียว
6. พิมพ์ **max** → ตัวละครเลเวลตัน
7. กด **1** → Save Management
8. กด **3** → รับ Transfer Code ใหม่

### 3. True Form All (ทำร่าง True Form ตัวที่มีทุกตัว)
1. กด **3** → เมนู Cat / Special Skills
2. กด **4** → True Form Cats
3. กด **2** → Cat ที่มี (owned cats)
4. กด **y** → ยืนยัน (finished selecting cats)
5. กด **1** → ยืนยันคำสั่ง True Form
6. กด **1** → Save Management
7. กด **3** → รับ Transfer Code ใหม่

### 4. Ultra Form All (ทำร่าง Ultra Form ตัวที่มีทุกตัว)
1. กด **3** → เมนู Cat / Special Skills
2. กด **6** → Ultra Form Cats
3. กด **2** → Cat ที่มี (owned cats)
4. กด **y** → ยืนยัน (finished selecting cats)
5. กด **1** → ยืนยันคำสั่ง Ultra Form
6. กด **1** → Save Management
7. กด **3** → รับ Transfer Code ใหม่

### 5. Talents Max All (อัปเกรด Talents ตัวที่มีทุกตัวให้เต็ม)
1. กด **3** → เมนู Cat / Special Skills
2. กด **8** → Upgrade Talents Cats
3. กด **2** → Cat ที่มี (owned cats)
4. กด **y** → ยืนยัน (finished selecting cats)
5. กด **1** → ยืนยันคำสั่ง
6. กด **2** → Max Upgrade Talents
7. กด **1** → Save Management
8. กด **3** → รับ Transfer Code ใหม่

### 6. Lucky Ticket (เพิ่มตั๋วโชคดี)

> ⚠️ Max value รวมสูงสุด **2,999** | วิธีคำนวณ: `current + จำนวนที่ต้องการ` (แสดงสมการให้ admin ดูก่อนพิมพ์)

1. กด **2** → เมนู Item
2. กด **21** → Event Ticket / Lucky Ticket
3. กด **1** → Lucky Ticket
4. พิมพ์ตัวเลข `current + จำนวนที่ต้องการ` เช่น `0 + 500 = 500`
5. กด **1** → Save Management
6. กด **3** → รับ Transfer Code ใหม่

### 7. Rare Ticket (ตั๋วแรร์ — Golden Ticket Trade)

> ⚠️ Max value รวมสูงสุด **299** | วิธีคำนวณ: `current + จำนวนที่ต้องการ` (แสดงสมการให้ admin ดูก่อนพิมพ์)

1. กด **2** → เมนู Item
2. กด **6** → Golden Ticket (Trade)
3. พิมพ์ตัวเลข `current + จำนวนที่ต้องการ` เช่น `0 + 100 = 100`
4. กด **1** → Save Management
5. กด **3** → รับ Transfer Code ใหม่
6. ส่งข้อความให้ลูกค้า: **"วิธีการใช้งาน: ให้ลูกค้ากดรับไอเทม นำเข้าตู้เย็น (Storage) กดใช้ทั้งหมด และทำการแลกบัตรทองได้เลยครับ"**

---

## Workflow & Preferences

- **ทำใน `test_no_payment.html` ก่อนเสมอ** แล้วค่อย apply ไปไฟล์อื่น
- "max เฉยๆ" = max base (Uber=60, SR/R=50) + **plus=0** ไม่ใช่ max+max
- ต้องการเห็น log หลัง operation เสร็จทุกครั้ง (แสดงต่อแมวใน result box)
- คุยภาษาไทย, code ใช้ภาษาอังกฤษได้
