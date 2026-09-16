"""BON-22: login throttle, CSRF/permission boundaries and the manual-run HTTP contract from
`docs/bonus2_design.md`'s admission table."""

import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from processing.models import LoginFailure, ManualRunRequest, TriggerAdmission


def _user(
    username: str = "op", password: str = "correct horse battery", *, can_trigger: bool = False
) -> User:
    user: User = get_user_model().objects.create_user(username=username, password=password)
    if can_trigger:
        content_type = ContentType.objects.get_for_model(ManualRunRequest)
        permission = Permission.objects.get(content_type=content_type, codename="trigger_run")
        user.user_permissions.add(permission)
    return user


class LoginViewTests(TestCase):
    def test_correct_credentials_sign_in_and_redirect_to_monitoring(self) -> None:
        _user("op", "correct horse battery")

        response = self.client.post(
            reverse("operator-login"), {"username": "op", "password": "correct horse battery"}
        )

        # Not `assertRedirects`: it would follow into `/ops/`, whose snapshot refuses to run
        # inside the outer atomic block `TestCase` itself wraps every test in (`TransactionTestCase`
        # is what `test_monitoring.py` uses for that reason); checking the redirect target alone
        # is exactly what this test is about, so nothing here needs the target to render.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("monitoring"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_wrong_password_shows_a_generic_error_and_records_one_failure_per_fingerprint(
        self,
    ) -> None:
        _user("op", "correct horse battery")

        response = self.client.post(
            reverse("operator-login"), {"username": "op", "password": "wrong"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid username or password.")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(LoginFailure.objects.filter(fingerprint="user:op").count(), 1)
        self.assertEqual(LoginFailure.objects.count(), 2)  # + one IP fingerprint

    def test_an_unknown_username_gets_the_same_generic_error(self) -> None:
        response = self.client.post(
            reverse("operator-login"), {"username": "ghost", "password": "whatever12345"}
        )

        self.assertContains(response, "Invalid username or password.")
        self.assertEqual(LoginFailure.objects.filter(fingerprint="user:ghost").count(), 1)

    def test_the_sixth_attempt_within_the_window_is_throttled_even_with_the_right_password(
        self,
    ) -> None:
        _user("op", "correct horse battery")
        for _ in range(5):
            self.client.post(reverse("operator-login"), {"username": "op", "password": "wrong"})
        self.assertEqual(LoginFailure.objects.filter(fingerprint="user:op").count(), 5)

        response = self.client.post(
            reverse("operator-login"), {"username": "op", "password": "correct horse battery"}
        )

        self.assertContains(response, "Invalid username or password.")
        self.assertNotIn("_auth_user_id", self.client.session)
        # A throttled attempt performs no real credential check, so it must not itself add rows.
        self.assertEqual(LoginFailure.objects.filter(fingerprint="user:op").count(), 5)

    def test_an_inactive_account_cannot_sign_in(self) -> None:
        user = _user("op", "correct horse battery")
        user.is_active = False
        user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("operator-login"), {"username": "op", "password": "correct horse battery"}
        )

        self.assertContains(response, "Invalid username or password.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_get_is_allowed_and_renders_the_form(self) -> None:
        response = self.client.get(reverse("operator-login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in")


class LogoutViewTests(TestCase):
    def test_post_signs_out(self) -> None:
        _user("op", "correct horse battery")
        self.client.login(username="op", password="correct horse battery")

        response = self.client.post(reverse("operator-logout"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("monitoring"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_get_is_not_allowed(self) -> None:
        response = self.client.get(reverse("operator-logout"))
        self.assertEqual(response.status_code, 405)


class RunViewTests(TestCase):
    def setUp(self) -> None:
        TriggerAdmission.objects.get_or_create(resource="manual_trigger")

    def test_get_is_not_allowed(self) -> None:
        self.assertEqual(self.client.get(reverse("manual-run")).status_code, 405)

    def test_anonymous_post_is_rejected_with_json_403_and_no_side_effects(self) -> None:
        response = self.client.post(reverse("manual-run"), {"request_id": str(uuid.uuid4())})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "forbidden"})
        self.assertEqual(ManualRunRequest.objects.count(), 0)

    def test_authenticated_without_permission_is_rejected_with_json_403(self) -> None:
        _user("plain", "correct horse battery", can_trigger=False)
        self.client.login(username="plain", password="correct horse battery")

        response = self.client.post(reverse("manual-run"), {"request_id": str(uuid.uuid4())})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(ManualRunRequest.objects.count(), 0)

    def test_csrf_failure_is_json_403(self) -> None:
        _user("op", "correct horse battery", can_trigger=True)
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.login(username="op", password="correct horse battery")

        response = strict_client.post(reverse("manual-run"), {"request_id": str(uuid.uuid4())})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "forbidden"})

    def test_an_invalid_request_id_is_400(self) -> None:
        _user("op", "correct horse battery", can_trigger=True)
        self.client.login(username="op", password="correct horse battery")

        response = self.client.post(
            reverse("manual-run"), {"request_id": "not-a-uuid"}, HTTP_ACCEPT="application/json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid_request"})

    def test_a_fresh_accepted_request_returns_202_with_the_request_id(self) -> None:
        _user("op", "correct horse battery", can_trigger=True)
        self.client.login(username="op", password="correct horse battery")
        key = str(uuid.uuid4())

        response = self.client.post(
            reverse("manual-run"), {"request_id": key}, HTTP_ACCEPT="application/json"
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"request_id": key, "state": "queued"})
        self.assertEqual(ManualRunRequest.objects.get(request_id=key).state, "queued")

    def test_a_non_json_request_redirects_to_monitoring_with_the_request_id(self) -> None:
        _user("op", "correct horse battery", can_trigger=True)
        self.client.login(username="op", password="correct horse battery")
        key = str(uuid.uuid4())

        response = self.client.post(reverse("manual-run"), {"request_id": key})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('monitoring')}?request={key}")

    def test_a_replayed_key_returns_200_not_202(self) -> None:
        _user("op", "correct horse battery", can_trigger=True)
        self.client.login(username="op", password="correct horse battery")
        key = str(uuid.uuid4())
        self.client.post(reverse("manual-run"), {"request_id": key}, HTTP_ACCEPT="application/json")

        response = self.client.post(
            reverse("manual-run"), {"request_id": key}, HTTP_ACCEPT="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ManualRunRequest.objects.filter(request_id=key).count(), 1)

    @override_settings(OPS_MANUAL_RUN_ENABLED=False)
    def test_disabled_feature_is_404(self) -> None:
        _user("op", "correct horse battery", can_trigger=True)
        self.client.login(username="op", password="correct horse battery")

        response = self.client.post(reverse("manual-run"), {"request_id": str(uuid.uuid4())})

        self.assertEqual(response.status_code, 404)


class RunStatusViewTests(TestCase):
    def test_anonymous_is_403(self) -> None:
        response = self.client.get(reverse("manual-run-status", args=[uuid.uuid4()]))
        self.assertEqual(response.status_code, 403)

    def test_another_operators_request_is_not_found(self) -> None:
        owner = _user("owner", "correct horse battery", can_trigger=True)
        _user("other", "correct horse battery", can_trigger=True)
        request = ManualRunRequest.objects.create(
            request_id=uuid.uuid4(), operator=owner, created_at=timezone.now()
        )
        self.client.login(username="other", password="correct horse battery")

        response = self.client.get(reverse("manual-run-status", args=[request.request_id]))

        self.assertEqual(response.status_code, 404)

    def test_the_owning_operator_sees_its_state(self) -> None:
        owner = _user("owner", "correct horse battery", can_trigger=True)
        request = ManualRunRequest.objects.create(
            request_id=uuid.uuid4(), operator=owner, created_at=timezone.now()
        )
        self.client.login(username="owner", password="correct horse battery")

        response = self.client.get(reverse("manual-run-status", args=[request.request_id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "queued")
