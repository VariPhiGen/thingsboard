# AI Copilot — Test Cases Catalog

**Suite location:** `ai-copilot/tests/`  
**Total collected cases:** 199  
**Run command:**

```bash
cd ai-copilot
source .venv/bin/activate
pytest tests/ -v
```

This document lists every automated test case, including parametrized edge cases.

---

## 1. Smoke / Core (`test_core.py`)

Quick sanity checks for the main building blocks.

| # | Test | What it verifies |
|---|------|------------------|
| 1 | `test_normalize_sentinel` | Sentinel values `32767` / `≥30000` → `N/A`; normal numbers format correctly |
| 2 | `test_intent_secrets` | Secrets blocked; alarms/status classified |
| 3 | `test_intent_analytics` | Statistics, trend, shift, duration, comparison, date, time intents |
| 4 | `test_time_window_and_metrics` | Last N hours + morning shift windows; metric alias extraction |
| 5 | `test_stats_trend_duration` | Avg/stats, rising trend, RPM-based running hours |
| 6 | `test_device_resolver_exact_and_ambiguous` | Resolve by ID/name; clarify when no device mentioned |

---

## 2. Intent Classifier (`test_intent.py`)

### 2.1 Empty / general

| Message | Expected intent |
|---------|-----------------|
| `""` | `GENERAL` |
| `"   "` | `GENERAL` |
| `hello` | `GENERAL` |
| `thanks` | `GENERAL` |

**Test:** `test_empty_and_general`

### 2.2 Secrets & config changes (blocked)

| Message | Expected |
|---------|----------|
| Show me the API key | `UNSUPPORTED_SECRETS` |
| what is the password? | `UNSUPPORTED_SECRETS` |
| reveal the secret token | `UNSUPPORTED_SECRETS` |
| private key please | `UNSUPPORTED_SECRETS` |
| change the configuration | `UNSUPPORTED_SECRETS` |
| update rule chain settings | `UNSUPPORTED_SECRETS` |
| delete credential for device | `UNSUPPORTED_SECRETS` |
| modify config of DG SET1 | `UNSUPPORTED_SECRETS` |
| API-KEY value | `UNSUPPORTED_SECRETS` |
| share credential | `UNSUPPORTED_SECRETS` |

**Test:** `test_secrets_and_config_changes_blocked`

### 2.3 Core operator intents

| Message | Expected |
|---------|----------|
| What alarms are active? | `ALARMS` |
| Any alert on DG? | `ALARMS` |
| Show faults and trips | `ALARMS` |
| common alarm status | `ALARMS` |
| Is DG SET1 running? | `STATUS` |
| Current oil pressure | `STATUS` |
| coolant and fuel levels | `STATUS` |
| battery voltage now | `STATUS` |
| rpm and power | `STATUS` |
| device offline? | `STATUS` |
| AI summary please | `AI_GUIDANCE` |
| health score and RUL | `AI_GUIDANCE` |
| failure risk guidance | `AI_GUIDANCE` |
| maintenance recommendation | `AI_GUIDANCE` |
| how to reset common alarm | `MANUAL_HOWTO` |
| SOP for night shift handover | `MANUAL_HOWTO` |
| manual procedure steps to start DG | `MANUAL_HOWTO` |
| how do I check oil filter | `MANUAL_HOWTO` |

**Test:** `test_core_operator_intents`

### 2.4 Analytics intents

| Message | Expected |
|---------|----------|
| Average power last 6 hours | `STATISTICS` |
| max coolant today | `STATISTICS` |
| min oil pressure | `STATISTICS` |
| stats for RPM | `STATISTICS` |
| mean fuel level | `STATISTICS` |
| median battery | `STATISTICS` |
| Coolant trend over time | `TREND` |
| is power rising? | `TREND` |
| RPM falling? | `TREND` |
| oil increasing or decreasing | `TREND` |
| Morning shift oil pressure | `SHIFT_BASED` |
| afternoon shift power | `SHIFT_BASED` |
| night shift status | `SHIFT_BASED` |
| A shift average load | `SHIFT_BASED` |
| B shift RPM | `SHIFT_BASED` |
| C shift fuel | `SHIFT_BASED` |
| How long did DG run today? | `DURATION_BASED` |
| running hours yesterday | `DURATION_BASED` |
| uptime last night | `DURATION_BASED` |
| duration of run | `DURATION_BASED` |
| downtime estimate | `DURATION_BASED` |
| Power yesterday | `DATE_BASED` |
| status today | `DATE_BASED` |
| this week average | `STATISTICS` *(statistics wins over date)* |
| this week power | `DATE_BASED` |
| on 2026-07-20 power | `DATE_BASED` |
| readings on 20/07/2026 | `DATE_BASED` |
| Last 2 hours RPM | `TIME_BASED` |
| last hour power | `TIME_BASED` |
| past 24 hours status | `TIME_BASED` |
| last day overview | `TIME_BASED` |
| history of oil | `TIME_BASED` |
| last 15 minutes coolant | `TIME_BASED` *(“min” must not match inside “minutes”)* |
| Compare today vs yesterday power | `COMPARISON` |
| power vs yesterday | `COMPARISON` |
| difference between morning and afternoon | `COMPARISON` |
| compare DG SET1 vs gateway001 | `COMPARE_DEVICES` |
| both devices power | `COMPARE_DEVICES` |
| fleet comparison | `COMPARE_DEVICES` |
| all devices RPM | `COMPARE_DEVICES` |

