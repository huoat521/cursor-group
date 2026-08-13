from celery import Celery

from app.config import settings

celery_app = Celery(settings.PROJECT_NAME)
celery_app.config_from_object(settings)
celery_app.conf.broker_url = settings.CELERY_BROKER_URL
celery_app.conf.result_backend = settings.CELERY_RESULT_BACKEND
celery_app.conf.timezone = settings.timezone
celery_app.conf.enable_utc = settings.enable_utc
celery_app.conf.beat_schedule = settings.beat_schedule

# Ensure tasks are registered
import app.api.cursor.tasks  # noqa: E402,F401
