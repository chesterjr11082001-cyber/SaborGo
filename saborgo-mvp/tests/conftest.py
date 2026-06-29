"""
Fixtures compartidas para todas las pruebas de integración de SaborGo.

Usa Testcontainers para crear una red Docker efímera (igual que la red
'saborgo-net' de docker-compose) y un PostgreSQL real con las mismas
credenciales que usa el proyecto en producción.
"""
import time
import pytest
import requests
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network


def wait_for_http(url: str, timeout: int = 40):
    """Espera hasta que un endpoint HTTP responda, o lanza TimeoutError."""
    start = time.time()
    last_error = None
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code < 500:
                return r
        except Exception as e:
            last_error = e
        time.sleep(1)
    raise TimeoutError(f"{url} no respondió en {timeout}s. Último error: {last_error}")


@pytest.fixture(scope="module")
def docker_network():
    """Red Docker compartida entre los contenedores de prueba."""
    with Network() as network:
        yield network


@pytest.fixture(scope="module")
def postgres_container(docker_network):
    """Levanta un PostgreSQL real, idéntico en credenciales al de producción."""
    container = (
        DockerContainer("postgres:15-alpine")
        .with_env("POSTGRES_USER", "saborgo_user")
        .with_env("POSTGRES_PASSWORD", "saborgo_password")
        .with_env("POSTGRES_DB", "saborgo_db")
        .with_network(docker_network)
        .with_network_aliases("db")
        .with_exposed_ports(5432)
    )
    with container as pg:
        time.sleep(5)  # margen para que Postgres acepte conexiones
        yield pg
