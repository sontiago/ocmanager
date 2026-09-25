import sys
from pathlib import Path

import ocmanager
import ocmanager.models

PACKAGE_ROOT = Path(ocmanager.__file__).parent


def test_every_models_module_is_registered() -> None:
    expected = {
        "ocmanager." + ".".join(p.relative_to(PACKAGE_ROOT).with_suffix("").parts)
        for p in PACKAGE_ROOT.rglob("models.py")
        if p.parent != PACKAGE_ROOT
    }
    missing = sorted(m for m in expected if m not in sys.modules)
    assert missing == [], f"добавьте импорт в ocmanager/models.py: {missing}"
