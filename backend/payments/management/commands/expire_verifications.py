from django.core.management.base import BaseCommand

from payments.workflow import expire_stale


class Command(BaseCommand):
    help = 'Cancels payments whose fraud-verification window has passed (run periodically, e.g. from cron).'

    def handle(self, *args, **options):
        self.stdout.write(f'Closed {expire_stale()} expired verification(s).')
