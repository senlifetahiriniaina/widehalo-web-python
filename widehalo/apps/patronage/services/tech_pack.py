"""RG-PAT-7 : dossier technique PDF consolide, bilingue FR/EN (meme
patron que ACC-FAC/MRP-OF pour la generation PDF via WeasyPrint)."""

from __future__ import annotations

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models.user import User
from apps.core.services.documents import store_document
from apps.patronage.models import PatPattern, PatTechPack
from apps.patronage.services.grading import apply_grading


def _measurements_table_html(pattern: PatPattern) -> str:
    try:
        graded = apply_grading(pattern.size_chart)
    except Exception:  # noqa: BLE001 - grille non graduee, dossier reste generable sans mesures.
        graded = {}

    if not graded:
        return "<p>Aucune mesure gradee disponible.</p>"

    sizes = pattern.size_chart.sizes
    header = "".join(f"<th>{size}</th>" for size in sizes)
    rows = "".join(
        "<tr><td>{code}</td>{cells}</tr>".format(
            code=code,
            cells="".join(f"<td>{values.get(size, '')}</td>" for size in sizes),
        )
        for code, values in graded.items()
    )
    return f"""
    <table border="1" cellspacing="0" cellpadding="4">
      <thead><tr><th>Point de mesure / Measurement point</th>{header}</tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def _bom_table_html(pattern: PatPattern) -> str:
    rows = "".join(
        f"<tr><td>{c.material_variant_id}</td><td>{c.size}</td><td>{c.length_m} m</td></tr>"
        for c in pattern.consumptions.all()
    )
    if not rows:
        return "<p>Aucune consommation matiere calculee.</p>"
    return f"""
    <table border="1" cellspacing="0" cellpadding="4">
      <thead><tr><th>Matiere</th><th>Taille</th><th>Metrage</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def _pieces_html(pattern: PatPattern) -> str:
    rows = "".join(
        f"<tr><td>{p.code}</td><td>{p.name}</td><td>{p.qty_per_garment}</td><td>{p.notes}</td></tr>"
        for p in pattern.pieces.all()
    )
    return f"""
    <table border="1" cellspacing="0" cellpadding="4">
      <thead><tr><th>Piece</th><th>Nom / Name</th><th>Qte / Qty</th>
      <th>Instructions de montage / Assembly instructions</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def generate_tech_pack(pattern: PatPattern, *, actor: User | None = None) -> PatTechPack:
    from weasyprint import HTML

    html = f"""
    <html><head><meta charset="utf-8"></head><body>
      <h1>Dossier technique / Tech pack — {pattern.code} v{pattern.version}</h1>
      <p>{pattern.name}</p>
      <h2>Tableau de mesures gradees / Graded measurement chart</h2>
      {_measurements_table_html(pattern)}
      <h2>Nomenclature matiere / Bill of materials</h2>
      {_bom_table_html(pattern)}
      <h2>Pieces et instructions de montage / Pieces and assembly instructions</h2>
      {_pieces_html(pattern)}
      <h2>Controles qualite / Quality controls</h2>
      <p>Cf. gamme operatoire MRP rattachee — voir mrp_routing_step.quality_check.</p>
    </body></html>
    """
    pdf_bytes: bytes = HTML(string=html).write_pdf()

    uploaded_file = SimpleUploadedFile(
        f"{pattern.code}-v{pattern.version}-tech-pack.pdf",
        pdf_bytes,
        content_type="application/pdf",
    )
    document = store_document(
        tenant=pattern.tenant,
        uploaded_file=uploaded_file,
        uploaded_by=actor,
        content_object=pattern,
    )

    tech_pack = PatTechPack.objects.create(
        tenant=pattern.tenant, pattern=pattern, version=pattern.version, document=document
    )
    return tech_pack
