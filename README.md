# Household Ledger

A local-first web app for reviewing household card and manual expenses. The app server uses Python, SQLite, and encrypted backup support. HSBC PDF import uses local PDF rendering and OCR.

## Run locally

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```
Open <http://127.0.0.1:8000>. The app binds to localhost by default. Its SQLite database and retained statement PDFs live in `data/`; keep that folder backed up. Do not expose this development server directly to the public internet.

For HSBC extraction, the machine needs Node.js, the `tesseract.js` Node dependency, and Poppler's `pdftoppm` command. The app detects the Codex desktop runtime automatically when available. The English OCR model is included under `vendor/tessdata/`; OCR runs locally and the PDF is not sent to a service. On a separate machine, install the Node dependency with `npm install` and install Poppler using that operating system's package manager.

## Current capabilities

- Add and review manual purchases, refunds, fees, interest, and card payments.
- Allocate shared purchases at 50%, wife-personal items at 100%, and your personal items at 0%; refunds can be assigned a negative share to reduce the balance.
- Review in a compact inbox with inline allocation, keyboard shortcuts, bulk assignment, and undo.
- Filter review by allocation, transaction type, cardholder, merchant text, and confidence in HSBC's INR Amount-column value; non-purchase statement lines stay grouped and expandable.
- Maintain merchant display names, optional legal names, and evolving statement aliases (for example, BUNDL → Swiggy).
- Queue unmatched statement aliases for optional Parallel Search lookup; results stay pending until you approve or reject them. Approving adds the alias and rematches structured transactions; search never auto-adds merchants.
- Store statement PDFs and export structured transactions and merchants as JSON.
- Extract HSBC statement lines from PDF locally; each imported line starts as **Needs review** and is linked to its source statement.
- Reconcile extracted INR charges against the HSBC statement summary; mismatches remain visible for correction.
- Correct OCR dates, descriptions, currencies, and amounts; statement reconciliation recalculates after a correction or a manually added line.
- Score the HSBC INR amount token separately from the full-line OCR score; saved amounts that differ from a fresh column-based read stay flagged for review.
- Preview the exact OCR source line from the review inbox, with amount-check issues and low-confidence values sorted first.
- Suggest allocations from explicit merchant rules or consistent reviewed history; suggestions require a user action to apply.
- Use the collapsible sidebar and ⌘K Spotlight search with recent queries and frequently opened records.
- The home dashboard defaults to the latest statement month and supports a year-grouped multi-month picker plus bank and card filters.
- Use only SQLite transaction records for totals and analytics; the PDF store is used only to view the source document.
- Enable hosted sign-in with PBKDF2-HMAC-SHA256 password hashes, expiring server-side sessions, same-site CSRF checks, login rate limiting, and administrator/member roles.
- Let admins create or deactivate accounts, change roles, and reset passwords; members can change their own passwords.
- Refuse a public network bind unless authentication, secure cookies, and a trusted TLS proxy are configured.
- Create daily encrypted SQLite + statement PDF backups, keep 30 snapshots, download them from Settings, and restore them offline with a confirmation prompt.

## Deploy to Vercel with Supabase

The Vercel container uses the existing Python, Poppler, and Tesseract OCR stack. Supabase provides the durable PostgreSQL database and private object storage for statement PDFs and encrypted backups. The local SQLite database and `data/` folder are excluded from deployment.

Create a Supabase project and a **private** Storage bucket named `ledger-statements`. Connect the project to this Vercel project, then add the server-only environment values to Vercel:

```text
POSTGRES_URL_NON_POOLING=<Supabase PostgreSQL connection URL>
SUPABASE_URL=<Supabase project URL>
SUPABASE_SECRET_KEY=<server-only secret key>
LEDGER_STORAGE_BUCKET=ledger-statements
LEDGER_AUTH_REQUIRED=1
LEDGER_SECURE_COOKIES=1
LEDGER_TRUST_PROXY=1
LEDGER_BOOTSTRAP_ADMIN_EMAIL=you@example.com
LEDGER_BOOTSTRAP_ADMIN_NAME=Your Name
LEDGER_BOOTSTRAP_ADMIN_PASSWORD=<unique password of 16+ characters>
WEBAUTHN_ORIGIN=https://ledger.example.com
WEBAUTHN_RP_ID=ledger.example.com
LEDGER_BACKUP_FERNET_KEY=<generated Fernet key>
CRON_SECRET=<random secret used by Vercel Cron>
```

Keep the Supabase database URL, secret key, admin password, backup key, and cron secret in Vercel's encrypted environment settings. Never add them to source control or the browser app. The statement bucket must remain private; the app fetches PDFs only after its own sign-in and access checks.

WebAuthn passkeys are scoped to the exact public HTTPS origin and relying-party hostname above. Users add and remove their own passkeys in **Settings**. Apple devices may offer iCloud Keychain in the system prompt; the app cannot force or inspect which authenticator stores the passkey.

Before the first production deployment, run `migrate_hosted.py` locally with the Supabase/Vercel values in your process environment. It creates the tables, uploads existing PDFs to the private bucket, imports the structured transaction history, creates the first admin account, and checks the uploaded PDFs. It refuses to run if the hosted database already contains ledger data. Deploy with `vercel deploy --prod` after migration. `Dockerfile.vercel` builds the application as a Vercel container function, and `vercel.json` schedules an encrypted database + PDF backup once per day. Admins can also create and download backups from Settings. To restore a hosted backup, install `postgresql-client`, set the database and Supabase environment variables plus the backup key, then run `python hosted_backup.py restore <backup-file>` and confirm the prompt.

The Vercel Hobby and Supabase Free tiers include usage allowances, but Supabase Free projects can pause after a week without activity and do not include automatic database backups. The daily Vercel backup schedule keeps the project active and provides an encrypted recovery copy; check both providers' usage dashboards as your PDF archive grows.

This repository is connected to the Household Ledger Vercel project. Pushes to `main` trigger production deployments. Keep household records, statement PDFs, and secrets out of source control.

## Private hosting preparation

The container image is provider-neutral. It excludes `data/`, work files, `.env`, and local PDFs so private statement records do not enter the image. Mount a persistent volume at `/app/data`, terminate TLS at the hosting provider or a trusted reverse proxy, and set the environment values below before exposing the service. The ingress must overwrite `X-Forwarded-Proto` with `https`; the app refuses to serve the sign-in page or authenticated endpoints over a direct HTTP connection when secure cookies are enabled. Keep port 8000 private behind that ingress:

```text
LEDGER_HOST=0.0.0.0
LEDGER_AUTH_REQUIRED=1
LEDGER_SECURE_COOKIES=1
LEDGER_TRUST_PROXY=1
LEDGER_BOOTSTRAP_ADMIN_EMAIL=you@example.com
LEDGER_BOOTSTRAP_ADMIN_NAME=Your Name
LEDGER_BOOTSTRAP_ADMIN_PASSWORD=<unique password of 16+ characters>
WEBAUTHN_ORIGIN=https://ledger.example.com
WEBAUTHN_RP_ID=ledger.example.com
LEDGER_BACKUP_FERNET_KEY=<generated Fernet key>
```

Generate a backup key with `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Keep the key in the hosting provider's secret settings and a separate password manager; it is required to restore encrypted backups. In hosted mode, the first administrator is created from the bootstrap values only when the user table is empty. Add your wife from **Settings → Users & access** after signing in. Never put passwords or backup keys in the container image or source control.

