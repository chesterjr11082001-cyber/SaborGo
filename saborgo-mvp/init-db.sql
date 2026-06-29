CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS platos (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    precio FLOAT NOT NULL,
    categoria VARCHAR(50) NOT NULL,
    imagen VARCHAR(255) NOT NULL
);

INSERT INTO platos (nombre, precio, categoria, imagen) VALUES 
('Hamburguesa Clásica', 15.50, 'Comida Rápida', '/img/hamburguesa.jpeg'),
('Salchipapa Power', 18.00, 'Comida Rápida', '/img/salchipapa.jpeg'),
('Pizza Americana', 35.00, 'Comida Rápida', '/img/pizza.jpeg'),
('Alitas BBQ (x12)', 28.00, 'Comida Rápida', '/img/alitasbbq.jpeg'),
('Club Sandwich', 22.00, 'Comida Rápida', '/img/clubsandwich.jpg'),
('Tacos de Pollo', 20.00, 'Comida Rápida', '/img/tacosdepollo.jpeg'),
('Ceviche de Pescado', 32.00, 'Platos Criollos', '/img/ceviche.jpeg'),
('Lomo Saltado', 30.00, 'Platos Criollos', '/img/lomosaltado.jpeg'),
('Aji de Gallina', 25.00, 'Platos Criollos', '/img/ajidegallina.jpeg'),
('Arroz con Pollo', 25.00, 'Platos Criollos', '/img/arrozconpollo.jpeg'),
('Seco con Frejoles', 28.00, 'Platos Criollos', '/img/secoconfrejoles.jpeg'),
('Pisco Sour', 25.00, 'Bebidas', '/img/piscosour.jpeg'),
('Inca Kola 500ml', 5.00, 'Bebidas', '/img/incakola.jpeg'),
('Chicha Morada', 8.00, 'Bebidas', '/img/chichamorada.jpeg'),
('Cerveza Cusqueña', 9.00, 'Bebidas', '/img/cerveza.jpeg'),
('Cafe Americano', 7.00, 'Bebidas', '/img/cafeamericano.jpeg'),
('Arroz con Leche', 10.00, 'Postres', '/img/arrozconleche.jpeg'),
('Mazamorra Morada', 10.00, 'Postres', '/img/mazamorra.jpeg'),
('Picarones', 12.00, 'Postres', '/img/picarones.jpeg'),
('Suspiro a la Limeña', 12.00, 'Postres', '/img/suspiro.jpeg'),
('Torta de Chocolate', 12.00, 'Postres', '/img/tortachocolate.jpeg'),
('Crema Volteada', 10.00, 'Postres', '/img/cremavolteada.jpeg');

CREATE TABLE IF NOT EXISTS ordenes (
    id SERIAL PRIMARY KEY,
    cliente VARCHAR(100) NOT NULL,
    direccion VARCHAR(255) NOT NULL,
    metodo_pago VARCHAR(50) NOT NULL,
    total FLOAT NOT NULL,
    estado VARCHAR(50) DEFAULT 'Pendiente',
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    calificacion INTEGER CHECK (calificacion >= 1 AND calificacion <= 5),
    lat_cliente FLOAT,
    lng_cliente FLOAT
);

CREATE TABLE IF NOT EXISTS repartidores (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    telefono VARCHAR(20) NOT NULL,
    disponible BOOLEAN DEFAULT TRUE
);

INSERT INTO repartidores (nombre, telefono, disponible) VALUES 
('Carlos Mendoza', '999111222', true),
('Luis Ramirez', '999333444', true),
('Ana Quispe', '999555666', true),
('Jorge Vargas', '999777888', true);


INSERT INTO users (username, password)
SELECT 'leonardo', '$2b$12$2vB3IgBgACkjnBm6AGO1Ku1Hh5tBflfBxknQnlYKZShTqS4cjpzEK'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'leonardo');