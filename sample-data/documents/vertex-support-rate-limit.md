---
title: API rate limit support ticket
type: support
company: Vertex Analytics
date: 2026-09-15
---

Customer: Tom Reyes (IT Administrator at Vertex Analytics)

Tom reported hitting the default API rate limit (500 requests/minute) while
running a bulk export of historical usage data for a board presentation. The
export failed partway through with a 429 response.

We explained the default limit applies per API key, and that Vertex's plan
allows requesting a temporary rate-limit increase for scheduled bulk jobs at
no extra cost — it just needs 24 hours' notice. Tom said he'd plan future
exports around that lead time, and asked if there was a way to see his
current rate-limit usage in real time; we pointed him to the usage panel in
the admin dashboard.