**Test:** `test_analytics_intents`

### 2.5 Priority / edge rules

| Test | Edge case |
|------|-----------|
| `test_shift_wins_over_today_date` | “morning shift today …” → `SHIFT_BASED` |
| `test_compare_without_device_is_period_comparison` | “compare today vs yesterday” → period `COMPARISON` |
| `test_secrets_take_priority_over_status` | Secrets beat status keywords |
| `test_manual_before_status_keywords` | “how to check oil …” → `MANUAL_HOWTO` |

---

## 3. Device Resolver (`test_device_resolver.py`)

| # | Test | Edge case / behavior |
|---|------|----------------------|
| 1 | `test_resolve_by_device_id` | Explicit UUID resolves without clarification |
| 2 | `test_resolve_inaccessible_device_id` | Unknown UUID → clarify, empty candidates |
| 3 | `test_single_device_auto_select` | One accessible device → auto-select |
| 4 | `test_multi_device_no_mention_needs_clarification` | Multi-device, no name → ask which device |
| 5 | `test_exact_name_from_message` | “status of DG SET1” extracts device |
| 6 | `test_device_query_exact` | `deviceQuery=gateway001` |
| 7 | `test_device_query_case_insensitive` | `dg set1` matches `DG SET1` |
| 8 | `test_partial_match_unique` | Unique partial “gateway” |
| 9 | `test_ambiguous_partial_match` | “DG SET” matches SET1/SET2/SET10 → clarify |
| 10 | `test_no_match_returns_catalog` | Unknown name returns catalog |
| 11 | `test_label_match` | Match by device label |
| 12 | `test_alias_dgset1` | Alias `dgset1` |
| 13 | `test_alias_set1` | Alias `set1` |
| 14 | `test_alias_gateway` | Alias `gateway` |
| 15 | `test_longer_name_preferred_over_shorter_substring` | `DG SET10` preferred over `DG SET1` |
| 16 | `test_empty_device_list` | No devices → clarify |
| 17 | `test_device_id_wins_over_message` | Explicit ID overrides name in message |

---

## 4. Time Window & Metrics (`test_time_window.py`)

| # | Test | Edge case / behavior |
|---|------|----------------------|
| 1 | `test_last_n_minutes` | “last 15 minutes” span = 15 min |
| 2 | `test_last_n_hours` | “last 3 hours” |
| 3 | `test_last_n_days` | “last 2 days” |
| 4 | `test_last_hour_and_past_hour` | Synonyms for 1 hour |
| 5 | `test_last_day_and_24h` | last day / last 24 / past 24 |
| 6 | `test_yesterday_full_day` | Full IST calendar day |
| 7 | `test_today_from_midnight_to_now` | Midnight → now |
| 8 | `test_this_week_monday_start` | Week starts Monday IST |
| 9 | `test_iso_date` | `2026-07-20` |
| 10 | `test_dmy_date` | `20/07/2026` |
| 11 | `test_morning_shift_hours` | 06:00–14:00 IST |
| 12 | `test_afternoon_and_evening_shift` | 14:00 start |
| 13 | `test_night_shift_crosses_midnight` | Night shift across midnight |
| 14 | `test_letter_shifts_a_b_c` | A/B/C shift aliases |
| 15 | `test_generic_shift_uses_current_clock` | “current shift” uses clock |
| 16 | `test_yesterday_morning_shift` | Yesterday + shift → shift window (not full day) |
| 17 | `test_default_relative_24h` | Unknown phrase → last 24h relative |
| 18 | `test_empty_message_defaults` | Empty string → relative 24h |
| 19 | `test_extract_metrics_aliases` | power / oil / rpm aliases |
| 20 | `test_extract_metrics_temperature_alias` | “temperature” → coolant |
| 21 | `test_extract_metrics_fallback_defaults` | Default DG metrics when none named |
| 22 | `test_extract_metrics_fallback_when_no_defaults` | Gateway keys fallback |
| 23 | `test_extract_metrics_empty_message_and_keys` | Empty → `[]` |

