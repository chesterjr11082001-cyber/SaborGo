"""
Pruebas de integración del microservicio AUTH.

Levanta PostgreSQL + la imagen Docker real (saborgo-auth:v1) en contenedores
efímeros, y valida el flujo completo de registro y login contra servicios
reales — no mocks.
"""
import uuid
import pytest
import requests
from testcontainers.core.container import DockerContainer

from .conftest import wait_for_http


@pytest.fixture(scope="module")
def auth_service(docker_network, postgres_container):
    container = (
        DockerContainer("saborgo-auth:v1")
        .with_env(
            "DATABASE_URL",
            "postgresql://saborgo_user:saborgo_password@db:5432/saborgo_db",
        )
        .with_network(docker_network)
        .with_network_aliases("auth")
        .with_exposed_ports(3004)
    )
    with container as svc:
        port = svc.get_exposed_port(3004)
        host = svc.get_container_host_ip()
        base_url = f"http://{host}:{port}"
        wait_for_http(f"{base_url}/docs", timeout=40)
        yield base_url


def test_registro_de_usuario_nuevo(auth_service):
    username = f"test_{uuid.uuid4().hex[:8]}"
    resp = requests.post(
        f"{auth_service}/registro",
        json={"username": username, "password": "Clave123!"},
    )
    assert resp.status_code == 200
    assert "msg" in resp.json()


def test_registro_de_usuario_duplicado_falla(auth_service):
    username = f"dup_{uuid.uuid4().hex[:8]}"
    payload = {"username": username, "password": "Clave123!"}

    primero = requests.post(f"{auth_service}/registro", json=payload)
    segundo = requests.post(f"{auth_service}/registro", json=payload)

    assert primero.status_code == 200
    assert segundo.status_code == 400
    assert "ya existe" in segundo.json()["detail"]


def test_login_exitoso_devuelve_jwt(auth_service):
    username = f"login_{uuid.uuid4().hex[:8]}"
    password = "Clave123!"
    requests.post(
        f"{auth_service}/registro",
        json={"username": username, "password": password},
    )

    resp = requests.post(
        f"{auth_service}/login",
        json={"username": username, "password": password},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 20


def test_login_con_password_incorrecta_falla(auth_service):
    username = f"badpass_{uuid.uuid4().hex[:8]}"
    requests.post(
        f"{auth_service}/registro",
        json={"username": username, "password": "Correcta123"},
    )

    resp = requests.post(
        f"{auth_service}/login",
        json={"username": username, "password": "Incorrecta"},
    )

    assert resp.status_code == 401
