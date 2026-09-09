# Export de garantie de sortie — le format, et ce qu'il n'emporte pas

*Phase 4, bloc H, critère CON-6. Livré au lot T8.*

> **CON-6** — « L'export de garantie de sortie produit l'intégralité des
> liaisons, échanges, verdicts et rapprochements dans un format documenté et
> relisible sans WideHalo. »

## Ce que ce document ferme

L'archive existait depuis la portabilité des données, et les quatre familles
que CON-6 nomme y étaient **par construction** : `export_tenant_archive`
parcourt `iter_concrete_basemodel_subclasses()`, c'est-à-dire toute
sous-classe concrète de `BaseModel`. Personne n'avait rien écrit pour cela,
et personne ne l'avait vérifié — la situation exacte de BNK-5 au lot T6 :
une propriété vraie par accident, que rien ne tient.

Deux manques, donc, et un défaut :

- **La preuve** : `apps/core/tests/test_con6_export_garantie_de_sortie.py`
  exerce l'archive PRODUITE, relue avec `zipfile` et `json` seuls.
- **Le format documenté** : ce fichier.
- **Le défaut** : l'archive emportait les identifiants d'accès aux tiers,
  **en clair**. Voir « Ce que l'archive n'emporte pas » ci-dessous.

## Le format

Une archive est un fichier **ZIP**. Rien d'autre : ni base, ni binaire
propriétaire, ni index à reconstituer.

```
manifest.json
data/<app_label>.<modele>.json
data/<app_label>.<modele>.json
...
```

### `manifest.json`

```json
{
  "format_version": 1,
  "exported_at": "2026-09-09T14:40:24.139Z",
  "tenant_code": "ACME",
  "models": ["accounting.accmove", "flows.flwexchange", "..."]
}
```

`models` est l'index : il **nomme exactement** les fichiers présents sous
`data/`. Un manifeste qui annoncerait une table absente rendrait l'archive
illisible sans nous, et le test le refuse.

`format_version` est versionné dans un sens seulement : une archive
ancienne se relit dans une version récente du produit
(`MANIFEST_MIGRATIONS`), l'inverse n'est pas garanti — on restaure vers
l'avant, jamais en arrière.

### `data/<app_label>.<modele>.json`

Le format de sérialisation de Django : une **liste** d'objets, chacun avec
son modèle, sa clef primaire et ses champs.

```json
[
  {
    "model": "flows.flwexchange",
    "pk": "01a0869c-…",
    "fields": {
      "tenant": "01a0869c-…",
      "created_at": "2026-09-09T14:40:24.139Z",
      "link": "01a0869c-…",
      "direction": "sortant",
      "operation": "push_document",
      "state": "accepte",
      "document_type": "accounting.AccMove",
      "document_id": "01a0869c-…",
      "correlation_key": "accounting.AccMove:01a0869c-…"
    }
  }
]
```

Les références entre objets sont des **UUID**, résolvables à l'intérieur de
l'archive : `flows.flwexchange.link` désigne une ligne de
`data/flows.flwlink.json`. Aucun identifiant n'est global à l'extérieur.

## Où lire les quatre familles que CON-6 nomme

| Famille | Fichier | Ce qui la porte |
|---|---|---|
| **Liaisons** | `data/flows.flwlink.json` | La liaison, son connecteur, son état. Le catalogue est dans `data/flows.flwconnector.json`. |
| **Échanges** | `data/flows.flwexchange.json` | Une ligne par échange : sens, opération, état, empreinte, tentative, corrélation, pièce désignée par `document_type` + `document_id`. La charge utile transmise, quand elle n'a pas été purgée (FLX-5), est à part dans `data/flows.flwpayload.json`. |
| **Verdicts** | `data/accounting.accmove.json` | `fiscal_verdict_raw` porte le verdict du tiers **dans sa forme d'origine** (EFA-4), à côté de `fiscal_state`, qui est notre lecture de ce verdict. Les deux sont conservés : notre interprétation ne remplace jamais le document opposable. |
| **Rapprochements** | `data/accounting.accmoveline.json`, `data/accounting.accbankstatementline.json`, `data/accounting.accaggregatorpayout.json` | Le **lettrage** est `AccMoveLine.matching_number` — c'est lui qui dit quelles pièces un même versement solde (PAY-5). Le **rapprochement bancaire** est `AccBankStatementLine.matched_move_line` avec `state = "matched"`. |

