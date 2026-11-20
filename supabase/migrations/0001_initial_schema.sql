-- Open ML Studio — Supabase foundation schema
-- Apply through the Supabase SQL Editor or a reviewed migration process.
-- This migration creates metadata tables and Row Level Security policies.
-- It does NOT create credentials or enable public access to stored files.

create extension if not exists pgcrypto;

create table if not exists public.projects (
    id uuid primary key default gen_random_uuid(),
    owner_user_id uuid not null references auth.users(id) on delete restrict,
    name text not null check (char_length(trim(name)) between 1 and 120),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.project_members (
    project_id uuid not null references public.projects(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null check (role in ('owner', 'admin', 'editor', 'viewer')),
    created_at timestamptz not null default now(),
    primary key (project_id, user_id)
);

create table if not exists public.datasets (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.projects(id) on delete cascade,
    owner_user_id uuid not null references auth.users(id) on delete restrict,
    filename text not null,
    object_key text not null unique,
    sha256 char(64) not null,
    size_bytes bigint not null check (size_bytes >= 0),
    row_count bigint check (row_count is null or row_count >= 0),
    column_count integer check (column_count is null or column_count >= 0),
    status text not null default 'pending' check (status in ('pending', 'ready', 'failed', 'deleting')),
    profile_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    deleted_at timestamptz
);

create table if not exists public.experiments (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.projects(id) on delete cascade,
    dataset_id uuid references public.datasets(id) on delete set null,
    owner_user_id uuid not null references auth.users(id) on delete restrict,
    task text not null check (task in ('classification', 'regression', 'clustering', 'anomaly_detection', 'analysis')),
    target text,
    config_json jsonb not null default '{}'::jsonb,
    metrics_json jsonb not null default '{}'::jsonb,
    status text not null default 'queued' check (status in ('queued', 'running', 'completed', 'failed', 'cancelled')),
    error_summary text,
    created_at timestamptz not null default now(),
    completed_at timestamptz
);

create table if not exists public.models (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references public.projects(id) on delete cascade,
    owner_user_id uuid not null references auth.users(id) on delete restrict,
    name text not null,
    task text not null check (task in ('classification', 'regression')),
    created_at timestamptz not null default now(),
    archived_at timestamptz
);

create table if not exists public.model_versions (
    id uuid primary key default gen_random_uuid(),
    model_id uuid not null references public.models(id) on delete cascade,
    experiment_id uuid references public.experiments(id) on delete set null,
    version integer not null check (version > 0),
    artifact_key text not null unique,
    metrics_json jsonb not null default '{}'::jsonb,
    feature_schema_json jsonb not null default '{}'::jsonb,
    library_versions_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    is_active boolean not null default false,
    unique (model_id, version)
);

create table if not exists public.audit_events (
    id uuid primary key default gen_random_uuid(),
    project_id uuid references public.projects(id) on delete set null,
    actor_user_id uuid references auth.users(id) on delete set null,
    action text not null,
    resource_type text not null,
    resource_id uuid,
    details_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_projects_owner on public.projects(owner_user_id, created_at desc);
create index if not exists idx_project_members_user on public.project_members(user_id, project_id);
create index if not exists idx_datasets_project on public.datasets(project_id, created_at desc) where deleted_at is null;
create index if not exists idx_experiments_project on public.experiments(project_id, created_at desc);
create index if not exists idx_experiments_dataset on public.experiments(dataset_id);
create index if not exists idx_models_project on public.models(project_id, created_at desc);
create index if not exists idx_model_versions_model on public.model_versions(model_id, version desc);
create index if not exists idx_audit_events_project on public.audit_events(project_id, created_at desc);

alter table public.projects enable row level security;
alter table public.project_members enable row level security;
alter table public.datasets enable row level security;
alter table public.experiments enable row level security;
alter table public.models enable row level security;
alter table public.model_versions enable row level security;
alter table public.audit_events enable row level security;

-- Projects: owners can manage their projects; invited members can read.
create policy "project members can read projects"
on public.projects for select to authenticated
using (
    owner_user_id = (select auth.uid())
    or exists (
        select 1 from public.project_members pm
        where pm.project_id = id and pm.user_id = (select auth.uid())
    )
);

create policy "users can create their own projects"
on public.projects for insert to authenticated
with check (owner_user_id = (select auth.uid()));

create policy "owners can update projects"
on public.projects for update to authenticated
using (owner_user_id = (select auth.uid()))
with check (owner_user_id = (select auth.uid()));

create policy "owners can delete projects"
on public.projects for delete to authenticated
using (owner_user_id = (select auth.uid()));

-- Membership management is restricted to project owners.
create policy "members can read project membership"
on public.project_members for select to authenticated
using (
    user_id = (select auth.uid())
    or exists (
        select 1 from public.projects p
        where p.id = project_id and p.owner_user_id = (select auth.uid())
    )
);

create policy "owners can add project members"
on public.project_members for insert to authenticated
with check (
    exists (
        select 1 from public.projects p
        where p.id = project_id and p.owner_user_id = (select auth.uid())
    )
);

create policy "owners can remove project members"
on public.project_members for delete to authenticated
using (
    exists (
        select 1 from public.projects p
        where p.id = project_id and p.owner_user_id = (select auth.uid())
    )
);

-- Tenant-owned resource access: owner or project member.
create policy "project members can read datasets"
on public.datasets for select to authenticated
using (
    deleted_at is null and exists (
        select 1 from public.project_members pm
        where pm.project_id = project_id and pm.user_id = (select auth.uid())
    )
    or owner_user_id = (select auth.uid())
);

create policy "project editors can create datasets"
on public.datasets for insert to authenticated
with check (
    owner_user_id = (select auth.uid())
    and exists (
        select 1 from public.project_members pm
        where pm.project_id = project_id
          and pm.user_id = (select auth.uid())
          and pm.role in ('owner', 'admin', 'editor')
    )
);

create policy "project editors can update datasets"
on public.datasets for update to authenticated
using (
    exists (
        select 1 from public.project_members pm
        where pm.project_id = project_id
          and pm.user_id = (select auth.uid())
          and pm.role in ('owner', 'admin', 'editor')
    )
)
with check (owner_user_id = (select auth.uid()));

create policy "project owners and admins can delete datasets"
on public.datasets for delete to authenticated
using (
    exists (
        select 1 from public.project_members pm
        where pm.project_id = project_id
          and pm.user_id = (select auth.uid())
          and pm.role in ('owner', 'admin')
    )
);

create policy "project members can read experiments"
on public.experiments for select to authenticated
using (
    exists (
        select 1 from public.project_members pm
        where pm.project_id = project_id and pm.user_id = (select auth.uid())
    )
);

create policy "project editors can create experiments"
on public.experiments for insert to authenticated
with check (
    owner_user_id = (select auth.uid())
    and exists (
        select 1 from public.project_members pm
        where pm.project_id = project_id
          and pm.user_id = (select auth.uid())
          and pm.role in ('owner', 'admin', 'editor')
    )
);

create policy "project editors can update experiments"
on public.experiments for update to authenticated
using (
    exists (
        select 1 from public.project_members pm
        where pm.project_id = project_id
          and pm.user_id = (select auth.uid())
          and pm.role in ('owner', 'admin', 'editor')
    )
)
with check (owner_user_id = (select auth.uid()));

create policy "project members can read models"
on public.models for select to authenticated
using (
    exists (
        select 1 from public.project_members pm
        where pm.project_id = project_id and pm.user_id = (select auth.uid())
    )
);

create policy "project editors can create models"
on public.models for insert to authenticated
with check (
    owner_user_id = (select auth.uid())
    and exists (
        select 1 from public.project_members pm
        where pm.project_id = project_id
          and pm.user_id = (select auth.uid())
          and pm.role in ('owner', 'admin', 'editor')
    )
);

create policy "project owners can update models"
on public.models for update to authenticated
using (
    exists (
        select 1 from public.project_members pm
        where pm.project_id = project_id
          and pm.user_id = (select auth.uid())
          and pm.role in ('owner', 'admin')
    )
);

create policy "project members can read model versions"
on public.model_versions for select to authenticated
using (
    exists (
        select 1 from public.models m
        join public.project_members pm on pm.project_id = m.project_id
        where m.id = model_id and pm.user_id = (select auth.uid())
    )
);

create policy "project editors can create model versions"
on public.model_versions for insert to authenticated
with check (
    exists (
        select 1 from public.models m
        join public.project_members pm on pm.project_id = m.project_id
        where m.id = model_id
          and pm.user_id = (select auth.uid())
          and pm.role in ('owner', 'admin', 'editor')
    )
);

create policy "project members can read audit events"
on public.audit_events for select to authenticated
using (
    actor_user_id = (select auth.uid())
    or exists (
        select 1 from public.project_members pm
        where pm.project_id = project_id and pm.user_id = (select auth.uid())
    )
);

-- Private artifact bucket. Server-side service-role access is expected for the
-- API after it independently authorizes the user/project. Do not expose the
-- service-role key to the browser.
insert into storage.buckets (id, name, public)
values ('open-ml-artifacts', 'open-ml-artifacts', false)
on conflict (id) do update set public = false;

-- Optional user-scoped storage access for clients using authenticated Supabase
-- sessions. Object keys must start with the authenticated user's UUID.
create policy "users can read own artifact objects"
on storage.objects for select to authenticated
using (
    bucket_id = 'open-ml-artifacts'
    and (storage.foldername(name))[1] = (select auth.uid())::text
);

create policy "users can upload own artifact objects"
on storage.objects for insert to authenticated
with check (
    bucket_id = 'open-ml-artifacts'
    and (storage.foldername(name))[1] = (select auth.uid())::text
);

create policy "users can delete own artifact objects"
on storage.objects for delete to authenticated
using (
    bucket_id = 'open-ml-artifacts'
    and (storage.foldername(name))[1] = (select auth.uid())::text
);
