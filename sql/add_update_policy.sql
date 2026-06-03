-- อนุญาตให้ admin อัปเดต status ออเดอร์ได้
-- รันใน Supabase Dashboard → SQL Editor

drop policy if exists "allow_update" on orders;

create policy "allow_update"
  on orders for update
  using (true)
  with check (true);
