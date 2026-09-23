-- Axiom Mind — схема Supabase (v14.0)
-- Выполнить в SQL Editor проекта Supabase.
-- Таблица leads уже могла существовать в прежней версии — этот скрипт
-- пересоздаёт её с новыми полями (fit_score, why_fit, description).
-- Если в ней уже есть данные, которые нужно сохранить — сначала сделайте бэкап
-- или замените "drop table" на "alter table ... add column ...".

drop table if exists public.emails cascade;
drop table if exists public.contacts cascade;
drop table if exists public.leads cascade;
drop table if exists public.searches cascade;

create table public.leads (
  id uuid not null default gen_random_uuid(),
  user_id text null,
  company_name text not null,
  website text null,
  description text null,
  fit_score integer default 0,
  why_fit text null,
  niche text null,
  city text null,
  created_at timestamp with time zone default now(),
  constraint leads_pkey primary key (id)
);

create table public.contacts (
  id uuid not null default gen_random_uuid(),
  lead_id uuid references public.leads(id) on delete cascade,
  full_name text null,
  position text null,
  email text null,
  email_status text default 'unknown',
  linkedin_url text null,
  created_at timestamp with time zone default now(),
  constraint contacts_pkey primary key (id)
);

create table public.emails (
  id uuid not null default gen_random_uuid(),
  lead_id uuid references public.leads(id) on delete cascade,
  variant text not null,
  subject text null,
  body text not null,
  created_at timestamp with time zone default now(),
  constraint emails_pkey primary key (id)
);

create table public.searches (
  id uuid not null default gen_random_uuid(),
  user_id text null,
  product_description text null,
  niche text null,
  city text null,
  created_at timestamp with time zone default now(),
  constraint searches_pkey primary key (id)
);

create index leads_fit_score_idx on public.leads(fit_score desc);
create index contacts_lead_id_idx on public.contacts(lead_id);
create index emails_lead_id_idx on public.emails(lead_id);
