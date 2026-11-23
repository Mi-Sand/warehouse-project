"""Наполнить пустую базу тестовыми данными — всем, кроме сотрудников.

    python manage.py demodata

Нужна, чтобы посмотреть систему в работе, не вбивая руками десятки
карточек и документов: показать её заказчику, обучить кладовщика,
проверить отчёт на правдоподобных цифрах.

Что заводится: единицы измерения сверх встроенных, склады, поставщики,
материалы, продукция, реквизиты своей организации, покупатели-
организации, приходы, выпуски продукции, расходы, заказы с витрины во
всех статусах, оплаты, инвентаризации и один документ в корзине.

Учётные записи сотрудников команда не трогает: их заводит
администратор (createsuperuser, страница «Сотрудники»). Документы
подписываются первым найденным администратором, а если сотрудников
ещё нет — остаются без автора.

Документы проводятся штатными функциями, теми же, что вызывает
интерфейс. Поэтому остатки, журнал движения, история цен и
себестоимость выпусков сходятся между собой так же, как при обычной
работе, — расхождения в тестовых данных означали бы ошибку в учёте, а
не в наполнении. Даты разнесены на два месяца назад, чтобы отчёты за
период и сводка показывали не одну точку.

Команда работает только с пустой базой: смешивать придуманные остатки
с настоящими нельзя, разделить их потом будет нечем.
"""
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone

from accounts.models import User
from billing.models import CompanyRequisites, Counterparty, Payment
from inventory.models import Inventory
from inventory.services import build_inventory_sheet, finalize_inventory
from warehouse.models import (InboundDocument, InboundItem, Material, Order,
                              OutboundDocument, OutboundItem, PriceHistory,
                              Product, ProductionRun, ProductPhoto,
                              StockMovement, Supplier, Unit, Warehouse)
from warehouse.order_services import (cancel_order, confirm_order,
                                      create_order, ship_order)
from warehouse.demo_images import render
from warehouse.services import (process_inbound_document,
                                process_outbound_document, produce_product)

D = Decimal

# Единицы сверх встроенных пяти: код, обозначение, название, ОКЕИ
UNITS = [
    ('pair', 'пара', 'Пара', '715'),
    ('roll', 'рулон', 'Рулон', '736'),
    ('pack', 'упак.', 'Упаковка', '778'),
]

WAREHOUSES = {
    'raw': ('Склад сырья № 1', 'raw', 'г. Дмитров, ул. Промышленная, д. 4, '
                                      'корп. 1', 500),
    'finished': ('Склад готовой продукции', 'finished',
                 'г. Дмитров, ул. Промышленная, д. 4, корп. 2', 2000),
    'shop': ('Магазин при производстве', 'finished',
             'г. Дмитров, ул. Советская, д. 10', 300),
}

SUPPLIERS = {
    'textile': ('ООО «ТексПром»', '7701234560', 'Соколова Анна Викторовна',
                '+7 495 123-45-67', 'sales@texprom.example'),
    'leather': ('ООО «Кожевенный двор»', '5032123456',
                'Морозов Игорь Петрович', '+7 496 222-33-44',
                'order@kozhdvor.example'),
    'polymer': ('АО «ПолимерСнаб»', '7728123459', 'Ершов Денис Олегович',
                '+7 495 777-10-20', 'info@polysnab.example'),
    'fittings': ('ИП Гаврилов Сергей Николаевич', '500712345678',
                 'Гаврилов Сергей Николаевич', '+7 916 555-12-34', ''),
}

