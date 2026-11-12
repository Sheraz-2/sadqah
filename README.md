# SadQah

**Small gifts. Practical support. Livelihoods that continue.**

SadQah is a micro-grant platform designed to help people living on very low incomes keep a small business running or take a practical step toward earning. Supporters can discover campaigns, give through PayPal Sandbox, follow gifts, and see how support reaches recipients. Recipient verification and payment workflows are supported by human review, with AI used as assistance rather than as the final decision-maker.

> **Demo environment:** This repository is configured for local development and PayPal Sandbox. It does not process real money. Do not change it to PayPal Live or expose the local development services to the public internet.

## What SadQah demonstrates

- Public and anonymous giving, with a donation-tracking flow for anonymous gifts.
- Recipient profiles and campaigns for practical livelihood needs.
- Recipient verification with human review; AI assessments are advisory and do not approve people or authorise payouts.
- PayPal Sandbox checkout, server-side capture handling, payout batching, webhook processing and reconciliation.
- Donor and recipient dashboards, private messages, thank-yous and campaign updates.
- An AI assistant with a built-in FAQ fallback and configurable AI provider.
- Role-based administration, moderation, reporting and an append-only ledger.

## Technology

| Layer | Technology |
|---|---|
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS, AG Grid |
| Backend | Python 3.12, FastAPI, Pydantic, asyncpg |
| Database | PostgreSQL 16 with role separation, database functions and row-level security |
| Supporting services | Redis 7; MinIO is optional for S3-compatible storage |
| Payments | PayPal Developer Sandbox / Payouts API |
| AI | Anthropic provider, optional local Ollama provider, or built-in FAQ mode |
| Local runtime | Docker Compose plus a Node.js frontend process |

## Run SadQah on a new computer (Windows)

These instructions use PowerShell. On Windows, use `npm.cmd` rather than `npm` if PowerShell blocks the `npm.ps1` script under its execution policy.

### 1. Install the required tools

Install these first:

1. **Git for Windows** — to clone the repository.
2. **Docker Desktop** with the WSL 2 backend enabled — Docker Desktop must be running before the next steps.
3. **Node.js 22 LTS or newer** — includes npm; Node 24.21.0 was present in the maintainer's audited environment.
4. **Python 3.12** — needed for generating local secrets and, if desired, loading the fictional demo data.

For the optional demo-data step, also install the PostgreSQL 16 **Command Line Tools** so that `psql.exe` is available on PATH. You do not need to install a separate PostgreSQL server; Docker runs the database.

### 2. Clone the repository

Replace the placeholder URL with the public GitHub repository URL shown on the Devpost submission.

```powershell
git clone https://github.com/Sheraz-2/sadqah.git
cd sadqah
```

If the repository uses a different folder name, `cd` into that folder instead.

### 3. Create your private environment file

Copy the example file:

```powershell
Copy-Item .env.example .env
```

Generate fresh local encryption and session secrets:

```powershell
py -3.12 backend\scripts\generate_secrets.py
```

The command prints five `KEY=value` lines. Open `.env` in a text editor and paste those values into the matching settings, replacing the blank values for `ENCRYPTION_KEYS`, `BLIND_INDEX_KEY`, `TOKEN_PEPPER` and `JWT_SECRET`; keep `ACTIVE_KEY_ID=v1` as printed.

Keep `ENV=dev` for this local judging setup. The example database passwords and the default PostgreSQL superuser password are development-only values. The Compose file binds database, Redis and API ports to `127.0.0.1`; do not expose this configuration to a network or use it for a public deployment.

**Never upload `.env` or share its contents.** It is excluded by `.gitignore`.

### 4. Add PayPal Sandbox credentials (for testing new payments)

Create or use a PayPal Developer Sandbox app and place its values in `.env`:

```dotenv
PAYPAL_ENV=sandbox
PAYPAL_CLIENT_ID=your_sandbox_client_id
PAYPAL_CLIENT_SECRET=your_sandbox_client_secret
PAYPAL_WEBHOOK_ID=your_sandbox_webhook_id
```

Use Sandbox credentials only. Follow [`docs/PAYPAL_SANDBOX_SETUP.md`](docs/PAYPAL_SANDBOX_SETUP.md) for creating the app, configuring the webhook and using Sandbox buyer/seller accounts. Do not commit these credentials. Without PayPal Sandbox credentials, the application can still start and seeded demo data can be explored, but new PayPal payments and payout/webhook tests will not work end to end.

### 5. Start the database and supporting services

From the repository root:

```powershell
docker compose up -d
```

This starts PostgreSQL 16 and Redis. The one-shot `db-init` service creates database roles, loads the schema and applies the SQL patches when the database volume is first created.

Check its result:

```powershell
docker compose logs db-init
```

On a fresh database, the final message should be `database provisioned`. If the database was already initialized, it should say `database already provisioned`.

### 6. Start the API and background workers

Still from the repository root:

```powershell
docker compose --profile app up -d --build
```

This builds and starts the FastAPI API, payout worker, webhook reconciler and KYC worker.

Check the API:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/healthz
```

The API is available at `http://localhost:8000`.

### 7. Install and start the frontend

Open a **second PowerShell window**, change to the repository's `frontend` folder, and install the exact dependencies recorded in the lockfile:

```powershell
cd path\to\sadqah\frontend
npm.cmd ci
npm.cmd run dev
```

Open **http://localhost:3000** in your browser. The Next.js configuration proxies `/api/*` requests to the API at `http://localhost:8000`; no separate frontend `.env.local` is required for the default local setup.

Keep both Docker Desktop and the frontend terminal running while testing the application.

