from flask import Flask, render_template, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, timezone
import feedparser
from newspaper import Article as NewsArticle
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
import logging
from dateutil import parser as date_parser
import os
from dotenv import load_dotenv
from flask import flash, redirect, url_for

# Загрузка переменных окружения
load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')

db = SQLAlchemy(app)

# Настройка логирования
logging.basicConfig(level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')))
logger = logging.getLogger(__name__)


class Category(db.Model):
    """Модель категории новостей."""

    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    display_name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Связи с другими моделями
    sources = db.relationship('Source', backref='category', lazy=True)
    articles = db.relationship('Article', backref='category', lazy=True)


class Source(db.Model):
    """Модель источника новостей."""

    __tablename__ = 'sources'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    url = db.Column(db.String(1000), nullable=False)
    rss_url = db.Column(db.String(1000), nullable=False)
    category_id = db.Column(
        db.Integer, 
        db.ForeignKey('categories.id'), 
        nullable=False
    )
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # Связи с другими моделями
    articles = db.relationship('Article', backref='source', lazy=True)
    update_logs = db.relationship('UpdateLog', backref='source', lazy=True)


class Article(db.Model):
    """Модель статьи новостей."""

    __tablename__ = 'articles'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    content = db.Column(db.Text)
    link = db.Column(db.String(1000), unique=True, nullable=False)
    image_url = db.Column(db.String(1000))  # URL изображения статьи из RSS ленты
    published_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    category_id = db.Column(
        db.Integer, 
        db.ForeignKey('categories.id'), 
        nullable=False
    )
    source_id = db.Column(
        db.Integer, 
        db.ForeignKey('sources.id'), 
        nullable=False
    )
    is_active = db.Column(db.Boolean, default=True)
    view_count = db.Column(db.Integer, default=0)
    guid = db.Column(db.String(500))

    def to_dict(self):
        """Преобразует объект статьи в словарь для JSON API."""
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'link': self.link,
            'image_url': self.image_url,
            'published_at': self.published_at.isoformat(),
            'category': self.category.name,
            'category_display': self.category.display_name,
            'source': self.source.name,
            'view_count': self.view_count
        }


class UpdateLog(db.Model):
    """Модель логов обновления источников новостей."""

    __tablename__ = 'update_logs'

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(
        db.Integer, 
        db.ForeignKey('sources.id'), 
        nullable=False
    )
    status = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text)
    articles_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


def extract_article_content(url):
    """
    Извлекает полный текст статьи с помощью библиотеки Newspaper3k.
    Args:
        url (str): URL статьи для извлечения контента
    Returns:
        str or None: Текст статьи (до 5000 символов) или None при ошибке
    """
    try:
        article = NewsArticle(url)
        article.download()
        article.parse()
        return (article.text[:5000] 
                if len(article.text) > 5000 else article.text)
    except Exception as e:
        logger.error(f"Ошибка извлечения контента из {url}: {str(e)}")
        return None


