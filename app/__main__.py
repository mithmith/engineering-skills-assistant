import uvicorn

from app.config import settings

host = settings.host
port = settings.port
reload_opt = settings.reload

if __name__ == "__main__":
    # ``app.api:app``.  Using the old import path resulted in ``uvicorn``
    # ``python -m app`` boots the service as expected.
    uvicorn.run("app.api:app", host=host, port=port, reload=reload_opt)
