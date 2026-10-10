# Agent 051 — instructions for Claude Code

Agent 051 reads job alert emails from Gmail, checks every listing against the user's criteria and
ends with a short briefing. JA.S.Mine, a separate program, asks it questions over MCP.
Code comments and names are in Romanian, without diacritics in code; keep new ones the same way.
The reasons behind every rule below are in [docs/DESIGN.md](docs/DESIGN.md).

## Map

| folder | role |
|---|---|
| `src/agent051/core/` | the logic, as pure functions: evaluation, scoring, briefing |
| `src/agent051/ingest/` | bringing data in: Gmail over IMAP, public listing pages |
| `src/agent051/parse/` | splitting emails into listings, one parser per source |
| `src/agent051/store/` | SQLite: schema, saving, reading |
| `src/agent051/adapters/` | the interfaces (MCP, CLI) **and orchestration**: the flows that join `ingest/`, `store/` and `core/` |
| `config/` | criteria, sources, cost |
| `ruleaza_*.py` | one script per pipeline step |
| `data/` | the database and what the program generates; ignored by git |

## Commands

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m unittest discover -s tests
.venv\Scripts\python.exe porneste_mcp.py
```

Every step that calls the model or the network shows a dry run first and caps its work with
`--limita`.

## Architecture rules

- **`core/` is pure. No I/O, ever** — not even "just to orchestrate". If a function in `core/`
  does not work with the network cut and no file on disk, it is in the wrong place.
  `core/briefing.py` imports nothing, not even `datetime`: moments come from the data.
- **Adapters are thin wrappers.** They turn a request into a call to `core/` and return the
  result. No decision is taken in an adapter.
- **What is deterministic stays deterministic.** The model is used only where the judgement is
  unavoidably subjective; salary, location, date, language and keywords are rules in code.
- **The model is injected.** Building the prompt and validating the answer are pure and live in
  `core/`; the flows in `adapters/` receive `cheama_model: (str) -> str` and make the call. **One
  file touches the network towards the model and the `anthropic` library:
  `adapters/model.py`.** A second one breaks the rule.
- **Ingestion keeps raw data.** It does not clean, simplify or decide what is useful. Cleaning
  and interpreting are separate steps on stored data, repeatable without the network.
- **The cheap check comes before the network:** disk before network, headers before bodies, a
  list of IDs before content.
- **What comes from the network is checked by identity**, not just by arrival: a 200 does not
  prove it is the page that was asked for.
- **"The model was not reached" is not "the model said no".** An infrastructure failure is
  raised as `EroareInfrastructura` and stops the run; a network failure on a page is never
  written as a listing status.
- **Validation rejects, it does not repair.** No defaults, no "translating" a wrong value into a
  close one.
- **One source of truth per fact.** Criteria in `config/criterii.yaml`, secrets in `.env`.
  Relevance is read only from `evaluari_calitative.relevant`.
- **Every warning figure must be able to reach zero.**
- **Tests touch no real model and need no key.** Criteria and the model are injected.

## Not to touch

- `.env` is not read, printed or copied; its shape changes in `.env.example`.
- `data/` is not deleted, rewritten or committed.
- No dependency is installed without being added to `requirements.txt`.