def fetch_rss_feed(source):
    """
    Получает и парсит RSS поток от источника новостей.

    Args:
        source (Source): Объект источника новостей

    Returns:
        list: Список словарей с данными статей
    """
    try:
        logger.info(f"Получение RSS потока от {source.name}: {source.rss_url}")

        # Установка User-Agent для избежания блокировки
        headers = {
            'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                           'AppleWebKit/537.36')
        }

        # Парсинг RSS фида
        feed = feedparser.parse(source.rss_url, request_headers=headers)

        if feed.bozo:
            logger.warning(
                f"Предупреждение при парсинге RSS для {source.name}: "
                f"{feed.bozo_exception}"
            )

        articles = []
        max_articles = int(os.getenv('MAX_ARTICLES_PER_SOURCE', 50))

        for entry in feed.entries[:max_articles]:
            # Парсинг даты публикации
            published_at = datetime.now(timezone.utc).replace(tzinfo=None)
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    published_at = datetime(*entry.published_parsed[:6])
                except Exception:
                    pass
            elif hasattr(entry, 'published'):
                try:
                    published_at = date_parser.parse(entry.published)
                    if published_at.tzinfo:
                        published_at = published_at.replace(tzinfo=None)
                except Exception:
                    pass

            # Извлечение описания
            description = ''
            if hasattr(entry, 'summary'):
                description = entry.summary
            elif hasattr(entry, 'description'):
                description = entry.description

            # Очистка HTML из описания
            if description:
                soup = BeautifulSoup(description, 'html.parser')
                description = soup.get_text()
                if len(description) > 1000:
                    description = description[:1000] + '...'

            # Извлечение URL картинки
            image_url = None
            try:
                # Поиск изображения в различных полях RSS
                if hasattr(entry, 'media_content') and entry.media_content:
                    # Media RSS намеспейс
                    for media in entry.media_content:
                        if media.get('type', '').startswith('image/'):
                            image_url = media['url']
                            break
                    if not image_url and entry.media_content:
                        image_url = entry.media_content[0]['url']
                
                elif hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0]['url']
                
                elif hasattr(entry, 'enclosures') and entry.enclosures:
                    # Поиск в enclosures
                    for enclosure in entry.enclosures:
                        if hasattr(enclosure, 'type') and enclosure.type.startswith('image/'):
                            image_url = enclosure.href
                            break
                
                # Поиск в содержимом (summary или content)
                if not image_url:
                    content_to_search = ''
                    if hasattr(entry, 'content') and entry.content:
                        content_to_search = entry.content[0].value
                    elif hasattr(entry, 'summary'):
                        content_to_search = entry.summary
                    
                    if content_to_search:
                        soup = BeautifulSoup(content_to_search, 'html.parser')
                        img_tags = soup.find_all('img')
                        for img in img_tags:
                            src = img.get('src')
                            if src and (src.startswith('http') or src.startswith('/')):
                                image_url = src
                                break
                
                # Проверяем, что URL корректный
                if image_url and not image_url.startswith('http'):
                    if image_url.startswith('//'):
                        image_url = 'https:' + image_url
                    elif image_url.startswith('/'):
                        # Пытаемся получить базовый URL сайта
                        from urllib.parse import urlparse
                        parsed_url = urlparse(source.url)
                        image_url = f"{parsed_url.scheme}://{parsed_url.netloc}{image_url}"
                
            except Exception as e:
                logger.warning(f"Ошибка при извлечении изображения для {entry.get('title', 'Unknown')}: {str(e)}")

            # Получение GUID
            guid = entry.get('id', entry.get('link', ''))

            article_data = {
                'title': (entry.title[:500] 
                          if hasattr(entry, 'title') else 'Без заголовка'),
                'description': description,
                'link': entry.link,
                'published_at': published_at,
                'guid': guid,
                'source_id': source.id,
                'category_id': source.category_id,
                'image_url': image_url
            }
            articles.append(article_data)

        return articles

    except Exception as e:
        logger.error(f"Ошибка получения RSS потока от {source.name}: {str(e)}")
        return []


def update_news():
    """Обновляет новости из всех активных RSS источников."""
    with app.app_context():
        logger.info("Начало обновления новостей...")

        # Получаем все активные источники
        sources = Source.query.filter_by(is_active=True).all()

        total_new_articles = 0

        for source in sources:
            try:
                articles_data = fetch_rss_feed(source)
                new_articles_count = 0

                for article_data in articles_data:
                    # Проверяем, существует ли уже такая статья
                    existing = Article.query.filter_by(
                        link=article_data['link']
                    ).first()

                    if not existing:
                        # Попытка извлечь полный контент статьи
                        full_content = extract_article_content(
                            article_data['link']
                        )
                        if full_content:
                            article_data['content'] = full_content

                        article = Article(**article_data)
                        db.session.add(article)
                        new_articles_count += 1

                # Логируем результат
                log_entry = UpdateLog(
                    source_id=source.id,
                    status='success',
                    message=(f"Успешно обработано {len(articles_data)} статей, "
                             f"{new_articles_count} новых"),
                    articles_count=new_articles_count
                )
                db.session.add(log_entry)
                total_new_articles += new_articles_count

            except Exception as e:
                logger.error(f"Ошибка обновления новостей от {source.name}: "
                             f"{str(e)}")
                log_entry = UpdateLog(
                    source_id=source.id,
                    status='error',
                    message=f"Ошибка: {str(e)}",
                    articles_count=0
                )
                db.session.add(log_entry)

        try:
            db.session.commit()
            logger.info(f"Обновление новостей завершено. "
                       f"Всего новых статей: {total_new_articles}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Ошибка сохранения обновлений: {str(e)}")


