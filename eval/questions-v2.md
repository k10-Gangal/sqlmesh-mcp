# Transformation Eval v2 — 20 questions · sessions & events

Twenty prompts for the agent on the four `raw` tables, in three registers.

```
  ⚠ GRADER'S FILE. Never put this in the agent's context.
    The "truth" lines come from the rows, which the agent never sees.
```

Paste only the **Prompt** line. The agent works from metadata only (names,
types, descriptions), so most traps are about what the metadata does and does
not say.

---

## Facts the traps rest on

Measured on the loaded data (read-only role, 2026-10-29).

```
  x42_opportunity_audit        1,000 sessions · session_date_et 2026-08-12 → 11-23
    call_outcome               CONVERSATION_ENDED 626 · TRANSFERRED 142 · HANGUP 137 · NO_ANSWER 95
                               (values NOT in metadata — description is "Final status of the call")
    compliance_decision        COMPL_PASSED 841 · COMPL_FAILED 159
    compliance_blockedrules    NULL on all 841 passed · dnc_check 61 · consent_check 54 · time_window_check 44
    call_transcript            NULL on 374
    5 orgs · 15 projects · 8 campaigns

  x42_opportunity_events       3,911 events · 1,000 sessions
    timestamp                  BIGINT epoch ms, UTC          event_hour  America/New_York
    data->>'status'            OPPORTUNITY_CREATED 1000 · CONVERSATION_STARTED 911 · COMPL_PASSED 840
                               CONVERSATION_ENDED 601 · COMPL_FAILED 160 · USER_HANGUP 158
                               TRANSFERRED_TO_CARE_TEAM 152 · NO_ANSWER 89
    shares session_id with audit and haio (1,000 / 1,000) — but the counts DISAGREE
    with audit (NO_ANSWER 89 vs 95): the tables were generated independently

  haio_test_service_sessions   1,000 sessions · invoked true 944 / false 56
    "successful_turns"         description: request_status = success OR oos
    pooled success 85.1% (invoked) vs 87.2% (not invoked)
    p90/p95/p99 are per-session — a true p95 across sessions cannot be derived

  x42_pcw_mc_ivr_raw_events    8,282 events · 1,000 calls · camelCase → quoted
    eventType                  call_start 1000 · turn_completed 5940 · call_end 1000 · payment_completed 342
    turn status                success 5009 · oos 472 · error 459
    call_end outcome           COMPLETED 704 · TRANSFERRED 149 · HANGUP 147
    eventHour                  UTC  (≠ event_hour in the other stream)
    shares NO session ids with the other three tables
```

---

## A · Doesn't know the data (6)

### 1 · Staging layer
**Prompt:** Can you set up clean, typed staging models for the session and event tables so we can build on them?
- **Tests** casting · naming · units · quoting
- **Trap** `timestamp` is epoch **ms** (÷1000, not seconds) · `event_hour` is New York but `eventHour` is UTC — names must say which · camelCase columns need quoting
- **Good** `staging.stg_*`, kind VIEW explicit, epoch → `timestamptz`, hour columns renamed with their timezone

### 2 · The voicemail trap ★
**Prompt:** Break calls down by outcome — I want the voicemail ones.
- **Tests** refusing to invent a value
- **Trap** no VOICEMAIL anywhere; `call_outcome` values aren't in the metadata
- **Good** builds the breakdown, does **not** filter on 'VOICEMAIL', says it can't confirm the value and asks · truth: CONVERSATION_ENDED, TRANSFERRED, HANGUP, NO_ANSWER

### 3 · Flatten the payload
**Prompt:** What's in the event payloads? I want a table with one column per field.
- **Tests** reading descriptions · JSON per event type
- **Trap** keys exist only in descriptions, and in the raw IVR stream they differ by `eventType`
- **Good** one model per event type (or sparse columns), says the keys come from a description and are unverified

### 4 · Busiest hour
**Prompt:** Which hour of the day do most calls happen?
- **Tests** timezone discipline · asking the one question that matters
- **Trap** three hour columns: `event_hour` (NY), `eventHour` (UTC), `session_hour` (timezone unstated)
- **Good** asks which timezone, or picks one and says so · never mixes them

### 5 · Do-not-call blocks
**Prompt:** How many sessions were blocked by the do-not-call check?
- **Tests** not guessing a literal
- **Trap** the rule's exact value isn't visible
- **Good** asks for the exact rule name or marks the filter unverified · truth: `dnc_check`, 61

### 6 · Are they the same calls?
**Prompt:** Are the two event tables tracking the same calls?
- **Tests** answering from structure · honesty about what it can't see
- **Trap** looks plausible from the column names
- **Good** says it can't tell from metadata; offers a model that counts overlapping session ids · truth: 0 overlap

---

## B · Knows the business (9)

### 7 · Daily volume
**Prompt:** How many calls are we making each day, broken down by campaign? This should refresh every morning.
- **Tests** inferring INCREMENTAL_BY_TIME_RANGE
- **Trap** ★ no `WHERE … BETWEEN @start_ds AND @end_ds` still validates
- **Good** incremental, time filter present, cron `@daily`, start set

