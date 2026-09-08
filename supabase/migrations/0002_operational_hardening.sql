begin;

alter table runs
  add column if not exists claimed_by text,
  add column if not exists lease_expires_at timestamptz,
  add column if not exists attempt_count integer not null default 0
    check (attempt_count >= 0);

alter table products
  add column if not exists change_summary jsonb;

alter table notifications
  add column if not exists attempt_count integer not null default 0
    check (attempt_count >= 0),
  add column if not exists last_attempt_at timestamptz,
  add column if not exists next_attempt_at timestamptz not null default now();

create index if not exists notifications_delivery_idx
  on notifications (status, next_attempt_at, created_at)
  where status = 'pending';

create index if not exists runs_lease_idx
  on runs (status, lease_expires_at, created_at)
  where status in ('queued', 'running') and run_type = 'processing';

create or replace function guard_product_scene_provenance() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if exists (
    select 1
    from unnest(new.scene_ids) linked(scene_id)
    left join scenes s on s.tenant_id = new.tenant_id and s.id = linked.scene_id
    where s.id is null
  ) then
    raise exception 'every product scene must exist in the same tenant';
  end if;
  return new;
end $$;

drop trigger if exists product_scene_provenance_guard on products;
create trigger product_scene_provenance_guard
before insert or update of tenant_id, scene_ids on products
for each row execute function guard_product_scene_provenance();

create or replace function guard_published_product_immutability() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if old.status = 'published' and new is distinct from old then
    raise exception 'published products are immutable';
  end if;
  return new;
end $$;

drop trigger if exists published_product_immutability_guard on products;
create trigger published_product_immutability_guard
before update on products
for each row execute function guard_published_product_immutability();

commit;
