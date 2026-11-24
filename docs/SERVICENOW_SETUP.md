# ServiceNow setup (optional, about 30 minutes)

Without this the copilot uses its local fake ticket table (`SN_BACKEND=fake`), and every test runs against fakes.
These steps connect it to a free ServiceNow **Personal Developer Instance** (PDI).

## 1. Instance
1. Sign in at the ServiceNow Developer Program and request a Personal Developer Instance.
2. Note the instance URL (`https://devNNNNNN.service-now.com`) and the admin password.

A PDI hibernates when idle and is **reclaimed after 10 days without a login** (API calls by an integration user do
not count). Log in regularly while you need it.

## 2. Table: Localization Requirement
In **System Definition → Tables** (or open `https://devNNNNNN.service-now.com/sys_db_object.do`), create a new
table. Use this classic form, not ServiceNow Studio, App Engine Studio or Creator Studio: those create the table in
an application scope with a different name.


| Setting | Value |
|---|---|
| Label / Name | `Localization Requirement` / `u_localization_requirement` |
| Extends table | `Task` (gives `number`, `short_description` and the record form) |
| Controls → Auto-number | on, prefix `LOCREQ`, 7 digits |
| Controls → Create module / role | keep the defaults (a role such as `u_localization_requirement_user` is created) |

Save the table, then add the columns one by one in the **Columns** tab (**New**, fill in Type, Column label, Max
length, **Submit**). Type is a search field: for the date, type `Date` and pick exactly **Date**. The column name
follows from the label (`country` → `u_country`); check it. Type String unless noted:

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

**Field access for the title.** The table's own access controls (created with the table) cover the `u_` columns, but
`short_description` is inherited from Task, and `task.short_description` allows writes only to Task roles. Without
the step below ServiceNow **silently drops the title** (the record is created with an empty Short description).
Elevate to `security_admin` (avatar, top right → Elevate role), then in **System Security → Access Control (ACL)**
create three rules:

| Type | Operation | Decision type | Name (table / field) | Requires role |
|---|---|---|---|---|
| record | create | Allow If | Localization Requirement / Short description | `u_localization_requirement_user` |
| record | write | Allow If | Localization Requirement / Short description | `u_localization_requirement_user` |
| record | read | Allow If | Localization Requirement / Short description | `u_localization_requirement_user` |

Check: searching the ACL list for `u_localization_requirement.short` shows three rows.

## 3. Integration user
In **User Administration → Users**, create `copilot.integration`:
- **Identity type: Machine** (no UI login). Older releases have a **Web service access only** checkbox instead.
  Leave **Internal Integration User** unticked (that is for ServiceNow's own integrations);
- submit, open the user again, **Set Password**, and untick *Password needs reset* if it is ticked;
- in the **Roles** tab add only the table's role (`u_localization_requirement_user`, shown under *Requires role* in
  the table's access controls), so it can read and create records in that table and nothing else.

## 4. Configure the copilot
In `.env` (git-ignored, never committed):

```ini
SN_BACKEND=rest
SN_INSTANCE_URL=https://devNNNNNN.service-now.com
SN_USER=copilot.integration
SN_PASSWORD=...
SN_TABLE=u_localization_requirement
```

A generated password often contains `#`, `$`, `<` or `&`: do not `source` the file in a shell, which breaks on them
and can print the value in the error. Export the settings another way (or set them in your IDE's run
configuration), then check it with the live contract tests (they create a few records with test titles):

```bash
SN_LIVE_TESTS=1 python -m pytest tests/test_servicenow_contract.py
```

Basic auth is enough for a demo instance; in production use OAuth with a dedicated client and a vault for the
secret.
