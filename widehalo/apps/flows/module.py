from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="flows",
    # AUCUNE dependance metier, et c'est structurel (cahier Phase 4 §14 :
    # « l'executeur ne connait aucun tiers : il connait des operations et
    # des adaptateurs, ce qui rend le socle testable sans reseau »).
    #
    # Le hub ne doit rien savoir de `sales`, `accounting` ou `whatsapp` : il
    # transporte des ECHANGES dont la piece metier est designee par un
    # couple (type, identifiant) opaque, jamais par une cle etrangere. Le
    # jour ou `flows` importe un modele metier, le socle cesse d'etre un
    # socle et devient un neuvieme module couple aux huit autres — c'est
    # exactement ce que la decision structurante n°2 du cahier interdit
    # (« un connecteur est un adaptateur de protocole, jamais un module »).
    #
    # Le sens de la dependance est donc INVERSE de l'intuition : ce sont les
    # modules metier qui declareront `flows` quand ils emettront un
    # echange, jamais l'inverse.
    dependencies=("core",),
    verbose_name="Hub de flux",
)