# ключ: наименование, артикул, цвет, единица, категория, минимум
MATERIALS = {
    'mesh': ('Сетка обувная 3D', 'ТК-101', 'чёрный', 'm', 'textile', 30),
    'canvas': ('Ткань хлопковая плотная', 'ТК-115', 'белый', 'm',
               'textile', 40),
    'fleece': ('Флис 280 г/м²', 'ТК-140', 'серый', 'm', 'textile', 25),
    'lining': ('Подкладка трикотажная', 'ТК-150', 'бежевый', 'roll',
               'textile', 2),
    'leather': ('Кожа натуральная КРС', 'КЖ-201', 'коричневый', 'm2',
                'leather', 15),
    'eco': ('Экокожа', 'КЖ-215', 'чёрный', 'm2', 'leather', 20),
    'sole': ('Подошва ЭВА', 'ПЛ-301', 'белый', 'pair', 'polymer', 50),
    'glue': ('Клей полиуретановый', 'ПЛ-320', '', 'l', 'polymer', 5),
    'foam': ('Пенополиуретан листовой', 'ПЛ-330', '', 'kg', 'polymer', 10),
    'laces': ('Шнурки плоские 120 см', 'ФР-401', 'чёрный', 'pair',
              'fittings', 100),
    'zip': ('Молния спиральная 60 см', 'ФР-410', 'чёрный', 'pc',
            'fittings', 80),
    'rivets': ('Люверсы 5 мм', 'ФР-420', 'никель', 'pack', 'fittings', 10),
}

# ключ: артикул, наименование, категория, размер, цвет, себестоимость,
# цена, описание
PRODUCTS = {
    'run41': ('КР-001-41', 'Кроссовки беговые «Темп»', 'shoes', '41',
              'чёрный', 480, 3990,
              'Лёгкие беговые кроссовки с сетчатым верхом и подошвой ЭВА.'),
    'run42': ('КР-001-42', 'Кроссовки беговые «Темп»', 'shoes', '42',
              'чёрный', 480, 3990,
              'Лёгкие беговые кроссовки с сетчатым верхом и подошвой ЭВА.'),
    'run43': ('КР-001-43', 'Кроссовки беговые «Темп»', 'shoes', '43',
              'чёрный', 480, 3990,
              'Лёгкие беговые кроссовки с сетчатым верхом и подошвой ЭВА.'),
    'boot40': ('БТ-010-40', 'Ботинки кожаные «Север»', 'shoes', '40',
               'коричневый', 1900, 7490,
               'Зимние ботинки из натуральной кожи на утеплённой подкладке.'),
    'boot42': ('БТ-010-42', 'Ботинки кожаные «Север»', 'shoes', '42',
               'коричневый', 1900, 7490,
               'Зимние ботинки из натуральной кожи на утеплённой подкладке.'),
    'hoodieM': ('ТЛ-020-M', 'Толстовка флисовая', 'clothing', 'M', 'серый',
                350, 2290, 'Тёплая толстовка с капюшоном и молнией.'),
    'hoodieL': ('ТЛ-020-L', 'Толстовка флисовая', 'clothing', 'L', 'серый',
                350, 2290, 'Тёплая толстовка с капюшоном и молнией.'),
    'bag': ('СМ-030', 'Сумка спортивная', 'accessories', '—', 'чёрный',
            600, 1890, 'Сумка из экокожи с плечевым ремнём.'),
    'insole': ('СТ-040', 'Стельки анатомические', 'accessories', '—',
               'синий', 120, 390, 'Покупное изделие, перепродаётся.'),
    'mat': ('КВ-050', 'Коврик для фитнеса', 'equipment', '—', 'зелёный',
            430, 1190, 'Покупное изделие, перепродаётся.'),
    'oldrun': ('КР-000-42', 'Кроссовки «Старт» (прошлая модель)', 'shoes',
               '42', 'белый', 1500, 2990,
               'Снята с производства, остатки распродаются.'),
}

# Что нарисовать для товара и сколько ракурсов: у обуви, одежды и сумки
# второй снимок есть, чтобы в карточке на витрине была галерея
PICTURES = {
    'run41': ('sneaker', 2), 'run42': ('sneaker', 2), 'run43': ('sneaker', 2),
    'boot40': ('boot', 2), 'boot42': ('boot', 2),
    'hoodieM': ('hoodie', 2), 'hoodieL': ('hoodie', 2), 'bag': ('bag', 2),
    'insole': ('insoles', 1), 'mat': ('mat', 1), 'oldrun': ('sneaker', 1),
}

