"""Проверка наполнения базы тестовыми данными.

Тестовые данные показывают систему людям, которые решают, работать ли
в ней. Если остатки в них не сходятся с журналом или страница падает,
это выглядит как ошибка учёта, а не наполнения.
"""
import shutil
import tempfile
from decimal import Decimal
from io import BytesIO, StringIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.utils import timezone

from billing.models import Counterparty, Payment
from inventory.models import Inventory

from .models import (InboundDocument, Material, Order, Product, ProductPhoto,
                     ProductionRun, Stock, StockMovement, Warehouse)

User = get_user_model()


def run():
    out = StringIO()
    call_command('demodata', stdout=out, stderr=out)
    return out.getvalue()


MEDIA = tempfile.mkdtemp(prefix='проверка-демо-')


@override_settings(MEDIA_ROOT=MEDIA)
class DemoDataTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def test_fills_everything_but_employees(self):
        admin = User.objects.create_superuser('admin', password='x')

        run()

        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Warehouse.objects.count(), 3)
        self.assertGreaterEqual(Material.objects.count(), 10)
        self.assertGreaterEqual(Product.objects.count(), 10)
        self.assertTrue(ProductionRun.objects.exists())
        self.assertTrue(Payment.objects.exists())
        self.assertTrue(Counterparty.objects.exists())
        self.assertEqual(
            set(Order.objects.values_list('status', flat=True)),
            {'new', 'confirmed', 'shipped', 'cancelled'})
        self.assertEqual(
            set(Inventory.objects.values_list('status', flat=True)),
            {'completed', 'in_progress'})
        # Документы подписаны найденным администратором
        self.assertFalse(
            InboundDocument.objects.exclude(created_by=admin).exists())
        # Черновик и документ в корзине
        self.assertTrue(InboundDocument.objects.filter(processed=False)
                        .exists())
        self.assertTrue(InboundDocument.all_objects
                        .filter(deleted_at__isnull=False).exists())

    def test_stock_matches_movement_journal(self):
        run()
        self.assertFalse(Stock.objects.filter(quantity__lt=0).exists())
        # Остаток каждой позиции равен приходу минус расход по журналу;
        # корректировки инвентаризации журнал хранит без знака, поэтому
        # позиции с ними сверяются отдельно ниже
        adjusted = set(StockMovement.objects.filter(movement_type='adjust')
                       .values_list('warehouse', 'material', 'product'))
        for stock in Stock.objects.all():
            key = (stock.warehouse_id, stock.material_id, stock.product_id)
            if key in adjusted:
                continue
            moves = StockMovement.objects.filter(
                warehouse=stock.warehouse, material=stock.material,
                product=stock.product)
            income = (moves.filter(movement_type='in')
                      .aggregate(s=Sum('quantity'))['s'] or Decimal('0'))
            outgo = (moves.filter(movement_type='out')
                     .aggregate(s=Sum('quantity'))['s'] or Decimal('0'))
            self.assertEqual(stock.quantity, income - outgo, stock)
        self.assertTrue(adjusted)

    def test_dates_spread_into_past(self):
        run()
        now = timezone.now()
        first = StockMovement.objects.order_by('created_at').first()
        self.assertGreater((now - first.created_at).days, 50)
        self.assertFalse(StockMovement.objects
                         .filter(created_at__gt=now).exists())
        self.assertFalse(Order.objects.filter(created_at__gt=now).exists())

    def test_no_letters_sent(self):
        run()
        self.assertEqual(mail.outbox, [])

    def test_works_without_employees(self):
        output = run()
        self.assertEqual(User.objects.count(), 0)
        self.assertIn('createsuperuser', output)

    def test_refuses_non_empty_database(self):
        run()
        before = Material.objects.count()
        with self.assertRaises(CommandError):
            run()
        self.assertEqual(Material.objects.count(), before)

    def test_every_product_has_a_photo(self):
        from PIL import Image

        run()
        self.assertFalse(Product.objects.filter(photo='').exists())
        # Размеры одного цвета выглядят одинаково — обложка у них общая,
        # а разные цвета показаны разными снимками
        by_color = {}
        for product in Product.objects.all():
            by_color.setdefault((product.name, product.color),
                                set()).add(product.photo.name)
        for (name, color), files in by_color.items():
            self.assertEqual(len(files), 1, (name, color))
        for name in {name for name, _ in by_color}:
            covers = [next(iter(files)) for (n, _), files in by_color.items()
                      if n == name]
            self.assertEqual(len(covers), len(set(covers)), name)

        with Product.objects.first().photo.open('rb') as f:
            picture = Image.open(BytesIO(f.read()))
        self.assertEqual(picture.format, 'JPEG')
        self.assertEqual(picture.width, picture.height)

        # Витрина отдаёт ссылки на снимки
        response = self.client.get('/api/shop/products/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('/media/products/photos/demo-',
                      response.content.decode())

    def test_models_come_in_several_colors_and_sizes(self):
        run()
        shoes = Product.objects.filter(name='Кроссовки беговые «Темп»')
        self.assertGreaterEqual(shoes.values('color').distinct().count(), 4)
        self.assertGreaterEqual(shoes.values('size').distinct().count(), 6)
        # Артикулы различают цвет и размер
        self.assertEqual(shoes.values('article_number').distinct().count(),
                         shoes.count())
        # Не всё в наличии: часть размеров разобрана или не шилась
        response = self.client.get('/api/shop/products/')
        card = next(c for c in response.data['products']
                    if c['name'] == 'Кроссовки беговые «Темп»')
        variants = [v for c in card['colors'] for v in c['variants']]
        self.assertTrue(any(v['available'] for v in variants))
        self.assertTrue(any(not v['available'] for v in variants))

    def test_every_photo_has_its_source_recorded(self):
        """Снимки чужие: у каждого должны быть записаны автор и лицензия.

        Лицензии CC BY и CC BY-SA разрешают брать снимок только с
        указанием автора. Снимок, добавленный без записи в ИСТОЧНИКИ.md,
        нарушал бы её.
        """
        from .management.commands.demodata import MODELS, PHOTOS_DIR

        sources = (PHOTOS_DIR / 'ИСТОЧНИКИ.md').read_text(encoding='utf-8')
        photos = sorted(PHOTOS_DIR.glob('*.jpg'))
        self.assertTrue(photos)
        for photo in photos:
            self.assertIn(f'`{photo.name}`', sources, photo.name)
        # И ни один цвет ни одной модели не остался без снимка
        for model, spec in MODELS.items():
            for code, _, _ in spec['colors']:
                self.assertTrue((PHOTOS_DIR / f'{model}-{code}.jpg').exists(),
                                f'{model}-{code}.jpg')

    def test_pages_open_on_demo_data(self):
        User.objects.create_superuser('admin', password='x')
        run()
        self.client.login(username='admin', password='x')
        order = Order.objects.filter(counterparty__isnull=False,
                                     status='shipped').first()
        urls = [
            '/', '/materials/', '/products/', '/inbound/', '/outbound/',
            '/inventory/', '/reports/', '/production/', '/orders/',
            '/trash/', '/audit/', '/shop/',
            '/api/dashboard/', '/api/reports/stock/',
            '/api/reports/movement/', '/api/reports/reorder/',
            '/api/reports/production-cost/',
            f'/api/orders/{order.pk}/invoice/',
            f'/api/orders/{order.pk}/torg12/',
            f'/print/order/{order.pk}/',
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)
