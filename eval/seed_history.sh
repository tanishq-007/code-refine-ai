#!/usr/bin/env bash
# eval/seed_history.sh
# Gives eval/sample_repo a realistic git history so analyzers/churn.py has
# real commit-count data instead of an empty repo. Idempotent-ish: re-running
# just re-inits and replays the same synthetic history.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$HERE/sample_repo"

cd "$REPO"
rm -rf .git
git init -q
git config user.email "eval@code-debt-collector.local"
git config user.name "Eval Seeder"

git add src/pricing.py tests
git commit -q -m "initial: pricing + tests scaffold"

git add src/orders.py
git commit -q -m "add orders module"

# Simulate a hot-spot: orders.py gets touched repeatedly (churn signal).
for msg in "tweak discount rounding" "add coupon handling" "add shipping rules" \
           "fix membership discount" "add fulfillment marking"; do
  { echo ""; echo "# churn commit: $msg"; } >> src/orders.py
  git add src/orders.py
  git commit -q -m "$msg"
done

echo "Seeded $(git -C "$REPO" log --oneline | wc -l) commits in $REPO"
