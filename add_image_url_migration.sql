-- Миграция для добавления поля image_url в таблицу articles
-- Выполнить этот скрипт для обновления существующей базы данных

ALTER TABLE articles ADD COLUMN IF NOT EXISTS image_url VARCHAR(1000);

-- Добавляем комментарий к полю
COMMENT ON COLUMN articles.image_url IS 'URL изображения статьи из RSS ленты';
