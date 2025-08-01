#!/bin/bash

# Скрипт для настройки базы данных PostgreSQL

echo "Настройка базы данных PostgreSQL для агрегатора новостей"
echo "=========================================================="

# Проверка установки PostgreSQL
if ! command -v psql &> /dev/null; then
    echo "PostgreSQL не установлен. Установите PostgreSQL сначала:"
    echo "На macOS: brew install postgresql"
    echo "На Ubuntu: sudo apt-get install postgresql postgresql-contrib"
    exit 1
fi

# Параметры по умолчанию
DB_NAME="news_aggregator"
DB_USER="news_app"
DB_PASSWORD="secure_password_123"
DB_HOST="localhost"
DB_PORT="5432"

# Запрос параметров у пользователя
read -p "Имя базы данных [$DB_NAME]: " input_db_name
DB_NAME=${input_db_name:-$DB_NAME}

read -p "Имя пользователя [$DB_USER]: " input_db_user
DB_USER=${input_db_user:-$DB_USER}

read -s -p "Пароль пользователя [$DB_PASSWORD]: " input_db_password
echo
DB_PASSWORD=${input_db_password:-$DB_PASSWORD}

read -p "Хост [$DB_HOST]: " input_db_host
DB_HOST=${input_db_host:-$DB_HOST}

read -p "Порт [$DB_PORT]: " input_db_port
DB_PORT=${input_db_port:-$DB_PORT}

echo
echo "Создание базы данных и пользователя..."

# Создание базы данных и пользователя
sudo -u postgres psql << EOF
CREATE DATABASE $DB_NAME;
CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
ALTER USER $DB_USER CREATEDB;
\q
EOF

if [ $? -eq 0 ]; then
    echo "База данных и пользователь созданы успешно!"
else
    echo "Ошибка при создании базы данных или пользователя"
    exit 1
fi

# Создание таблиц
echo "Создание таблиц..."
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f create_tables.sql

if [ $? -eq 0 ]; then
    echo "Таблицы созданы успешно!"
else
    echo "Ошибка при создании таблиц"
    exit 1
fi

# Обновление .env файла
echo "Обновление конфигурации..."
sed -i.bak "s|DATABASE_URL=.*|DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME|" .env

echo
echo "Настройка завершена!"
echo "Параметры подключения сохранены в файле .env"
echo "Для запуска приложения выполните:"
echo "  python app.py"
