"""Дубли, которых требует граница модулей, не расходятся."""

from ocmanager.billing import plans
from ocmanager.nodes import files
from ocmanager.provisioning.pki import certs
from ocmanager.subscriptions import state


def test_username_regex_is_the_same_in_nodes_and_provisioning() -> None:
    assert files.USERNAME_RE.pattern == certs.USERNAME_RE.pattern


def test_day_limits_are_the_same_in_billing_and_subscriptions() -> None:
    assert plans.MAX_DURATION_DAYS == state.MAX_DAYS
