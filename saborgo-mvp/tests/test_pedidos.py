"""
Pruebas de integración del microservicio PEDIDOS.

Levanta PostgreSQL + Redis reales junto a la imagen de pedidos, validando
la creación de órdenes y las reglas de calificación. No se incluye un
Kafka real: el productor de pedidos falla en segundo plano sin bloquear
la respuesta HTTP, igual que ocurre en producción si Kafka aún no está
listo (ver bloque try/except con reintentos en pedidos/main.py).
"""
import pytest
import requests
from testcontainers.core.container import DockerContainer

from .conftest import wait_for_http


@pytest.fixture(scope="module")
def redis_container(docker_network):
    container = (
        DockerContainer("redis:7-alpine")
        .with_network(docker_network)
        .with_network_aliases("redis")
        .with_exposed_ports(6379)
    )
    with container as r:
        yield r


@pytest.fixture(scope="module")
def pedidos_service(docker_network, postgres_container, redis_container):
    container = (
        DockerContainer("saborgo-pedidos:v1")
        .with_env(
            "DATABASE_URL",
            "postgresql://saborgo_user:saborgo_password@db:5432/saborgo_db",
        )
        .with_env("REDIS_URL", "redis://redis:6379/0")
        .with_env("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
        .with_network(docker_network)
        .with_network_aliases("pedidos")
        .with_exposed_ports(3002)
    )
    with container as svc:
        port = svc.get_exposed_port(3002)
        host = svc.get_container_host_ip()
        base_url = f"http://{host}:{port}"
        wait_for_http(f"{base_url}/pedidos/recientes", timeout=40)
        yield base_url


def test_pedidos_recientes_responde_lista(pedidos_service):
    resp = requests.get(f"{pedidos_service}/pedidos/recientes")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_crear_pedido_exitoso(pedidos_service):
    payload = {
        "cliente": "Cliente de Prueba",
        "direccion": "Av. Test 123, Lima",
        "metodo_pago": "Yape",
        "total": 45.5,
        "lat_cliente": -12.0179,
        "lng_cliente": -77.0508,
    }
    resp = requests.post(f"{pedidos_service}/pedidos/crear", json=payload)
    assert resp.status_code == 200

    data = resp.json()
    assert data["estado"] == "Pendiente"
    assert "orden_id" in data


def test_calificar_pedido_no_aprobado_falla(pedidos_service):
    payload = {
        "cliente": "Cliente Calificación",
        "direccion": "Av. Test 456, Lima",
        "metodo_pago": "Tarjeta",
        "total": 20.0,
    }
    creado = requests.post(f"{pedidos_service}/pedidos/crear", json=payload)
    orden_id = creado.json()["orden_id"]

    resp = requests.post(
        f"{pedidos_service}/pedidos/{orden_id}/calificar",
        json={"estrellas": 5},
    )
    assert resp.status_code == 400


def test_calificar_con_estrellas_invalidas_falla(pedidos_service):
    payload = {
        "cliente": "Cliente Estrellas",
        "direccion": "Av. Test 789, Lima",
        "metodo_pago": "Yape",
        "total": 15.0,
    }
    creado = requests.post(f"{pedidos_service}/pedidos/crear", json=payload)
    orden_id = creado.json()["orden_id"]

    resp = requests.post(
        f"{pedidos_service}/pedidos/{orden_id}/calificar",
        json={"estrellas": 9},
    )
    assert resp.status_code == 400
