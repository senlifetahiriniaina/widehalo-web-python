"""Garde-fou bloquant — le budget d'une passe de vidange reste sous le
délai que Django-Q accorde à une tâche.

**Le défaut que cette garde empêche est silencieux et total.** Une passe de
vidange s'exécute dans une tâche Django-Q, et Django-Q tue toute tâche qui
dépasse `Q_CLUSTER["timeout"]`. Une passe dont le budget dépasserait ce
délai serait donc tuée AVANT d'avoir fini — et comme rien n'est écrit tant
qu'un échange n'a pas été traité, elle recommencerait au même endroit à la
passe suivante, pour être tuée de nouveau. La file ne se viderait plus
jamais, sans une seule erreur dans les journaux.

Rien ne relie aujourd'hui ces deux réglages : ils vivent dans le même
fichier, à quinze lignes l'un de l'autre, et l'un est réglé pour le hub de
flux tandis que l'autre l'est pour l'ensemble des tâches de fond. Le jour
où quelqu'un abaissera `timeout` — pour libérer plus vite un worker bloqué,
ce qui est un motif raisonnable — c'est ce test qui le préviendra.
"""

from __future__ import annotations

from django.conf import settings


def test_a_drain_pass_fits_inside_the_task_timeout() -> None:
    timeout = settings.Q_CLUSTER["timeout"]
    assert timeout > settings.FLOWS_MAX_PASS_SECONDS, (
        f"Le budget d'une passe de vidange ({settings.FLOWS_MAX_PASS_SECONDS} s) atteint "
        f"ou dépasse le délai que Django-Q accorde à une tâche ({timeout} s). La passe "
        "serait tuée avant la fin, recommencerait au même endroit et serait tuée de "
        "nouveau : la file de sortie ne se viderait plus jamais, sans une seule erreur "
        "dans les journaux. Baisser le budget de passe, ou relever le délai des tâches."
    )


def test_a_single_call_fits_inside_a_pass() -> None:
    """Un délai par appel supérieur au budget de passe rendrait le premier
    réglage inopérant : la passe s'arrêterait avant que l'appel n'ait eu le
    droit d'expirer, et « délai maximal par appel » ne serait jamais qu'une
    intention."""
    assert settings.FLOWS_MAX_CALL_SECONDS <= settings.FLOWS_MAX_PASS_SECONDS, (
        f"Le délai maximal par appel ({settings.FLOWS_MAX_CALL_SECONDS} s) dépasse le "
        f"budget d'une passe ({settings.FLOWS_MAX_PASS_SECONDS} s) : aucun appel ne "
        "pourrait aller au bout de son délai."
    )


def test_a_pass_can_fit_more_than_one_call() -> None:
    """Une passe qui n'a le temps que d'un seul appel viderait la file au
    rythme d'un échange par heure — soit, avec la cadence horaire de la
    commande, vingt-quatre échanges par jour. Ce n'est pas une file, c'est
    un goutte-à-goutte."""
    assert settings.FLOWS_MAX_PASS_SECONDS >= 2 * settings.FLOWS_MAX_CALL_SECONDS, (
        "Une passe ne peut contenir qu'un seul appel au délai maximal : la file se "
        f"viderait à raison d'un échange par passe ({settings.FLOWS_MAX_PASS_SECONDS} s "
        f"de budget pour {settings.FLOWS_MAX_CALL_SECONDS} s par appel)."
    )
