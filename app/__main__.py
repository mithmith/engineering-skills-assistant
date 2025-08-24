import uvicorn

from app.config import settings

# Позволяет запускать:  python -m app
# Хост/порт/reload берутся из Settings (и могут прийти из .env)
host = settings.host
port = settings.port
reload_opt = settings.reload

if __name__ == "__main__":
    # ``app.main`` no longer exists.  The FastAPI application instance is
    # created in ``app/api/__init__.py`` and can be imported as
    # ``app.api:app``.  Using the old import path resulted in ``uvicorn``
    # failing to start with ``Error loading ASGI app`` because the module did
    # not exist.  Point ``uvicorn`` to the correct location so running
    # ``python -m app`` boots the service as expected.
    uvicorn.run("app.api:app", host=host, port=port, reload=reload_opt)
