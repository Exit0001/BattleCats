-- ตาราง profiles สำหรับระบบ login/register
-- รันใน Supabase Dashboard → SQL Editor

create table if not exists profiles (
  id           uuid        default gen_random_uuid() primary key,
  created_at   timestamptz default now(),
  username     text        not null unique,
  password_hash text       not null
);

alter table profiles enable row level security;

drop policy if exists "profiles_insert" on profiles;
drop policy if exists "profiles_select" on profiles;

create policy "profiles_insert"
  on profiles for insert with check (true);

create policy "profiles_select"
  on profiles for select using (true);
