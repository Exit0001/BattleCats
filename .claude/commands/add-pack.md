# Add New Character Pack to Shop

เมื่อต้องการเพิ่ม Pack ตัวละครชุดใหม่ (เช่น Baki Pack, Sonic Pack) ให้ทำตามขั้นตอนนี้

## ข้อมูลที่ต้องรู้ก่อน
- **Pack Name** — ชื่อ pack (เช่น `Baki`, `Sonic`, `KnY`)
- **Cat IDs** — รายการ ID ตัวละครในชุด (เช่น `[789, 790, 791, 792, 793, 794]`)
- **Tiers** — tier ของแต่ละตัว (ใช้คำนวณราคา)
- **ราคา Unlock Only** — ดูจากตาราง tier ด้านล่าง
- **รูป pack** — ไฟล์ PNG สำหรับ card หน้าเว็บ (user จะส่งให้)

## คำนวณราคา

| Tier | ราคา unlock/ตัว (ปกติ) |
|------|------------------------|
| Uber Rare (UR) | ฿39 |
| Super Rare (SR) | ฿25 |
| Rare (RR) | ฿15 |

**สูตร Pack:**
- นับ UR × 39 + SR × 25 + RR × 15 = ราคาถ้าซื้อแยก
- Pack ตั้งราคาประมาณ **70–80% ของราคาแยก** (ให้ส่วนลดจูงใจ)
- Pack + Upgrade Max บวกเพิ่ม (จำนวนตัว × ฿15) แล้วหักส่วนลดเล็กน้อย

**Upgrade Max ราคาต่อตัว:** ฿15

---

## ขั้นตอน

### 1. เพิ่มใน `main.py`

**เพิ่มใน `ALL_PACKAGE_MAP`** (ต่อท้ายบรรทัด `manic_all`):
```python
"{name}_all":         {"label": "{Name} Pack",          "price": XXX, "runner": None},
"{name}_upgrade_all": {"label": "{Name} Pack + Upgrade", "price": YYY, "runner": None},
```

**เพิ่ม ID list** (ต่อท้าย `BAKI_CAT_IDS`):
```python
{NAME}_CAT_IDS = [789, 790, 791, ...]  # ใส่ ID จริง
```

**เพิ่ม handler** ในฟังก์ชัน `_run_bcsfe_steps` (ต่อท้าย baki_upgrade_all block):
```python
if "{name}_all" in all_pkg_set:
    r = _call("run_unlock_characters", {NAME}_CAT_IDS)
    if not r["success"]: return _fail(r)
    _upd(r["new_transfer_code"])
    summary.append({"item": "{Name} Pack (Unlock)", "amount": len({NAME}_CAT_IDS)})
    print(f"[BCSFE] {name}_all done -> tc={cur_tc}")

if "{name}_upgrade_all" in all_pkg_set:
    r = _call("run_unlock_characters", {NAME}_CAT_IDS)
    if not r["success"]: return _fail(r)
    _upd(r["new_transfer_code"])
    r = _call("run_upgrade_characters", {NAME}_CAT_IDS)
    if not r["success"]: return _fail(r)
    _upd(r["new_transfer_code"])
    summary.append({"item": "{Name} Pack + Upgrade (Unlock+Max)", "amount": len({NAME}_CAT_IDS)})
    print(f"[BCSFE] {name}_upgrade_all done -> tc={cur_tc}")
```

### 2. เพิ่ม section ใน `characters.html`

วาง **ก่อน** `</section>` ที่ปิด section Crazed/Manic/Baki (ค้นหาด้วย `<!-- TIER FILTER`):

