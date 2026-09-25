"""Реестр ORM-моделей для Alembic и тестов.

Импорт модуля регистрирует таблицу в Base.metadata. Каждая задача, которая
создаёт models.py, дописывает его сюда — иначе autogenerate не увидит таблицу.
test_models.py падает, если какой-то models.py здесь забыт.
"""

from ocmanager.core.db import Base

metadata = Base.metadata
