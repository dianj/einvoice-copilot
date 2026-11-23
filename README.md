# E-Invoice Compliance Copilot

An assistant for e-invoicing localization teams: grounded, **date-aware** answers about country e-invoicing rules
with citations, **deterministic** validation of UBL invoices explained in plain language, country comparisons, and
requirement tickets after human approval.

> **The countries, regulations, platforms, tax IDs and companies in this project are fictional.** Valdoria
> (clearance), Kestria (post-audit with a four-corner network) and Orlavia (real-time reporting) follow real-world
> e-invoicing models, so the problems are realistic, but no real law or standard text is used. The invoice syntax is
> real: OASIS UBL 2.1.

> **Work in progress.** Phase E1 is done: the fictional world (15 regulation documents and the key facts they must
> agree on), about 30 validation rule definitions, an async FastAPI skeleton, CI and a Docker image. Next: the rule
> engine and sample invoices (E2), date-aware retrieval and the LangGraph agent (E3).

## Design principles

1. **The model explains, the code decides.** Validity comes only from the rule engine; tickets only after explicit
   human approval; dates are parsed in code.
2. **Grounded or silent.** Answers cite passages valid for the date in question; otherwise "not in the documents".
3. **Time on two axes.** Each document *version* has `valid_from` / `valid_to` (which version was current); the
   obligation dates a document announces live in its text. An amendment published in March that moves an obligation
   to 1 July is therefore found for a question about 30 June. Rules apply by the invoice's date.
4. **Everything external has a fake**, so tests need no GPU, network or keys.

## The fictional world

| | Valdoria (VD) | Kestria (KS) | Orlavia (OL) |
|---|---|---|---|
| Model | clearance before issue (VCP) | post-audit, KesNet four-corner network | real-time reporting after issue (ORTS) |
| Timeline | B2G 2025; large-taxpayer B2B 2026; all B2B moved from 2027 to 1 July 2026 by an amendment | B2B/B2G since 1 September 2024 | all invoices from 2025; deadline 24 h → 4 h from 1 April 2026 |
| Typical rule | mod-11 tax ID check digit, Clearance ID on cleared invoices | VAT total also in KSK; reduced rate 12 % → 10 % by tax point date | QR payload with a SHA-256 hash; self-billing agreement |

`corpus/facts.yaml` holds the key facts; tests check that every document states them exactly, that every rule is
described in the section it cites, and that superseded versions end the day before their successor.

## Quick start

```bash
pip install -r requirements.txt
uvicorn server:app --port 8000          # or: docker compose up
```

`http://localhost:8000/api/health`, `/api/corpus`, `/api/rules?country=KS&transaction_type=B2G&as_of=2026-03-05`.
The LLM (from E3) is any OpenAI-compatible server; see [.env.example](.env.example).

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest --cov=copilot --cov=server
```

## License

[MIT](LICENSE)
