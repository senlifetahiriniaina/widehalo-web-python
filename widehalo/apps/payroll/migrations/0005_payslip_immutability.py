"""Bloc E, E9 (PAY-8) : verrou base de données sur `PayPayslip`/
`PayPayslipLine` publiés — même discipline « une garantie de service
seule est contournable, une garantie base ne l'est pas » que `acc_move`
(accounting.0003/0005), `stk_move` (stocks.0015), `qlt_recall_dossier`
(quality.0003). L'audit Phase 3 relevait explicitement ce trou : « à la
différence de `AccMove`, protégé par un trigger base de données », rien
ne garantissait l'immuabilité du bulletin publié contre un accès ORM/
admin/shell direct — seule l'absence d'endpoint de modification
protégeait jusqu'ici (`ensure_active_contract_for_recompute`,
`apps.payroll.services.periods`, un garde de SERVICE, jamais une
contrainte base de données).

« Publié » = `PayPayslip.state IN ('approved', 'paid')` — analyse du
code réel (aucune définition explicite n'existe dans le modèle ni dans
la doc) : `cancel()` n'a pour `source` que `[draft, computed,
to_approve]`, jamais `approved`/`paid` — une fois `approved`, la SEULE
transition FSM légale restante est `approved -> paid`
(`apps.payroll.services.periods._mark_payslip_paid`). C'est également
le moment où `validate_and_post_batch` (E6) fait passer la période à
`validee` (RG-PAY-10) — les deux notions coïncident dans le flux réel.

Différence structurelle avec `AccMove`/`invoice_state` (un statut MÉTIER
sur une colonne SÉPARÉE, toujours mutable après publication) : ici la
seule transition légitime après publication porte sur la MÊME colonne
`state` qui définit aussi la publication elle-même. Le champ `state`
n'est donc pas exclu de la protection comme le serait `invoice_state`
(ce qui laisserait n'importe quelle valeur passer) — il reste protégé,
avec une exception explicite et unique : `OLD.state='approved' AND
NEW.state='paid'`. Toute autre valeur de transition (y compris un
retour arrière, ou un saut direct `computed -> paid`) reste rejetée
alors même que le bulletin est déjà publié.

`move_id` (RG-PAY-8, écriture comptable) est renseigné par
`validate_and_post_batch` QUAND `payslip.state == 'computed'` — donc
AVANT la transition vers `approved` (`apps/payroll/services/
batches.py`, séquence vérifiée : `payslip.move_id = move_id` puis
`_submit_and_approve_payslip`) — cette écriture n'est jamais bloquée
par ce trigger (`OLD.state` n'est encore ni `approved` ni `paid` à ce
moment). Aucune écriture ultérieure de `move_id` n'existe dans le code
actuel : une fois publié, il reste protégé comme tout autre champ
financier.

Champs protégés une fois publié : `employee_id`, `contract_id`,
`period_id`, `batch_id`, `date_from`, `date_to`, `worked_days`,
`worked_hours`, `absence_days`, `overtime_hours`, `gross`,
`taxable_base`, `irsa`, `social_employee`, `social_employer`,
`net_to_pay`, `payment_method`, `payment_reference`, `move_id`,
`rectifies_id`, `reference` (+ `state`, cf. ci-dessus). Volontairement
EXCLUS (même choix que tous les précédents) : les champs de suivi
communs `BaseModel` (`is_active`/`archived_at`/`created_by`/
`updated_by`/`updated_at`) — un `soft_delete()` reste possible sur un
bulletin publié. DELETE toujours bloqué une fois publié.

`PayPayslipLine` : protégée par un second trigger, même patron exact
que `acc_move_line` (sous-requête sur l'état du bulletin PARENT via
`payslip_id`) — ferme le trou concret identifié à la recherche :
`apps.payroll.services.payslip.compute_payslip` fait un `payslip.lines.
all().delete()` PUIS recrée les lignes, SANS jamais vérifier lui-même
`payslip.state`/`period.state` (seul l'appelant, via `ensure_active_
contract_for_recompute`, empêche ce chemin en pratique) — ce trigger
est le filet de sécurité base de données qui manquait précisément là.
Aucun flux légitime actuel n'appelle `compute_payslip` sur un bulletin
`approved`/`paid` : ce verrou ne casse donc aucun service existant, il
ferme une porte qui n'était ouverte que par accident/contournement."""

from django.db import migrations