## Optional: load the fictional judging/demo accounts

A fresh database has no sample campaigns until you create accounts and campaigns or load the demo seed. The seed script creates fictional donors, recipients, campaigns, gifts and thank-you notes. It refuses to run unless `ENV=dev`, is designed to be idempotent, and parks seeded queued payouts far in the future so fictional recipients are not paid.

This optional step requires Python 3.12, the PostgreSQL `psql` client tools and the backend dependencies. From the repository root:

```powershell
py -3.12 -m pip install -e .\backend
$env:PGHOST = "localhost"
$env:PGPORT = "5432"
$env:PGUSER = "postgres"
$env:PGPASSWORD = "postgres-dev-only"
py -3.12 .\backend\scripts\seed_dev.py --database sadqah
```

If you changed `POSTGRES_SUPERUSER_PASSWORD` in your `.env`, set `PGPASSWORD` to that same value instead of `postgres-dev-only`.

The default demo password is **`SadQah-Demo-Pass-2026`**. The seed creates these fictional accounts:

| Role | Login |
|---|---|
| Admin | `admin.demo@example.com` |
| Reviewer | `reviewer.demo@example.com` |
| Donors | `donor1.demo@example.com` through `donor3.demo@example.com` |
| Recipients | `recipient1.demo@example.com` through `recipient8.demo@example.com` |

All seeded accounts share the default demo password above unless a different `--password` is supplied. These credentials are for a fresh local development database only. Do not reuse them for a public or production deployment. If the seed reports `Already seeded`, the demo accounts were previously created.

## AI options

The project supports three explicit assistant modes. It does not silently switch to a different provider.

- **Anthropic (`ASSISTANT_PROVIDER=anthropic`)**: the default. Add `ANTHROPIC_API_KEY` in `.env` to enable the cloud AI assistant. The KYC AI assessment pipeline also uses the Anthropic key. AI assessments are advisory; human reviewers make verification decisions.
- **Ollama (`ASSISTANT_PROVIDER=ollama`)**: optional local assistant. Install Ollama separately, then run `ollama pull qwen2.5:1.5b`. The default Docker configuration reaches the host through `http://host.docker.internal:11434`. This local text model supports assistant chat and price estimates, but it does not inspect proof photos or PDFs; those remain for human review. KYC document AI still requires its configured Anthropic integration.
- **FAQ-only (`ASSISTANT_PROVIDER=none`)**: uses the built-in assistant guide without a model API.

For a first-time judge setup, **Ollama is not required**. Use the built-in FAQ mode if no AI key is available, or configure an Anthropic key to test the AI-enabled features. See [`docs/OLLAMA_ASSISTANT.md`](docs/OLLAMA_ASSISTANT.md) for optional Ollama details.

## Optional MinIO storage

The normal configuration uses local file storage (`STORAGE_BACKEND=local`) and does not require MinIO. MinIO is included only for the optional S3 profile. Use it only if you deliberately configure `STORAGE_BACKEND=s3` and the corresponding S3 settings.

## Useful URLs

| What | URL |
|---|---|
| SadQah frontend | http://localhost:3000 |
| Campaign discovery | http://localhost:3000/campaigns |
| Donor dashboard | http://localhost:3000/dashboard |
| Recipient portal | http://localhost:3000/recipient |
| Admin console | http://localhost:3000/admin |
| API health check | http://localhost:8000/api/v1/healthz |

## Stop the local application

In the frontend terminal, press `Ctrl+C`. From the repository root, stop the Docker services without deleting the database volume:

```powershell
docker compose --profile app down
```

Do **not** add `-v` unless you intentionally want to delete the local database and stored demo data.

## Testing and development checks

Backend tests (from the `backend` directory, with the development dependencies installed):

```powershell
py -3.12 -m pip install -e ".[dev]"
py -3.12 -m pytest -q
py -3.12 -m ruff check app scripts tests
```

Frontend checks (from `frontend`):

```powershell
npm.cmd run typecheck
npm.cmd run build
```

Database flow and privacy checks are in `database/tests/`. Follow the comments at the top of each SQL test and use a disposable development database where required. **Never run destructive reset scripts or committing concurrency tests against a database containing real or valuable data.**

## Security and demo boundaries

- PayPal is configured for Sandbox; no real money is moved by this demo configuration.
- Do not publish `.env`, API keys, database passwords, encryption keys, tokens, private certificates or real user data.
- The demo seed contains fictional names, reserved `example.com` emails and fake payment identifiers. It is for local evaluation only.
- AI output is assistance, not proof of identity, a verification decision or a payment authorisation. Human review remains part of the workflow.
- Do not expose local Docker ports or Ollama port `11434` to the public internet.

## More detail

- [`docs/ABOUT_SADQAH.md`](docs/ABOUT_SADQAH.md) — project purpose.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system architecture.
- [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) — API endpoints and response conventions.
- [`docs/PAYPAL_SANDBOX_SETUP.md`](docs/PAYPAL_SANDBOX_SETUP.md) — PayPal Sandbox setup.
- [`docs/SECURITY.md`](docs/SECURITY.md) — security design and deployment notes.
- [`docs/OLLAMA_ASSISTANT.md`](docs/OLLAMA_ASSISTANT.md) — optional local AI setup.

## Verification note

In the maintainer's Windows environment, the backend suite reported **398 passed** after the P5.1 encryption changes, and the P5.1 focused suite reported **80 passed** with Ruff passing. The frontend production build and live donor dashboard/messaging pages were also successfully checked during the project work. These are maintainer-reported local checks; a judge should still follow the clean-machine setup above and report any environment-specific issue.