```html
<!-- แถว {Name} Pack -->
<div style="margin-top:28px;">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
    <span style="font-family:'Russo One',sans-serif;font-size:14px;color:#FCD34D;letter-spacing:1px;">🎌 {NAME} PACK</span>
    <span style="height:1px;flex:1;background:linear-gradient(90deg,rgba(252,211,77,0.35),transparent);"></span>
    <span style="font-family:'Chakra Petch',sans-serif;font-size:11px;color:rgba(210,190,255,0.4);">Cat #{first}–{last} ({count} ตัว)</span>
  </div>
  <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:20px;max-width:min(calc(66.67% - 8px),660px);margin:0 auto;">

    <!-- Unlock only -->
    <div class="card" style="cursor:default;padding:24px 20px;border-color:rgba(252,211,77,0.3);">
      <div class="card-picture"><img loading="lazy" src="pictures/{name}_pack.png" style="width:100%;height:auto;display:block;" onerror="this.style.display='none'"></div>
      <div class="card-tag" style="background:rgba(252,211,77,0.15);color:#FCD34D;border-color:rgba(252,211,77,0.4);">SET</div>
      <div class="card-name" style="font-size:15px;font-family:'Russo One',sans-serif;margin-bottom:8px;">{Name} Pack</div>
      <div class="card-desc" style="line-height:1.8;">ปลดล็อค <strong style="color:#EDE6FF;">{count} ตัว</strong> ครบชุด<br>
        <span style="font-size:11px;color:rgba(210,190,255,0.75);">
          #{id1} Name1 · #{id2} Name2<br>
          ...
        </span>
      </div>
      <div class="card-price" style="margin-top:14px;"><span class="price-now">฿XXX</span></div>
      <div style="margin-top:auto;padding-top:14px;">
        <button class="btn btn-primary" style="width:100%;background:linear-gradient(135deg,#b45309,#f59e0b);" onclick="addAllPackage('{name}_all','{Name} Pack',XXX)">+ ใส่ตะกร้า</button>
      </div>
    </div>

    <!-- Unlock + Upgrade -->
    <div class="card" style="cursor:default;padding:24px 20px;border-color:rgba(252,211,77,0.5);">
      <div class="card-picture"><img loading="lazy" src="pictures/{name}_pack.png" style="width:100%;height:auto;display:block;" onerror="this.style.display='none'"></div>
      <div class="card-tag" style="background:rgba(252,211,77,0.25);color:#FCD34D;border-color:rgba(252,211,77,0.6);">SET+</div>
      <div class="card-name" style="font-size:15px;font-family:'Russo One',sans-serif;margin-bottom:8px;">{Name} Pack + Max</div>
      <div class="card-desc" style="line-height:1.8;">ปลดล็อค + <strong style="color:#EDE6FF;">Upgrade Max</strong> ครบชุด<br>
        <span style="font-size:11px;color:rgba(210,190,255,0.75);">
          #{id1} Name1 · #{id2} Name2<br>
          ...
        </span>
      </div>
      <div class="card-price" style="margin-top:14px;"><span class="price-now">฿YYY</span></div>
      <div style="margin-top:auto;padding-top:14px;">
        <button class="btn btn-primary" style="width:100%;background:linear-gradient(135deg,#92400e,#d97706);" onclick="addAllPackage('{name}_upgrade_all','{Name} Pack + Max',YYY)">+ ใส่ตะกร้า</button>
      </div>
    </div>

  </div>
</div>
```

### 3. อัพโหลดรูป pack ไป VPS

```powershell
Set-SCPItem -ComputerName "187.77.156.253" -Credential $cred -Path "path\to\{name}_pack.png" -Destination "/battlecats/pictures/" -Force -AcceptKey
```

### 4. Deploy ขึ้น VPS

```powershell
# อัพโหลดไฟล์
Set-SCPItem ... main.py → /battlecats/
Set-SCPItem ... characters.html → /battlecats/

# Restart
Invoke-SSHCommand ... "systemctl restart battlecats"
```

---

## VPS Credentials
- IP: `187.77.156.253`
- User: `root`
- Password: ดูใน memory `reference-vps.md`
- Path: `/battlecats/`

## หมายเหตุ
- Pack key ต้องไม่ซ้ำกับที่มีอยู่แล้วใน `ALL_PACKAGE_MAP`
- ถ้า pack มีตัวละครที่ต้อง True Form ก่อน → ต้องเพิ่ม step `run_true_form_characters` ระหว่าง unlock กับ upgrade
- รูป pack วางที่ `pictures/{name}_pack.png` บน VPS
- ถ้าจะทำ pack ชั่วคราว (event) → ลบ card จาก characters.html เมื่อหมดเวลา, ไม่ต้องลบ backend (ไม่กระทบอะไร)
