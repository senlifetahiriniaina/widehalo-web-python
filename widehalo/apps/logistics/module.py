from apps.core.module import ModuleSpec

MODULE = ModuleSpec(
    name="logistics",
    # Dependances declarees des le squelette (LOG1) plutot qu'ajoutees au
    # fil des etapes comme les modules precedents : `stocks` existe deja
    # (construit expressement avant ce module, cf. plan — "plus aucun
    # stub structurel dans logistics") donc RG-LOG-5/RG-LOG-7 s'appuient
    # sur `stocks.services.public` des LOG3/LOG5, pas de dette differee.
    # "purchase"/"sales"/"accounting"/"catalog"/"partners" sont
    # consommees via `services.public` a partir de LOG2/LOG4/LOG5/LOG6 —
    # jamais un import de modele d'une de ces apps.
    dependencies=("core", "partners", "catalog", "purchase", "sales", "accounting", "stocks"),
    verbose_name="Logistique",
)
