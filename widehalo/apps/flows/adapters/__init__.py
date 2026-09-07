"""Les adaptateurs livres par l'editeur — DU CODE, jamais de la donnee.

`FlwConnector` est la DECLARATION d'un connecteur, editable par le client ;
un module de ce repertoire est le CODE qui sait lui parler. La separation
n'est pas cosmetique : c'est elle qui permet au plafond de douze
(`settings.BUDGET_MAX_ADAPTERS`, verifie par
`tests/architecture/test_phase4_budgets.py`) de compter ce qui coute
REELLEMENT a entretenir. Un plafond qui compterait des lignes de base
dependrait de la production pour rendre un verdict d'architecture.

Un adaptateur ne s'enregistre jamais tout seul a l'import : il est declare
depuis `apps/flows/apps.py::ready()`, comme les rapports, les anomalies et
les commandes periodiques. Un module qui s'enregistrerait a l'import
rendrait le registre dependant de l'ordre des imports — et un `import`
oublie dans un test suffirait a changer le comportement de la vidange.
"""
