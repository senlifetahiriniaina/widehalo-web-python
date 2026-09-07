# BI-3 — ce qu'il faut du maître d'ouvrage, et pourquoi ça ne s'invente pas

*Document de demande. Une page, à remplir une fois, qui débloque un critère resté ❌
depuis l'audit.*

## Le critère, et la moitié qui manque

> **BI-3** — « Les rapports retenus à l'issue de la rationalisation sont reconstruits sur
> la couche sémantique et **rapprochés à l'ariary près** de leur version d'origine. »
> *(cahier Phase 2, §14)*

Ce critère contient deux travaux distincts, et un seul est bloqué.

| Moitié | État | Pourquoi |
|---|---|---|
| **Le catalogue interne** — domaine, description, propriétaire | ✅ **livré** | Ne dépendait d'aucune information extérieure. 63 rapports, chacun avec le rôle qui répond de sa définition et une phrase disant ce qu'il montre. `register_report` refuse désormais un enregistrement incomplet. |
| **La rationalisation du catalogue hérité** — conserver / fusionner / paramétrer / supprimer, puis rapprocher à l'ariary près | ❌ **bloqué** | Le catalogue des **91 rapports du système existant n'est pas dans le dépôt**, et rien ne permet de le déduire. |

**Pourquoi nous ne l'inventons pas.** Produire un arbitrage « conserver / fusionner /
supprimer » sur un inventaire qu'on n'a jamais vu serait un faux. Il aurait l'apparence
d'un livrable, passerait la recette, et le premier utilisateur qui chercherait son rapport
habituel découvrirait qu'il n'a jamais été examiné. Un rouge assumé coûte moins cher qu'un
vert fabriqué — c'est la même règle qui a fait dire, ailleurs dans ce projet, que le
routage WhatsApp n'était qu'un tenant par défaut.

Le cahier lui-même pose l'enjeu (hypothèse H6) : « mieux vaut porter 40 rapports justes que
91 rapports hétérogènes ». Le tri est donc l'essentiel du travail, et il ne peut être fait
que par ceux qui utilisent ces rapports.

## Ce qu'il faut, rapport par rapport

Un tableau, quatre-vingt-onze lignes. Le format importe peu — tableur, export du système
existant, capture — pourvu que ces cinq colonnes y soient.

| Colonne | Pourquoi elle est indispensable |
|---|---|
| **Nom du rapport** | Tel que les utilisateurs le nomment, pas son nom technique. C'est sous ce nom qu'ils réclameront son absence. |
| **Qui s'en sert, et à quelle fréquence** | Le seul critère de tri qui vaille. Un rapport édité une fois par an par une personne ne se traite pas comme un rapport quotidien de quatre services. |
| **Une sortie de référence** | **La pièce la plus importante du lot.** Un exemplaire réel, avec ses chiffres, et la période sur laquelle il porte. C'est contre elle que le rapprochement « à l'ariary près » se fait — sans elle, ce membre du critère est intestable, quel que soit le code écrit. |
| **La source des chiffres** | Requête, définition, ou à défaut la description de ce qui est compté. Deux rapports au même nom peuvent compter deux populations différentes : c'est précisément ce que la rationalisation doit trancher. |
| **À conserver ?** | Votre avis initial, même approximatif. Il n'engage à rien et fait gagner l'essentiel du temps de tri. |

**Si une seule colonne peut être fournie, que ce soit la sortie de référence.** Le reste se
reconstitue par entretien ; un chiffre d'origine, non.

## Ce qui se passe ensuite, et ce que ça coûte

1. **Tri** — chaque rapport reçoit une décision : conserver tel quel, fusionner avec un
   autre, remplacer par un rapport paramétrable, ou supprimer. Environ un jour pour
   quatre-vingt-onze lignes, une fois le tableau reçu.
2. **Rapprochement** — chaque rapport conservé est reconstruit puis comparé à sa sortie de
   référence, à l'ariary près. Le dépôt sait déjà faire ce contrôle : il l'exécute à chaque
   rafraîchissement de l'entrepôt, avec une tolérance de **un ariary**
   (`analytics/services/refresh.py`). Il n'y a donc pas de mécanisme à inventer, seulement
   des valeurs de référence à lui donner.
3. **Écart** — tout rapport dont le rapprochement échoue est signalé avec son écart plutôt
   que corrigé en silence. Un écart est souvent la découverte que les deux systèmes ne
   comptaient pas la même chose — c'est de l'information, pas un incident.

## Ce que le dépôt fait déjà, sans attendre ce tableau

À ne pas redemander : ces trois points sont livrés et vérifiés en intégration continue.

- **Le catalogue interne** (63 rapports, domaine, description, propriétaire), refusé à
  l'enregistrement s'il est incomplet.
- **Le budget de rapports** plafonné à 80 et contrôlé à chaque construction — il ne dit pas
  que le catalogue est cohérent, il dit qu'il ne grossit plus sans décision.
- **Le contrôle de rapprochement à l'ariary près** sur le chiffre d'affaires, exécuté à
  chaque rafraîchissement de l'entrepôt et affiché sur les écrans de pilotage.

## Le risque de ne pas trancher

Le cahier le nomme (risque P2-R2) : « porter le catalogue tel quel industrialise
l'incohérence ». Reconstruire quatre-vingt-onze rapports sans les trier revient à
reconduire, pour dix ans, les doublons et les définitions divergentes du système existant —
et à en faire porter l'entretien par une équipe d'une personne. **Ne pas choisir revient à
choisir de tout garder.**
