# How it was built

The code was written with AI coding agents. This page describes the process that kept the result checkable: a
written specification, small phases with a done-check each, a person reviewing every change before it was committed,
independent reviews that probe the running code, and evaluations that decide whether a change is kept.

## 1. A specification before code

Work started from a build specification (kept outside the repository): the fictional countries and their key facts,
the architecture, the graph, the API, the evaluation plan and five phases with a definition of done each. Examples of
done-checks:

- **E1, the fictional world:** every key fact in `corpus/facts.yaml` is found in the document that states it, and
  every rule is described in the section it cites (`tests/test_corpus.py`).
- **E2, the rule engine:** every one of the 45 sample invoices yields exactly its expected rule ids, and every rule
  fails in one sample and passes in another.
- **E3, retrieval and the assistant:** a labelled retrieval benchmark (now 78 questions) and a graph whose citations are
  checked in code.
- **E4, tickets:** one contract test suite for the local fake, the REST adapter and a real ServiceNow developer
  instance.
- **E5, evidence:** real-model evals on two local models, observability, documentation.

Decisions that changed the plan were written down with their reason, for example: hybrid retrieval because rule ids
and codes are exact tokens; no confidence score from the router, because it would not be calibrated; the country
name in the keyword index but not in the embeddings, because measured vector-only hit@3 fell from 1.00 to 0.60 with
it ([README](../README.md#date-aware-retrieval)); calibrated decision gates for typed approvals
([DECISIONS.md](DECISIONS.md)).

## 2. What the model is not trusted with

The design keeps the decisions that matter out of the model's hands, so that an agent-written prompt or a model's
bad day cannot change them:

| Decision | Made by |
|---|---|
| Is the invoice valid? | the rule engine (`copilot/rules/`), never the model |
| Which date does a question mean? | `dateparser` in code; the model only quotes the phrase |
| Is a citation real? | code: every reference must be a retrieved passage, wherever it stands in the answer |
| Which of two conflicting documents applies? | code, from authority and publication date (`copilot/graph/nodes/conflicts.py`) |
| Is a ticket created? | a person, through the approval interrupt; a typed "yes" only through a calibrated gate |

## 3. A person reviews every change

Each phase ended uncommitted. A person ran the app, read the diff and tested by hand; only then was it split into
small commits, each of which passes the whole suite on its own. Nothing was pushed without that person's explicit
approval.

## 4. Independent reviews that probe the code

After the phases, separate review passes read the code against the specification and **probed the running app**
(a disconnect in the middle of a stream, a ServiceNow instance that answers with an HTML page, a timeout after the
record was stored, a reference outside square brackets, an input containing the prompt's own closing tag, a guessed
thread id). Every finding became a work item with the file and function, a fix and a test. The rule for each item:

1. write the test that shows the problem, and see it fail;
2. fix it;
3. run the whole suite and the linter; update the README where behaviour or a number changed.

Examples from the commit history: a run left `running` forever after a disconnect (an `asyncio.CancelledError` is not
an `Exception`); a retried POST that could duplicate a ServiceNow ticket; a 15 MB upload read to the end before the
size check; graph nodes that replaced the list of notes instead of adding to it, which a unit test of one node could
not see.

## 5. Evaluations decide

- **Real-model evals** (`evals/run_evals.py`) run scripted conversations through the HTTP API on two local models and
  grade what the system did (intent, dates, cited documents, the engine's rule ids, the ticket), not the wording.
  The first full run gave 70/84 and 36/42; every failure was read and classified before anything changed: five were
  the grader's mistakes (the checks were fixed, not the answers), the rest were reproduced as tests first.
- **A held-out set** of 20 conversations was written after development by a separate review and is kept outside the
  repository; the agent that changes the code runs it but never opens its cases. It is run once before and once
  after a round of changes. Its results are reported apart from the
  development numbers, and prompts, graders and thresholds are not tuned on it.
- **Calibration** for the decision gates is measured on labelled messages per model; changing a gate's question
  changes its prompt hash and requires a new calibration.

## 6. What this does not prove

The fakes are faithful only to what was known when they were written: the first live ServiceNow run found that the
integration user could not write a field inherited from Task, which no fake had modelled. The evals are small (tens
of cases per model), so a single run's pass rate has a wide confidence interval. Both limits are stated where the
numbers are.
