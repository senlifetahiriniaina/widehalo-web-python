from apps.core.module import ModuleSpec

# **Deviation disclosed (FIN2)** : le plan enumere initialement les
# dependances de `financing` comme `core`/`accounting`/`sales`/`purchase`/
# `logistics` (section "Entites nouvelles"), mais son propre sous-
# sequencement FIN2 demande explicitement d'alimenter le scenario de
# prevision depuis `payroll.services.public.get_payroll_mass_projection`
# (projection masse salariale) en plus d'`accounting` — `payroll` est donc
# ajoutee ici, coherente avec l'usage reel (cf. `services/forecast.py`,
# verifie au chantier plutot que devine).
MODULE = ModuleSpec(
    name="financing",
    dependencies=("core", "accounting", "sales", "purchase", "logistics", "payroll"),
    verbose_name="Financement bancaire PME",
)