---

## 5. Analytics (`test_analytics.py`)

| # | Test | Edge case / behavior |
|---|------|----------------------|
| 1 | `test_to_float_valid_and_sentinel` | Numbers, empty, non-numeric, ≥30000 → `None` |
| 2 | `test_series_values_sorts_and_skips_invalid` | Sort ascending; skip bad ts/sentinel |
| 3 | `test_compute_stats_empty` | Empty → `{count: 0}` |
| 4 | `test_compute_stats_single_and_many` | min/max/avg/first/last |
| 5 | `test_compute_trend_insufficient` | 0–1 points → `insufficient_data` |
| 6 | `test_compute_trend_rising_falling_stable` | Direction matrix |
| 7 | `test_compute_trend_zero_baseline_pct` | From 0 → `change_pct` is `None` |
| 8 | `test_duration_insufficient` | No series → 0 hours |
| 9 | `test_duration_from_rpm` | RPM > 100 accumulates running time |
| 10 | `test_duration_from_status_when_no_rpm` | `dg_status ≥ 1` fallback |
| 11 | `test_duration_prefers_rpm_over_status` | RPM method preferred |
| 12 | `test_analyze_window_modes` | statistics/trend/duration/time/date/shift/general |
| 13 | `test_analyze_window_no_samples` | “no valid samples” messaging |
| 14 | `test_fetch_window_series_builds_keys` | Includes metric + status/rpm extras |
| 15 | `test_compare_periods_and_devices` | Period A/B and multi-device compare text |

---

## 6. Telemetry (`test_telemetry.py`)

### 6.1 `normalize_value` matrix

| Input | Expected |
|-------|----------|
| `None` | `N/A` |
| `""` | `N/A` |
| `32767` | `N/A` |
| `30000` | `N/A` |
| `30000.1` | `N/A` |
| `1500` | `1500` |
| `1500.0` | `1500` |
| `128.90` | `128.9` |
| `128.901` | `128.9` |
| `"RUNNING"` | `RUNNING` |
| `"12.50"` | `12.5` |

**Test:** `test_normalize_value_matrix`

### 6.2 Other telemetry tests

| Test | Behavior |
|------|----------|
| `test_keys_for_device_gateway_by_name_and_type` | Gateway vs DG key sets |
| `test_flatten_latest_empty` | Empty telemetry → empty values |
| `test_flatten_latest_picks_first_point_and_max_ts` | Latest point + max timestamp |
| `test_fetch_latest_snapshot` | Snapshot with sentinel RPM → `N/A` |
| `test_fetch_active_alarms_details_shapes` | dict / string / null alarm details |
| `test_fetch_ai_scores_and_history` | AI keys + history first/last points |

---

## 7. Memory & Rate Limit (`test_memory.py`)

| # | Test | Edge case / behavior |
|---|------|----------------------|
| 1 | `test_ensure_conversation_id_generates_and_reuses` | New UUID vs reuse |
| 2 | `test_append_and_get_messages` | USER/ASSISTANT stored |
| 3 | `test_append_empty_content_ignored` | Empty content not stored |
| 4 | `test_memory_max_messages_trim` | Trims to max messages |
| 5 | `test_memory_ttl_expires` | Stale conversation cleared |
| 6 | `test_unknown_conversation_returns_empty` | Unknown ID → `[]` |
| 7 | `test_rate_limiter_allows_then_blocks_min_interval` | Min interval between asks |
| 8 | `test_rate_limiter_window_count` | Window count limit |
| 9 | `test_rate_limiter_keys_by_device` | Limits keyed per user+device |

---

## 8. Session / Orchestrator (`test_session.py`)

End-to-end orchestrator flows with mocked TB + LLM.

| # | Test | Edge case / behavior |
|---|------|----------------------|
| 1 | `test_secrets_intent_short_circuits` | Secrets reply without LLM/tools |
| 2 | `test_clarify_when_no_device` | Numbered device list clarification |
| 3 | `test_status_with_device_id` | Status grounded on selected device |
| 4 | `test_resolve_from_message_name` | Name in question resolves device |
| 5 | `test_rate_limit_blocks` | Rate limit message returned |
| 6 | `test_permission_denied` | Access denied for device |
| 7 | `test_llm_failure_returns_fallback` | OpenAI error → fallback text |
| 8 | `test_empty_llm_answer_uses_fallback` | Empty model answer → fallback |
| 9 | `test_analytics_time_based` | History analysis source attached |
| 10 | `test_comparison_today_vs_yesterday` | Period comparison grounding |
| 11 | `test_compare_devices_intent` | Fleet/device comparison grounding |
| 12 | `test_manual_howto_uses_rag` | RAG snippets included for SOP |
| 13 | `test_inaccessible_device_id_clarifies` | Bad deviceId → clarify |
| 14 | `test_list_devices` | Device catalog listing |
| 15 | `test_tooling_exception_still_answers` | TB tool failure still returns LLM answer |

