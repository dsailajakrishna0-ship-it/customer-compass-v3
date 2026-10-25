---
title: Dashboard export timeout support conversation
type: support
company: Acme Fabrication
date: 2026-09-02
---

Customer: Maya Chen
Issue: The "Export full history" button on the operations dashboard times out
for reports covering more than 90 days of interaction data.

Support notes: Reproduced the issue. The export times out because it builds
the CSV synchronously in the request instead of generating it in the
background. As a workaround, we suggested exporting in 30-day windows until a
background-export feature ships.

Maya accepted the workaround for now but said it is "not a long-term fix" for
a team that reviews quarterly history. We scheduled a follow-up call for
early September to confirm whether the background-export fix has shipped, and
to revisit the pricing breakdown she is waiting on for the renewal.

Status: Workaround shared. Follow-up scheduled. Engineering ticket opened for
background CSV export.
