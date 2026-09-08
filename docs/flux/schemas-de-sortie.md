# Schémas de sortie — ce qu'un module accepte de laisser partir

*Phase 4, axes A1 et A2, §9.2. Livré au lot T0.*

## Le problème que ce registre ferme

Le hub de flux savait, depuis le sprint S5, refuser une correspondance de
champs incomplète **au regard du schéma du tiers** (FLX-6). Il ne savait
rien du nôtre : `save_mapping` confrontait `field_map` à `target_schema`,
c'est-à-dire à ce que le tiers déclare attendre, et jamais à ce que nous
acceptons d'émettre.

Conséquence concrète : une correspondance pouvait désigner
`lines[].margin_pct` en source. Elle était acceptée, enregistrée, et la
marge partait chez le tiers au premier échange. Le §9.2 du cahier
l'interdit mot pour mot — « Champs internes — marge, coût de revient,
commentaires de gestion — exclus par défaut de toute correspondance » —
mais un interdit sans schéma source n'est qu'une phrase.

## Où ça vit

| Fichier | Rôle |
|---|---|
| `apps/core/services/outbound_schemas.py` | Le registre, les six catégories du §9.2, la validation d'un chemin source, l'élagage de la projection. |
| `apps/<module>/services/flow_schema_registration.py` | Ce que CE module déclare. Appelé depuis `apps.py::ready()`. |
| `apps/flows/services/mapping.py` | `save_mapping` refuse un chemin source non déclaré, interdit, ou non exigé par l'opération. |
| `apps/flows/services/triggers.py` | `save_trigger` refuse un filtre sur un champ non déclaré filtrable (axe A1). |
| `tests/architecture/test_outbound_field_governance.py` | La garde d'intégration continue que le §9.2 exige nommément. |

## Les quatre règles du §9.2, et ce que le code en fait

- **Pièce commerciale complète** — « marge, coût de revient, commentaires
  de gestion exclus par défaut de toute correspondance ». Ces champs sont
  **déclarés interdits**, avec motif écrit, sur `sales.SalesOrder` et
  `sales.SalesQuotation`.
- **Identité et coordonnées de client** — « minimisation obligatoire :
  seuls les champs exigés par l'opération partent ». Chaque champ
  personnel de `crm.CrmLead` déclare les opérations (OP1–OP8) qui
  l'exigent. Un connecteur fiscal (OP4) ne peut pas correspondre le
  téléphone du client ; un connecteur d'encaissement (OP5) le peut.
- **Montant et référence de règlement** — « aucun numéro de compte complet
  dans une trace ou une charge utile archivée ». `lines[].account_code` et
  `bank_account_number` sont déclarés interdits sur `accounting.AccMove` ;
  seule la classe PCG (`lines[].account_class`) sort.
- **Rémunération et données de paie** — « interdiction absolue […]
  vérifiée en intégration continue ». Aucun document dont le code commence
  par `payroll.` ou `hr.` ne peut être enregistré ; une garde le vérifie.

## Pourquoi déclarer un interdit plutôt que l'omettre

Un champ absent du registre est déjà refusé — c'est la règle de fermeture.
Nommer en plus `lines[].margin_pct` comme interdit paraît redondant. Ça ne
l'est pas :

1. **Le message.** « champ non déclaré » et « marge : champ interne, §9.2 »
   n'apprennent pas la même chose à qui configure la liaison.
2. **La garde.** Un interdit qu'on n'a pas nommé ne se teste pas. Le jour
   où quelqu'un ajoute `margin_pct` aux champs émis, seule une assertion
   qui NOMME ce champ s'y oppose.

## La double barrière

Le module déclare ce qui peut sortir **et** construit la projection
(`builder`). Si seule la déclaration protégeait, un `builder` distrait
suffirait à tout défaire. `project_document` **élague** donc la projection
aux seuls chemins déclarés émis, et le test
`test_pruning_removes_a_forbidden_field_even_when_the_builder_emits_it`
donne au registre un `builder` qui produit délibérément la marge, pour
vérifier qu'elle ne sort pas.

## Déclarer un nouveau module

Un module dont le schéma de sortie n'est pas déclaré ne peut recevoir
**aucune** correspondance : `save_mapping` refuse en bloc. C'est
deny-by-default, et c'est voulu — une correspondance qu'on ne sait pas
confronter à notre propre schéma est exactement celle qui laisse fuir.

Pour en déclarer un :

1. Créer `apps/<module>/services/flow_schema_registration.py` sur le
   patron des trois existants.
2. Un `OutboundDocument` par pièce liable, dont le `code` vaut
   `app_label.NomDeModele` — exactement ce que `workflow.transitioned`
   porte sous la clef `model`.
3. Un `OutboundField` par chemin émis, avec sa catégorie §9.2 ; un
   `OutboundField(..., forbidden_because="…")` (motif d'au moins
   40 caractères) pour chaque champ que le §9.2 nomme.
4. `filterable=True` sur les champs qu'un filtre de portée (axe A1) a le
   droit de nommer — un champ interdit ne peut jamais être filtrable, car
   filtrer sur lui le divulgue par déduction.
5. Un `builder` qui projette la pièce en dictionnaire, en lisant par les
   gestionnaires filtrés (jamais `all_objects` : la RLS est ce qui empêche
   la pièce d'une autre société de partir).
6. Appeler `register_outbound_schemas()` depuis `apps.py::ready()`.

## Ce qui n'est pas encore déclaré, et ce que ça implique

Seuls `accounting`, `crm` et `sales` sont déclarés — les trois modules du
périmètre de la vague. Les quinze autres ne peuvent donc pas recevoir de
correspondance tant qu'ils ne l'auront pas fait. Ce n'est pas une
régression : `save_mapping` n'avait aucun appelant de production avant ce
lot.

## L'axe A1, et ce qu'il a coûté à l'ancien format de condition

Le cahier : « Portée — quels objets partent : filtres sur des champs
déclarés du modèle, **jamais une expression libre**. Un filtre non déclaré
est refusé à l'enregistrement. »

`FlwTrigger.condition` portait une chaîne évaluée par `safe_eval` sur la
charge de l'événement, et rien ne la validait à l'enregistrement. Elle
porte désormais :

```json
{"filters": [{"field": "state", "op": "eq", "value": "confirmed"}]}
```

où `field` doit être un champ **déclaré filtrable** de la pièce déclarée
par `FlwTrigger.document_type`, et `op` appartient au jeu fermé de huit
opérateurs (`eq`, `ne`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`).

**Aucune migration ne convertit les anciennes conditions.** Deviner
l'intention de l'auteur d'une expression et se tromper *élargirait* la
portée d'un déclencheur — donc ferait sortir des pièces que personne n'a
décidé d'envoyer. Une condition portant l'ancienne clef `expression` cesse
simplement de déclencher : ne rien envoyer est le seul sens dans lequel
une erreur d'interprétation est rattrapable.
