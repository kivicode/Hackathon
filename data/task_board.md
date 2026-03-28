# Project Task Board

---

## ✅ Done

### TASK-2801 — Implement Feature X core logic

- **Assignee:** @david.chen
- **Priority:** Critical
- **Sprint:** Sprint 47
- **Completed:** Mar 24, 2026
- **Description:** Implement the main processing pipeline for Feature X including data ingestion, transformation, and API endpoints.
- **Labels:** `feature-x`, `backend`, `core`

### TASK-2802 — Feature X unit tests

- **Assignee:** @james.wright
- **Priority:** High
- **Sprint:** Sprint 47
- **Completed:** Mar 24, 2026
- **Description:** Write comprehensive unit tests for Feature X core logic. Coverage target: 85%.
- **Labels:** `feature-x`, `testing`

### TASK-2803 — Feature X API documentation

- **Assignee:** @sarah.kim
- **Priority:** Medium
- **Sprint:** Sprint 47
- **Completed:** Mar 25, 2026
- **Description:** Document all Feature X endpoints in the API reference. Include request/response examples.
- **Labels:** `feature-x`, `docs`

### TASK-2788 — Update billing dashboard charts

- **Assignee:** @tom.bradley
- **Priority:** Medium
- **Sprint:** Sprint 47
- **Completed:** Mar 22, 2026
- **Description:** Replace legacy chart library with new D3-based components on the billing dashboard.
- **Labels:** `frontend`, `billing`

### TASK-2790 — Migrate user auth to OAuth 2.1

- **Assignee:** @sarah.kim
- **Priority:** High
- **Sprint:** Sprint 46
- **Completed:** Mar 15, 2026
- **Description:** Upgrade authentication flow from OAuth 2.0 to 2.1 spec. Update all client libraries.
- **Labels:** `security`, `auth`

### TASK-2795 — Poland cluster reserved instance renewal

- **Assignee:** @mike.torres
- **Priority:** Medium
- **Sprint:** Sprint 46
- **Completed:** Mar 18, 2026
- **Description:** Renew reserved instance contracts for Poland infrastructure. Negotiated 12% discount on 2-year term.
- **Labels:** `infra`, `poland`

---

## 🔧 In Progress

### TASK-2804 — Feature X staging deployment

- **Assignee:** @david.chen
- **Priority:** Critical
- **Sprint:** Sprint 47
- **Status:** Blocked — deployment issues
- **Description:** Deploy Feature X to staging environment. Currently hitting 502 errors due to load balancer health check timing. Readiness probe fix in canary testing.
- **Labels:** `feature-x`, `deployment`, `blocked`
- **Blockers:** Load balancer config incompatible with new container startup sequence

### TASK-2805 — Feature X load testing

- **Assignee:** @mike.torres
- **Priority:** High
- **Sprint:** Sprint 47
- **Status:** Waiting on TASK-2804
- **Description:** Run full load test suite against Feature X staging deployment. Must pass before production release.
- **Labels:** `feature-x`, `testing`, `infra`

### TASK-2812 — Analytics suite demo prep for GlobalTech

- **Assignee:** @raj.patel
- **Priority:** Medium
- **Sprint:** Sprint 47
- **Description:** Prepare analytics suite demo environment for GlobalTech call next week. Seed with sample data.
- **Labels:** `sales`, `apac`, `demo`

### TASK-2815 — Notification service async handler fix

- **Assignee:** @sarah.kim
- **Priority:** Low
- **Sprint:** Sprint 48 (backlog)
- **Description:** Fix race condition in notification service async handler causing flaky CI tests.
- **Labels:** `backend`, `bugfix`

---

## 📋 To Do

### TASK-2806 — Feature X production release

- **Assignee:** @david.chen
- **Priority:** Critical
- **Sprint:** Sprint 48
- **Description:** Production deployment of Feature X. Requires TASK-2804 and TASK-2805 to be completed first.
- **Labels:** `feature-x`, `deployment`, `release`
- **Dependencies:** TASK-2804, TASK-2805

### TASK-2810 — Acme Inc. contract renewal

- **Assignee:** @lisa.park
- **Priority:** High
- **Sprint:** Sprint 48
- **Description:** Process Acme Inc. contract renewal. Approved discount: max 5%. Current contract: $180K/year.
- **Labels:** `sales`, `contracts`

### TASK-2818 — Q2 roadmap planning

- **Assignee:** @cto.nina
- **Priority:** Medium
- **Sprint:** Sprint 48
- **Description:** Draft Q2 product roadmap based on Q1 results and customer feedback.
- **Labels:** `planning`, `roadmap`

### TASK-2820 — LATAM integration services cost review

- **Assignee:** @cfo.rachel
- **Priority:** High
- **Sprint:** Sprint 48
- **Description:** Review LATAM operations — revenue declining while costs remain high. Prepare recommendation for exec meeting.
- **Labels:** `finance`, `latam`, `review`

### TASK-2822 — Floor 3 coffee machine replacement

- **Assignee:** @facilities
- **Priority:** Low
- **Sprint:** Unscheduled
- **Description:** Coffee machine on floor 3 is broken. Ticket submitted for replacement.
- **Labels:** `facilities`

---

## 📊 Board Summary

| Status      | Count  | Critical    |
| ----------- | ------ | ----------- |
| Done        | 6      | 1           |
| In Progress | 4      | 1 (blocked) |
| To Do       | 5      | 1           |
| **Total**   | **15** | **3**       |
