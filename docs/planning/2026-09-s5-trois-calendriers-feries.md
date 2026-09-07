# Trois calendriers de jours fériés, dont deux morts

*Constat établi en S5, en remontant le calendrier de `forecast` vers `core`.
Mesuré, pas estimé : chaque chiffre ci-dessous vient d'un `grep` sur le
dépôt entier, hors migrations et fichiers compilés.*

## Ce qu'on a trouvé

Le dépôt contient **trois** représentations des jours fériés. Une seule est
vivante.

| Source | Écrit par | Lu par | Testé |
|---|---|---|---|
| `core.Holiday` (ex-`forecast.ForHoliday`), table `core_holiday` | `manage.py load_mg_holidays`, écran `forecast` | `core.services.calendar`, `forecast.services.workload_forecast`, `flows.services.scheduling` (S5) | oui |
| `presence/services/calendar.py` — `RegulatoryParameter`, code `presence.public_holiday` | **personne** | **personne** | **aucun test** |
| `core.CountryDefaultsProfile.holidays` (JSONField) | **personne** | **personne** | **aucun test** |

Les deux dernières lignes ne sont pas des approximations : `set_public_holiday`,
`get_public_holiday`, `list_public_holidays`, `is_public_holiday` et
`PUBLIC_HOLIDAY_CODE` n'ont **aucune** occurrence hors du fichier qui les
définit ; `.holidays` n'en a aucune hors de la déclaration du champ.

## Ce que S5 a fait, et ce qu'il n'a pas fait

**Fait.** Le calendrier vivant est remonté de `apps.forecast` vers
`apps.core` (table renommée en place, aucune donnée déplacée). Il devient la
référence unique des DATES non ouvrées, lisible par tout module —
`flows` en avait besoin pour la planification (axe A4) et ne pouvait pas
atteindre `forecast` sans violer la règle de couplage n°1.

**Pas fait, et délibérément.** Les deux calendriers morts ne sont pas
supprimés. Le motif est différent pour chacun.

## `presence` — ce n'est pas un doublon, c'est une moitié manquante

`presence/services/calendar.py` porte une information que `core.Holiday`
n'a pas : `is_worked` et `pay_rate_pct`. « Le 26 juin est férié » et « un
férié travaillé se paie 150 % » sont deux faits distincts, et le second est
de la paie.

Le vrai défaut n'est donc pas la duplication, c'est que **le module de paie
n'a aucun calendrier renseigné** : rien n'écrit ces lignes, ni la commande
de chargement, ni un écran, ni la création d'une société. Un férié travaillé
est aujourd'hui payé au taux ordinaire, en silence.

**Proposition.** `presence` lit les DATES dans `core.Holiday` et ne conserve
en `RegulatoryParameter` que la MAJORATION, pour les seules dates qui en
portent une. Un chargement suffit alors à remplir les deux usages. Le
chiffrage est modeste — le service fait 65 lignes — mais le sujet est la
paie, il appelle donc une validation métier avant d'être touché.

## `CountryDefaultsProfile.holidays` — à supprimer

Ce champ n'a ni écrivain, ni lecteur, ni test, ni portée par société (il vit
sur le profil pays). Il ne peut pas devenir la référence : un calendrier
national par pays ne sait pas représenter une journée chômée décidée par une
entreprise, ni un scrutin, ni un deuil national — c'est précisément ce que
`core.Holiday` fait, par société.

Le garder est un piège : le prochain développeur qui cherchera « où sont les
jours fériés » trouvera deux réponses, dont une fausse. **Proposition :
suppression du champ**, par migration, une fois la décision confirmée. Aucun
code n'est à modifier — c'est la définition même d'un champ mort.

## Décision du commanditaire — les deux sont supprimées

*Tranché le 7 septembre 2026, en même temps que la règle de paie : un jour
férié travaillé vaut une prime de 100 %, soit 200 % du taux normal.*

**`presence/services/calendar.py` : supprimé.** La règle confirmée règle du
même coup le doute qui avait fait reporter : ce module annonçait 150 %, la
paie applique 2,00. Ce n'était donc pas une information complémentaire mais
une **valeur fausse**, que personne ne lisait — le pire des deux. La
majoration vit désormais à un seul endroit, celui où elle est effectivement
lue : `payroll.overtime_multipliers["ferie"]`.

**`CountryDefaultsProfile.holidays` : supprimé** par la migration
`core/0040`. Champ sans lecteur, sans écrivain, sans test, et porté par le
profil PAYS — donc structurellement incapable de représenter une journée
chômée décidée par une entreprise.

`core.Holiday` est la source unique.

## Ce que la même décision a révélé

En branchant la majoration, un défaut plus coûteux est apparu : **elle
n'arrivait jamais au bulletin.** `presence` n'exposait qu'un total d'heures
supplémentaires « toutes catégories confondues », et `payroll` imputait donc
tout à `h_sup_30` (1,30). Une heure de férié était payée **1,30 au lieu de
2,00** — 35 % de moins que le dû ; une heure de dimanche 7 % de moins ; une
heure de `h_sup_50` 13 % de moins. La catégorie était pourtant saisie,
validée et stockée : elle se perdait à la dernière marche.

Corrigé pour les cinq catégories, sur décision du commanditaire.

## Ce qui reste ouvert, et qui n'est pas mince

La règle dit « si le jour férié est **travaillé** ». Elle porte sur toutes
les heures de la journée, pas seulement sur des heures supplémentaires
déclarées.

Le dépôt ne sait pas l'exprimer : `payslip.py` calcule
`worked_days = reference_days − absences`, un forfait mensuel de jours sans
valorisation par jour. Un salarié qui fait sa journée normale un 26 juin
n'a aucune heure supplémentaire à déclarer, et son bulletin est identique à
celui d'un 25 juin.

Livré : la majoration correcte pour les heures **déclarées** sur un férié —
tout ce que le modèle sait aujourd'hui exprimer. Non livré : la valorisation
par jour, qui suppose de reprendre le cœur du bulletin et une validation RH.
Chiffré séparément plutôt que glissé ici à moitié.
