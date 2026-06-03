-- แก้ check constraint เพื่อรองรับ status = 'test'
-- รันใน Supabase Dashboard → SQL Editor

alter table orders drop constraint if exists orders_status_check;

alter table orders add constraint orders_status_check
  check (status in ('pending','processing','done','cancelled','test'));
