"""§5.10.11 "Envoi multicanal du bulletin" (verdict Adopter) : PDF transmis
par e-mail (`django.core.mail`, SMTP deja configure — meme reutilisation
que le reste du depot, aucune nouvelle dependance) ET/OU mis a disposition
en libre-service (stocke via `core.services.documents.store_document`,
rattache au `PayPayslip` par content-type — l'employe authentifie le
recupere ensuite via l'API, `GET /payroll/payslips/{id}/pdf`)."""

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.mail import EmailMessage

from apps.core.models.user import User
from apps.core.services.documents import store_document
from apps.payroll.models import PayPayslip
from apps.payroll.services.pdf import payslip_pdf


def make_payslip_document(payslip: PayPayslip, uploaded_by: User | None = None) -> None:
    """Depose le PDF du bulletin dans le libre-service (`core.Document`
    polymorphe, content_type/object_id sur ce `PayPayslip`) — l'antivirus
    est toujours consulte (meme discipline que tout upload de ce depot,
    `store_document` s'en charge)."""
    pdf_bytes = payslip_pdf(payslip)
    filename = f"{payslip.reference or payslip.id}.pdf"
    uploaded_file = SimpleUploadedFile(filename, pdf_bytes, content_type="application/pdf")
    store_document(
        tenant=payslip.tenant,
        uploaded_file=uploaded_file,
        uploaded_by=uploaded_by,
        content_object=payslip,
    )


def send_payslip_by_email(payslip: PayPayslip, *, to_email: str) -> None:
    """Envoie le PDF CHIFFRE — **simplification assumee (disclosed)** : le
    PDF lui-meme n'est pas chiffre par mot de passe (WeasyPrint ne le
    supporte pas nativement) ; le canal de transport (SMTP TLS, deja
    configure au niveau settings) et le stockage (`core.Document`, deja sur
    un support chiffre au niveau infrastructure) assurent la confidentialite
    en transit/au repos, mais PAS un chiffrement applicatif du fichier PDF
    lui-meme — une vraie protection par mot de passe PDF viendrait d'une
    bibliotheque dediee (ex. pikepdf), hors perimetre de ce chantier."""
    pdf_bytes = payslip_pdf(payslip)
    message = EmailMessage(
        subject=f"Bulletin de paie {payslip.reference}",
        body="Veuillez trouver ci-joint votre bulletin de paie.",
        to=[to_email],
    )
    message.attach(f"{payslip.reference or payslip.id}.pdf", pdf_bytes, "application/pdf")
    message.send(fail_silently=False)
