begin;

create extension if not exists postgis;
create extension if not exists pgcrypto;

create type product_status as enum ('draft', 'approved', 'published');
create type run_status as enum ('queued', 'running', 'succeeded', 'failed', 'skipped');
create type notification_status as enum ('pending', 'sent', 'failed');

create table tenants (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  created_at timestamptz not null default now()
);

create table tenant_members (
  tenant_id uuid not null references tenants(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('viewer', 'reviewer', 'admin')),
  primary key (tenant_id, user_id)
);

create table aois (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  name text not null,
  geometry geometry(MultiPolygon, 4326) not null,
  cadence_days integer not null check (cadence_days > 0),
  cloud_threshold numeric(5,2) not null check (cloud_threshold between 0 and 100),
  product_recipes text[] not null check (cardinality(product_recipes) > 0),
  stac_collections text[] not null default array['sentinel-2-l2a']::text[],
  internal_only boolean not null default false,
  enabled boolean not null default true,
  stakeholder_emails text[] not null default '{}',
  stakeholder_imessage_handles text[] not null default '{}',
  reference_config jsonb,
  drift_config jsonb not null default '{}'::jsonb,
  last_scheduled_at timestamptz,
  created_at timestamptz not null default now(),
  unique (tenant_id, name)
);
create index aois_geometry_gix on aois using gist (geometry);
create index aois_due_idx on aois (enabled, last_scheduled_at);

create table scenes (
  id text not null,
  tenant_id uuid not null references tenants(id) on delete cascade,
  sensor text not null,
  acquired_at timestamptz not null,
  cloud_pct numeric(5,2) not null check (cloud_pct between 0 and 100),
  cog_href text not null,
  stac_collection text not null,
  stac_item jsonb not null,
  created_at timestamptz not null default now(),
  primary key (tenant_id, id)
);

create table products (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  aoi_id uuid not null references aois(id) on delete cascade,
  recipe text not null,
  model_name text not null,
  model_version text not null,
  scene_ids text[] not null check (cardinality(scene_ids) > 0),
  accuracy jsonb,
  drift jsonb,
  status product_status not null default 'draft',
  asset_href text,
  cloud_threshold numeric(5,2) not null check (cloud_threshold between 0 and 100),
  processed_at timestamptz not null,
  created_at timestamptz not null default now(),
  approved_by uuid references auth.users(id),
  approved_at timestamptz,
  published_at timestamptz,
  constraint product_approval_consistency check (
    (status = 'draft' and approved_by is null and approved_at is null and published_at is null)
    or (status = 'approved' and approved_by is not null and approved_at is not null and published_at is null)
    or (status = 'published' and published_at is not null and (
      (approved_by is not null and approved_at is not null)
      or (approved_by is null and approved_at is null)
    ))
  )
);
create index products_tenant_aoi_created_idx on products (tenant_id, aoi_id, created_at desc);
create index products_review_queue_idx on products (tenant_id, status, created_at);

create table runs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  aoi_id uuid references aois(id) on delete cascade,
  product_id uuid references products(id) on delete set null,
  parent_run_id uuid references runs(id) on delete set null,
  run_type text not null,
  runner text not null,
  status run_status not null default 'queued',
  action text not null,
  details jsonb not null default '{}'::jsonb,
  auto_fix boolean not null default false,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now()
);
create index runs_queue_idx on runs (status, created_at) where status = 'queued';
create index runs_tenant_created_idx on runs (tenant_id, created_at desc);

create table product_approvals (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  product_id uuid not null references products(id) on delete cascade,
  reviewer_id uuid not null references auth.users(id),
  decision text not null check (decision in ('approved', 'rejected')),
  comment text,
  created_at timestamptz not null default now()
);

create table notifications (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  product_id uuid not null references products(id) on delete cascade,
  channel text not null check (channel in ('email', 'imessage')),
  recipient text not null,
  status notification_status not null default 'pending',
  provider_message_id text,
  error text,
  sent_at timestamptz,
  created_at timestamptz not null default now()
);

create table tenant_push_tokens (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references tenants(id) on delete cascade,
  provider text not null,
  secret_ref text not null,
  scopes text[] not null default '{}',
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  unique (tenant_id, provider)
);
comment on column tenant_push_tokens.secret_ref is 'Reference to an external secret manager; never plaintext credentials.';

create or replace function current_tenant_id() returns uuid
language sql stable as $$
  select nullif(current_setting('app.tenant_id', true), '')::uuid
$$;

create or replace function is_tenant_member(target uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from tenant_members
    where tenant_id = target and user_id = coalesce(auth.uid(), nullif(current_setting('app.user_id', true), '')::uuid)
  ) or target = current_tenant_id()
$$;

create or replace function has_tenant_role(target uuid, allowed text[]) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from tenant_members
    where tenant_id = target
      and user_id = coalesce(auth.uid(), nullif(current_setting('app.user_id', true), '')::uuid)
      and role = any(allowed)
  )
$$;

alter table tenants enable row level security;
alter table tenant_members enable row level security;
alter table aois enable row level security;
alter table scenes enable row level security;
alter table products enable row level security;
alter table runs enable row level security;
alter table product_approvals enable row level security;
alter table notifications enable row level security;
alter table tenant_push_tokens enable row level security;

create policy tenants_select on tenants for select using (is_tenant_member(id));
create policy members_select on tenant_members for select using (is_tenant_member(tenant_id));

do $$
declare table_name text;
begin
  foreach table_name in array array['aois','scenes','products','runs','product_approvals','notifications','tenant_push_tokens']
  loop
    execute format('create policy %I on %I for select using (is_tenant_member(tenant_id))', table_name || '_select', table_name);
  end loop;
end $$;

create policy products_reviewer_update on products for update
using (has_tenant_role(tenant_id, array['reviewer','admin']))
with check (has_tenant_role(tenant_id, array['reviewer','admin']));
create policy approvals_reviewer_insert on product_approvals for insert
with check (has_tenant_role(tenant_id, array['reviewer','admin']) and reviewer_id = auth.uid());

create or replace function guard_product_status_transition() returns trigger
language plpgsql security definer set search_path = public as $$
declare internal_aoi boolean;
begin
  if old.status = 'published' and new.status <> old.status then
    raise exception 'published products are immutable';
  end if;
  if old.status = 'draft' and new.status = 'published' then
    select internal_only into internal_aoi from aois where id = new.aoi_id and tenant_id = new.tenant_id;
    if not coalesce(internal_aoi, false) then
      raise exception 'official products must be approved before publication';
    end if;
  end if;
  if old.status = 'approved' and new.status = 'published' then
    if old.approved_by is null or old.approved_at is null or not exists (
      select 1 from product_approvals pa
      where pa.product_id = old.id and pa.tenant_id = old.tenant_id
        and pa.reviewer_id = old.approved_by and pa.decision = 'approved'
    ) then
      raise exception 'logged human approval required';
    end if;
  end if;
  return new;
end $$;

create trigger product_status_guard before update of status on products
for each row execute function guard_product_status_transition();

commit;
