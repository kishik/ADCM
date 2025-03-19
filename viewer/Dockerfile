# Используйте базовый образ Python
FROM python:3.11
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DOCKER_BUILDKIT=1

WORKDIR /app

RUN apt update && \
    apt install -y nodejs npm

# Команда для запуска скрипта при запуске контейнера
COPY creation_script.sh .
RUN bash creation_script.sh

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY . .

EXPOSE 8070
EXPOSE 3000
CMD python3 -m http.server 3000 & uvicorn main:app --host 0.0.0.0 --port 8070
