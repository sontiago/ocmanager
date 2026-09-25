from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from fastapi import Request


async def create_redis(url: str) -> ArqRedis:
    """Пул Redis на процесс. ArqRedis — это обычный клиент redis-py
    плюс enqueue_job, поэтому один пул закрывает и кэш, и очередь."""
    return await create_pool(RedisSettings.from_dsn(url))


def get_redis(request: Request) -> ArqRedis:
    redis: ArqRedis = request.app.state.redis
    return redis