Daily backups are stored under `data/backups/` on the persistent volume, and admins can download the encrypted files. Those snapshots share the host's storage failure domain until you configure an off-site backup destination. To restore, stop the service and run `python3 backup.py restore <backup-name>` in the deployed environment; the command asks you to type `RESTORE` and saves a pre-restore snapshot first.

Build the image with `docker build -t household-ledger .`. The app listens on port 8000 inside the container. Do not publish that port directly to the public internet; the TLS proxy must be the public entry point. Deployment still requires selecting a hosting provider and configuring its persistent volume, secrets, domain, and off-site backup destination.

## Optional merchant lookup

Merchant lookup is disabled until configured. Create a Parallel Search API key, copy `.env.example` to `.env`, and set `PARALLEL_API_KEY` (or add it as a server-only Vercel environment variable). Restart the app, open Merchants, and choose **Search aliases**. Searches use Parallel's Fast mode and return up to five sources. The server sends only the cleaned statement alias and a merchant-identification objective; it does not send transaction amounts, dates, cardholder names, or PDFs. The key stays server-side. Every result remains pending until you approve or reject it. Parallel's Build plan currently advertises $5 of monthly credits with a card on file; usage beyond included credits can be billed, so set an account spend limit if you want to prevent overage charges.

## Current limitations

Only HSBC PDF extraction is implemented. The OCR result is a draft: verify dates, cardholder, merchant, currency, and INR amount for every line before assigning an allocation. Refund matching and other bank importers are later milestones. Local mode remains a single-user localhost app; hosted mode requires the auth and TLS proxy settings above. INR amounts are displayed to two decimal places and OCR confidence is stored separately from amount formatting.
