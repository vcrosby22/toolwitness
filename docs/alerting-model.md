# Alerting Model

ToolWitness serves two distinct user profiles with different feedback needs. This document captures the design decisions behind the notification system.

## User Profiles

### Profile A — Developer building with agents

The developer is in the conversation. They're writing code, testing agent behavior, iterating. They see tool calls and agent responses in real time.

**Primary feedback loop:** Inline verification via Cursor rule or `tw_verify_response`. The agent calls the verification tool after using monitored tools, and the result appears right in the conversation.

**Secondary:** Dashboard for aggregate review (failure rates, patterns over time).

**What they need:** Immediate, contextual feedback. "The agent just told me something wrong — catch it now."

### Profile B — Team lead, PM, or someone overseeing agent usage

Not in every conversation. Needs to know *after the fact* that something went wrong. May manage multiple agents or team members using AI tools.

**Primary feedback loop:** Push notifications (Slack, webhook) when failures accumulate. Dashboard for trend analysis and drill-down.

**Secondary:** Daily digest reports summarizing verification activity.

**What they need:** Passive monitoring. "Alert me when things go wrong — I'm not watching every conversation."

## Three-Tier Feedback Model

```
Layer 1: INLINE (real-time, in-conversation)
  └─ Agent calls tw_verify_response → result appears in chat
  └─ For Profile A (developer)

Layer 2: DASHBOARD (pull, historical)
  └─ Web UI with KPIs, classification breakdown, session timeline
  └─ For both Profile A and B

Layer 3: PUSH NOTIFICATIONS (automatic, background)
  └─ Alerts fire when thresholds are breached
  └─ Daily digest summarizes activity
  └─ For Profile B (team lead / PM)
```

## Alerting Tiers

| Tier | Trigger | Delivery | Default Config |
|------|---------|----------|----------------|
| **Daily digest** | Scheduled (cron or manual) | Slack / webhook / stdout | `toolwitness digest --send` |
| **Count threshold** | N failures in M minutes | Slack / webhook (immediate) | 10 failures in 60 min |
| **Rate threshold** | Failure rate > X% with min Y verifications | Slack / webhook (immediate) | >20% rate, min 10 verifications |

### Why not alert on every failure?

Too noisy. A single FABRICATED classification at 70% confidence may be a false positive (text grounding is heuristic). Alerting on every failure trains users to ignore alerts. The threshold approach catches *accumulation* — when something is systematically wrong, not when one check is borderline.

### Why both count and rate?

Count alone misleads. 10 failures out of 200 verifications (5%) is probably fine. 10 failures out of 12 verifications (83%) is a serious problem. Rate thresholds with a minimum verification count prevent both false calm and false alarm.

## Configuration

```yaml
# toolwitness.yaml
alerting:
  slack_webhook_url: https://hooks.slack.com/services/...
  webhook_url: https://your-endpoint.com/toolwitness

  threshold_rules:
    - name: failure_accumulation
      max_failures: 10
      window_minutes: 60

    - name: high_failure_rate
      max_failure_rate: 0.20
      min_verifications: 10
      window_minutes: 60
```

Daily digest via cron:

```bash
# Run at 6pm daily
0 18 * * * /path/to/toolwitness digest --send --period 24h
```
