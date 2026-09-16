"""BON-22: creates a non-superuser operator account with `processing.trigger_run`.

Run once via the `migrate` role (it already owns the schema): e.g.
`docker compose ... run --rm migrate python app/manage.py create_operator <username>`.
The password is never written to any log, docs, or evidence file -- only shown once, here.
"""

import getpass
import secrets
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from processing.models import ManualRunRequest

MIN_PASSWORD_LENGTH = 12


class Command(BaseCommand):
    help = "Creates a non-superuser operator account with processing.trigger_run."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("username")
        parser.add_argument(
            "--generate-password",
            action="store_true",
            help="Generate and print a random password instead of an interactive prompt.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        user_model = get_user_model()
        username = options["username"]
        if user_model.objects.filter(username=username).exists():
            raise CommandError(f"User {username!r} already exists")
        if options["generate_password"]:
            password = secrets.token_urlsafe(18)
        else:
            password = getpass.getpass("Operator password: ")
            if password != getpass.getpass("Confirm password: "):
                raise CommandError("Passwords did not match")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise CommandError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
        with transaction.atomic():
            user = user_model.objects.create_user(
                username=username, password=password, is_staff=False, is_superuser=False
            )
            content_type = ContentType.objects.get_for_model(ManualRunRequest)
            permission = Permission.objects.get(content_type=content_type, codename="trigger_run")
            user.user_permissions.add(permission)
        if options["generate_password"]:
            self.stdout.write(
                self.style.SUCCESS(f"Created operator {username!r}; password: {password}")
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Created operator {username!r}"))