COUNTERPARTIES = {
    'sport': ('ООО «Спорт-Регион»', '5007045678', '500701001',
              'Московская обл., г. Дмитров, ул. Загорская, д. 15',
              '+7 496 224-11-22', 'zakupki@sport-region.example'),
    'school': ('МБОУ «Гимназия № 2»', '5007098765', '500701001',
               'Московская обл., г. Дмитров, ул. Школьная, д. 3',
               '+7 496 227-30-40', ''),
}

# Покупатели с витрины: имя, телефон, почта, адрес
CUSTOMERS = [
    ('Ольга Смирнова', '+7 915 101-20-30', 'olga.s@example.com',
     'г. Дмитров, ул. Почтовая, д. 12, кв. 8'),
    ('Алексей Кузнецов', '8 (926) 222-33-44', '',
     'г. Москва, ул. Профсоюзная, д. 45, кв. 112'),
    ('Мария Волкова', '+7 903 555-66-77', 'm.volkova@example.com', ''),
    ('Дмитрий Новиков', '+7 916 777-88-99', '',
     'Московская обл., г. Яхрома, ул. Ленина, д. 3'),
    ('Екатерина Павлова', '+7 925 333-44-55', 'katya.p@example.com',
     'г. Талдом, ул. Салтыкова-Щедрина, д. 20, кв. 4'),
    ('Сергей Лебедев', '+7 985 123-12-12', '', ''),
    ('Наталья Козлова', '+7 917 909-08-07', 'n.kozlova@example.com',
     'г. Дубна, просп. Боголюбова, д. 7, кв. 31'),
]


