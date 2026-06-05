# config.py - BCSFE Item Map และ Amount Options

ITEM_MAP = {
    # key              menu_no  max          has_warning  label             sub_select
    "cat_food":        {"menu_no": 2,  "max": 45000,    "has_warning": True,  "label": "Cat Food",            "sub_select": None},
    "xp":              {"menu_no": 3,  "max": 99999999, "has_warning": False, "label": "XP",                  "sub_select": None},
    "normal_ticket":   {"menu_no": 4,  "max": 2999,     "has_warning": False, "label": "Normal Ticket",       "sub_select": None},
    "rare_ticket":     {"menu_no": 6,  "max": 299,      "has_warning": False, "label": "Rare Ticket (Trade)", "sub_select": None,
                        "no_add": True,
                        "custom_prompt": "Enter the number of rare tickets",
                        "note": "⚠️ หลังรับของ: เข้าตู้เย็น → กดใช้ทั้งหมด → แลกบัตรทอง"},
    "np":              {"menu_no": 10, "max": 9999,     "has_warning": False, "label": "NP",                  "sub_select": None},
    "platinum_shard":  {"menu_no": 9,  "max": 99,       "has_warning": False, "label": "Platinum Shard",      "sub_select": None},
    "leadership":      {"menu_no": 11, "max": 9999,     "has_warning": False, "label": "Leadership",          "sub_select": None},
    # catseye ต้องให้ลูกค้าเลือก sub-type 1-6 ก่อน (ตาม diagram diamond "เลือก 1-6")
    "catseye":         {"menu_no": 14, "max": 9999,     "has_warning": False, "label": "Catseye",             "sub_select": "1-6",
                        "sub_label": "เลือกประเภท Catseye (1=Normal, 2=Rare, 3=SR, 4=UR, 5=LR, 6=Alien)"},
    # catfruit จาก diagram: เมนู 15, เลือก sub-type 1-29
    "catfruit":        {"menu_no": 15, "max": 998,      "has_warning": False, "label": "Catfruit (ผลไม้แมว)", "sub_select": "1-29",
                        "sub_label": "เลือกประเภท Catfruit (1-29)"},

    # ── 4 item ใหม่ ──
    # Battle Item: 2→12, วนลูป sub 1-6 เหมือน catseye
    "battle_item":     {"menu_no": 12, "max": 9999,     "has_warning": False, "label": "Battle Item",           "sub_select": "1-6",
                        "sub_label": "เลือกประเภท Battle Item (1-6)"},

    # Catamins: 2→17, วนลูป sub 1-3 เหมือน catseye
    "catamins":        {"menu_no": 17, "max": 9999,     "has_warning": False, "label": "Catamins",              "sub_select": "1-3",
                        "sub_label": "เลือกประเภท Catamins (1-3)"},

    # Legend Ticket: 2→8, วนลูป sub 1-4 เหมือน catseye, บวก current value
    "legend_ticket":   {"menu_no": 8,  "max": 4,        "has_warning": True,  "label": "Legend Ticket",         "sub_select": None},

    # Lucky Ticket: 2→21→1, ต้องกด sub_enter=1 ก่อนใส่ค่า
    "lucky_ticket":    {"menu_no": 21, "max": 2999,     "has_warning": False, "label": "Lucky Ticket",          "sub_select": None,
                        "sub_enter": 1},

    # ── All-character packages (amount always = 1) ──
    "upgrade_all":   {"max": 1, "label": "Upgrade Max All",  "is_all_package": True},
    "unlock_all":    {"max": 1, "label": "Unlock All",        "is_all_package": True},
    "trueform_all":  {"max": 1, "label": "True Form All",     "is_all_package": True},
    "ultraform_all": {"max": 1, "label": "Ultra Form All",    "is_all_package": True},
    "talents_all":   {"max": 1, "label": "Max Talents All",   "is_all_package": True},
}

# ตัวเลือกจำนวนที่แสดงบนเว็บ
AMOUNT_OPTIONS = {
    "cat_food":        [10000, 20000, 30000, 45000],
    "xp":              [5000000, 20000000, 50000000, 99999999],
    "normal_ticket":   [100, 500, 1000, 2999],
    "rare_ticket":     [50, 100, 200, 299],
    "np":              [100, 1000, 5000, 9999],
    "platinum_shard":  [10, 30, 60, 99],
    "leadership":      [100, 1000, 5000, 9999],
    "catseye":         [100, 500, 5000, 9999],
    "catfruit":        [100, 300, 500, 998],
    "battle_item":     [100, 500, 5000, 9999],
    "catamins":        [100, 500, 5000, 9999],
    "legend_ticket":   [1, 2, 3, 4],
    "lucky_ticket":    [100, 500, 1000, 2999],
}

# ข้อมูลเพิ่มเติมเกี่ยวกับแต่ละ item
ITEM_NOTES = {
    "rare_ticket":     "⚠️ ต้องใช้ route Trade เพื่อหลีกเลี่ยง ban",
    "cat_food":        "⚠️ Cat Food มีความเสี่ยง ban ตามเตือนของ BCSFE",
    "platinum_shard":  "💡 ครบ 10/30/40/60/80/99 shard → ได้ Platinum Ticket",
    "catseye":         "💡 มี 6 ประเภท (ต้องระบุประเภท)",
}

# Countries
COUNTRIES = {
    "1": "EN (English)",
    "2": "JP (日本語)",
    "3": "KR (한국어)",
    "4": "TW (繁體中文)",
}