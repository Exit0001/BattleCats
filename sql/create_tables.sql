-- Battle Cats Shop — Supabase Schema
-- รันใน Supabase Dashboard → SQL Editor → New query

create table if not exists orders (
  id            uuid        default gen_random_uuid() primary key,
  created_at    timestamptz default now(),
  auth_user     text,
  username      text        not null,
  transfer_code text,
  confirm_code  text,
  server        text,
  contact       text,
  items         jsonb       default '[]'::jsonb,
  total         numeric     default 0,
  status        text        default 'pending'
    check (status in ('pending','processing','done','cancelled','test'))
);

-- Row Level Security
alter table orders enable row level security;

-- drop ก่อนเพื่อให้รัน script ซ้ำได้โดยไม่ error
drop policy if exists "allow_insert"      on orders;
drop policy if exists "allow_select_own"  on orders;

-- ลูกค้าสร้างออเดอร์ได้ (anon key)
create policy "allow_insert"
  on orders for insert
  with check (true);

-- ลูกค้าดูออเดอร์ได้
create policy "allow_select_own"
  on orders for select
  using (true);
