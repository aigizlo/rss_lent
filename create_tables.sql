-- Создание базы данных (выполнить от имени суперпользователя)
-- CREATE DATABASE news_aggregator;

-- Подключиться к базе данных news_aggregator
-- \c news_aggregator;

-- Создание таблицы для категорий новостей
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Создание таблицы для источников новостей
CREATE TABLE IF NOT EXISTS sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) UNIQUE NOT NULL,
    url VARCHAR(1000) NOT NULL,
    rss_url VARCHAR(1000) NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Создание таблицы для статей
CREATE TABLE IF NOT EXISTS articles (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    content TEXT,
    link VARCHAR(1000) UNIQUE NOT NULL,
    image_url VARCHAR(1000), -- URL изображения статьи
    published_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    category_id INTEGER REFERENCES categories(id),
    source_id INTEGER REFERENCES sources(id),
    is_active BOOLEAN DEFAULT TRUE,
    view_count INTEGER DEFAULT 0,
    guid VARCHAR(500) -- для уникальности RSS элементов
);

-- Создание индексов для оптимизации запросов
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_category_id ON articles(category_id);
CREATE INDEX IF NOT EXISTS idx_articles_source_id ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_link ON articles(link);
CREATE INDEX IF NOT EXISTS idx_articles_active ON articles(is_active);
CREATE INDEX IF NOT EXISTS idx_articles_guid ON articles(guid);

-- Создание таблицы для логов обновлений
CREATE TABLE IF NOT EXISTS update_logs (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES sources(id),
    status VARCHAR(50) NOT NULL, -- success, error, warning
    message TEXT,
    articles_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Вставка начальных данных для категорий
INSERT INTO categories (name, display_name, description) VALUES
('sports', 'Спорт', 'Новости спорта со всего мира'),
('economics', 'Экономика', 'Экономические новости и финансы'),
('politics', 'Политика', 'Политические новости и события'),
('technology', 'IT Технологии', 'Новости IT и технологий')
ON CONFLICT (name) DO NOTHING;

-- Вставка начальных данных для источников
INSERT INTO sources (name, url, rss_url, category_id) VALUES
-- Спорт
('BBC Sport', 'https://www.bbc.com/sport', 'http://feeds.bbci.co.uk/sport/rss.xml', 
 (SELECT id FROM categories WHERE name = 'sports')),
('ESPN', 'https://www.espn.com', 'https://www.espn.com/espn/rss/news', 
 (SELECT id FROM categories WHERE name = 'sports')),
('Reuters Sports', 'https://www.reuters.com/sports', 'https://feeds.reuters.com/reuters/sportsNews', 
 (SELECT id FROM categories WHERE name = 'sports')),

-- Экономика
('Reuters Business', 'https://www.reuters.com/business', 'https://feeds.reuters.com/reuters/businessNews', 
 (SELECT id FROM categories WHERE name = 'economics')),
('BBC Business', 'https://www.bbc.com/business', 'http://feeds.bbci.co.uk/news/business/rss.xml', 
 (SELECT id FROM categories WHERE name = 'economics')),
('Financial Times', 'https://www.ft.com', 'https://www.ft.com/rss/home', 
 (SELECT id FROM categories WHERE name = 'economics')),

-- Политика
('Reuters Politics', 'https://www.reuters.com/politics', 'https://feeds.reuters.com/Reuters/PoliticsNews', 
 (SELECT id FROM categories WHERE name = 'politics')),
('BBC Politics', 'https://www.bbc.com/news/politics', 'http://feeds.bbci.co.uk/news/politics/rss.xml', 
 (SELECT id FROM categories WHERE name = 'politics')),
('Associated Press Politics', 'https://apnews.com/politics', 'https://feeds.apnews.com/rss/apf-politics', 
 (SELECT id FROM categories WHERE name = 'politics')),

-- Технологии
('TechCrunch', 'https://techcrunch.com', 'https://feeds.feedburner.com/TechCrunch', 
 (SELECT id FROM categories WHERE name = 'technology')),
('Ars Technica', 'https://arstechnica.com', 'https://feeds.arstechnica.com/arstechnica/index', 
 (SELECT id FROM categories WHERE name = 'technology')),
('Reuters Technology', 'https://www.reuters.com/technology', 'https://feeds.reuters.com/reuters/technologyNews', 
 (SELECT id FROM categories WHERE name = 'technology'))
ON CONFLICT (name) DO NOTHING;

-- Создание функции для обновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Создание триггера для автоматического обновления updated_at
CREATE TRIGGER update_articles_updated_at 
    BEFORE UPDATE ON articles 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Создание пользователя для приложения (опционально)
-- CREATE USER news_app WITH PASSWORD 'your_secure_password';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO news_app;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO news_app;