---

## 9. Auth & API (`test_auth_api.py`)

| # | Test | Edge case / behavior |
|---|------|----------------------|
| 1 | `test_extract_bearer_from_authorization` | `Bearer …` and raw token |
| 2 | `test_extract_bearer_prefers_x_authorization` | Header order |
| 3 | `test_extract_bearer_missing` | Missing → HTTP 401 |
| 4 | `test_get_tb_user_success` | Valid TB `/api/auth/user` |
| 5 | `test_get_tb_user_unauthorized` | TB 401 → HTTP 401 |
| 6 | `test_get_tb_user_bad_gateway` | TB 5xx → HTTP 502 |
| 7 | `test_chat_request_validation` | Empty message / >4000 chars rejected |
| 8 | `test_chat_routes_with_dependency_overrides` | `GET /v1/devices`, `POST /v1/chat` OK |
| 9 | `test_chat_routes_map_permission_and_errors` | 403 for permission, 500 for errors |

---

## 10. LLM, Prompt, Reports, RAG, Permissions (`test_llm_prompt_reports.py`)

| # | Test | Edge case / behavior |
|---|------|----------------------|
| 1 | `test_soften_replaces_banned_terms` | ThingsBoard/TB/API/telemetry softened |
| 2 | `test_soften_none_and_empty` | `None` / `""` safe |
| 3 | `test_llm_complete_without_api_key` | Missing key → operator-friendly message |
| 4 | `test_llm_complete_softens_model_output` | Model jargon cleaned |
| 5 | `test_build_messages_structure_and_history_cap` | System prompt + last 8 history turns |
| 6 | `test_load_report_missing_dir` | Missing reports dir → `None` |
| 7 | `test_load_report_skips_bad_json_uses_latest` | Bad JSON skipped; latest good used |
| 8 | `test_format_report_context_variants` | None / list / raw / dict shapes |
| 9 | `test_rag_chunk_short_and_long` | Short text one chunk; long text overlapped |
| 10 | `test_rag_format_snippets_empty_and_filled` | Empty vs sourced snippets |
| 11 | `test_rag_retrieve_empty_query` | Empty query → `[]` |
| 12 | `test_permissions_skips_bad_items_and_ensures_access` | Bad TB rows skipped; deny raises |

---

## Coverage map (module → tests)

| Production module | Primary test file(s) |
|-------------------|----------------------|
| `app/services/intent.py` | `test_intent.py`, `test_core.py` |
| `app/services/device_resolver.py` | `test_device_resolver.py` |
| `app/services/time_window.py` | `test_time_window.py` |
| `app/services/tools/analytics.py` | `test_analytics.py` |
| `app/services/tools/telemetry.py` | `test_telemetry.py` |
| `app/services/memory.py` | `test_memory.py` |
| `app/services/session.py` | `test_session.py` |
| `app/auth/jwt_tb.py`, `app/api/chat.py` | `test_auth_api.py` |
| `app/services/llm.py`, `prompt_builder.py`, `rag.py`, `permissions.py`, `tools/reports.py` | `test_llm_prompt_reports.py` |

---

## Notable edge cases locked by tests

1. **`min` vs `minutes`** — statistics keyword uses word boundaries so “last 15 minutes” stays `TIME_BASED`.
2. **Yesterday + shift** — “yesterday morning shift” is a shift window, not a full calendar day.
3. **Ambiguous device names** — `DG SET` / `DG SET1` vs `DG SET10` clarification and longer-name preference.
4. **Sentinel Modbus values** — `32767` / `≥30000` treated as `N/A` / invalid for analytics.
5. **Secrets & config change** — never call LLM; return unsupported message.
6. **Rate limits** — per user+device min-interval and window count.
7. **LLM / TB failures** — fallback answer or tooling warning without crashing the chat turn.
8. **Auth failures** — missing token 401, invalid token 401, TB outage 502.

---

## How to extend

1. Add a failing test under the matching `tests/test_*.py` file.
2. Prefer `@pytest.mark.parametrize` for input matrices.
3. Keep orchestrator tests mocked (no live OpenAI / ThingsBoard).
4. Re-run `pytest tests/ -v` and update this document when new cases are added.
