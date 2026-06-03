-- ════════════════════════════════════════════════
-- รันใน Supabase Dashboard → SQL Editor
-- ════════════════════════════════════════════════

-- 1. เพิ่มคอลัมน์ slip_data และ paid_at ใน orders
alter table orders
  add column if not exists slip_data text,
  add column if not exists paid_at   timestamptz;

-- 2. อัปเดต status check ให้ครอบคลุม pending_payment / pending_confirm
alter table orders drop constraint if exists orders_status_check;
alter table orders add constraint orders_status_check
  check (status in (
    'pending', 'pending_payment', 'pending_confirm',
    'processing', 'done', 'cancelled', 'test'
  ));

-- 3. เพิ่ม is_admin ใน profiles
alter table profiles
  add column if not exists is_admin boolean default false;

-- 4. allow_update policy ครอบคลุม slip_data
drop policy if exists "allow_update" on orders;
create policy "allow_update"
  on orders for update using (true) with check (true);

-- ════════════════════════════════════════════════
-- 5. สร้าง admin account
--    เปลี่ยน 'admin' และ password ตามต้องการ
--    password_hash = btoa(unescape(encodeURIComponent('รหัสผ่านของคุณ')))
--    ตัวอย่างด้านล่างใช้รหัสผ่าน: Admin@1234
-- ════════════════════════════════════════════════
insert into profiles (username, password_hash, is_admin)
values ('admin', 'QWRtaW5AMTIzNA==', true)
on conflict (username) do update set is_admin = true;
-- หมายเหตุ: QWRtaW5AMTIzNA== = btoa('Admin@1234')
-- เปลี่ยนได้โดยรัน: btoa(unescape(encodeURIComponent('รหัสผ่านใหม่'))) ใน console browser
