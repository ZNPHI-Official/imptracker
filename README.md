ImpTracker is a Django/PostgreSQL web app for multi-year activity planning, procurement tracking, attachments with versioning, audit logging, dashboards, and email notifications (assignments, status changes, due date alerts) with role-based access control.

## Architecture Diagram (text)
- Client (browser) → Nginx → Gunicorn (Django) → PostgreSQL
- Static/Media served by Nginx from shared volumes
- Certbot issues/renews TLS certs; pgAdmin available for DB admin

## Environment Variables
- Core: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL`
- DB: `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- Email: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`
- Notifications: `NOTIFICATIONS_ENABLED`, `DUE_DATE_ALERT_DAYS`, `SEND_TEST_EMAIL`
- Security: `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`
- SSL: `CERTBOT_EMAIL`, `SERVER_NAME`
- Compose extras: `PGADMIN_DEFAULT_EMAIL`, `PGADMIN_DEFAULT_PASSWORD`
- Optional: set `ENV_FILE` or `DJANGO_ENV_FILE` to pick env file (defaults to `.env`)

## Local Development (PostgreSQL)
1) Copy `local.env` to `.env` (or export `ENV_FILE=local.env`). Update DB creds if needed.
2) Install deps: `python -m venv venv && venv\Scripts\activate && pip install -r requirements.txt`.
3) Start Postgres locally (DB `imptracker`, user/password from `.env`).
4) Apply migrations and seed defaults:
   - `python manage.py migrate`
   - `python manage.py seed_defaults`
   - `python manage.py createsuperuser`
5) Run server: `python manage.py runserver` and open http://localhost:8000.

## Docker Production Stack
1) Set `production.env` values (SECRET_KEY, DB_PASSWORD, SERVER_NAME, CERTBOT_EMAIL, pgAdmin creds).
2) Build and start: `docker compose up -d --build`.
3) Run one-off certificate issuance (first time):
   - `docker compose run --rm certbot certonly --webroot -w /var/www/certbot -d $SERVER_NAME --email $CERTBOT_EMAIL --agree-tos --non-interactive`
   - Reload Nginx: `docker compose exec nginx nginx -s reload`
4) Services:
   - web: Django via Gunicorn (collectstatic/migrate/seed on entry)
   - db: Postgres 15 (volume `pgdata`)
   - pgadmin: http://localhost:5050
   - nginx: ports 80/443, serves static/media and proxies to web
   - certbot: renews every 12h using webroot

## Migrations & Seeding
- Apply: `python manage.py migrate`
- Seed defaults (roles, statuses, currencies, procurement types): `python manage.py seed_defaults`
- Recurring activities generation: `python manage.py generate_recurring_activities --months=3`
- Due date alerts: `python manage.py send_due_date_alerts --days=7`

- PULL MIGRATIONS MADE IN DOCKER INTO FILES: `docker cp django_web:/app/activities/migrations/0017_sync_missing_fields.py ./activities/migrations/`

## SSL Setup & Renewal
- Initial issuance via certbot command above.
- Renewal handled by `certbot` service (webroot `/var/www/certbot`, certs in `certbot-conf` volume).
- Ensure `SERVER_NAME` DNS points to the host before issuing/renewing.

## Common Issues
- Postgres not ready: restart `web` after `db` is healthy or add a short wait.
- Static files missing: ensure `web` ran `collectstatic` (entrypoint does this) and volumes are mounted to nginx.
- Emails failing: verify SMTP credentials and that `NOTIFICATIONS_ENABLED=True`.
- Login/CSRF errors behind HTTPS: set `CSRF_TRUSTED_ORIGINS` to your https domain and enable secure cookies.

## Deployment Checklist
- [ ] `production.env` filled (secrets, DB, domain, email)
- [ ] DNS A/AAAA points to server
- [ ] `docker compose up -d --build`
- [ ] Certbot initial run + nginx reload
- [ ] `docker compose exec web python manage.py migrate`
- [ ] `docker compose exec web python manage.py seed_defaults`
- [ ] Admin user created; smoke-test login, upload, dashboards, notifications

## License
Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