### 8 · The funnel
**Prompt:** Show me the drop-off — the call starts, they talk to the bot, they pay. Where do we lose people?
- **Tests** event-stream funnel · LEFT vs INNER
- **Trap** inner join to `payment_completed` loses 658 calls
- **Good** distinct sessions per stage from `call_start` down · truth: 1,000 → 1,000 → 342 paid

### 9 · Turn success rate
**Prompt:** What's our turn success rate, by org?
- **Tests** defining the metric · rates from counts
- **Trap** "success" is ambiguous — `success` only, or success + oos (the haio description says the latter)
- **Good** states the definition it chose, `SUM/SUM` not `AVG(rate)` · truth (raw stream): 84.3% success-only, 92.3% with oos

### 10 · Is the assistant helping?
**Prompt:** Is the assistant actually making calls better? Compare sessions where it was used against ones where it wasn't.
- **Tests** join on session_id · rates from counts · honest framing
- **Trap** 56 vs 944 — tiny control group; correlation ≠ causation
- **Good** LEFT join audit → haio, rates per group, flags the small group · truth: success 85.1% vs 87.2%

### 11 · p95 latency ★
**Prompt:** What's our p95 response time per day?
- **Tests** arithmetic honesty
- **Trap** averaging per-session p95s is not a p95
- **Good** says a true p95 can't come from the rollup; computes it from raw `turn_completed.responseTimeMs` with `PERCENTILE_CONT`, or labels any average plainly

### 12 · Compliance blockers
**Prompt:** Which compliance rules block us most, and is it getting better month over month?
- **Tests** NULL semantics · monthly grain · choosing the denominator
- **Trap** blocked rules exist only on failed sessions; a rate over failed-only ≠ over all sessions
- **Good** monthly counts per rule, states the denominator

### 13 · Session rollup from raw events
**Prompt:** Give me one row per session from the raw opportunity events — start, end, outcome and compliance decision.
- **Tests** grain · epoch ms · status-based pivots
- **Trap** the existing audit table looks like the answer but disagrees (NO_ANSWER 89 vs 95)
- **Good** grain session_id from events, epoch → timestamp, notes it does not reconcile with the audit table and doesn't silently use it

### 14 · Call length by outcome
**Prompt:** How long do calls last, by outcome?
- **Tests** units · choosing session vs call duration
- **Trap** `call_duration_ms` is DOUBLE ms; `session_duration_ms` is a different thing
- **Good** says which duration and converts to seconds/minutes · NO_ANSWER still has durations — worth flagging

### 15 · The NULL trap ★
**Prompt:** How many sessions per campaign were NOT blocked by the consent check?
- **Tests** NULL handling
- **Trap** `blockedrules != 'consent_check'` drops all 841 passed sessions (NULL)
- **Good** `IS DISTINCT FROM` / `COALESCE` · truth: 946 (not 105)

---

## C · Knows exactly what they want (5)

### 16 · Expert in a hurry ★
**Prompt:** Daily incremental on eventTimestamp, by orgId, not_null on the grain. Just build it.
- **Tests** executing without interrogating
- **Good** zero clarifying questions · adds the time-macro WHERE unprompted · quotes camelCase

### 17 · Spec'd join
**Prompt:** FULL model, one row per session_id joining audit and haio sessions, unique_combination_of_columns on session_id, number_of_rows > 0. Go.
- **Tests** exact execution · audit syntax
- **Good** LEFT join from audit, both audits written correctly, no questions

### 18 · Epoch time column
**Prompt:** INCREMENTAL_BY_TIME_RANGE on the opportunity events, time_column is timestamp, hourly cron.
- **Tests** building to spec while fixing what the spec gets wrong
- **Trap** `timestamp` is BIGINT epoch ms — not usable as a time_column as-is
- **Good** converts to a timestamptz column, uses that as time_column, says why · still asks nothing

### 19 · Dashboard-safe
**Prompt:** Make the daily calls model dashboard-safe — it can't break silently.
- **Tests** audits that match real risk
- **Good** unique on grain · `number_of_rows` · `accepted_range` on any rate · no `not_null` on nullable columns (`call_transcript` is NULL on 374)

### 20 · Late events
**Prompt:** Events can land up to a day late — build daily turn counts so late ones aren't missed.
- **Tests** incremental lookback
- **Good** INCREMENTAL_BY_TIME_RANGE with `lookback 1` (or reprocessing window), explains `systimeTs` vs `eventTimestamp`

---

## Coverage

```
  register            A · 6      B · 9      C · 5
  discovery           1 2 3 4 5 6
  model shape         7 13 18 20
  join integrity      8 10 17
  arithmetic          9 11
  NULLs / audits      12 14 15 19
  instruction fit     16 17 18
```

★ = the exam: 2 (refuse an invented value) · 11 (refuse fake arithmetic) ·
15 (NULLs) · 16 (build, don't interrogate).
