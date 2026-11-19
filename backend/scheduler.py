"""Planificateur simple : traite les alertes dues toutes les 15 minutes.

Lancement : python -m backend.scheduler
(Alternative en production : une tâche cron qui lance `flask --app backend.app run-due`.)
"""
import logging
import time

from .db import init_db
from .pipeline import run_due

INTERVAL_SECONDS = 15 * 60
log = logging.getLogger("scheduler")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    log.info("Planificateur démarré (toutes les %d min)", INTERVAL_SECONDS // 60)
    while True:
        started = time.monotonic()
        try:
            for result in run_due():
                log.info("%s", result)
        except Exception:
            log.exception("Passage du planificateur en erreur")
        time.sleep(max(60, INTERVAL_SECONDS - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
