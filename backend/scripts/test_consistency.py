"""Дубли, которых требует граница модулей, не расходятся."""

from ocmanager.nodes import files
from ocmanager.provisioning.pki import certs


def test_username_regex_is_the_same_in_nodes_and_provisioning() -> None:
    assert files.USERNAME_RE.pattern == certs.USERNAME_RE.pattern
