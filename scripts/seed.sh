#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Seeding sample project..."

docker compose exec -T postgres psql -U mas -d mas_pipeline <<'SQL'
INSERT INTO projects (user_id, name, description, pipeline, config, status)
SELECT 1, 'Demo Blog Project', 'A sample project using the blog generation pipeline', 'blog_generation', '{}', 'active'
WHERE NOT EXISTS (
    SELECT 1 FROM projects WHERE name = 'Demo Blog Project'
);
SQL

echo "Done. Sample project seeded (if not already present)."
