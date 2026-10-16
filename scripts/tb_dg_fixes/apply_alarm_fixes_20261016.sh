#!/usr/bin/env bash
# Applies the tested alarm fixes of 16 Oct 2026 to the live ThingsBoard and checks the result.
#   1. Fire / LT Panels / RO profile alarm rules (scripts/tb_dg_fixes/alarm_rules_fire_lt_ro.py)
#   2. 'DG No Data' alarm in the root rule chain (scripts/tb_dg_fixes/deploy_dg_no_data_alarm.py)
#   3. Live check: a '[TEST]' device with a 60 s inactivity timeout must raise and clear 'DG No Data'
#      (its alarms reach only the notifier log, never the real Telegram chats)
# Backups go to /home/ubuntu/tb_alarm_fix/backup. Stops at the first failure.
set -euo pipefail
cd /home/ubuntu/thingsboard
B=/home/ubuntu/tb_alarm_fix/backup
quiet() { grep -v -E "^INFO|impersonation" || true; }

echo "== 1. Fire / LT / RO alarm rules"
python3 scripts/tb_dg_fixes/alarm_rules_fire_lt_ro.py --apply "$B" 2>&1 | quiet

echo "== 2. DG No Data alarm"
python3 scripts/tb_dg_fixes/deploy_dg_no_data_alarm.py "$B/rulechain_before_no_data_20261016.json" --apply 2>&1 | quiet | grep -E "^POST|already|backup"

echo "== 3. Live check of the No Data alarm (about 4 minutes)"
python3 scripts/tb_dg_fixes/check_no_data_alarm.py 2>&1 | quiet
