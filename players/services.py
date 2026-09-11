"""Import de joueurs en masse (§37, §59, §61)."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field


@dataclass
class ImportReport:
    created: list[str] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)


REQUIRED_COLUMNS = {"prenom", "nom"}


def import_players_from_csv(file_obj, *, created_by=None) -> ImportReport:
    from .models import Player

    report = ImportReport()
    text_stream = io.TextIOWrapper(file_obj, encoding="utf-8-sig")
    try:
        reader = csv.DictReader(text_stream)
        fieldnames = {(name or "").strip().lower() for name in (reader.fieldnames or [])}
        if not REQUIRED_COLUMNS.issubset(fieldnames):
            report.skipped.append((0, "Colonnes requises manquantes : prenom, nom."))
            return report

        for line_number, row in enumerate(reader, start=2):
            normalized = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            first_name = normalized.get("prenom")
            last_name = normalized.get("nom")
            if not first_name or not last_name:
                report.skipped.append((line_number, "Prénom ou nom manquant."))
                continue
            player = Player.objects.create(
                first_name=first_name,
                last_name=last_name,
                club=normalized.get("club", ""),
                country=normalized.get("pays", ""),
                created_by=created_by,
            )
            report.created.append(player.full_name)
    finally:
        # Détache le buffer sous-jacent pour ne pas fermer le fichier uploadé
        # géré par Django lorsque le TextIOWrapper est libéré.
        text_stream.detach()

    return report
