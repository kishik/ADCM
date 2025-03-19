#!/bin/bash

# Клонируем репозиторий в директорию 'xeokit-bim-viewer-app'
git clone 'https://github.com/kishik/xeokit-bim-viewer-app.git' 'xeokit-bim-viewer-app' || exit 1

# Переходим в директорию проекта
cd ./xeokit-bim-viewer-app || exit 1

# Устанавливаем зависимости
npm install || exit 1

# Собираем проект
npm run build || exit 1

echo "Скрипт выполнен успешно!"