# Маршруты веб-интерфейса
@app.route('/')
def index():
    """Главная страница с последними новостями."""
    page = request.args.get('page', 1, type=int)
    source_id = request.args.get('source', type=int)
    per_page = 20

    # Фильтр: только новости за последние 7 дней
    seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

    query = Article.query.filter_by(is_active=True)\
        .filter(Article.published_at >= seven_days_ago)

    # Фильтрация по источнику
    if source_id:
        query = query.filter_by(source_id=source_id)

    articles = query.order_by(Article.published_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)

    categories = Category.query.all()
    sources = Source.query.filter_by(is_active=True)\
        .order_by(Source.name).all()
    selected_source = Source.query.get(source_id) if source_id else None

    return render_template('index.html',
                           articles=articles.items,
                           categories=categories,
                           sources=sources,
                           selected_source=selected_source,
                           pagination=articles)


@app.route('/category/<category_name>')
def category_news(category_name):
    """Страница новостей по категории."""
    category = Category.query.filter_by(name=category_name).first_or_404()

    page = request.args.get('page', 1, type=int)
    source_id = request.args.get('source', type=int)
    per_page = 20

    # Фильтр: только новости за последние 7 дней
    seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

    query = Article.query.filter_by(category_id=category.id, is_active=True)\
        .filter(Article.published_at >= seven_days_ago)

    # Фильтрация по источнику
    if source_id:
        query = query.filter_by(source_id=source_id)

    articles = query.order_by(Article.published_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)

    categories = Category.query.all()
    # Получаем источники только для данной категории
    category_sources = Source.query.filter_by(
        category_id=category.id,
        is_active=True
    ).order_by(Source.name).all()
    selected_source = Source.query.get(source_id) if source_id else None

    return render_template('category.html',
                           articles=articles.items,
                           category=category,
                           categories=categories,
                           sources=category_sources,
                           selected_source=selected_source,
                           pagination=articles)


@app.route('/article/<int:article_id>')
def article_detail(article_id):
    """Страница детальной информации о статье."""
    article = Article.query.get_or_404(article_id)

    # Увеличиваем счетчик просмотров
    article.view_count += 1
    db.session.commit()

    # Получаем похожие статьи из той же категории за последние 7 дней
    seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    similar_articles = Article.query.filter_by(
        category_id=article.category_id,
        is_active=True
    ).filter(Article.id != article_id)\
        .filter(Article.published_at >= seven_days_ago)\
        .order_by(Article.published_at.desc())\
        .limit(5).all()

    return render_template('article.html',
                           article=article,
                           similar_articles=similar_articles)


# Маршруты административной панели
@app.route('/admin')
def admin_dashboard():
    """Административная панель."""
    sources = Source.query.order_by(Source.created_at.desc()).all()
    categories = Category.query.all()

    # Получаем статистику - только за последние 7 дней
    seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

    stats = {
        'total_articles': Article.query.filter_by(is_active=True)
            .filter(Article.published_at >= seven_days_ago).count(),
        'total_sources': Source.query.filter_by(is_active=True).count(),
        'categories': []
    }

    for category in categories:
        article_count = Article.query.filter_by(
            category_id=category.id,
            is_active=True
        ).filter(Article.published_at >= seven_days_ago).count()
        stats['categories'].append({
            'name': category.name,
            'display_name': category.display_name,
            'article_count': article_count
        })

    return render_template('admin_dashboard.html',
                           sources=sources,
                           categories=categories,
                           stats=stats)


