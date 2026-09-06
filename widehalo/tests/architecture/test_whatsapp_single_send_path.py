"""Garde-fou bloquant (WA-1, L10) : aucune voie applicative ne contourne le
point d'entree gouverne d'envoi WhatsApp.

Le critere WA-1 ne demande pas seulement que le controle de consentement
existe a l'envoi — il demande **un test qu'aucune voie applicative ne le
contourne**. Ce test-la n'existait pas : `send_governed_template_message`
etait le point d'entree unique par convention et par docstring, rien ne
l'imposait. Un module futur qui appelle `get_whatsapp_client()` directement
envoie un message sans consentement, sans plafond de cout, sans limite de
frequence et sans ligne au journal, et aucun test ne rougit.

**Ce que la garde inspecte.** L'IMPORT des deux fonctions de transport
(`apps.core.services.whatsapp.get_whatsapp_client`, qui donne le client
reseau, et `apps.core.services.notifications.send_whatsapp_notification`,
qui envoie et journalise d'un coup). Niveau import et non niveau appel :
`tests/architecture/_ast_utils.py` n'offre pas d'extracteur d'appels, et
c'est suffisant ici — les deux fonctions sont inatteignables sans un import
detectable, y compris en import local dans un corps de fonction (patron
employe par les trois voies legitimes ci-dessous), qu'`ast.walk` traverse.
Meme niveau d'analyse que `test_no_direct_task_queue_usage.py`.

**La liste d'exception est motivee, jamais une commodite.** Trois entrees,
et chacune est un maillon du transport lui-meme, pas un raccourci :

1. `core/services/notifications.py` — c'est la couche de transport. Lui
   interdire d'importer le client reviendrait a interdire au telephone de
   composer le numero.
2. `whatsapp/services/messaging.py` — le point d'entree gouverne lui-meme,
   qui doit bien finir par appeler le reseau (file, reprise, envoi direct).
3. `whatsapp/services/inbound.py` — WA-8, le menu d'intentions. Seul
   contournement REEL, et il est justifie : une reponse dans la fenetre de
   service (WA-3) est une reponse au client, pas une sollicitation
   business-initiated, et n'a donc pas a exiger le consentement WA-1/WA-2
   qui protege les secondes. L'exemption porte sur le CONSENTEMENT et sur
   lui seul : depuis L10 cette voie journalise son envoi comme les autres
   (elle ne le faisait pas, cf. sa docstring).

Toute quatrieme entree ajoutee ici sans motif ecrit du meme ordre est une
regression de gouvernance, pas une mise a jour de liste."""

from __future__ import annotations

from pathlib import Path

from tests.architecture._ast_utils import discover_apps, extract_imports, iter_app_python_files

# Modules de transport : les importer, c'est pouvoir envoyer.
_TRANSPORT_MODULES = {
    "apps.core.services.whatsapp",
    "apps.core.services.notifications",
}

# Noms qui, importes depuis ces modules, donnent le pouvoir d'envoyer. Les
# autres exports de `notifications` (notifications applicatives, e-mail)
# ne sont pas concernes : ce garde-fou porte sur le canal WhatsApp.
_SENDING_NAMES = {"get_whatsapp_client", "send_whatsapp_notification"}

# Chemins autorises, relatifs a `apps/` — cf. docstring pour le motif de
# chacun. Format `<app>/<chemin>` pour rester lisible et resistant a un
# deplacement du depot.
_ALLOWED_PATHS = {
    "core/services/notifications.py",
    "whatsapp/services/messaging.py",
    "whatsapp/services/inbound.py",
}


def _relative_app_path(path: Path) -> str:
    parts = path.parts
    return "/".join(parts[parts.index("apps") + 1 :])


def _violations() -> list[str]:
    found: list[str] = []
    for app in discover_apps():
        for file in iter_app_python_files(app, exclude_tests=True):
            relative = _relative_app_path(file)
            if relative in _ALLOWED_PATHS:
                continue
            source = file.read_text(encoding="utf-8")
            for record in extract_imports(file):
                if record.module not in _TRANSPORT_MODULES:
                    continue
                # `extract_imports` ne retient que le module ; on regarde le
                # texte pour savoir si c'est bien un nom d'ENVOI qui est
                # importe, et non `record_inbound_whatsapp_message` ou
                # `dispatch_notification`, tous deux sans pouvoir d'envoi.
                for name in _SENDING_NAMES:
                    if name in source:
                        found.append(f"{relative} : importe '{name}' depuis {record.module}")
    return found


def test_no_path_bypasses_the_governed_send_entry_point() -> None:
    violations = _violations()
    assert not violations, (
        "WA-1 : voie(s) d'envoi WhatsApp contournant `send_governed_template_message` "
        "(ni consentement, ni plafond, ni limite de fréquence, ni journal) :\n"
        + "\n".join(violations)
        + "\n\nUtiliser `apps.whatsapp.services.messaging.queue_governed_template_message`. "
        "Une exception ne s'ajoute à `_ALLOWED_PATHS` qu'avec un motif écrit dans la "
        "docstring de ce module."
    )


def test_the_allowlist_has_no_obsolete_entry() -> None:
    """Une liste d'exception qui survit au fichier qu'elle exemptait est un
    trou silencieux : elle autoriserait a recreer ce chemin plus tard sans
    que personne ne rejoue la decision."""
    apps_dir = Path(__file__).resolve().parent.parent.parent / "apps"
    missing = [entry for entry in _ALLOWED_PATHS if not (apps_dir / entry).exists()]
    assert not missing, f"Entrée(s) d'exception pointant sur un fichier disparu : {missing}"


def test_the_detector_actually_detects(tmp_path: Path) -> None:
    """Auto-test du detecteur, sans quoi cette garde serait un theatre de
    securite : `_violations()` renvoie la liste vide aussi bien quand tout
    est conforme que quand le detecteur est casse (un nom mal orthographie
    dans `_SENDING_NAMES`, un module renomme). On verifie donc qu'il voit
    une violation quand on lui en presente une."""
    fake = tmp_path / "apps" / "faux_module" / "services"
    fake.mkdir(parents=True)
    offender = fake / "envoi_sauvage.py"
    offender.write_text(
        "from apps.core.services.whatsapp import get_whatsapp_client\n\n"
        "def envoyer():\n"
        "    get_whatsapp_client().send_template('+261340000000', 'promo', {})\n",
        encoding="utf-8",
    )

    records = extract_imports(offender)
    assert any(r.module in _TRANSPORT_MODULES for r in records), (
        "Le detecteur ne reconnait plus le module de transport : `_TRANSPORT_MODULES` "
        "est desynchronise du code."
    )
    source = offender.read_text(encoding="utf-8")
    assert any(name in source for name in _SENDING_NAMES), (
        "Le detecteur ne reconnait plus les noms d'envoi : `_SENDING_NAMES` est "
        "desynchronise du code."
    )
    assert _relative_app_path(offender) not in _ALLOWED_PATHS


def test_the_governed_entry_points_exist() -> None:
    """Si `messaging.py` cessait d'exporter ses points d'entree, la garde
    ci-dessus resterait verte tout en ne protegeant plus rien."""
    from apps.whatsapp.services import messaging

    assert hasattr(messaging, "send_governed_template_message")
    assert hasattr(messaging, "queue_governed_template_message")
