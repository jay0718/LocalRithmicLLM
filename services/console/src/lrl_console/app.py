"""HTTP API for firms and stored Rithmic connections."""

import hmac

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, SecretStr

from .crypto import PasswordCipher
from .settings import Settings
from .store import Connection, DuplicateConnection, Store
from .systems import FetchSystems, SystemCatalog, SystemsUnavailable, fetch_rithmic_systems, is_test_system

_bearer = HTTPBearer(auto_error=False)


class ConnectionCreate(BaseModel):
    system_name: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=200)
    password: SecretStr = Field(min_length=1)


class ConnectionUpdate(BaseModel):
    system_name: str | None = Field(default=None, min_length=1, max_length=100)
    username: str | None = Field(default=None, min_length=1, max_length=200)
    password: SecretStr | None = None


class ConnectionOut(BaseModel):
    id: int
    system_name: str
    username: str
    status: str
    last_checked_at: float | None
    created_at: float


class SystemOut(BaseModel):
    name: str
    is_test: bool


class SystemsOut(BaseModel):
    systems: list[SystemOut]
    cached: bool
    fetched_at: float


def _out(connection: Connection) -> ConnectionOut:
    return ConnectionOut(**connection.__dict__)


def create_app(settings: Settings, fetch_systems: FetchSystems | None = None) -> FastAPI:
    store = Store(settings.db_path)
    cipher = PasswordCipher(settings.secret_key)
    catalog = SystemCatalog(
        fetch_systems or (lambda: fetch_rithmic_systems(settings.systems_uri)), store, settings.systems_ttl_seconds
    )

    def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:  # noqa: B008
        if not settings.admin_token:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Admin token is not configured")
        supplied = credentials.credentials if credentials else ""
        if not hmac.compare_digest(supplied.encode(), settings.admin_token.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid admin token")

    app = FastAPI(title="LocalRithmicLLM Console")
    router = APIRouter(dependencies=[Depends(require_admin)])

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        # FastAPI's default response echoes the submitted body, including passwords.
        detail = [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in error.errors()]
        return JSONResponse(status_code=422, content={"detail": detail})

    @router.get("/systems")
    async def list_systems() -> SystemsOut:
        try:
            result = await catalog.get()
        except SystemsUnavailable:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The firm list is unavailable") from None
        systems = [SystemOut(name=name, is_test=is_test_system(name)) for name in result.names]
        return SystemsOut(systems=systems, cached=result.cached, fetched_at=result.fetched_at)

    @router.get("/connections")
    def list_connections() -> list[ConnectionOut]:
        return [_out(connection) for connection in store.all()]

    @router.post("/connections", status_code=status.HTTP_201_CREATED)
    def create_connection(body: ConnectionCreate) -> ConnectionOut:
        ciphertext = cipher.encrypt(body.password.get_secret_value())
        try:
            return _out(store.create(body.system_name, body.username, ciphertext))
        except DuplicateConnection:
            raise HTTPException(status.HTTP_409_CONFLICT, "That connection already exists") from None

    @router.get("/connections/{connection_id}")
    def get_connection(connection_id: int) -> ConnectionOut:
        connection = store.get(connection_id)
        if connection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
        return _out(connection)

    @router.put("/connections/{connection_id}")
    def update_connection(connection_id: int, body: ConnectionUpdate) -> ConnectionOut:
        password = body.password.get_secret_value() if body.password else ""
        ciphertext = cipher.encrypt(password) if password else None
        try:
            connection = store.update(connection_id, body.system_name, body.username, ciphertext)
        except DuplicateConnection:
            raise HTTPException(status.HTTP_409_CONFLICT, "That connection already exists") from None
        if connection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
        return _out(connection)

    @router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_connection(connection_id: int) -> Response:
        if not store.delete(connection_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    app.include_router(router)
    return app
