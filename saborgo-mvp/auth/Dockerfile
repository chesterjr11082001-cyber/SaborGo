FROM python:3.10-slim

WORKDIR /app

# Copiamos los archivos de la carpeta actual al contenedor
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ejecutamos uvicorn apuntando a main:app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3004"]