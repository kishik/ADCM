# Используйте базовый образ Python
FROM python:3.11
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DOCKER_BUILDKIT=1

# Создайте рабочую директорию внутри контейнера
WORKDIR /app

# Скопируйте зависимости в контейнер
COPY requirements.txt .

# Установите зависимости
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Скопируйте ваш скрипт Python в контейнер
COPY creation_script.sh GESN_graph_creation.py create_group_graph.py 2022-02-07.xlsx solution.xls ./

# Команда для запуска скрипта при запуске контейнера
CMD ["bash", "creation_script.sh"]
