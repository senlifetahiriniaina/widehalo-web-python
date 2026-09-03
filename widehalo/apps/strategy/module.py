from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="strategy",
    # "bi" : valeur courante d'un indicateur du dictionnaire gouverné
    # (`bi.services.public.get_metric_current_value`) — STR-1 (avancement
    # d'un résultat clé calculé, jamais déclaré) et STR-5 (écart budgétaire
    # calculé sur la même définition que le réel), cahier §13.3.
    # "analytics" : lecture directe de la définition d'un indicateur du
    # dictionnaire gouverné (`analytics.services.public.get_metric_
    # definition`) pour valider un `metric_code` a la creation d'un key
    # result et pour figer sa definition (libelle/formule/version) dans un
    # pack de revue — cote lecture seule, distinct de "bi" qui calcule la
    # valeur courante.
    # "simulation"/"forecast" : initialisation d'un budget depuis un
    # scénario de simulation ou une prévision publiée (STR-4), référence et
    # version de la source conservées.
    # "chat" : chatter des initiatives (écran « Initiatives et plans
    # d'action », réutilise le canal générique de la Phase 1).
    dependencies=(
        "core",
        "presence",
        "sales",
        "payroll",
        "accounting",
        "mrp",
        "bi",
        "analytics",
        "simulation",
        "forecast",
        "chat",
    ),
    verbose_name="Strategie et pilotage",
)
