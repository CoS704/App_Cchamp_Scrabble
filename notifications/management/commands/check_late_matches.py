"""À exécuter périodiquement (cron / tâche planifiée) : notifie les joueurs
dont un match dépasse le seuil de retard configuré pour l'édition (§40)."""
from django.core.management.base import BaseCommand

from championships.models import Championship
from competition.services.match import late_matches_queryset
from core.enums import ChampionshipStatus, NotificationKind, NotificationPriority
from notifications.models import Notification
from notifications.services import championship_admin_user_ids


class Command(BaseCommand):
    help = "Crée une notification « match en retard » pour chaque joueur concerné, une fois par match."

    def handle(self, *args, **options):
        created = 0
        championships = Championship.objects.filter(status=ChampionshipStatus.IN_PROGRESS)
        for championship in championships:
            matches = late_matches_queryset(championship).select_related(
                "player1__player", "player2__player"
            )
            for match in matches:
                for participation in (match.player1, match.player2):
                    if not participation or not participation.player.user_id:
                        continue
                    already_notified = Notification.objects.filter(
                        recipient_id=participation.player.user_id,
                        kind=NotificationKind.MATCH_LATE,
                        data__match_id=match.id,
                    ).exists()
                    if already_notified:
                        continue
                    opponent = match.player2 if participation == match.player1 else match.player1
                    opponent_label = opponent.player if opponent else "un adversaire exempté"
                    Notification.objects.create(
                        recipient_id=participation.player.user_id,
                        championship=championship,
                        kind=NotificationKind.MATCH_LATE,
                        title="Match en retard",
                        body=(
                            f"Votre match contre {opponent_label} était prévu le "
                            f"{match.scheduled_date:%d/%m/%Y} et n'a pas encore de résultat."
                        ),
                        data={"match_id": match.id},
                        priority=NotificationPriority.HIGH,
                    )
                    created += 1

                p1 = match.player1.player if match.player1 else "Exempt"
                p2 = match.player2.player if match.player2 else "Exempt"
                link_url = f"/gestion/championnats/{championship.slug}/dashboard/"
                for admin_user_id in championship_admin_user_ids(championship):
                    already_notified_admin = Notification.objects.filter(
                        recipient_id=admin_user_id,
                        kind=NotificationKind.MATCH_LATE_ADMIN,
                        data__match_id=match.id,
                    ).exists()
                    if already_notified_admin:
                        continue
                    Notification.objects.create(
                        recipient_id=admin_user_id,
                        championship=championship,
                        kind=NotificationKind.MATCH_LATE_ADMIN,
                        title="Match en retard",
                        body=(
                            f"{p1} vs {p2} était prévu le {match.scheduled_date:%d/%m/%Y} "
                            "et n'a toujours pas de résultat — à relancer ou reprogrammer."
                        ),
                        link_url=link_url,
                        data={"match_id": match.id},
                        priority=NotificationPriority.NORMAL,
                    )
                    created += 1
        self.stdout.write(self.style.SUCCESS(f"{created} notification(s) créée(s)."))
