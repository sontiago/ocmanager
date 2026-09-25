from importlib.metadata import version

import ocmanager


def test_version_matches_distribution_metadata() -> None:
    assert ocmanager.__version__ == version("ocmanager")
