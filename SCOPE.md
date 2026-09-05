# Scope — defense-only declaration

Praman defends merchants against payment disputes they would otherwise lose. It
decides whether contesting a given chargeback is worth its cost, assembles the
evidence the issuer's specific reason code actually requires, and drafts a
representment narrative in which every sentence cites a retrievable document
field. It operates on one side of one problem: a merchant who is about to lose
money, either by failing to respond before `respond_by` or by responding with
documents that do not satisfy the code that was raised. It has no capability
directed at cardholders, at issuers, at other merchants, or at fraud-detection
systems, and it is designed so that it can recommend *accepting* a dispute — a
system that can only ever say "fight" is a sales tool, not a risk tool.

The defense-only constraint is enforced structurally rather than by policy text,
because a policy statement is not an architecture. No card primary account
number is stored anywhere in the system; all identity joins are performed on
salted hashes computed at the ingest boundary, so the entity graph cannot be
inverted to name a real person. The `action` field is hard-coded to `draft` and
there is no code path that transmits to an issuing bank; submission requires a
human approval that writes its own audit record. The language model holds no
tools, no retrieval and no write authority — it drafts prose from a fixed
evidence package, and every claim it emits is stripped unless a deterministic
verifier can resolve its citation to a matching document field. Detection is
one-directional: the system identifies coordinated abuse, and exposes no
surface for evading detection, probing cards, enumerating BINs, or generating
adversarial inputs against a fraud model.

## Enforcement map

| Capability | Status | How it is enforced |
|---|---|---|
| Fabricating evidence or unsupported claims | Prohibited | Grounding verifier resolves every citation; ungrounded claims stripped, draft blocked if required coverage drops |
| Auto-submitting to an issuing bank | Prohibited | `action` hard-coded to `draft`; no transmission code path; human approval writes its own audit record |
| Card testing, BIN enumeration, credential probing | Not implemented | No such code path exists; no PAN is stored at any point |
| Fingerprint or velocity evasion tooling | Not implemented | Detection is one-directional; no evasion surface is exposed |
| Adversarial generation against fraud models | Not implemented | The generator emits labelled test fixtures, never optimised attack sequences |
| Deanonymising real individuals | Prohibited | All identity joins on salted hashes; raw PII never crosses the ingest boundary |

## What that means in practice

The system is auditable end to end. Every arrow in the architecture writes an
append-only, hash-chained `AuditRecord`, so any decision can be replayed and any
tampering is evident. The contest-versus-accept decision is a deterministic
inequality over a calibrated probability, not a model's opinion, and the
rationale shown to the merchant is templated from the decision inputs rather
than written by a language model. Every number in it is traceable to a source.
