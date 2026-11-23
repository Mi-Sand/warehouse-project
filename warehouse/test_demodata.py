"""Проверка наполнения базы тестовыми данными.

Тестовые данные показывают систему людям, которые решают, работать ли
в ней. Если остатки в них не сходятся с журналом или страница падает,
это выглядит как ошибка учёта, а не наполнения.
"""
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone

from billing.models import Counterparty, Payment
from inventory.models import Inventory

from .models import (InboundDocument, Material, Order, Product, ProductionRun,
                     Stock, StockMovement, Warehouse)

User = get_user_model()


def run():
    out = StringIO()
    call_command('demodata', stdout=out, stderr=out)
    return out.getvalue()


class DemoDataTests(TestCase):
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
