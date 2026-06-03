# runner.py - BCSFERunner using bcsfe 3.x Python API (no subprocess)

from datetime import datetime
from pathlib import Path
import shutil

from bcsfe import core

from config import ITEM_MAP

COUNTRY_MAP = {"1": "en", "2": "jp", "3": "kr", "4": "tw"}

BCSFE_SAVE_PATH = Path.home() / "Documents" / "bcsfe" / "saves" / "SAVE_DATA"


class BCSFERunner:
    def __init__(self, transfer: str, confirm: str, country: str = "1"):
        self.transfer = transfer.strip()
        self.confirm  = confirm.strip()
        self.country  = country.strip()

    # ──────────────────────────────────────────────────
    # helpers
    # ──────────────────────────────────────────────────

    def _get_cc(self) -> core.CountryCode:
        code = COUNTRY_MAP.get(self.country, "en")
        return core.CountryCode.from_code(code)

    def _download_save(self):
        cc = self._get_cc()
        gv = core.GameVersion(120200)
        print(f"[BCSFE] ⬇️  Downloading save (transfer={self.transfer[:6]}... cc={cc})")
        handler, result = core.ServerHandler.from_codes(
            self.transfer, self.confirm, cc, gv, print=False, save_backup=True
        )
        if handler is None:
            raise RuntimeError(
                "❌ Transfer Code หรือ Confirmation Code ไม่ถูกต้อง หรือหมดอายุแล้ว "
                "กรุณากด 'Begin Data Transfer' ในเกมใหม่แล้วลองอีกครั้ง"
            )
        print("[BCSFE] ✅ Download สำเร็จ")
        return handler.save_file

    def _upload_save(self, save_file) -> dict:
        save_path = core.SaveFile.get_saves_path().add("SAVE_DATA")
        save_file.to_file(save_path)
        print(f"[BCSFE] 💾 บันทึก save → {save_path}")

        self._backup(save_file)

        print("[BCSFE] ⬆️  Uploading save...")
        result = core.ServerHandler(save_file).get_codes()
        if result is None:
            raise RuntimeError("❌ Upload ล้มเหลว กรุณาลองใหม่")

        new_tc, new_cc = result
        print(f"[BCSFE] ✅ Transfer: {new_tc} | Confirm: {new_cc}")
        return {"transfer": new_tc, "confirmation": new_cc}

    def _backup(self, save_file):
        try:
            src = core.SaveFile.get_saves_path().add("SAVE_DATA")
            if not Path(src.to_str()).exists():
                return
            backup_dir = Path("saves_backup")
            backup_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = backup_dir / f"SAVE_{ts}_{self.transfer[:8]}"
            shutil.copy2(src.to_str(), dest)
            print(f"[BCSFE] 📁 Backup → {dest}")
        except Exception as e:
            print(f"[BCSFE] ⚠️  Backup ล้มเหลว: {e}")

    # ──────────────────────────────────────────────────
    # item editors
    # ──────────────────────────────────────────────────

    def _edit_item(self, save_file, item: dict):
        key    = item["key"]
        amount = item["amount"]
        cfg    = ITEM_MAP.get(key)
        if not cfg:
            raise ValueError(f"ไม่รู้จัก item key: {key}")

        max_val = cfg["max"]
        label   = cfg["label"]

        # ── array items (sub-type loop) ──
        if cfg.get("sub_select"):
            self._edit_array_item(save_file, key, amount, max_val, label)
            return

        # ── simple scalar items ──
        cur = self._get_scalar(save_file, key)
        new_val = min(cur + amount, max_val) if not cfg.get("no_add") else min(amount, max_val)
        self._set_scalar(save_file, key, new_val)
        print(f"[BCSFE] ✔ {label}: {cur} → {new_val}")

    def _get_scalar(self, sf, key: str) -> int:
        mapping = {
            "cat_food":      lambda: sf.catfood,
            "xp":            lambda: sf.xp,
            "normal_ticket": lambda: sf.normal_tickets,
            "rare_ticket":   lambda: sf.rare_tickets,
            "np":            lambda: sf.np,
            "platinum_shard":lambda: sf.platinum_shards,
            "leadership":    lambda: sf.leadership,
            "legend_ticket": lambda: sf.legend_tickets,
            "lucky_ticket":  lambda: sf.lucky_tickets[0] if sf.lucky_tickets else 0,
        }
        fn = mapping.get(key)
        if fn is None:
            raise ValueError(f"ไม่รู้จัก scalar key: {key}")
        return int(fn())

    def _set_scalar(self, sf, key: str, val: int):
        if   key == "cat_food":       sf.catfood          = val
        elif key == "xp":             sf.xp               = val
        elif key == "normal_ticket":  sf.normal_tickets   = val
        elif key == "rare_ticket":    sf.rare_tickets     = val
        elif key == "np":             sf.np               = val
        elif key == "platinum_shard": sf.platinum_shards  = val
        elif key == "leadership":     sf.leadership       = val
        elif key == "legend_ticket":  sf.legend_tickets   = val
        elif key == "lucky_ticket":
            lst = list(sf.lucky_tickets) if sf.lucky_tickets else [0]
            lst[0] = val
            sf.lucky_tickets = lst
        else:
            raise ValueError(f"ไม่รู้จัก scalar key: {key}")

    def _edit_array_item(self, sf, key: str, amount: int, max_val: int, label: str):
        sub_range  = ITEM_MAP[key].get("sub_select", "1-1")
        max_sub    = int(sub_range.split("-")[1])

        if key == "catseye":
            arr = list(sf.catseyes)
        elif key == "catfruit":
            arr = list(sf.catfruit)
        elif key == "catamins":
            arr = list(sf.catamins)
        elif key == "battle_item":
            arr = [item.amount for item in sf.battle_items.items]
        else:
            raise ValueError(f"ไม่รู้จัก array key: {key}")

        n = min(max_sub, len(arr))
        for i in range(n):
            arr[i] = min(arr[i] + amount, max_val)

        if key == "catseye":
            sf.catseyes = arr
        elif key == "catfruit":
            sf.catfruit = arr
        elif key == "catamins":
            sf.catamins = arr
        elif key == "battle_item":
            for i in range(n):
                sf.battle_items.items[i].amount = arr[i]

        print(f"[BCSFE] ✔ {label} ({n} types) → {amount} each (max {max_val})")

    # ──────────────────────────────────────────────────
    # public run methods
    # ──────────────────────────────────────────────────

    def run(self, items: list) -> dict:
        try:
            core.core_data.init_data()
            save_file = self._download_save()

            for item in items:
                self._edit_item(save_file, item)

            codes = self._upload_save(save_file)
            return {"success": True, "new_transfer_code": codes}

        except Exception as e:
            print(f"[BCSFE] ❌ {e}")
            return {"success": False, "error": str(e)}

    def _find_cats(self, save_file, cat_ids: list):
        """หา Cat objects จาก IDs — cats.cats เป็น list เรียงตาม index == id"""
        id_set = set(cat_ids)
        result = []
        for cat in save_file.cats.cats:
            if cat.id in id_set:
                result.append(cat)
        return result

    def run_unlock_characters(self, cat_ids: list) -> dict:
        try:
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_cats(save_file, cat_ids)
            print(f"[BCSFE] 🔍 Found {len(cats)}/{len(cat_ids)} cats in save")

            for cat in cats:
                # set unlocked + ให้ form 1 ด้วยเพื่อให้ใช้งานได้จริง
                cat.unlocked = 1
                cat.gatya_seen = 1
                if cat.unlocked_forms == 0:
                    cat.unlocked_forms = 1
                print(f"[BCSFE]   ✔ cat.id={cat.id} unlocked={cat.unlocked} forms={cat.unlocked_forms}")

            print(f"[BCSFE] ✔ Unlocked {len(cats)} cats")
            codes = self._upload_save(save_file)
            return {"success": True, "new_transfer_code": codes}

        except Exception as e:
            import traceback
            print(f"[BCSFE] ❌ {e}\n{traceback.format_exc()}")
            return {"success": False, "error": str(e)}

    def run_upgrade_characters(self, cat_ids: list) -> dict:
        try:
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_cats(save_file, cat_ids)
            max_upgrade = core.Upgrade(plus=90, base=29)  # base 30 = index 29, plus 90
            for cat in cats:
                cat.set_upgrade(save_file, max_upgrade)
            print(f"[BCSFE] ✔ Upgraded {len(cats)}/{len(cat_ids)} cats to max")

            codes = self._upload_save(save_file)
            return {"success": True, "new_transfer_code": codes}

        except Exception as e:
            print(f"[BCSFE] ❌ {e}")
            return {"success": False, "error": str(e)}

    def run_true_form_characters(self, cat_ids: list) -> dict:
        try:
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_cats(save_file, cat_ids)
            for cat in cats:
                cat.true_form(save_file)
            print(f"[BCSFE] ✔ True Form {len(cats)}/{len(cat_ids)} cats")

            codes = self._upload_save(save_file)
            return {"success": True, "new_transfer_code": codes}

        except Exception as e:
            print(f"[BCSFE] ❌ {e}")
            return {"success": False, "error": str(e)}

    def run_ultra_form_characters(self, cat_ids: list) -> dict:
        try:
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_cats(save_file, cat_ids)
            for cat in cats:
                cat.unlock_fourth_form(save_file)
            print(f"[BCSFE] ✔ Ultra Form {len(cats)}/{len(cat_ids)} cats")

            codes = self._upload_save(save_file)
            return {"success": True, "new_transfer_code": codes}

        except Exception as e:
            print(f"[BCSFE] ❌ {e}")
            return {"success": False, "error": str(e)}

    def run_talents_max_characters(self, cat_ids: list) -> dict:
        try:
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_cats(save_file, cat_ids)
            for cat in cats:
                for talent in (cat.talents or []):
                    if hasattr(talent, "max_level"):
                        talent.level = talent.max_level
            print(f"[BCSFE] ✔ Max Talents {len(cats)}/{len(cat_ids)} cats")

            codes = self._upload_save(save_file)
            return {"success": True, "new_transfer_code": codes}

        except Exception as e:
            print(f"[BCSFE] ❌ {e}")
            return {"success": False, "error": str(e)}
