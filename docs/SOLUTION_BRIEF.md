# E-Invoice Compliance Copilot: solution brief

A one-page view of the problem, the solution and how it is measured. The design is in the [README](../README.md);
the calibrated gates are in [DECISIONS.md](DECISIONS.md). Valdoria, Kestria and Orlavia, their laws, platforms and
companies are fictional; the invoice syntax (OASIS UBL 2.1) is real.

## The problem

An ERP localization team keeps invoices compliant in many countries at once. Each country has its own model
(clearance before issue, post-audit, real-time reporting), its own platform and tax-ID formats, and rules that change
on fixed dates: a rate that drops on 1 March, a deadline that shortens on 1 April, an obligation an amendment moves a
year earlier. The questions sound simple ("which rate applies to an invoice dated 28 February?") but the answer
depends on the date, on which version of which document was in force, and on documents that contradict each other.
Wrong answers become wrong invoices, rejected by the platform or found in an audit. Each change then has to become a
requirement in the team's ticketing system.

## Goals

| Goal | How the copilot meets it |
|---|---|
| Answer rule questions correctly for a given date | date-aware retrieval: only document versions in force on that date; dates parsed in code; one answer per date when the question has several |
| Never invent a rule or a source | every `[DOC §n]` citation must be a retrieved passage, others are removed; no valid citation → "not in the documents" |
| Judge invoices deterministically | a rule engine with 30 rules decides validity; the model only explains the engine's findings and may not add or drop one |
| Explain conflicts between documents | conflicts resolved by authority and publication date, and named in the answer |
| Turn a change into a requirement, under control | a drafted user story with acceptance criteria, checked by code; a ticket only after a person approves it (button, or a typed approval through a calibrated gate) |
| Resist instructions hidden in data | invoice notes, document passages and user text are data; "skip the validation" still validates; "I approve in advance" creates nothing |
| Show what happened | every run and node span stored: trace per answer, latency, tokens, abstentions, findings per rule |

## Users and surfaces

| User | Surface |
|---|---|
| Localization analyst / functional consultant | Assistant (questions, follow-ups, drafts), Validate (UBL upload or samples), Compare (country table) |
| Team lead / product owner | approval card, Tickets tab, ServiceNow record |
| Developer / operator | Trace drawer, Metrics tab, `/api/runs/{id}/trace`, `/api/metrics` |

## Scope

In: three fictional countries with 14 documents (laws, amendments, specifications, an FAQ that is out of date, a
comparison overview), 30 rules, 45 sample invoices, a local LLM, ServiceNow (fake or a real developer instance).
Out: real legal content, real tax-authority APIs, invoice signing, ERP integration, multiple tenants, production
deployment.

## KPIs (metrics tab and evals)

| KPI | Why it matters | Definition |
|---|---|---|
| Grounded-answer accuracy | wrong rules become wrong invoices | real-model evals: right fact, right document cited |
| Abstention rate | silence is better than a guess | questions answered "not in the documents" |
| Findings per rule | which rules the invoices break most | from the engine's reports |
| Approved vs rejected drafts | quality of the drafts | approvals on the approval card |
| Latency p50 / p95 per node | usability; where the time goes | from the stored spans |
| Injection result | safety | eval group: no ticket, no "valid", no injected text followed |

## Results

Measured with two local models, fresh data per run, graded on what the system did (intent, dates, cited documents,
rule ids, tickets), not on the wording. Details in the [README](../README.md#results) and
[evals/results/](../evals/results/).

| | Result |
|---|---|
| Real-model evals, 42 cases in 9 groups | Gemma 4 26B **83/84** (2 runs), Qwen 3.8 27B **42/42**; the one miss: a correct answer that did not name the outdated FAQ |
| Injection (forum post in the index, "pre-approved" in the XML, "skip the validation", "I approve in advance") | **8/8** on Gemma (2 runs), **12/12** on Qwen (3 runs) |
| Retrieval, 78 labelled questions | hit@3 **1.000** with the date filter, 0 date-filter violations, 3.4 ms median |
| Validation | 45 sample invoices yield exactly their expected rule ids; every rule fails in one sample and passes in another |
| Typed approvals through the gate (32 labelled replies) | 32/32 on both models; no steering reply approved |
| ServiceNow | 19/19 contract tests against a real developer instance |
| Automated tests | 383, 99 % line coverage, run in CI on every push |

Every failure the evals found was first reproduced, then fixed in code (or in the grader) and measured again; the
README lists them.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A wrong rule for the date | date filter in the search and again in Python; dates parsed in code; temporal eval cases on the boundary days |
| Hallucinated citations | a citation must match a retrieved passage; the answer is replaced if none is valid |
| The model changes a validation result | the engine is the only judge; the explanation schema only allows the report's rule ids |
| Prompt injection (invoice notes, documents, user) | passages and XML wrapped as data; code rules over the route; an approval gate with a second "text aimed at the system?" question; injection eval group on both models |
| An unwanted ticket | LangGraph interrupt: nothing is created without a person; typed approvals checked by a calibrated gate |
| Out-of-date documents | each version has `valid_from` / `valid_to`; the FAQ that contradicts the amendment is named as the conflict |
| Model variance | two local models, repeated runs, every failure reproduced as a test or an eval before the fix |
| Vendor lock-in | adapters for the LLM (OpenAI-compatible), the ticketing system and the embeddings |

## What production would need

Real regulation texts with an owner who keeps them current, and a review of the rules against them; authentication
and roles for analysts and approvers; a hosted LLM with a data-processing agreement, or a GPU server; ServiceNow with
an integration user per environment and the field access rules from the setup guide; the spans exported to the
company's monitoring (OpenTelemetry) instead of SQLite.