@app.route('/admin/add_source', methods=['GET', 'POST'])
def add_source():
    """Добавление нового источника новостей."""
    categories = Category.query.all()
    
    if request.method == 'POST':
        name = request.form.get('name')
        url = request.form.get('url')
        rss_url = request.form.get('rss_url')
        category_id = request.form.get('category_id')

        if not all([name, url, rss_url, category_id]):
            flash('Все поля обязательны для заполнения!', 'danger')
            return redirect(url_for('add_source'))

        new_source = Source(
            name=name,
            url=url,
            rss_url=rss_url,
            category_id=int(category_id)
        )

        try:
            db.session.add(new_source)
            db.session.commit()
            flash('Источник успешно добавлен!', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка добавления источника: {str(e)}', 'danger')

    return render_template('add_source.html', categories=categories)


# API маршруты
@app.route('/api/news')
def api_news():
    """API эндпоинт для получения последних новостей."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)

    # Фильтр: только новости за последние 7 дней
    seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

    articles = Article.query.filter_by(is_active=True)\
        .filter(Article.published_at >= seven_days_ago)\
        .order_by(Article.published_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'articles': [article.to_dict() for article in articles.items],
        'pagination': {
            'page': articles.page,
            'pages': articles.pages,
            'per_page': articles.per_page,
            'total': articles.total
        }
    })


@app.route('/api/news/<category_name>')
def api_category_news(category_name):
    """API эндпоинт для получения новостей по категории."""
    category = Category.query.filter_by(name=category_name).first_or_404()

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)

    # Фильтр: только новости за последние 7 дней
    seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

    articles = Article.query.filter_by(category_id=category.id, is_active=True)\
        .filter(Article.published_at >= seven_days_ago)\
        .order_by(Article.published_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'articles': [article.to_dict() for article in articles.items],
        'category': category.display_name,
        'pagination': {
            'page': articles.page,
            'pages': articles.pages,
            'per_page': articles.per_page,
            'total': articles.total
        }
    })


@app.route('/api/categories')
def api_categories():
    """API эндпоинт для получения списка категорий."""
    categories = Category.query.all()
    return jsonify([{
        'name': cat.name,
        'display_name': cat.display_name,
        'description': cat.description
    } for cat in categories])


@app.route('/api/update')
def api_update():
    """API эндпоинт для ручного обновления новостей."""
    update_news()
    return jsonify({'status': 'success', 'message': 'Обновление новостей запущено'})


@app.route('/api/stats')
def api_stats():
    """API эндпоинт для получения статистики."""
    # Статистика только за последние 7 дней
    seven_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

    stats = {
        'total_articles': Article.query.filter_by(is_active=True)
            .filter(Article.published_at >= seven_days_ago).count(),
        'total_sources': Source.query.filter_by(is_active=True).count(),
        'categories': []
    }

    for category in Category.query.all():
        article_count = Article.query.filter_by(
            category_id=category.id,
            is_active=True
        ).filter(Article.published_at >= seven_days_ago).count()
        stats['categories'].append({
            'name': category.name,
            'display_name': category.display_name,
            'article_count': article_count
        })

    return jsonify(stats)


if __name__ == '__main__':
    # Инициализация планировщика для автоматического обновления новостей
    scheduler = BackgroundScheduler()
    update_interval = int(os.getenv('UPDATE_INTERVAL_MINUTES', 30))

    scheduler.add_job(
        func=update_news,
        trigger="interval",
        minutes=update_interval,
        id='news_update'
    )

    # Запуск планировщика
    scheduler.start()

    # Первоначальное обновление новостей
    with app.app_context():
        update_news()

    try:
        app.run(
            debug=os.getenv('FLASK_DEBUG', 'True').lower() == 'true',
            host='0.0.0.0',
            port=5003
        )
    except KeyboardInterrupt:
        logger.info("Завершение работы...")
        scheduler.shutdown()