"""
Pruebas de integración del microservicio CATALOGO.

Verifica que /menu responda correctamente contra una base de datos real
sembrada con datos de prueba, dentro de un contenedor efímero.
"""
import pytest
import requests
import psycopg2
from testcontainers.core.container import DockerContainer

from .conftest import wait_for_http


@pytest.fixture(scope="module")
def catalogo_service(docker_network, postgres_container):
    container = (
        DockerContainer("saborgo-catalogo:v1")
        .with_env(
            "DATABASE_URL",
            "postgresql://saborgo_user:saborgo_password@db:5432/saborgo_db",
        )
        .with_network(docker_network)
        .with_network_aliases("catalogo")
        .with_exposed_ports(3001)
    )
    with container as svc:
        port = svc.get_exposed_port(3001)
        host = svc.get_container_host_ip()
        base_url = f"http://{host}:{port}"
        wait_for_http(f"{base_url}/menu", timeout=40)
        yield base_url


def _conexion_postgres(postgres_container):
    pg_port = postgres_container.get_exposed_port(5432)
    pg_host = postgres_container.get_container_host_ip()
    return psycopg2.connect(
        host=pg_host, port=pg_port,
        user="saborgo_user", password="saborgo_password", dbname="saborgo_db",
    )


@pytest.fixture
def platos_sembrados(postgres_container):
    """Inserta 3 platos de prueba directamente en la BD del contenedor."""
    conn = _conexion_postgres(postgres_container)
    cur = conn.cursor()
    cur.execute("DELETE FROM platos;")
    cur.execute(
        """
        INSERT INTO platos (nombre, precio, categoria, imagen) VALUES
        ('Ceviche de Prueba', 32.0, 'Platos Criollos', '/img/ceviche.jpeg'),
        ('Inca Kola de Prueba', 5.0, 'Bebidas', '/img/incakola.jpeg'),
        ('Picarones de Prueba', 12.0, 'Postres', '/img/picarones.jpeg');
        """
    )
    conn.commit()
    cur.close()
    conn.close()
    yield


def test_menu_vacio_si_no_hay_platos(catalogo_service, postgres_container):
    conn = _conexion_postgres(postgres_container)
    cur = conn.cursor()
    cur.execute("DELETE FROM platos;")
    conn.commit()
    cur.close()
    conn.close()

    resp = requests.get(f"{catalogo_service}/menu")
    assert resp.status_code == 200
    assert resp.json() == []


def test_menu_devuelve_platos_sembrados(catalogo_service, platos_sembrados):
    resp = requests.get(f"{catalogo_service}/menu")
    assert resp.status_code == 200

    platos = resp.json()
    assert len(platos) == 3
    nombres = {p["nombre"] for p in platos}
    assert "Ceviche de Prueba" in nombres
    assert all("categoria" in p and "imagen" in p for p in platos)
