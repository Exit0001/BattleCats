# runner.py - BCSFERunner using bcsfe 3.x Python API + CLI subprocess for lucky/rare ticket

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import re
import time
import uuid
import threading

from bcsfe import core
from bcsfe.core.game.catbase.cat import Talent as BCSFETalent

from config import ITEM_MAP

BCSFE_CLI = Path(__file__).parent / ".venv" / "Scripts" / "bcsfe.exe"
BCSFE_SAVES_DIR = Path.home() / "Documents" / "bcsfe" / "saves"

COUNTRY_MAP = {"1": "en", "2": "jp", "3": "kr", "4": "tw"}
LOG_DIR = Path("logs")

# CLI subprocess ยังต้องรัน sequential (SAVE_DATA hardcoded ใน bcsfe CLI)
_CLI_LOCK = threading.Lock()


class BCSFERunner:
    def __init__(self, transfer: str, confirm: str, country: str = "1"):
        self.transfer = transfer.strip()
        self.confirm  = confirm.strip()
        self.country  = country.strip()
        self._session_id  = uuid.uuid4().hex[:8]
        self._save_path   = BCSFE_SAVES_DIR / f"SAVE_DATA_{self._session_id}"
        self._cli_save_path = BCSFE_SAVES_DIR / f"SAVE_DATA_cli_{self._session_id}"
        LOG_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = LOG_DIR / f"api_log_{ts}_{self.transfer[:8]}.txt"
        self._log_file = open(self._log_path, "w", encoding="utf-8")
        self._deferred_cli = []
        self._last_cli_output = ""
        self._log(f"{'='*60}")
        self._log(f"เวลา      : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._log(f"Transfer  : {self.transfer}")
        self._log(f"Confirm   : {self.confirm}")
        self._log(f"Country   : {COUNTRY_MAP.get(self.country, 'en')}")
        self._log(f"{'='*60}")

    def _log(self, msg: str):
        print(msg)
        self._log_file.write(msg + "\n")
        self._log_file.flush()

    def _close_log(self):
        self._log_file.close()

    # ──────────────────────────────────────────────────
    # CLI subprocess helper (lucky_ticket / rare_ticket)
    # ──────────────────────────────────────────────────

    def _run_cli_item(self, transfer: str, confirm: str, key: str,
                      amount: int, current: int = 0, use_local: bool = False) -> dict:
        """
        รัน bcsfe CLI ด้วย communicate() — ส่ง inputs ทั้งหมดพร้อมกัน
        use_local=True → Load from SAVE_DATA (option 3) แทนการ download
        """
        import os
        cc_num = self.country

        if key == "lucky_ticket":
            value_to_send = min(current + amount, 2999)
            self._log(f"[CLI] Lucky Ticket: {current} + {amount} = {value_to_send}")
            nav = ["3", "21", "1", str(value_to_send)]
        else:
            to_add = min(amount, 299 - current)
            self._log(f"[CLI] Rare Ticket: current={current}, add={to_add}")
            nav = ["3", "6", str(to_add)]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        cli_path_str = str(self._cli_save_path)

        if use_local:
            # ใช้ --input-path โหลดจาก unique path โดยตรง → ข้าม initial menu → parallel ได้
            self._log(f"[CLI] โหลดจาก {cli_path_str} (--input-path)")
            inputs = "\n".join(nav + ["2", "3"]) + "\n"
            result = self._cli_communicate(inputs, env, cli_args=["--input-path", cli_path_str])
        else:
            # Download: ส่ง unique path แทน "" → save ลง cli_save_path ของ session นี้
            inputs = "\n".join(["1", transfer, confirm, cc_num, cli_path_str] + nav + ["2", "3"]) + "\n"
            result = self._cli_communicate(inputs, env)

        # ── Lucky Ticket: ตรวจ current value จาก CLI output แล้ว re-run ถ้าจำเป็น ──
        if key == "lucky_ticket" and result.get("success"):
            last_output = getattr(self, "_last_cli_output", "")
            m = re.search(r'current value[:\s]+(\d+)', last_output, re.IGNORECASE)
            if m:
                actual_current = int(m.group(1))
                correct_total = min(actual_current + amount, 2999)
                if correct_total != value_to_send:
                    self._log(f"[CLI] Lucky Ticket current จริง={actual_current} ≠ assumed={current} → re-run ด้วย {actual_current}+{amount}={correct_total}")
                    nav2 = ["3", "21", "1", str(correct_total)]
                    # ใช้ --input-path เพื่อโหลด session save ที่ถูกต้อง ไม่ใช่ default SAVE_DATA
                    inputs2 = "\n".join(nav2 + ["2", "3"]) + "\n"
                    result = self._cli_communicate(inputs2, env,
                                                   cli_args=["--input-path", str(self._cli_save_path)])

        return result

    def _cli_communicate(self, inputs: str, env: dict, label: str = "", cli_args: list = None) -> dict:
        """รัน CLI ด้วย communicate() แล้ว parse transfer code"""
        try:
            cmd = [str(BCSFE_CLI)] + (cli_args or [])
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", env=env,
            )
            stdout, _ = proc.communicate(input=inputs, timeout=120)

            clean = re.sub(r'\x1b\[[0-9;]*[mGKH]', '', stdout)
            self._last_cli_output = clean  # เก็บไว้ให้ caller ตรวจสอบ
            for line in clean.splitlines():
                if line.strip():
                    prefix = f"[{label}]" if label else "[CLI]"
                    self._log_file.write(f"  {prefix} {line}\n")
            self._log_file.flush()

            tc_list = re.findall(r'Transfer Code[:\s]+([a-f0-9]{8,9})', clean)
            cc_list = re.findall(r'Confirmation Code[:\s]+(\d{4})', clean)

            if tc_list:
                new_tc = tc_list[-1]
                new_cc = cc_list[-1] if cc_list else None
                self._log(f"[CLI] ✅ Transfer ใหม่: {new_tc} | Confirm ใหม่: {new_cc}")
                return {"success": True, "transfer": new_tc, "confirmation": new_cc}

            if "Failed to upload save file" in clean:
                self._log("[CLI] ⚠ Upload ล้มเหลว (rate limit) — รอ 8 วินาทีแล้ว retry...")
                time.sleep(8)
                retry_inputs = "\n".join(["3", "2", "3"]) + "\n"
                return self._cli_communicate(retry_inputs, env, label="RETRY")

            self._log("[CLI] ❌ parse transfer code ไม่ได้")
            for line in clean.splitlines()[-15:]:
                self._log(f"  {line}")
            return {"success": False, "error": "parse transfer code ไม่ได้"}

        except subprocess.TimeoutExpired:
            proc.kill()
            self._log("[CLI] ❌ timeout (120s)")
            return {"success": False, "error": "CLI timeout"}
        except Exception as e:
            self._log(f"[CLI] ❌ {e}")
            return {"success": False, "error": str(e)}

    # ──────────────────────────────────────────────────
    # helpers
    # ──────────────────────────────────────────────────

    def _get_cc(self) -> core.CountryCode:
        code = COUNTRY_MAP.get(self.country, "en")
        return core.CountryCode.from_code(code)

    def _download_save(self):
        cc = self._get_cc()
        gv = core.GameVersion(120200)
        self._log(f"[BCSFE] ⬇  Downloading save (transfer={self.transfer[:6]}... cc={cc})")
        handler, result = core.ServerHandler.from_codes(
            self.transfer, self.confirm, cc, gv, print=False, save_backup=True
        )
        if handler is None:
            raise RuntimeError(
                "❌ Transfer Code หรือ Confirmation Code ไม่ถูกต้อง หรือหมดอายุแล้ว "
                "กรุณากด 'Begin Data Transfer' ในเกมใหม่แล้วลองอีกครั้ง"
            )
        self._log("[BCSFE] ✅ Download สำเร็จ")
        return handler.save_file

    def _upload_save(self, save_file) -> dict:
        # ใช้ unique path ของ session นี้ → parallel sessions ไม่ conflict
        bcsfe_path = core.SaveFile.get_saves_path().add(f"SAVE_DATA_{self._session_id}")
        save_file.to_file(bcsfe_path)
        self._log(f"[BCSFE] 💾 บันทึก save → {bcsfe_path}")

        self._backup()

        self._log("[BCSFE] ⬆  Uploading save...")
        result = core.ServerHandler(save_file).get_codes()

        # ลบ temp file หลัง upload
        try:
            Path(bcsfe_path.to_str()).unlink(missing_ok=True)
        except Exception:
            pass

        if result is None:
            raise RuntimeError("❌ Upload ล้มเหลว กรุณาลองใหม่")

        new_tc, new_cc = result
        self._log(f"[BCSFE] ✅ Transfer ใหม่: {new_tc} | Confirm ใหม่: {new_cc}")
        self._log(f"{'='*60}")
        return {"transfer": new_tc, "confirmation": new_cc}

    def _backup(self):
        """Backup จาก temp save file ของ session นี้"""
        try:
            src = BCSFE_SAVES_DIR / f"SAVE_DATA_{self._session_id}"
            if not src.exists():
                return
            backup_dir = Path("saves_backup")
            backup_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = backup_dir / f"SAVE_{ts}_{self.transfer[:8]}"
            shutil.copy2(src, dest)
            self._log(f"[BCSFE] 📁 Backup → {dest}")
        except Exception as e:
            self._log(f"[BCSFE] ⚠  Backup ล้มเหลว: {e}")

    # ──────────────────────────────────────────────────
    # item editors
    # ──────────────────────────────────────────────────

    def _read_lucky_ticket_current(self, save_file) -> int:
        try:
            tickets = save_file.lucky_tickets
            if tickets and len(tickets) > 0:
                return int(tickets[0])
        except Exception:
            pass
        return 0

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

        # ── lucky_ticket / rare_ticket: deferred ไปรัน CLI หลัง upload ──
        if key in ("lucky_ticket", "rare_ticket"):
            cur = 0
            if key == "rare_ticket":
                cur = int(save_file.rare_tickets)
            elif key == "lucky_ticket":
                cur = self._read_lucky_ticket_current(save_file)
            self._deferred_cli.append({"key": key, "amount": amount, "label": label, "current": cur})
            self._log(f"[ITEM] {label}: defer → CLI (current={cur})")
            return

        # ── simple scalar items — ทุกตัว ADD เสมอ ──
        cur = self._get_scalar(save_file, key)
        new_val = min(cur + amount, max_val)
        self._set_scalar(save_file, key, new_val)
        self._log(f"[ITEM] {label}: {cur} → {new_val}  (+{new_val - cur})")

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
        before = arr[:n].copy()
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

        self._log(f"[ITEM] {label} ({n} types) +{amount} each:")
        for i in range(n):
            self._log(f"       type {i+1}: {before[i]} → {arr[i]}")

    # ──────────────────────────────────────────────────
    # public run methods
    # ──────────────────────────────────────────────────

    def run(self, items: list) -> dict:
        try:
            self._log(f"[OP] เพิ่มของ {len(items)} รายการ")
            core.core_data.init_data()
            save_file = self._download_save()

            for item in items:
                self._edit_item(save_file, item)

            # ── Python API items: upload ──
            codes = self._upload_save(save_file)
            current_tc = codes["transfer"]
            current_cc = codes["confirmation"]

            # ── CLI deferred items (lucky_ticket / rare_ticket) ──
            # แต่ละ session ใช้ unique cli_save_path → parallel ได้แล้ว ไม่ต้อง lock
            has_rare = False
            if self._deferred_cli:
                self._log("[CLI] รอ 4 วินาที (rate limit)...")
                time.sleep(4)
                for idx, deferred in enumerate(self._deferred_cli):
                    key = deferred["key"]
                    use_local = (idx > 0)
                    r = self._run_cli_item(current_tc, current_cc, key, deferred["amount"], deferred.get("current", 0), use_local)
                    if r["success"]:
                        current_tc = r["transfer"]
                        current_cc = r["confirmation"]
                        if key == "rare_ticket":
                            has_rare = True
                    else:
                        raise RuntimeError(f"{deferred['label']} CLI ล้มเหลว: {r.get('error')}")
                # cleanup unique cli save file
                try:
                    self._cli_save_path.unlink(missing_ok=True)
                except Exception:
                    pass

            final_codes = {"transfer": current_tc, "confirmation": current_cc}
            self._log(f"{'='*60}")
            self._close_log()

            result = {"success": True, "new_transfer_code": final_codes}
            if has_rare:
                result["customer_note"] = "วิธีการใช้งาน: ให้ลูกค้ากดรับไอเทม นำเข้าตู้เย็น (Storage) กดใช้ทั้งหมด และทำการแลกบัตรทองได้เลยครับ"
            return result

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return {"success": False, "error": str(e)}

    def _find_cats(self, save_file, cat_ids: list):
        """หา Cat objects จาก IDs (ทุกตัว รวม locked) — ใช้สำหรับ unlock"""
        id_set = set(cat_ids)
        return [cat for cat in save_file.cats.cats if cat.id in id_set]

    def _find_owned_cats(self, save_file, cat_ids: list):
        """หา Cat objects เฉพาะตัวที่ unlocked จาก IDs — ใช้สำหรับ upgrade/form/talents"""
        id_set = set(cat_ids)
        return [cat for cat in save_file.cats.get_unlocked_cats() if cat.id in id_set]

    def run_unlock_characters(self, cat_ids: list) -> dict:
        try:
            self._log(f"[OP] Unlock Characters จำนวน {len(cat_ids)} ตัว")
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_cats(save_file, cat_ids)
            self._log(f"[BCSFE] พบ {len(cats)}/{len(cat_ids)} ตัวใน save")

            logs = []
            not_found = [i for i in cat_ids if not any(c.id == i for c in cats)]
            for cat in cats:
                cat.unlocked = 1
                cat.gatya_seen = 1
                if cat.unlocked_forms == 0:
                    cat.unlocked_forms = 1
                logs.append(f"✔ #{cat.id} — unlocked")
                self._log(f"[CAT] ✔ #{cat.id} — unlocked")
            for i in not_found:
                logs.append(f"✘ #{i} — ไม่พบใน save")
                self._log(f"[CAT] ✘ #{i} — ไม่พบใน save")

            self._log(f"[BCSFE] Unlocked {len(cats)} cats")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            import traceback
            self._log(f"[BCSFE] ❌ {e}\n{traceback.format_exc()}")
            self._close_log()
            return {"success": False, "error": str(e)}

    @staticmethod
    def _set_base_max(cat, save_file) -> None:
        """Set to max level WITH catseyes (e.g. level 50), plus = 0"""
        power_up = core.PowerUpHelper(cat, save_file)
        power_up.reset_upgrade()
        power_up.max_upgrade()
        cat.upgrade.plus = 0

    def run_upgrade_characters(self, cat_ids: list) -> dict:
        """Upgrade max level (with catseyes) ตาม IDs ที่ระบุ, plus = 0"""
        try:
            self._log(f"[OP] Upgrade Characters จำนวน {len(cat_ids)} ตัว")
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_owned_cats(save_file, cat_ids)
            logs = []
            not_found = [i for i in cat_ids if not any(c.id == i for c in cats)]
            for cat in cats:
                old_lv = cat.upgrade.base + 1
                old_plus = cat.upgrade.plus
                self._set_base_max(cat, save_file)
                entry = f"✔ #{cat.id} — Lv{old_lv}+{old_plus} → Lv{cat.upgrade.base+1}+{cat.upgrade.plus}"
                logs.append(entry)
                self._log(f"[CAT] {entry}")
            for i in not_found:
                logs.append(f"✘ #{i} — ไม่พบใน save")
                self._log(f"[CAT] ✘ #{i} — ไม่พบใน save")
            self._log(f"[BCSFE] Upgraded {len(cats)}/{len(cat_ids)} cats → max, plus=0")

            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return {"success": False, "error": str(e)}

    def run_upgrade_all_characters(self) -> dict:
        """Upgrade max (with catseyes) ทุกตัวที่ unlock อยู่ในรหัส, plus = 0"""
        try:
            self._log("[OP] Upgrade ALL unlocked cats → max, plus=0")
            core.core_data.init_data()
            save_file = self._download_save()

            count = 0
            logs = []
            for cat in save_file.cats.cats:
                if cat.unlocked:
                    old_lv = cat.upgrade.base + 1
                    old_plus = cat.upgrade.plus
                    self._set_base_max(cat, save_file)
                    entry = f"✔ #{cat.id} — Lv{old_lv}+{old_plus} → Lv{cat.upgrade.base+1}+{cat.upgrade.plus}"
                    logs.append(entry)
                    self._log(f"[CAT] {entry}")
                    count += 1
            self._log(f"[BCSFE] Upgraded all {count} unlocked cats → max, plus=0")

            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "count": count, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return {"success": False, "error": str(e)}

    def run_true_form_characters(self, cat_ids: list) -> dict:
        try:
            self._log(f"[OP] True Form Characters จำนวน {len(cat_ids)} ตัว")
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_owned_cats(save_file, cat_ids)
            logs = []
            not_found = [i for i in cat_ids if not any(c.id == i for c in cats)]
            save_file.cats.true_form_cats(save_file, cats)
            for cat in cats:
                logs.append(f"✔ #{cat.id} — True Form applied")
                self._log(f"[CAT] ✔ #{cat.id} — True Form applied")
            for i in not_found:
                logs.append(f"✘ #{i} — ไม่พบใน save")
                self._log(f"[CAT] ✘ #{i} — ไม่พบใน save")
            self._log(f"[BCSFE] True Form {len(cats)}/{len(cat_ids)} cats")

            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return {"success": False, "error": str(e)}

    def run_ultra_form_characters(self, cat_ids: list) -> dict:
        try:
            self._log(f"[OP] Ultra Form Characters จำนวน {len(cat_ids)} ตัว")
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_owned_cats(save_file, cat_ids)
            logs = []
            not_found = [i for i in cat_ids if not any(c.id == i for c in cats)]
            # fourth_form_cats checks NyankoPictureBook — only applies to cats with 4 forms
            save_file.cats.fourth_form_cats(save_file, cats)
            for cat in cats:
                logs.append(f"✔ #{cat.id} — Ultra Form applied")
                self._log(f"[CAT] ✔ #{cat.id} — Ultra Form applied")
            for i in not_found:
                logs.append(f"✘ #{i} — ไม่พบใน save")
                self._log(f"[CAT] ✘ #{i} — ไม่พบใน save")
            self._log(f"[BCSFE] Ultra Form {len(cats)}/{len(cat_ids)} cats")

            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return {"success": False, "error": str(e)}

    @staticmethod
    def _init_and_max_talents(cat, talent_data) -> int:
        """init talent objects ถ้าไม่มี แล้ว set max — return จำนวน talents ที่ max"""
        cat_skill = talent_data.get_cat_skill(cat.id)
        if cat_skill is None:
            return 0
        # init talents ถ้ายังเป็น None หรือขาด talent บางตัว
        if cat.talents is None:
            cat.talents = [BCSFETalent(s.ability_id, 0) for s in cat_skill.skills]
        else:
            existing = {t.id for t in cat.talents}
            for s in cat_skill.skills:
                if s.ability_id not in existing:
                    cat.talents.append(BCSFETalent(s.ability_id, 0))
        # max levels
        talent_count = 0
        for s in cat_skill.skills:
            talent = cat.get_talent_from_id(s.ability_id)
            if talent:
                talent.level = s.max_lv if s.max_lv > 0 else 1
                talent_count += 1
        return talent_count

    def run_talents_max_characters(self, cat_ids: list) -> dict:
        try:
            self._log(f"[OP] Max Talents Characters จำนวน {len(cat_ids)} ตัว")
            core.core_data.init_data()
            save_file = self._download_save()

            cats = self._find_owned_cats(save_file, cat_ids)

            talent_data = save_file.cats.read_talent_data(save_file)
            if talent_data is None:
                self._close_log()
                return {"success": False, "error": "ไม่สามารถโหลด talent data ได้"}

            logs = []
            not_found = [i for i in cat_ids if not any(c.id == i for c in cats)]
            count = 0
            for cat in cats:
                n = self._init_and_max_talents(cat, talent_data)
                if n > 0:
                    logs.append(f"✔ #{cat.id} — {n} talents maxed")
                    self._log(f"[CAT] ✔ #{cat.id} — {n} talents maxed")
                    count += 1
                else:
                    logs.append(f"— #{cat.id} — ไม่มี talent data")
                    self._log(f"[CAT] — #{cat.id} — ไม่มี talent data")
            for i in not_found:
                logs.append(f"✘ #{i} — ไม่พบใน save")
                self._log(f"[CAT] ✘ #{i} — ไม่พบใน save")

            self._log(f"[BCSFE] Max Talents {count}/{len(cat_ids)} cats")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return {"success": False, "error": str(e)}

    # ── All-cats variants (ทำกับทุกตัวใน save) ────────────────

    def run_unlock_all(self) -> dict:
        """Unlock ทุกตัวละครในเกม"""
        try:
            self._log("[OP] Unlock ALL cats in game")
            core.core_data.init_data()
            save_file = self._download_save()

            count = 0
            logs = []
            for cat in save_file.cats.cats:
                cat.unlocked = 1
                cat.gatya_seen = 1
                if cat.unlocked_forms == 0:
                    cat.unlocked_forms = 1
                logs.append(f"✔ #{cat.id} — unlocked")
                count += 1

            self._log(f"[BCSFE] Unlocked all {count} cats")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "count": count, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return {"success": False, "error": str(e)}

    def run_true_form_all(self) -> dict:
        """True Form ทุกตัวที่ลูกค้ามีอยู่แล้ว"""
        try:
            self._log("[OP] True Form ALL unlocked cats")
            core.core_data.init_data()
            save_file = self._download_save()

            owned = save_file.cats.get_unlocked_cats()
            save_file.cats.true_form_cats(save_file, owned)
            logs = [f"✔ #{cat.id} — True Form applied" for cat in owned]
            self._log(f"[BCSFE] True Form all {len(owned)} unlocked cats")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "count": len(owned), "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return {"success": False, "error": str(e)}

    def run_ultra_form_all(self) -> dict:
        """Ultra Form ทุกตัวที่ลูกค้ามีอยู่แล้ว (เฉพาะที่มี 4 forms จริง)"""
        try:
            self._log("[OP] Ultra Form ALL unlocked cats")
            core.core_data.init_data()
            save_file = self._download_save()

            owned = save_file.cats.get_unlocked_cats()
            # fourth_form_cats ใช้ NyankoPictureBook check total_forms — ไม่ bug แมวที่ไม่มี 4th form
            save_file.cats.fourth_form_cats(save_file, owned)
            logs = [f"✔ #{cat.id} — Ultra Form applied" for cat in owned]
            self._log(f"[BCSFE] Ultra Form all {len(owned)} unlocked cats")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "count": len(owned), "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return {"success": False, "error": str(e)}

    def run_talents_max_all(self) -> dict:
        """Max Talents ทุกตัวที่ลูกค้ามีอยู่แล้ว"""
        try:
            self._log("[OP] Max Talents ALL unlocked cats")
            core.core_data.init_data()
            save_file = self._download_save()

            talent_data = save_file.cats.read_talent_data(save_file)
            if talent_data is None:
                self._close_log()
                return {"success": False, "error": "ไม่สามารถโหลด talent data ได้"}

            owned = save_file.cats.get_unlocked_cats()
            count = 0
            logs = []
            for cat in owned:
                n = self._init_and_max_talents(cat, talent_data)
                if n > 0:
                    logs.append(f"✔ #{cat.id} — {n} talents maxed")
                    self._log(f"[CAT] ✔ #{cat.id} — {n} talents maxed")
                    count += 1

            self._log(f"[BCSFE] Max Talents all {count} cats")
            codes = self._upload_save(save_file)
            self._close_log()
            return {"success": True, "new_transfer_code": codes, "count": count, "log": logs}

        except Exception as e:
            self._log(f"[BCSFE] ❌ {e}")
            self._close_log()
            return {"success": False, "error": str(e)}