PAYSLIP_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION pay_payslip_reject_mutation_if_published()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.state IN ('approved', 'paid') THEN
            RAISE EXCEPTION
                'pay_payslip publie est immuable (id=%) : '
                'suppression interdite (PAY-8)', OLD.id;
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.state NOT IN ('approved', 'paid') THEN
        RETURN NEW;
    END IF;

    IF NEW.state IS DISTINCT FROM OLD.state
        AND NOT (OLD.state = 'approved' AND NEW.state = 'paid')
    THEN
        RAISE EXCEPTION
            'pay_payslip publie est immuable (id=%) : seule la '
            'transition approved->paid reste autorisee (PAY-8)', OLD.id;
    END IF;

    IF NEW.employee_id IS DISTINCT FROM OLD.employee_id OR
        NEW.contract_id IS DISTINCT FROM OLD.contract_id OR
        NEW.period_id IS DISTINCT FROM OLD.period_id OR
        NEW.batch_id IS DISTINCT FROM OLD.batch_id OR
        NEW.date_from IS DISTINCT FROM OLD.date_from OR
        NEW.date_to IS DISTINCT FROM OLD.date_to OR
        NEW.worked_days IS DISTINCT FROM OLD.worked_days OR
        NEW.worked_hours IS DISTINCT FROM OLD.worked_hours OR
        NEW.absence_days IS DISTINCT FROM OLD.absence_days OR
        NEW.overtime_hours IS DISTINCT FROM OLD.overtime_hours OR
        NEW.gross IS DISTINCT FROM OLD.gross OR
        NEW.taxable_base IS DISTINCT FROM OLD.taxable_base OR
        NEW.irsa IS DISTINCT FROM OLD.irsa OR
        NEW.social_employee IS DISTINCT FROM OLD.social_employee OR
        NEW.social_employer IS DISTINCT FROM OLD.social_employer OR
        NEW.net_to_pay IS DISTINCT FROM OLD.net_to_pay OR
        NEW.payment_method IS DISTINCT FROM OLD.payment_method OR
        NEW.payment_reference IS DISTINCT FROM OLD.payment_reference OR
        NEW.move_id IS DISTINCT FROM OLD.move_id OR
        NEW.rectifies_id IS DISTINCT FROM OLD.rectifies_id OR
        NEW.reference IS DISTINCT FROM OLD.reference
    THEN
        RAISE EXCEPTION
            'pay_payslip publie est immuable sur ses champs metier '
            '(id=%) : seule une regularisation (nouveau bulletin) '
            'peut corriger (PAY-8/PAY-9)', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

PAYSLIP_LINE_IMMUTABLE_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION pay_payslip_line_reject_mutation_if_published()
RETURNS TRIGGER AS $$
DECLARE
    parent_state text;
BEGIN
    SELECT state INTO parent_state FROM pay_payslip WHERE id = OLD.payslip_id;

    IF TG_OP = 'DELETE' THEN
        IF parent_state IN ('approved', 'paid') THEN
            RAISE EXCEPTION
                'ligne d''un pay_payslip publie est immuable '
                '(payslip_id=%) : suppression interdite (PAY-8)',
                OLD.payslip_id;
        END IF;
        RETURN OLD;
    END IF;

    IF parent_state IN ('approved', 'paid') THEN
        RAISE EXCEPTION
            'ligne d''un pay_payslip publie est immuable '
            '(payslip_id=%) : modification interdite (PAY-8)',
            OLD.payslip_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

PAYSLIP_IMMUTABLE_TRIGGER_SQL = """
CREATE TRIGGER pay_payslip_immutable_when_published
BEFORE UPDATE OR DELETE ON pay_payslip
FOR EACH ROW EXECUTE FUNCTION pay_payslip_reject_mutation_if_published();
"""

PAYSLIP_LINE_IMMUTABLE_TRIGGER_SQL = """
CREATE TRIGGER pay_payslip_line_immutable_when_published
BEFORE UPDATE OR DELETE ON pay_payslip_line
FOR EACH ROW EXECUTE FUNCTION pay_payslip_line_reject_mutation_if_published();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0004_paybatch_anomaly_acknowledgments"),
    ]

    operations = [
        migrations.RunSQL(
            sql=PAYSLIP_IMMUTABLE_FUNCTION_SQL,
            reverse_sql=(
                "DROP FUNCTION IF EXISTS pay_payslip_reject_mutation_if_published() CASCADE"
            ),
        ),
        migrations.RunSQL(
            sql=PAYSLIP_LINE_IMMUTABLE_FUNCTION_SQL,
            reverse_sql=(
                "DROP FUNCTION IF EXISTS pay_payslip_line_reject_mutation_if_published() CASCADE"
            ),
        ),
        migrations.RunSQL(
            sql=PAYSLIP_IMMUTABLE_TRIGGER_SQL,
            reverse_sql=(
                "DROP TRIGGER IF EXISTS pay_payslip_immutable_when_published ON pay_payslip"
            ),
        ),
        migrations.RunSQL(
            sql=PAYSLIP_LINE_IMMUTABLE_TRIGGER_SQL,
            reverse_sql=(
                "DROP TRIGGER IF EXISTS pay_payslip_line_immutable_when_published "
                "ON pay_payslip_line"
            ),
        ),
    ]