## Ce que l'archive n'emporte pas — et le défaut que cela corrige

> **§13.2** — la table des identifiants d'accès à un tiers est « table à
> part, chiffrée, **jamais exportée**, jamais lue par le copilote ».

Elle l'était. Mesuré au lot T8, sur une société portant un seul
identifiant : `data/flows.flwcredential.json` contenait
`"secret": "<le clair>"`.

Deux causes empilées, et aucune n'est une erreur d'inattention :

1. L'export parcourt **toutes** les sous-classes de `BaseModel`.
   `FlwCredential` en est une. Le « table à part » du cahier protège du
   droit de lecture, pas de la boucle d'export.
2. `EncryptedCharField.from_db_value` **déchiffre à la lecture**. Les objets
   que le sérialiseur reçoit portent donc le clair. Le chiffrement au repos
   protège la BASE ; il ne protège pas une archive qui se télécharge depuis
   un écran d'administration.

**Ce qui est rédigé désormais** (`apps/core/services/secret_redaction.py`,
appelé par `export_tenant_archive`) : la ligne reste — le client doit savoir
**quels** raccordements il avait —, sa valeur part vide.

| Champ | Pourquoi |
|---|---|
| `flows.FlwCredential.secret` | Chiffré en base, en clair dans l'archive. C'est la fuite. |
| `logistics.LogServiceProvider.webhook_secret` | Idem, même mécanisme, autre module. |
| `flows.FlwApiKey.token_hash` | Une empreinte ne se retourne pas, mais elle se **vérifie** hors ligne autant de fois qu'on veut. Et elle est régénérée à la réimportation : la valeur exportée était morte avant d'être relue. |
| `projects.PrjGuestAccess.token_hash` | Idem. |
| `core.UserEmailChangeRequest.token_hash` | Idem — et ce jeton-là change l'identifiant de connexion d'un compte. |

**Une seule dérogation**, déclarée avec son motif dans
`secret_redaction.EXPORT_ALLOWLIST` : `core.User.password`. C'est un
condensé PBKDF2 produit par Django, jamais un secret de tiers, et c'est le
seul champ dont la rédaction casserait une **restauration** — un tenant
restauré dont plus personne ne peut se connecter n'est pas restauré.

**Le prix, écrit plutôt que découvert.** Une archive ne restaure plus les
identifiants de connecteur : après restauration, ils sont à ressaisir par
l'assistant d'enrôlement. C'est exactement ce que « jamais exportée » coûte,
et le cahier le demande sans réserve. L'alternative — un drapeau
`include_secrets` — aurait laissé la fuite vivre par défaut sous couvert de
l'avoir nommée.

## Où ça vit

| Fichier | Rôle |
|---|---|
| `apps/core/services/tenant_export.py` | L'export et l'import. `export_tenant_archive` produit l'archive décrite ici. |
| `apps/core/services/secret_redaction.py` | Ce que l'archive n'emporte pas, et l'unique dérogation avec son motif. |
| `apps/core/tests/test_con6_export_garantie_de_sortie.py` | La preuve, sur l'archive produite, relue avec `zipfile` + `json` seuls. |
| `tests/architecture/test_secrets_are_never_exported.py` | La garde d'intégration continue : la CLASSE de défaut, pas les six champs d'aujourd'hui. |

## Une leçon d'instrument, payée ici

La première version de la mesure cherchait le clair dans les **octets** de
l'archive :

```python
assert SECRET.encode() not in archive_bytes   # rend True — et c'est FAUX
```

Elle passait. Le secret était pourtant bien là, en clair, dans
`data/flows.flwcredential.json` — **le zip est compressé**, et le clair
n'apparaît nulle part tel quel dans ses octets. L'instrument déclarait le
système sain.

Toute vérification porte donc sur les entrées **décompressées**, jamais sur
l'archive brute.
