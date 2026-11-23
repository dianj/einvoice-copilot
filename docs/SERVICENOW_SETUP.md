# ServiceNow setup (optional, about 20 minutes)

Without this the copilot uses its local fake ticket table (`SN_BACKEND=fake`), and every test runs against fakes.
These steps connect it to a free ServiceNow **Personal Developer Instance** (PDI).

## 1. Instance
1. Sign in at the ServiceNow Developer Program and request a Personal Developer Instance.
2. Note the instance URL (`https://devNNNNNN.service-now.com`) and the admin password.

A PDI hibernates when idle and is **reclaimed after 10 days without a login** (API calls by an integration user do
not count). Log in regularly while you need it.

## 2. Table: Localization Requirement
In **System Definition → Tables**, create a new table:

| Setting | Value |
|---|---|
| Label / Name | `Localization Requirement` / `u_localization_requirement` |
| Extends table | `Task` (gives `number`, `short_description` and the record form) |
| Controls → Auto-number | on, prefix `LOCREQ`, 7 digits |
| Controls → Create module / role | keep the defaults (a role such as `u_localization_requirement_user` is created) |

Add these columns (type String unless noted):

| Column name | Max length |
|---|---|
| `u_country` | 2 |
| `u_effective_date` | Date (type) |
| `u_user_story` | 4000 |
| `u_acceptance_criteria` | 4000 |
| `u_rule_ids` | 200 |
| `u_doc_refs` | 400 |
| `u_priority` | 10 |
| `u_idempotency_key` | 40 |
| `u_source_thread` | 64 |

The title goes into the Task field `short_description`. Optional: make `u_idempotency_key` unique (an index), so
even two concurrent requests cannot create the same ticket twice.

## 3. Integration user
In **User Administration → Users**, create `copilot.integration`:
- set a password, tick **Web service access only** (no UI login);
- give it the table's role (`u_localization_requirement_user`), so it can read and create records in that table
  and nothing else.

## 4. Configure the copilot
In `.env` (git-ignored, never committed):

```ini
SN_BACKEND=rest
SN_INSTANCE_URL=https://devNNNNNN.service-now.com
SN_USER=copilot.integration
SN_PASSWORD=...
SN_TABLE=u_localization_requirement
```

Check it with the live contract tests, with the same settings exported in the shell (the tests create a few records
with test titles):

```bash
SN_LIVE_TESTS=1 python -m pytest tests/test_servicenow_contract.py
```

Basic auth is enough for a demo instance; in production use OAuth with a dedicated client and a vault for the
secret.
