-- Postgres schema: relational CRM data (companies, contacts, deals, interactions) plus tasks and audit log
CREATE TABLE companies (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  industry TEXT NOT NULL,
  website TEXT,
  relationship_status TEXT NOT NULL CHECK (relationship_status IN ('lead', 'customer', 'former_customer')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE contacts (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  full_name TEXT NOT NULL,
  job_title TEXT,
  email TEXT NOT NULL
);

CREATE TABLE deals (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  name TEXT NOT NULL,
  amount NUMERIC(12, 2) NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open', 'won', 'lost')),
  expected_close_date DATE
);

CREATE TABLE interactions (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  interaction_type TEXT NOT NULL CHECK (interaction_type IN ('email', 'call', 'meeting', 'note', 'support')),
  subject TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  summary TEXT NOT NULL
);

-- Stage 9 (tool calling / MCP): follow-up tasks the model can propose via the
-- create_followup_task tool. A row only appears here once a proposal has been
-- explicitly confirmed by the user -- a "proposed, not yet confirmed" action
-- is tracked only in tool_audit_log, never written here.
CREATE TABLE tasks (
  id SERIAL PRIMARY KEY,
  company_id INTEGER NOT NULL REFERENCES companies(id),
  note TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Stage 9: durable record of every MCP tool invocation (read and mutating),
-- so tool usage has a queryable history the same way Stage 7 (usage) and
-- Stage 8 (guardrail) telemetry do, rather than log-lines-only.
CREATE TABLE tool_audit_log (
  id SERIAL PRIMARY KEY,
  tool_name TEXT NOT NULL,
  arguments JSONB NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('executed', 'proposed', 'confirmed', 'error')),
  result_summary TEXT,
  company_id INTEGER REFERENCES companies(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Stage 8.c: every guardrail detection (input, document, tool result, model
-- output). The API also creates this with IF NOT EXISTS at startup so
-- volumes created before Stage 8.c get it without a reset.
CREATE TABLE security_audit_log (
  id SERIAL PRIMARY KEY,
  event_type TEXT NOT NULL CHECK (event_type IN ('input', 'document', 'tool', 'output')),
  endpoint TEXT NOT NULL,
  pattern TEXT NOT NULL,
  location TEXT NOT NULL,
  excerpt TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO companies (name, industry, website, relationship_status) VALUES
  ('Acme Fabrication', 'Manufacturing', 'https://acme-fabrication.example', 'customer'),
  ('Northstar Logistics', 'Logistics', 'https://northstar-logistics.example', 'lead'),
  ('Harbor & Pine', 'Retail', 'https://harbor-pine.example', 'customer'),
  ('Vertex Analytics', 'Technology', 'https://vertex-analytics.example', 'customer'),
  ('Golden Valley Foods', 'Food & Beverage', 'https://goldenvalley-foods.example', 'lead'),
  ('Summit Builders', 'Construction', 'https://summit-builders.example', 'former_customer'),
  ('Riverside Health Group', 'Healthcare', 'https://riverside-health.example', 'customer');

INSERT INTO contacts (company_id, full_name, job_title, email) VALUES
  (1, 'Maya Chen', 'Operations Director', 'maya.chen@acme-fabrication.example'),
  (1, 'Ravi Patel', 'Procurement Manager', 'ravi.patel@acme-fabrication.example'),
  (2, 'Jordan Brooks', 'Head of Customer Success', 'jordan.brooks@northstar-logistics.example'),
  (3, 'Elena Torres', 'Owner', 'elena.torres@harbor-pine.example'),
  (4, 'Priya Nandakumar', 'VP Engineering', 'priya.nandakumar@vertex-analytics.example'),
  (4, 'Tom Reyes', 'IT Administrator', 'tom.reyes@vertex-analytics.example'),
  (5, 'Carlos Mendez', 'Operations Manager', 'carlos.mendez@goldenvalley-foods.example'),
  (6, 'Dana Whitfield', 'Former Project Manager', 'dana.whitfield@summit-builders.example'),
  (7, 'Dr. Sarah Kim', 'Clinic Director', 'sarah.kim@riverside-health.example'),
  (7, 'James Okafor', 'IT Director', 'james.okafor@riverside-health.example');

INSERT INTO deals (company_id, name, amount, status, expected_close_date) VALUES
  (1, 'Premium Operations Plan renewal', 48000.00, 'open', '2026-10-15'),
  (1, 'Premium Operations Plan (initial contract)', 42000.00, 'won', '2025-10-01'),
  (2, 'Fleet Visibility rollout', 72000.00, 'open', '2026-11-01'),
  (3, 'Retail support package', 12000.00, 'won', '2026-07-12'),
  (3, 'Fleet Visibility upsell', 18000.00, 'open', '2026-12-01'),
  (4, 'Analytics Pro upgrade', 36000.00, 'open', '2026-11-20'),
  (4, 'Initial onboarding package', 15000.00, 'won', '2026-02-10'),
  (5, 'Fleet Visibility pilot', 20000.00, 'open', '2026-12-10'),
  (6, 'Site Ops Suite', 30000.00, 'lost', '2026-04-15'),
  (7, 'Premium Operations Plan', 55000.00, 'won', '2026-01-20'),
  (7, 'Fleet Visibility expansion', 40000.00, 'open', '2026-12-20');

INSERT INTO interactions (company_id, interaction_type, subject, occurred_at, summary) VALUES
  (1, 'call', 'Renewal planning call', '2026-08-28T10:00:00Z', 'Maya asked about premium-plan pricing and implementation support.'),
  (1, 'email', 'Volume discount request', '2026-08-30T14:30:00Z', 'Ravi requested a pricing breakdown for adding two factory locations.'),
  (1, 'support', 'Dashboard export timeout', '2026-09-02T09:15:00Z', 'Support shared a workaround and scheduled a follow-up.'),
  (1, 'meeting', 'Quarterly business review', '2026-09-20T15:00:00Z', 'Maya reviewed usage trends and confirmed renewal intent ahead of the October date.'),
  (2, 'meeting', 'Discovery session', '2026-08-20T16:00:00Z', 'Jordan described a need for delivery-status visibility for their team.'),
  (2, 'support', 'Pre-sales alerting limits question', '2026-08-26T13:00:00Z', 'Jordan asked whether delay alerts can be configured per fleet customer before committing.'),
  (3, 'note', 'Quarterly check-in', '2026-08-18T11:00:00Z', 'Elena is happy with response times and plans to renew.'),
  (3, 'support', 'Point-of-sale sync issue', '2026-09-05T10:30:00Z', 'Resolved a sync delay between the POS system and the dashboard within a few hours during a busy period.'),
  (4, 'call', 'Contract renewal discussion', '2026-09-10T09:00:00Z', 'Priya asked about upgrading to Analytics Pro for additional custom dashboards.'),
  (4, 'support', 'API rate limit question', '2026-09-15T14:00:00Z', 'Tom hit the default API rate limit during a bulk export and asked about raising it.'),
  (5, 'meeting', 'Discovery call on supply-chain visibility', '2026-09-08T11:00:00Z', 'Carlos described a need to track shipment delays across multiple co-packers.'),
  (5, 'email', 'Fleet Visibility pilot pricing question', '2026-09-12T16:45:00Z', 'Carlos asked for pilot pricing ahead of a budget approval meeting.'),
  (6, 'call', 'Exit interview', '2026-04-10T13:00:00Z', 'Dana explained Summit cancelled due to a company-wide budget freeze, not product dissatisfaction.'),
  (6, 'note', 'Cancellation reason', '2026-04-12T09:00:00Z', 'Recorded that Summit paused all vendor contracts during a restructuring and may revisit in the future.'),
  (7, 'call', 'Renewal discussion', '2026-09-18T10:00:00Z', 'Dr. Kim confirmed renewal and asked about expanding to a second clinic location.'),
  (7, 'support', 'Data handling and compliance question', '2026-09-22T15:30:00Z', 'James asked how patient-adjacent operational data is stored and whether it meets their compliance requirements.'),
  (7, 'email', 'Positive feedback on uptime', '2026-09-25T12:00:00Z', 'Dr. Kim praised the service uptime over the past quarter and asked about the expansion timeline.');

