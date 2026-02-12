from django.apps import AppConfig


class ListingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "listings"

    def ready(self):
        # Skip scheduler for management commands (migrate, shell, check, …)
        if _is_manage_command():
            return

        import os
        import threading

        # Defer DB access by a couple of seconds so Django is fully ready.
        # This avoids the "Accessing the database during app initialization" warning.
        def _start():
            try:
                from listings.scheduler import start_scheduler
                start_scheduler()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Could not start scheduler: %s", exc)

        t = threading.Timer(2.0, _start)
        t.daemon = True
        t.start()


def _is_manage_command() -> bool:
    """Return True when running a Django management command (migrate, shell, …)."""
    import sys

    argv = sys.argv
    if len(argv) >= 2 and argv[1] in (
        "migrate",
        "makemigrations",
        "shell",
        "dbshell",
        "check",
        "collectstatic",
        "createsuperuser",
        "test",
    ):
        return True
    return False
