create table if not exists public.mirofish_simulations (
  simulation_id text primary key,
  project_id text not null,
  graph_id text not null,
  status text not null,
  state jsonb not null default '{}'::jsonb,
  simulation_config jsonb,
  reddit_profiles jsonb,
  twitter_profiles jsonb,
  project_snapshot jsonb,
  run_state jsonb,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_mirofish_simulations_project_id
  on public.mirofish_simulations (project_id);

create index if not exists idx_mirofish_simulations_status
  on public.mirofish_simulations (status);

alter table public.mirofish_simulations enable row level security;
