# Agent 051 — design decisions

This document explains how Agent 051 is built and why: the principles behind the code and the
decisions that were closed during development, each with its reason. Where a decision came from
a failure, the failure is given in one line. The private repository keeps the full record, with
dates and measurements; this is the part that shapes the code published here.

## 1. Scope and non-goals

Agent 051 **reads** job alerts, **checks** every listing against the user's criteria and
**tells** which ones are worth opening. It never applies, never writes to the mailbox and never
decides for the user: the briefing is a list to read, not an action.

Non-goals: running on a schedule (section 7); reading pages that refuse automated requests
(section 5); converting or guessing salaries it cannot compare (section 4).

## 2. Principles

**The model judges; code decides.** Figures and anything irreversible belong to deterministic
code and to the user. The model is used only where the judgement is unavoidably subjective: how
well a listing fits the target roles. Salary, location, date, languages and keywords are rules in
code. If the model states a figure it was not given by the code, the figure is invented.

**The core is pure.** Every function in `src/agent051/core/` takes data and returns data: no
files, no network, no database, not even "just to orchestrate". The test: if it does not work
with the network cut and no file on disk, it is in the wrong place. The adapters are thin
wrappers; orchestration is input and output, and lives in `src/agent051/adapters/`.

**Ingestion keeps raw data.** Emails are stored as received, HTML and text. Cleaning, extracting
and interpreting are separate steps that can be repeated at any time without the network. *(What
is thrown away at ingestion cannot be recovered without reading everything again: the eJobs
links were once lost together with the HTML.)*

**The cheap check comes before the network.** Disk before network, headers before bodies, a list
of message IDs before their content. *(An early run spent 103 of its 134 seconds finding out
that no email was new.)*

**What comes from the network is checked by identity.** A 200 status does not prove that the
page received is the page requested: the listing's identifier must survive in the final address.
*(eJobs answers a dead listing with a redirect to its general list, which arrives as a 200 and a
valid page about something else.)*

**"The model was not reached" is not "the model said no".** An infrastructure failure, such as a
missing library, a rejected key or a dropped network, is raised as `EroareInfrastructura` and
stops the run. A network failure while reading job pages stops the run too; it is never written
down as a listing status.

**Every warning figure must be able to reach zero.** A warning that can never clear becomes
furniture. *(An `expirat` page was once retried at every run, so three dead listings stayed in
`in_asteptare` for good and the count could never reach zero.)*

**One source of truth for each fact.** Criteria in `config/criterii.yaml`, network politeness in
`config/surse.yaml`, secrets in `.env`. Relevance has a single source:
`evaluari_calitative.relevant`. *(Two `relevant` fields in two tables once disagreed.)*

**One stage at a time.** No stage starts until the previous one is in real use. *(138 of the
first 143 evaluations were given without a description, because the stage that fetched the text
was built and tested but not yet running.)*

## 3. The model

- **The agent has its own model function**, with its own key, in
  `src/agent051/adapters/model.py`. It does not borrow the model of the assistant that calls it:
  MCP lets a client call tools, not inject functions; MCP sampling is not supported by the
  client in use; and it would tie every run to the assistant being up.
- **Normalization gives no relevance verdict.** It extracts four facts (`rol_normalizat`,
  seniority, work mode, domain); relevance belongs to the evaluation.
- **The briefing calls no model.** The judgement was made at evaluation and is stored. A model
  here would pay for a summary that can be computed exactly, and would give two different
  briefings on the same data.
- **Validation rejects; it does not repair.** No default values, no "translating" a near-miss
  into an allowed value. A rejected field is visible and can be retried; an invented one is
  never seen again.
- **There is no default model.** Without `MODEL_NORMALIZARE` in `.env`, the model steps stop at
  the pre-flight check, as they do for a missing key, and the cost report says why it cannot
  price the run. A fallback model would silently change the judge.
