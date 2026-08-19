---
name: add-event-pack
description: "เพิ่ม Event Pack ใหม่เข้า BattleCats Shop — รับข้อมูลจาก user แล้ว generate SQL INSERT พร้อมใช้"
---

# Add Event Pack Skill

เมื่อ user บอกรายละเอียด event pack ใหม่ ให้ generate SQL INSERT สำหรับรันใน Supabase SQL Editor

---

## ข้อมูลที่ต้องรู้ก่อน generate

ถามหากไม่มีในข้อความ:

| Field | คำถาม | หมายเหตุ |
|-------|--------|----------|
| `id` | ชื่อ key (ตัวเล็ก ไม่มีช่องว่าง) | เช่น `sonic`, `kny`, `evangelion` |
| `label` | ชื่อ Unlock card | เช่น `Sonic Pack` |
| `label_max` | ชื่อ Max card | ถ้าไม่มี = `label + ' + Max'` |
| `cat_ids` | Cat IDs ในชุด | เช่น `[789,790,791]` |
| `price_unlock` | ราคา Unlock | คำนวณจาก tier ถ้าไม่รู้ |
| `price_max` | ราคา Max | null = ไม่มี Max variant |
| `banner_img` | path รูป Unlock | เช่น `pictures/sonic_pack.png` |
| `banner_img_max` | path รูป Max | null = ใช้รูปเดียวกัน |
| `warning_text` | คำเตือนก่อนใส่ตะกร้า | null = ไม่มี |
| `desc_unlock` | คำอธิบาย Unlock card | HTML ได้ |
| `desc_max` | คำอธิบาย Max card | null = ใช้อันเดียวกับ Unlock |
| `group_id` | กลุ่มร่วม section กับ pack อื่น | เช่น `crazed_manic` — ปกติ null |
| `group_label` | หัว section ของกลุ่ม | ใช้คู่กับ `group_id` |
| `header_color` | สีหัว section (hex) | default `#FCD34D` |
| `starts_at` | เวลาเปิด | ISO string หรือ null = เปิดทันที |
| `expires_at` | เวลาหมดอายุ | null = ไม่หมดอายุ |
| `sort_order` | ลำดับแสดง | ถามหรือใส่ต่อท้ายจากที่มีอยู่ |

---

## คำนวณราคา (ถ้า user บอก tier แทน)

| Tier | ราคา/ตัว |
|------|----------|
| Uber Rare (UR) | ฿39 |
| Super Rare (SR) | ฿25 |
| Rare (RR) | ฿15 |

**สูตร:**
- `price_unlock` = รวมราคาแยก × 0.75 (ปัดเป็นหลักสิบ)
- `price_max` = `price_unlock` + (จำนวนตัว × 15) ปัดเป็นหลักสิบ

---

## Template SQL INSERT

```sql
INSERT INTO event_packs (
  id, label, label_max,
  enabled, sort_order,
  price_unlock, price_max,
  cat_ids,
  banner_img, banner_img_max,
  actions_unlock, actions_max,
  warning_text,
  desc_unlock, desc_max,
  group_id, group_label, header_color,
  starts_at, expires_at
) VALUES (
  '{id}',
  '{label}',
  {label_max},           -- NULL หรือ '{label_max}'
  true,
  {sort_order},
  {price_unlock},
  {price_max},           -- NULL หรือ ตัวเลข
  '{cat_ids_json}',      -- '[789,790,791]'
  '{banner_img}',
  {banner_img_max},      -- NULL หรือ '{path}'
  '["unlock"]',
  {actions_max},         -- NULL หรือ '["unlock","upgrade"]'
  {warning_text},        -- NULL หรือ '⚠️ ...'
  {desc_unlock},         -- NULL หรือ 'ปลดล็อค <strong>6 ตัว</strong>...'
  {desc_max},            -- NULL หรือ 'text'
  {group_id},            -- NULL หรือ 'group_key'
  {group_label},         -- NULL หรือ 'SET CRAZED & MANIC'
  '{header_color}',      -- '#FCD34D'
  {starts_at},           -- NULL หรือ '2025-01-01T00:00:00+07:00'
  {expires_at}           -- NULL หรือ timestamp
);
```

---

## กฎ output

1. แสดง SQL ที่พร้อมรันทันที (ไม่มี placeholder เหลือ)
2. ถ้า user ไม่ให้ข้อมูลบางอย่าง ให้ใส่ NULL / ค่า default แล้วแจ้งว่าแก้ที่จุดไหนทีหลัง
3. แสดงราคาที่คำนวณได้พร้อม breakdown ให้ user ยืนยันก่อน generate
4. ถ้ามีรูปให้เตือนว่าต้องอัพโหลดไฟล์รูปไปที่ `pictures/` ด้วย

---

## ตัวอย่าง

**User บอก:** "เพิ่ม Sonic Pack, cat 866-872, UR ทุกตัว, รูป sonic_pack.png"

**ผม:**
- คำนวณ: 7 UR × ฿39 = ฿273 → pack unlock ≈ ฿200, max ≈ ฿300
- ถาม: มี Max variant ไหม? ชื่อ Max card ว่าอะไร?
- generate SQL INSERT พร้อม desc_unlock อัตโนมัติ

---

## หมายเหตุ

- `actions_unlock` = `'["unlock"]'` เสมอ (เว้นแต่ user บอกอื่น เช่น trueform only)
- `actions_max` = `'["unlock","upgrade"]'` ถ้ามี Max, NULL ถ้าไม่มี
- ถ้า pack ต้อง True Form ก่อน → `actions_unlock = '["unlock","trueform"]'`
- ถ้า pack ต้อง Ultra Form → `actions_max = '["unlock","upgrade","trueform","ultraform"]'`
- `cat_ids` ต้องเป็น JSON array string: `'[789,790,791]'`