class Command(BaseCommand):
    help = ('Заполнить пустую базу тестовыми данными: справочники, '
            'документы, заказы, оплаты, инвентаризации. Сотрудников не '
            'заводит.')

    def handle(self, *args, **options):
        busy = [title for qs, title in (
            (Warehouse.objects, 'склады'), (Material.objects, 'материалы'),
            (Product.objects, 'продукция'), (Supplier.objects, 'поставщики'),
            (Order.objects, 'заказы'),
            (InboundDocument.all_objects, 'приходы'),
            (OutboundDocument.all_objects, 'расходы'),
        ) if qs.exists()]
        if busy:
            raise CommandError(
                'В базе уже есть данные (' + ', '.join(busy) + '). '
                'Тестовые данные добавляются только в пустую базу: '
                'смешанные с настоящими, их потом не отделить.')

        self.author = (
            User.objects.filter(is_active=True, is_superuser=True).first()
            or User.objects.filter(is_active=True, role=User.Role.ADMIN)
            .first())
        self.today = timezone.localdate()

        # Письма о недостаче по инвентаризации тестовым данным не нужны:
        # на настроенной почте они ушли бы настоящему ответственному.
        with override_settings(
                EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend',
                NOTIFY_LOW_STOCK_INSTANTLY=False):
            with transaction.atomic():
                self.fill()

        self.report()

    # --- Даты ---------------------------------------------------------------
    def day(self, ago):
        return self.today - timedelta(days=ago)

    @contextmanager
    def on_day(self, ago, hour=11):
        """Отнести всё, что создано внутри, к дню `ago` дней назад.

        Время записей ставится в момент создания самой базой, и
        переопределить его при создании нельзя. Поэтому после шага
        найденные новые строки сдвигаются на нужный день.
        """
        tables = [
            (StockMovement.objects, 'created_at'),
            (PriceHistory.objects, 'recorded_at'),
            (ProductionRun.objects, 'created_at'),
            (Order.objects, 'created_at'),
            (Inventory.objects, 'created_at'),
            (Payment.objects, 'created_at'),
            (InboundDocument.all_objects, 'created_at'),
            (OutboundDocument.all_objects, 'created_at'),
        ]
        last = [(qs.order_by('-pk').values_list('pk', flat=True).first()
                 or 0) for qs, _ in tables]
        yield
        # Сегодняшние записи не должны оказаться в будущем, если
        # команду запустили раньше назначенного часа
        moment = min(timezone.now(), timezone.make_aware(
            datetime.combine(self.day(ago), time(hour, 0))))
        for (qs, field), edge in zip(tables, last):
            qs.filter(pk__gt=edge).update(**{field: moment})

    # --- Наполнение ---------------------------------------------------------
    def fill(self):
        self.references()

        raw, fin, shop = (self.wh['raw'], self.wh['finished'],
                          self.wh['shop'])
        m, p = self.mat, self.prod

        with self.on_day(60):
            self.inbound('ПР-0001', 60, 'textile', raw, [
                (m['mesh'], 120, 210), (m['canvas'], 150, 160),
                (m['fleece'], 80, 340), (m['lining'], 6, 4200)])
        with self.on_day(58):
            self.inbound('ПР-0002', 58, 'leather', raw, [
                (m['leather'], 60, 1450), (m['eco'], 70, 620)])
        with self.on_day(57):
            self.inbound('ПР-0003', 57, 'polymer', raw, [
                (m['sole'], 200, 280), (m['glue'], 20, 540),
                (m['foam'], 30, 310)])
        with self.on_day(56):
            self.inbound('ПР-0004', 56, 'fittings', raw, [
                (m['laces'], 300, 35), (m['zip'], 150, 48),
                (m['rivets'], 25, 260)])

        with self.on_day(52, hour=15):
            self.produce(p['run41'], 30, fin, raw, [
                (m['mesh'], 15), (m['sole'], 30), (m['laces'], 30),
                (m['glue'], 2)])
            self.produce(p['run42'], 40, fin, raw, [
                (m['mesh'], 20), (m['sole'], 40), (m['laces'], 40),
                (m['glue'], 2.5)])
            self.produce(p['run43'], 25, fin, raw, [
                (m['mesh'], 13), (m['sole'], 25), (m['laces'], 25),
                (m['glue'], 1.5)])

        with self.on_day(48):
            self.inbound('ПР-0005', 48, 'polymer', fin, [
                (p['insole'], 100, 115), (p['mat'], 40, 420)])

        with self.on_day(45, hour=15):
            self.produce(p['boot40'], 12, fin, raw, [
                (m['leather'], 9), (m['sole'], 12), (m['lining'], 1),
                (m['laces'], 12), (m['rivets'], 2), (m['glue'], 1.5)])
            self.produce(p['boot42'], 18, fin, raw, [
                (m['leather'], 14), (m['sole'], 18), (m['lining'], 1.5),
                (m['laces'], 18), (m['rivets'], 3), (m['glue'], 2)])

        with self.on_day(40, hour=15):
            self.produce(p['hoodieM'], 35, fin, raw, [
                (m['fleece'], 28), (m['zip'], 35)])
            self.produce(p['hoodieL'], 30, fin, raw, [
                (m['fleece'], 26), (m['zip'], 30)])
            self.produce(p['bag'], 20, fin, raw, [
                (m['eco'], 16), (m['zip'], 20), (m['rivets'], 2)])

        with self.on_day(38):
            self.outbound('РС-0001', 38, raw, 'writeoff', '', [
                (m['canvas'], 12, 0)])
        with self.on_day(35):
            self.outbound('РС-0002', 35, fin, 'sale', 'Перемещение в магазин',
                          [(p['run42'], 6, 3990), (p['hoodieM'], 5, 2290),
                           (p['insole'], 20, 390)])
            self.inbound('ПР-0006', 35, 'polymer', shop, [
                (p['run42'], 6, 1850), (p['hoodieM'], 5, 950),
                (p['insole'], 20, 115)])

        # Вторая закупка сетки дороже первой — в истории цен видно
        # подорожание, а у следующего выпуска себестоимость выше плановой
        with self.on_day(30):
            self.inbound('ПР-0007', 30, 'textile', raw, [
                (m['mesh'], 100, 245), (m['fleece'], 40, 355)])
        with self.on_day(28):
            self.inbound('ПР-0008', 28, 'polymer', raw, [
                (m['sole'], 120, 295)])
        with self.on_day(25, hour=15):
            self.produce(p['run42'], 30, fin, raw, [
                (m['mesh'], 16), (m['sole'], 30), (m['laces'], 30),
                (m['glue'], 2)])
            self.produce(p['run43'], 20, fin, raw, [
                (m['mesh'], 11), (m['sole'], 20), (m['laces'], 20),
                (m['glue'], 1.5)])

        with self.on_day(22):
            self.outbound('РС-0003', 22, raw, 'production', 'Образцы для '
                          'новой коллекции', [(m['leather'], 3, 1450),
                                              (m['canvas'], 8, 160)])

        self.orders(fin)

        # Продукция прошлой модели: приход остатков от сторонней фабрики,
        # после чего модель снята с производства
        with self.on_day(20):
            self.inbound('ПР-0009', 20, 'leather', fin, [
                (p['oldrun'], 15, 1500)])
        Product.objects.filter(pk=p['oldrun'].pk).update(status='archived')

        self.inventories(raw, shop)

        # Черновик прихода — ещё не проведён, кладовщик сверяет накладную
        with self.on_day(1):
            self.inbound('ПР-0010', 1, 'fittings', raw, [
                (m['laces'], 200, 37), (m['zip'], 100, 50)], post=False)

        # Ошибочный документ, удалённый в корзину
        with self.on_day(3):
            doc = self.inbound('ПР-0011', 3, 'textile', raw, [
                (m['canvas'], 10, 160)], post=False)
        doc.deleted_at = timezone.now() - timedelta(days=2)
        doc.deleted_by = self.author
        doc.save(update_fields=['deleted_at', 'deleted_by'])

    def references(self):
        for number, (code, name, full_name, okei) in enumerate(UNITS):
            Unit.objects.get_or_create(code=code, defaults={
                'name': name, 'full_name': full_name, 'okei': okei,
                'sort_order': 10 + number})

        self.wh = {key: Warehouse.objects.create(
            name=name, type=kind, location=place, capacity=capacity)
            for key, (name, kind, place, capacity) in WAREHOUSES.items()}

        self.sup = {key: Supplier.objects.create(
            name=name, inn=inn, contact_person=person, phone=phone,
            email=email)
            for key, (name, inn, person, phone, email) in SUPPLIERS.items()}

        self.mat = {key: Material.objects.create(
            name=name, article_number=article, color=color, unit=unit,
            category=category, reorder_point=D(minimum))
            for key, (name, article, color, unit, category, minimum)
            in MATERIALS.items()}

        self.prod = {key: Product.objects.create(
            article_number=article, name=name, category=category, size=size,
            color=color, cost=D(cost), selling_price=D(price),
            description=text)
            for key, (article, name, category, size, color, cost, price, text)
            in PRODUCTS.items()}
        self.pictures()

        self.cp = {key: Counterparty.objects.create(
            short_name=name, inn=inn, kpp=kpp, legal_address=address,
            phone=phone, email=email)
            for key, (name, inn, kpp, address, phone, email)
            in COUNTERPARTIES.items()}

        # Реквизиты не перезаписываются, если их уже внесли
        self.requisites_created = False
        if CompanyRequisites.get_active() is None:
            CompanyRequisites.objects.create(
                short_name='ООО «ЛЕКО»',
                full_name='Общество с ограниченной ответственностью «ЛЕКО»',
                inn='5007001234', kpp='500701001', ogrn='1025001234567',
                legal_address='141800, Московская обл., г. Дмитров, '
                              'ул. Промышленная, д. 4',
                phone='+7 496 220-00-00',
                bank_name='ПАО «Тестовый банк»', bank_bik='044525000',
                settlement_account='40702810900000000001',
                correspondent_account='30101810400000000225',
                director_name='Петров П. П.',
                accountant_name='Сидорова С. С.')
            self.requisites_created = True

    def pictures(self):
        """Обложка и дополнительные ракурсы для каждого товара.

        Одинаковые товары разных размеров рисуются одинаково — у
        настоящих снимков было бы так же. Рисунок готовится один раз на
        модель и цвет, а не на каждый размер.
        """
        drawn = {}
        for key, product in self.prod.items():
            kind, views = PICTURES[key]
            for view in range(views):
                look = (kind, product.color, view)
                if look not in drawn:
                    drawn[look] = render(*look)
                name = f'demo-{key}-{view + 1}.jpg'
                if view == 0:
                    product.photo.save(name, ContentFile(drawn[look]),
                                       save=True)
                else:
                    extra = ProductPhoto(product=product, sort_order=view)
                    extra.image.save(name, ContentFile(drawn[look]),
                                     save=True)

    def inbound(self, number, ago, supplier, warehouse, rows, post=True):
        doc = InboundDocument.objects.create(
            doc_number=number, doc_date=self.day(ago),
            supplier=self.sup[supplier], warehouse=warehouse,
            created_by=self.author)
        for item, quantity, price in rows:
            InboundItem.objects.create(
                inbound_doc=doc, quantity=D(quantity), unit_price=D(price),
                batch_number=f'{number}-{item.pk}',
                **self.position(item))
        if post:
            process_inbound_document(doc.pk, user=self.author)
        return doc

    def outbound(self, number, ago, warehouse, purpose, note, rows):
        doc = OutboundDocument.objects.create(
            doc_number=number, doc_date=self.day(ago), warehouse=warehouse,
            purpose=purpose, production_order=note, created_by=self.author)
        for item, quantity, price in rows:
            OutboundItem.objects.create(
                outbound_doc=doc, quantity=D(quantity), unit_price=D(price),
                **self.position(item))
        process_outbound_document(doc.pk, user=self.author)
        return doc

    @staticmethod
    def position(item):
        if isinstance(item, Material):
            return {'material': item}
        return {'product': item}

    def produce(self, product, quantity, product_wh, material_wh, rows):
        return produce_product(
            product.pk, quantity, product_wh.pk,
            [{'material': mat.pk, 'quantity': str(qty)} for mat, qty in rows],
            material_wh.pk, user=self.author)

    def orders(self, warehouse):
        p = self.prod

        # (дней назад, покупатель, позиции, что сделать, комментарий)
        plan = [
            (19, 0, [('run42', 1), ('insole', 2)], 'ship', ''),
            (16, 1, [('boot42', 1)], 'ship', 'Позвонить за час до доставки'),
            (14, 2, [('hoodieM', 2)], 'cancel', ''),
            (12, 3, [('run43', 1), ('bag', 1)], 'ship', ''),
            (9, 4, [('hoodieL', 1), ('mat', 1)], 'ship', ''),
            (6, 6, [('boot40', 1)], 'confirm', 'Самовывоз в субботу'),
            (4, 5, [('run41', 1)], 'confirm', ''),
            (2, 0, [('mat', 2), ('insole', 1)], 'new', ''),
            (0, 3, [('hoodieM', 1)], 'new', 'Можно ли в подарочной упаковке?'),
        ]
        shipped = []
        for ago, who, items, action, comment in plan:
            name, phone, email, address = CUSTOMERS[who]
            with self.on_day(ago, hour=10):
                order = create_order(
                    name, phone,
                    [{'product': p[key].pk, 'quantity': qty}
                     for key, qty in items],
                    customer_email=email, address=address, comment=comment)
            # Отгрузка и подтверждение — на следующий день после заказа
            next_day = max(ago - 1, 0)
            if action in ('ship', 'confirm'):
                confirm_order(order.pk)
            if action == 'ship':
                with self.on_day(next_day, hour=14):
                    ship_order(order.pk, warehouse.pk, user=self.author)
                order.refresh_from_db()
                OutboundDocument.objects.filter(
                    pk=order.outbound_document_id).update(
                    doc_date=self.day(next_day))
                shipped.append((order, next_day))
            if action == 'cancel':
                cancel_order(order.pk)

        # Оптовый заказ организации — со счётом, отгрузкой и частичной
        # оплатой, чтобы акт сверки показал долг
        with self.on_day(11, hour=9):
            school = create_order(
                'Ирина Белова', '+7 496 227-30-40',
                [{'product': p['run41'].pk, 'quantity': 10},
                 {'product': p['run42'].pk, 'quantity': 10}],
                comment='Для спортивной секции, оплата по счёту')
        Order.objects.filter(pk=school.pk).update(
            counterparty=self.cp['school'])
        confirm_order(school.pk)
        with self.on_day(8, hour=14):
            ship_order(school.pk, warehouse.pk, user=self.author)
        school.refresh_from_db()
        OutboundDocument.objects.filter(
            pk=school.outbound_document_id).update(doc_date=self.day(8))

        with self.on_day(5, hour=10):
            sport = create_order(
                'Виктор Орлов', '+7 496 224-11-22',
                [{'product': p['boot42'].pk, 'quantity': 4},
                 {'product': p['bag'].pk, 'quantity': 5}],
                customer_email='zakupki@sport-region.example',
                comment='Счёт на организацию')
        Order.objects.filter(pk=sport.pk).update(
            counterparty=self.cp['sport'])
        confirm_order(sport.pk)

        # Оплаты: розничные заказы оплачены при получении, гимназия
        # перечислила половину
        methods = ['card', 'cash', 'card', 'cash']
        for (order, ago), method in zip(shipped, methods):
            order.refresh_from_db()
            with self.on_day(ago, hour=16):
                Payment.objects.create(
                    order=order, amount=self.order_sum(order),
                    paid_at=self.day(ago), method=method,
                    created_by=self.author)
        with self.on_day(6, hour=12):
            Payment.objects.create(
                order=school, amount=(self.order_sum(school) / 2).quantize(
                    D('0.01')),
                paid_at=self.day(6), method='bank', document_number='318',
                comment='Предоплата 50%', created_by=self.author)

    @staticmethod
    def order_sum(order):
        return sum((item.quantity * item.price for item in order.items.all()),
                   D('0'))

    def inventories(self, raw, shop):
        # Завершённая опись склада сырья: немного недостачи и излишек
        with self.on_day(15, hour=17):
            inv = Inventory.objects.create(
                number='ИНВ-0001', warehouse=raw, created_by=self.author)
            build_inventory_sheet(inv.pk)
            corrections = {self.mat['canvas'].pk: D('-2'),
                           self.mat['laces'].pk: D('-5'),
                           self.mat['foam'].pk: D('0.8')}
            for item in inv.items.all():
                item.actual_quantity = (item.system_quantity
                                        + corrections.get(item.material_id,
                                                          D('0')))
                item.save()
            finalize_inventory(inv.pk, user=self.author)
        Inventory.objects.filter(pk=inv.pk).update(
            completed_at=timezone.make_aware(
                datetime.combine(self.day(15), time(18, 0))))

        # Опись магазина в работе: пересчитана только часть позиций
        with self.on_day(1, hour=18):
            inv = Inventory.objects.create(
                number='ИНВ-0002', warehouse=shop, created_by=self.author)
            build_inventory_sheet(inv.pk)
            first = inv.items.order_by('pk').first()
            if first:
                first.actual_quantity = first.system_quantity
                first.save()

    # --- Итог ---------------------------------------------------------------
    def report(self):
        counts = [
            ('Склады', Warehouse.objects.count()),
            ('Поставщики', Supplier.objects.count()),
            ('Материалы', Material.objects.count()),
            ('Продукция', Product.objects.count()),
            ('Покупатели-организации', Counterparty.objects.count()),
            ('Приходы', InboundDocument.all_objects.count()),
            ('Расходы', OutboundDocument.objects.count()),
            ('Выпуски продукции', ProductionRun.objects.count()),
            ('Заказы', Order.objects.count()),
            ('Оплаты', Payment.objects.count()),
            ('Инвентаризации', Inventory.objects.count()),
            ('Записи журнала движения', StockMovement.objects.count()),
        ]
        self.stdout.write(self.style.SUCCESS('  Тестовые данные добавлены:'))
        for title, number in counts:
            self.stdout.write(f'    {title}: {number}')
        if self.author is None:
            self.stdout.write(self.style.WARNING(
                '  Сотрудников в базе нет, документы остались без автора. '
                'Заведите администратора: python manage.py createsuperuser'))
        if self.requisites_created:
            self.stdout.write(self.style.WARNING(
                '  Реквизиты организации заполнены вымышленными '
                'значениями. Замените их настоящими, прежде чем печатать '
                'счета и накладные.'))