- **Thinking and effort stay at their defaults; no prompt cache for now.** A paid probe on eight
  real listings (64 calls, US$0.43) showed that lower effort on normalization cut cost by 13–14%
  but matched the stored verdicts on 4–5 of 8, against 7 of 8. Caching the criteria would save
  about 23% on evaluation, but needs a separate cost counter for cached tokens, which are priced
  differently. Reopened if the number of runs grows.

## 4. Listings and verdicts

- **Three verdicts, not two.** A listing passes, is rejected with the rule it broke, or is
  uncertain when data is missing. Uncertain is never treated as rejected.
- **`ok` and `expirat` are final statuses.** A reposted job is a new listing: a new link, in a new
  email.
- **In the briefing, a repost is not news.** Same title and same company: one line, marked as
  reposted with the date it first appeared. Same title at an aggregator (`agregatori` in
  `config/surse.yaml`): its own line, marked "possibly reposted", never hidden. Without an
  aggregator, the same title at two companies gets no mark: generic titles produced lists of six
  companies. The window is `varsta_maxima_zile`.
- **On eJobs, a listing's identity is its number**, not the shape of its address: `/j/N` and
  `/name/N` are the same listing.
- **On eJobs, the country is decided by the residence required of the applicant**
  (`applicantLocationRequirements`); the workplace address (`jobLocation`) decides only when that
  is missing. A remote job for Romania at a company based elsewhere is not rejected.
- **An unknown company country does not reject.** eJobs and BestJobs are Romanian markets;
  missing evidence is not evidence. When `tara_firma` is used, the signal is the country in the
  structured data, not the company's name.
- **No exchange rate in the code.** It changes daily, and the filter must give the same result
  every time. A salary in another currency is marked `necomparabil`, visibly.

## 5. The network

- **LinkedIn pages are not requested.** LinkedIn blocks automated requests; getting past the
  block would mean disguising the agent. This is reopened only on an honest path, such as a
  public feed or an API with one's own account.
- **The User-Agent is honest**, not copied from a browser, and the same for pages and for
  `robots.txt`.
- **`robots.txt` is respected.** A page it forbids is stored as `interzis_robots` and stays
  retryable, in case the rule changes.
- **The mailbox is read-only.** IMAP is opened `readonly` and messages are fetched with
  `BODY.PEEK`, so nothing is marked as read.

## 6. Cost and failures

- **Cost is counted per program.** The API key may be shared with other programs, so
  `ContorCost` records the calls and tokens of every run in the database; the report shows only
  what Agent 051 spent.
- **The monthly budget reports; it does not stop a run.** The hard stop is the API account's own
  credit.
- **There is no cap on attempts per listing.** A rejected listing stays eligible at every run:
  repeated failure is information about the prompt or the model, and a cap would hide it. The
  cost shows in `esecuri_pe_anunt`, and a repeated failure must be seen growing
  (`incercari_esuate`). *(An `INSERT OR REPLACE` once made the tenth rejection look like the
  first.)*

## 7. Running and the interface

- **No automatic schedule.** A run starts only when the user asks, from the command line or from
  an MCP client. The need is rare and irregular, and a scheduled run would pay for answers that
  nobody reads.
- **The briefing marker does not move by itself.** `briefing()` only reads;
  `briefing(marcheaza_citit=True)` consumes. A repeat is visible and can be ignored; a gap is not
  visible at all.
- **The interface is a standard, not a model.** The agent is reached through MCP, so the
  assistant that calls it can be replaced without touching the agent. The model itself is called
  directly, from a single provider, on purpose.
- **Other people's data is removed before it leaves.** Names and codes found in third-party
  emails are anonymized (`src/agent051/core/anonimizare.py`) before they reach an MCP client. The
  user's own criteria stay in their copy of `config/criterii.yaml`; the values published here are
  fictional.

## 8. What is not in this repository

The private repository also keeps the working notes of the project: the full log of lessons
with their dates, the decisions about the development environment, and the user's real
criteria. They are left out on purpose; the decisions above are the ones the published code
follows.
