"""Реестр ORM-моделей для Alembic и тестов.

Импорт модуля регистрирует таблицу в Base.metadata. Каждая задача, которая
создаёт models.py, дописывает его сюда — иначе autogenerate не увидит таблицу.
test_models.py падает, если какой-то models.py здесь забыт.
"""

from ocmanager.admin import models as _admin  # noqa: F401
from ocmanager.audit import models as _audit  # noqa: F401
from ocmanager.billing import models as _billing  # noqa: F401
from ocmanager.core import models as _core  # noqa: F401
from ocmanager.core.db import Base
from ocmanager.events import models as _events  # noqa: F401
from ocmanager.nodes import models as _nodes  # noqa: F401
from ocmanager.notifications import models as _notifications  # noqa: F401
from ocmanager.provisioning import models as _provisioning  # noqa: F401
from ocmanager.subscriptions import models as _subscriptions  # noqa: F401

metadata = Base.metadata
