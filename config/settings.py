
from pathlib import Path
import os
from dotenv import load_dotenv


def _env_bool(name: str, default: bool = False) -> bool:
	val = os.getenv(name)
	if val is None:
		return default
	return str(val).strip().lower() in ("1", "true", "yes", "on")


# Choose which env file to load by default.
# - Local/dev: .env
# - Production: production.env
# Can be overridden via ENV_FILE or DJANGO_ENV_FILE.
_bootstrap_env = os.getenv("DJANGO_ENV", "").strip().lower()
_bootstrap_debug = os.getenv("DEBUG")

_default_env_file = ".env"
if _bootstrap_env in ("prod", "production"):
	_default_env_file = "production.env"
elif _bootstrap_debug is not None and str(_bootstrap_debug).strip().lower() in ("0", "false", "no", "off"):
	_default_env_file = "production.env"

ENV_FILE = os.getenv("ENV_FILE", os.getenv("DJANGO_ENV_FILE", _default_env_file))
load_dotenv(ENV_FILE)

# Define the base directory of your project
BASE_DIR = Path(__file__).resolve().parent.parent

# Core settings from environment
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
DEBUG = _env_bool("DEBUG", True)

# Hosts and site metadata
ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000")

INSTALLED_APPS = [
 'jet.dashboard',
 'jet',
	'django.contrib.humanize',
	"crispy_forms",
		"crispy_bootstrap5",
 'django.contrib.admin','django.contrib.auth','django.contrib.contenttypes',
 'django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles',
 'import_export',
 'django_htmx',
 'django_crontab',
 'accounts','activities','masters','uploads','audit','dashboards','support',
 # Fleet Manager apps (merged from ZNPHI-Fleet-Manager)
 'bookings','fleet','dashboard','settings_app',
]
AUTH_USER_MODEL='accounts.User'

# Database configuration (default to PostgreSQL)
DATABASES={
		'default':{
				'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.postgresql'),
				'NAME': os.getenv('DB_NAME', 'imptracker'),
				'USER': os.getenv('DB_USER', 'postgres'),
				'PASSWORD': os.getenv('DB_PASSWORD', 'password'),
				'HOST': os.getenv('DB_HOST', 'db' if not DEBUG else 'localhost'),
				'PORT': os.getenv('DB_PORT', '5432'),
		}
}

MIDDLEWARE = [
	'django.middleware.security.SecurityMiddleware',
	'whitenoise.middleware.WhiteNoiseMiddleware',
	'django.contrib.sessions.middleware.SessionMiddleware',
	'django_htmx.middleware.HtmxMiddleware',
	'django.middleware.common.CommonMiddleware',
	'django.middleware.csrf.CsrfViewMiddleware',
	'django.contrib.auth.middleware.AuthenticationMiddleware',
	'django.contrib.messages.middleware.MessageMiddleware',
	'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

TEMPLATES = [
	{
		'BACKEND': 'django.template.backends.django.DjangoTemplates',
		'DIRS': [BASE_DIR / 'templates'],
		'APP_DIRS': True,
		'OPTIONS': {
			'context_processors': [
				'django.template.context_processors.debug',
				'django.template.context_processors.request',
				'django.contrib.auth.context_processors.auth',
				'django.contrib.messages.context_processors.messages',
				'accounts.context_processors.user_roles',
				'bookings.context_processors.pending_request_count',
			],
		},
	},
]
ROOT_URLCONF = 'config.urls'
STATIC_URL = '/static/'
# Optional: Directory where 'collectstatic' will gather all static files for deployment
STATIC_ROOT = BASE_DIR / 'staticfiles'
# Define the directory where your general static files are located
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ============================================================================
# EMAIL CONFIGURATION - GMAIL SMTP
# ============================================================================

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS', True)
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', os.getenv('GMAIL_EMAIL', ''))
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', os.getenv('GMAIL_APP_PASSWORD', ''))
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'no-reply@example.com')

# ============================================================================
# NOTIFICATION SETTINGS
# ============================================================================

# Enable/disable notifications
NOTIFICATIONS_ENABLED = _env_bool('NOTIFICATIONS_ENABLED', True)

# Due date alert days (send alert X days before deadline)
DUE_DATE_ALERT_DAYS = int(os.getenv('DUE_DATE_ALERT_DAYS', '7'))

# Send test email (for debugging)
SEND_TEST_EMAIL = _env_bool('SEND_TEST_EMAIL', False)

# ==========================================================================
# DJANGO TASKS (Django 6)
# ==========================================================================

TASKS = {
	"default": {
		"BACKEND": "services.task_backends.threaded.ThreadedBackend",
		"OPTIONS": {
			"MAX_WORKERS": int(os.getenv("TASKS_MAX_WORKERS", "4")),
		},
	}
}
# Locale / TZ defaults
LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.getenv('TIME_ZONE', 'Africa/Lusaka')
USE_I18N = True
USE_L10N = True
USE_TZ = True

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/apps/"
LOGOUT_REDIRECT_URL = "/login/"

# Fleet Manager scheduled tasks (django-crontab only registers on Linux via
# `manage.py crontab add`; on Windows/dev run `manage.py run_transitions` manually)
CRONJOBS = [
	('0 1 * * *', 'django.core.management.call_command', ['run_transitions']),
]


#JET_DEFAULT_THEME = 'light-gray' # green, light-violet, light-green, light-blue, light-gray
JET_SIDE_MENU_COMPACT = True


CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"

CRISPY_TEMPLATE_PACK = "bootstrap5"

# Security defaults for production
SECURE_SSL_REDIRECT = _env_bool('SECURE_SSL_REDIRECT', False)
SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', False)
CSRF_COOKIE_SECURE = _env_bool('CSRF_COOKIE_SECURE', False)
