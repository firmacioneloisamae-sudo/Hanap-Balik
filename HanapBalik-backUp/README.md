# HanapBalik

HanapBalik is a Flask lost-and-found application. The original HTML/CSS visual
design is retained, with a SQLite database for local development and
PostgreSQL support for hosted deployments.

## Requirements

- Python 3.10 or later
- A virtual environment is recommended
- PostgreSQL (optional; local SQLite works without a separate database server)

## Run locally (Windows PowerShell)

From the cloned repository's root, change into the project folder first:

```powershell
Set-Location .\HanapBalik-backUp
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set both `SECRET_KEY` and `ID_ENCRYPTION_KEY` to unique random
values. Generate them with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Initialize the database and start the development server:

```powershell
flask --app app db upgrade
flask --app app run
```

Open <http://127.0.0.1:5000>. SQLite data and private uploads are stored in the
Flask `instance` folder.

The Flask development server is for local development only. For a simple
production WSGI server, run Waitress behind an HTTPS-terminating reverse proxy:

```powershell
$env:COOKIE_SECURE = "true"
waitress-serve --host=127.0.0.1 --port=8080 --call app:create_app
```

Configure the proxy/firewall and your hosting provider's persistent storage
before exposing the service publicly.

## Create an administrator

There is no default admin account. Create one after applying migrations:

```powershell
flask --app app create-admin admin@example.com
```

The command prompts for a password and administrator name; it does not put
credentials in source code or command history. Admins can review claims,
manage report statuses, inspect submitted identity documents, and verify
accounts.

## Database configuration

`DATABASE_URL` defaults to `sqlite:///hanapbalik.db`. To use PostgreSQL, set it
to a private connection URL, for example:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require
```

The application selects the psycopg 3 driver for PostgreSQL URLs. Supabase
PostgreSQL connection URLs work the same way. Keep database credentials and
`SECRET_KEY` in `.env` or your hosting provider's secret manager; never put
them in browser code or commit `.env`.

Apply schema changes with `flask --app app db upgrade`. The initial schema is
in `migrations/versions/20261105_01_initial_schema.py`. To create a migration
after changing the SQLAlchemy models:

```powershell
flask --app app db migrate -m "Describe the schema change"
flask --app app db upgrade
```

Review generated migrations before applying them to production.

## Security and uploads

- Passwords are stored as Werkzeug password hashes; sessions use HTTP-only,
  SameSite cookies and API mutations require a session CSRF token.
- Set `COOKIE_SECURE=true` behind HTTPS in production.
- Identity documents and claim evidence are stored outside the static/public
  directories and can only be downloaded by an administrator. Item photos
  are public while the report is open or matched.
- Uploaded files are limited to 5 MB and checked by file signature as well as
  extension. Back up the `instance` directory (or persistent upload storage)
  along with the database and `ID_ENCRYPTION_KEY`; losing or rotating that key
  without re-encrypting existing records makes identity and claim evidence
  unrecoverable.
- Identity numbers, identity documents, claim evidence text and claim
  attachments are encrypted at rest with `ID_ENCRYPTION_KEY`.
- Accounts begin unverified. An administrator reviews the submitted ID and
  controls verification; private identity fields are never included in public
  item responses.

## Tests

```powershell
python -m unittest discover -s tests -v
```
