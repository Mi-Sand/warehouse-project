"""
Заполнение базы демонстрационными данными предприятия-производителя
спортивных изделий: сотрудники, склады, поставщики, материалы,
продукция, приходы, выпуски продукции, заказы с витрины,
инвентаризация.

Все операции проводятся штатной логикой системы (проведение
документов, выпуск продукции, оформление и отгрузка заказов,
завершение инвентаризации), поэтому остатки, журнал движения, история
закупочных цен и журнал действий согласованы между собой так же, как
при настоящей работе.

События проводятся в хронологическом порядке: выпуск продукции берёт
закупочные цены, действовавшие на его дату, а инвентаризация видит
остатки на день пересчёта.

Запуск на пустой базе:

    python manage.py migrate
    python manage.py seed_demo

Даты событий — июль–сентябрь 2026 года. Ключ --to-today сдвигает их
так, чтобы последние события пришлись на вчерашний день: тогда графики
на главной странице не пустуют и в день показа.

Пароль всех демонстрационных учётных записей — demo12345 (задаётся
ключом --password). Для рабочей базы команда не предназначена.
"""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from audit.current_user import reset_current_user, set_current_user
from audit.models import AuditEntry
from inventory.models import Inventory
from inventory.services import build_inventory_sheet, finalize_inventory
from warehouse.models import (InboundDocument, InboundItem, Material,
                              OutboundDocument, OutboundItem, PriceHistory,
                              Product, ProductionRun, StockMovement,
                              Supplier, Unit, Warehouse)
from warehouse.order_services import (cancel_order, confirm_order,
                                      create_order, ship_order)
from warehouse.services import (process_inbound_document,
                                process_outbound_document, produce_product)

from ._demo_pictures import picture_for

D = Decimal

USERS = [
    # логин, фамилия, имя, отчество, роль, суперпользователь
    ('admin', 'Шубин', 'Михаил', 'Игоревич', 'admin', True),
    ('petrov', 'Петров', 'Сергей', 'Николаевич', 'storekeeper', False),
    ('smirnova', 'Смирнова', 'Ольга', 'Викторовна', 'economist', False),
    ('vasiliev', 'Васильев', 'Андрей', 'Павлович', 'manager', False),
]

EXTRA_UNITS = [
    # код, обозначение, полное название, ОКЕИ
    ('pair', 'пар', 'Пара', '715'),
    ('roll', 'рул.', 'Рулон', '736'),
    ('pack', 'упак.', 'Упаковка', '778'),
    ('set', 'компл.', 'Комплект', '839'),
]

SUPPLIERS = [
    ('ООО «Текстиль-Опт»', 'Кравцова Ирина', '+7 495 000-11-01'),
    ('ООО «ПоролонСнаб»', 'Громов Олег', '+7 495 000-11-02'),
    ('АО «Полимер-Трейд»', 'Ершова Наталья', '+7 495 000-11-03'),
    ('ООО «Фурнитура-М»', 'Лебедев Виктор', '+7 495 000-11-04'),
]

# ключ, наименование, артикул, ед., категория, минимум, цвет
MATERIALS = [
    ('pvc_blue', 'Ткань ПВХ тентовая 650 г/м²', 'ТПВХ-650-С', 'm',
     'textile', 150, 'синий'),
    ('pvc_red', 'Ткань ПВХ тентовая 650 г/м²', 'ТПВХ-650-К', 'm',
     'textile', 100, 'красный'),
    ('oxford', 'Ткань «Оксфорд 600D» с ПУ-пропиткой', 'ТОКС-600', 'm',
     'textile', 100, 'чёрный'),
    ('leather_black', 'Искусственная кожа «Винилискожа-Т»', 'ИК-ВТ-Ч', 'm',
     'leather', 80, 'чёрный'),
    ('leather_red', 'Искусственная кожа «Винилискожа-Т»', 'ИК-ВТ-К', 'm',
     'leather', 50, 'красный'),
    ('ppu50', 'Поролон ППУ ST 2536, лист 2000×1000×50 мм', 'ППУ-50', 'pc',
     'polymer', 40, ''),
    ('ppu100', 'Поролон ППУ HL 3030, лист 2000×1000×100 мм', 'ППУ-100',
     'pc', 'polymer', 30, ''),
    ('npe', 'Пенополиэтилен НПЭ 10 мм, рулон 1,05×50 м', 'НПЭ-10', 'roll',
     'polymer', 4, ''),
    ('eva', 'Гранулы EVA (этиленвинилацетат)', 'EVA-GR', 'kg',
     'polymer', 300, ''),
    ('pp', 'Полипропилен гранулированный PP H030 GP', 'PP-H030', 'kg',
     'polymer', 400, ''),
    ('crumb', 'Резиновая крошка, фракция 2–3 мм', 'РК-2-3', 'kg',
     'polymer', 400, ''),
    ('zipper', 'Молния спиральная Т5 (рулонная)', 'МЛ-Т5', 'm',
     'fittings', 200, 'чёрный'),
    ('thread', 'Нитки армированные 45ЛЛ, катушка 5000 м', 'НТ-45ЛЛ', 'pc',
     'fittings', 20, 'чёрный'),
    ('strap', 'Стропа ременная 40 мм', 'СТР-40', 'm',
     'fittings', 150, 'чёрный'),
    ('carabine', 'Карабин стальной оцинкованный 8 мм', 'КР-8', 'pc',
     'fittings', 100, ''),
    ('chain', 'Цепь подвесная для мешка, 4 точки', 'ЦП-4', 'set',
     'fittings', 30, ''),
    ('velcro', 'Лента контактная (велкро) 50 мм', 'ЛК-50', 'm',
     'fittings', 100, 'чёрный'),
    ('spring', 'Пружина батутная оцинкованная 140 мм', 'ПБ-140', 'pc',
     'fittings', 300, ''),
]

# ключ, артикул, наименование, категория, размер, цвет, себест., цена,
# описание
PRODUCTS = [
    ('mat10_blue', 'МГ-10-С', 'Мат гимнастический складной', 'equipment',
     '100×200×10', 'синий', 3500, 6900,
     'Чехол из тентовой ткани ПВХ, наполнитель — поролон повышенной '
     'жёсткости. Складывается пополам, ручки для переноски.'),
    ('mat10_red', 'МГ-10-К', 'Мат гимнастический складной', 'equipment',
     '100×200×10', 'красный', 3500, 6900,
     'Чехол из тентовой ткани ПВХ, наполнитель — поролон повышенной '
     'жёсткости. Складывается пополам, ручки для переноски.'),
    ('mat5_blue', 'МГ-5-С', 'Мат гимнастический', 'equipment',
     '100×200×5', 'синий', 2150, 4900,
     'Для школьных спортивных залов и домашних занятий.'),
    ('bag100', 'МБ-30-100', 'Мешок боксёрский', 'equipment', 'Ø30×100',
     'чёрный', 2100, 6500,
     'Искусственная кожа, наполнитель — резиновая крошка. Масса около '
     '30 кг, подвес на четырёх цепях.'),
    ('bag120', 'МБ-35-120', 'Мешок боксёрский', 'equipment', 'Ø35×120',
     'чёрный', 2950, 8900,
     'Искусственная кожа, наполнитель — резиновая крошка. Масса около '
     '45 кг, подвес на четырёх цепях.'),
    ('bag80', 'МБ-25-80-К', 'Мешок боксёрский', 'equipment', 'Ø25×80',
     'красный', 1450, 4700,
     'Облегчённая модель для детских секций и домашних тренировок.'),
    ('step', 'СП-3У', 'Степ-платформа трёхуровневая', 'equipment',
     '68×28', 'серый', 290, 2300,
     'Три уровня высоты: 10, 15 и 20 см. Нескользящее покрытие.'),
    ('puzzle', 'ПП-EVA-10', 'Покрытие пазловое EVA 50×50 см', 'equipment',
     '10 мм', 'мульти', 70, 190,
     'Модульное напольное покрытие. Продаётся поштучно, по 4 плитки в '
     'упаковке.'),
    ('cube', 'ММ-К-40', 'Мягкий модуль «Кубик»', 'equipment', '40×40×40',
     'жёлтый', 1000, 2600,
     'Для детских игровых и спортивных комнат. Съёмный чехол на '
     'молнии.'),
    ('tramp', 'БТ-140', 'Батут с защитной сеткой', 'equipment', 'Ø140',
     'синий', 1500, 9800,
     'Каркас из стальной трубы, 30 пружин, защитная сетка по периметру.'),
    ('cover100', 'ЧХ-МБ-100', 'Чехол для боксёрского мешка', 'accessories',
     '100', 'чёрный', 540, 2100,
     'Запасной чехол из искусственной кожи для мешков высотой 100 см.'),
]

# номер, дата, поставщик (индекс), [(материал, количество, цена)]
INBOUND = [
    ('ПР-000101', date(2026, 7, 1), 0, [
        ('pvc_blue', 300, '185.00'), ('pvc_red', 200, '185.00'),
        ('oxford', 150, '210.00')]),
    ('ПР-000102', date(2026, 7, 3), 1, [
        ('ppu50', 80, '1450.00'), ('ppu100', 60, '2750.00')]),
    ('ПР-000103', date(2026, 7, 8), 2, [
        ('eva', 600, '240.00'), ('pp', 800, '145.00'),
        ('crumb', 1800, '38.00'), ('npe', 6, '5900.00')]),
    ('ПР-000104', date(2026, 7, 10), 3, [
        ('zipper', 400, '18.00'), ('thread', 30, '690.00'),
        ('strap', 300, '42.00'), ('carabine', 200, '55.00'),
        ('chain', 80, '380.00'), ('velcro', 200, '24.00'),
        ('spring', 600, '29.00')]),
    ('ПР-000105', date(2026, 7, 17), 0, [
        ('leather_black', 150, '420.00'), ('leather_red', 80, '420.00'),
        ('pvc_blue', 200, '192.00')]),
    ('ПР-000106', date(2026, 9, 17), 1, [
        ('ppu50', 60, '1520.00'), ('ppu100', 20, '2890.00')]),
    ('ПР-000107', date(2026, 9, 24), 3, [
        ('zipper', 300, '18.50'), ('thread', 20, '705.00'),
        ('carabine', 150, '56.00')]),
]

# Непроведённый приход (черновик) и приход, удалённый в корзину
DRAFT_INBOUND = ('ПР-000108', date(2026, 9, 28), 0, [
    ('oxford', 120, '215.00'), ('leather_black', 80, '435.00')])
TRASHED_INBOUND = ('ПР-000109', date(2026, 9, 29), 2, [
    ('eva', 200, '245.00')])

# продукция, количество, дата, [(материал, количество)]
PRODUCTION = [
    ('mat10_blue', 30, date(2026, 7, 14), [
        ('pvc_blue', '87'), ('ppu100', '30'), ('zipper', '30'),
        ('thread', '3'), ('velcro', '12')]),
    ('mat10_red', 20, date(2026, 7, 15), [
        ('pvc_red', '58'), ('ppu100', '20'), ('zipper', '20'),
        ('thread', '2'), ('velcro', '8')]),
    ('mat5_blue', 25, date(2026, 7, 21), [
        ('pvc_blue', '67.5'), ('ppu50', '25'), ('zipper', '25'),
        ('thread', '2')]),
    ('bag100', 25, date(2026, 7, 23), [
        ('leather_black', '32.5'), ('crumb', '700'), ('chain', '25'),
        ('carabine', '25'), ('strap', '30'), ('thread', '2.5')]),
    ('step', 60, date(2026, 7, 28), [('pp', '126')]),
    ('puzzle', 400, date(2026, 7, 30), [('eva', '112')]),
    ('cube', 30, date(2026, 8, 11), [
        ('ppu50', '15'), ('oxford', '36'), ('zipper', '12'),
        ('thread', '1')]),
    ('bag120', 12, date(2026, 8, 13), [
        ('leather_black', '20'), ('crumb', '520'), ('chain', '12'),
        ('carabine', '12'), ('strap', '15'), ('thread', '1.5')]),
    ('bag80', 15, date(2026, 8, 18), [
        ('leather_red', '15'), ('crumb', '240'), ('chain', '15'),
        ('carabine', '15'), ('thread', '1')]),
    ('tramp', 10, date(2026, 8, 25), [
        ('spring', '300'), ('pvc_blue', '22'), ('strap', '40')]),
    ('cover100', 20, date(2026, 9, 18), [
        ('leather_black', '24'), ('zipper', '20'), ('thread', '1')]),
    ('mat10_blue', 20, date(2026, 9, 22), [
        ('pvc_blue', '60'), ('ppu100', '20'), ('zipper', '20'),
        ('thread', '2'), ('velcro', '8')]),
]

# Списание испорченного материала
WRITEOFF = ('РС-000201', date(2026, 8, 20), [('pvc_red', '4', '185.00')])

# покупатель, телефон, e-mail, адрес, [(продукция, количество)],
# итоговый статус, дата оформления
ORDERS = [
    ('Орлов Дмитрий Сергеевич', '+7 916 204-18-37', 'orlov.d@example.ru',
     'Московская обл., г. Дмитров, ул. Школьная, д. 5, кв. 12',
     [('mat10_blue', 2)], 'shipped', date(2026, 8, 3)),
    ('Никитина Елена Андреевна', '+7 926 318-44-05', '',
     'Московская обл., г. Яхрома, ул. Ленина, д. 21',
     [('bag100', 1), ('mat5_blue', 1)], 'shipped', date(2026, 8, 19)),
    ('Фёдоров Павел Игоревич', '+7 903 771-29-64', 'fedorov.p@example.ru',
     'г. Москва, ул. Академика Королёва, д. 8, кв. 45',
     [('step', 4)], 'cancelled', date(2026, 9, 1)),
    ('Морозова Анна Викторовна', '+7 915 460-82-19', '',
     'Московская обл., г. Лобня, ул. Ленина, д. 3, кв. 7',
     [('puzzle', 40), ('cube', 2)], 'confirmed', date(2026, 9, 21)),
    ('Григорьев Артём Денисович', '+7 910 385-72-46', '',
     'Московская обл., г. Дмитров, ул. Профессиональная, д. 30, кв. 5',
     [('step', 2), ('puzzle', 16)], 'shipped', date(2026, 9, 23)),
    ('Волков Игорь Николаевич', '+7 985 132-57-90', 'volkov@example.ru',
     'Московская обл., г. Дмитров, мкр. Внуковский, д. 14, кв. 30',
     [('bag120', 1)], 'confirmed', date(2026, 9, 24)),
    ('Соколова Татьяна Юрьевна', '+7 917 208-66-41', '',
     'Московская обл., г. Долгопрудный, Лихачёвский пр-т, д. 6',
     [('mat5_blue', 3)], 'new', date(2026, 9, 28)),
    ('Лебедева Ксения Олеговна', '+7 962 590-13-28', 'k.lebedeva@example.ru',
     'Московская обл., г. Сергиев Посад, пр-т Красной Армии, д. 45',
     [('tramp', 1)], 'new', date(2026, 9, 29)),
    ('Кузьмин Роман Алексеевич', '+7 929 744-35-16', '',
     'Московская обл., пос. Некрасовский, ул. Строительная, д. 2',
     [('bag80', 2), ('mat5_blue', 1)], 'new', date(2026, 9, 29)),
]

# Инвентаризация склада сырья: номер, дата, расхождения (факт − учёт)
INVENTORY = ('ИНВ-2026-09', date(2026, 9, 15),
             {'zipper': '-6', 'thread': '-1', 'carabine': '2'})

# Справочники заводятся до первых операций; правки экономиста — после
# того как выпуск ВЫП-00012 показал рост себестоимости мата
CATALOG_DAY = date(2026, 6, 30)
ECONOMIST_DAY = date(2026, 9, 23)

LAST_DAY = date(2026, 9, 29)


def _at(day, hour=10, minute=0):
    """Момент времени в часовом поясе проекта."""
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def _new_ids(model, before):
    """Записи модели, появившиеся после снимка before."""
    return model.objects.exclude(id__in=before)


class Command(BaseCommand):
    help = 'Заполнить пустую базу демонстрационными данными'

    def add_arguments(self, parser):
        parser.add_argument('--password', default='demo12345',
                            help='Пароль демонстрационных учётных записей')
        parser.add_argument('--to-today', action='store_true',
                            help='Сдвинуть даты так, чтобы последние '
                                 'события пришлись на вчерашний день')

    def handle(self, *args, **options):
        if Material.objects.exists() or Product.objects.exists():
            raise CommandError(
                'В базе уже есть материалы или продукция. Команда '
                'заполняет только пустую базу: сохраните копию '
                '(manage.py backup), начните с новой базы и повторите.')
        self.shift = timedelta(0)
        if options['to_today']:
            yesterday = timezone.localdate() - timedelta(days=1)
            self.shift = yesterday - LAST_DAY
        with transaction.atomic():
            self._seed(options['password'])
        self.stdout.write(self.style.SUCCESS(
            'Демонстрационные данные загружены. Вход: admin, пароль — '
            f'{options["password"]}.'))

    def d(self, day):
        return day + self.shift

    @contextmanager
    def _dated(self, day, hour, minute=0):
        """Записи журнала действий, сделанные внутри блока, — задним числом.

        Журнал ставит время сам, в момент записи. Без поправки все
        действия демонстрационной базы оказались бы сделанными в одну
        минуту — в день загрузки, а не в дни самих операций.
        """
        before = set(AuditEntry.objects.values_list('id', flat=True))
        yield
        AuditEntry.objects.exclude(id__in=before).update(
            happened_at=_at(self.d(day), hour, minute))

    # ------------------------------------------------------------------
    def _as(self, user, func, *args):
        token = set_current_user(user)
        try:
            return func(*args)
        finally:
            reset_current_user(token)

    def _seed(self, password):
        User = get_user_model()
        self.users = {}
        with self._dated(CATALOG_DAY, 9, 0):
            for login, last, first, middle, role, is_super in USERS:
                user = User(username=login, last_name=last,
                            first_name=first, patronymic=middle, role=role,
                            is_staff=is_super, is_superuser=is_super,
                            email=f'{login}@leko.example')
                user.set_password(password)
                user.save()
                self.users[role] = user
        with self._dated(CATALOG_DAY, 10, 0):
            self._as(self.users['economist'], self._catalogs)

        events = []
        for row in INBOUND:
            events.append((row[1], 0, self._inbound, row))
        for row in PRODUCTION:
            events.append((row[2], 1, self._produce, row))
        events.append((WRITEOFF[1], 2, self._writeoff, WRITEOFF))
        for row in ORDERS:
            events.append((row[6], 3, self._order, row))
        events.append((INVENTORY[1], 4, self._inventory, INVENTORY))
        events.append((DRAFT_INBOUND[1], 5, self._draft, DRAFT_INBOUND))
        events.append((TRASHED_INBOUND[1], 6, self._trashed,
                       TRASHED_INBOUND))
        events.append((ECONOMIST_DAY, 7, self._economist_edits, None))
        events.sort(key=lambda e: (e[0], e[1]))

        # Время дня, которым помечаются записи журнала действий
        times = {self._inbound: (9, 30), self._produce: (15, 0),
                 self._writeoff: (11, 0), self._inventory: (17, 30),
                 self._draft: (10, 0), self._trashed: (11, 20),
                 self._economist_edits: (11, 0)}
        users = {self._order: self.users['manager'],
                 self._economist_edits: self.users['economist']}
        for day, _, handler, row in events:
            user = users.get(handler, self.users['storekeeper'])
            if handler == self._order:
                # время каждого шага заказа своё — см. _order
                self._as(user, handler, row)
                continue
            with self._dated(day, *times[handler]):
                self._as(user, handler, row)

    # ------------------------------------------------------------------
    def _catalogs(self):
        for code, name, full, okei in EXTRA_UNITS:
            Unit.objects.get_or_create(
                code=code, defaults={'name': name, 'full_name': full,
                                     'okei': okei})
        self.raw = Warehouse.objects.create(
            name='Склад сырья и материалов', type='raw',
            location='Корпус 1, первый этаж', capacity=1200)
        self.finished = Warehouse.objects.create(
            name='Склад готовой продукции', type='finished',
            location='Корпус 2', capacity=800)
        self.suppliers = [Supplier.objects.create(
            name=name, contact_person=person, phone=phone)
            for name, person, phone in SUPPLIERS]
        self.materials = {}
        for key, name, art, unit, cat, reorder, color in MATERIALS:
            self.materials[key] = Material.objects.create(
                name=name, article_number=art, unit=unit, category=cat,
                reorder_point=D(reorder), color=color)
        self.products = {}
        for (key, art, name, cat, size, color, cost, price,
             descr) in PRODUCTS:
            product = Product.objects.create(
                article_number=art, name=name, category=cat, size=size,
                color=color, cost=D(cost), selling_price=D(price),
                description=descr)
            picture = picture_for(product)
            if picture:
                product.photo.save(f'demo-product-{product.pk}.jpg',
                                   ContentFile(picture), save=True)
            self.products[key] = product

    def _make_inbound(self, row):
        number, day, sup, lines = row
        doc = InboundDocument.objects.create(
            doc_number=number, doc_date=self.d(day),
            supplier=self.suppliers[sup], warehouse=self.raw,
            created_by=self.users['storekeeper'])
        for key, qty, price in lines:
            InboundItem.objects.create(
                inbound_doc=doc, material=self.materials[key],
                quantity=D(qty), unit_price=D(price))
        InboundDocument.objects.filter(pk=doc.pk).update(
            created_at=_at(self.d(day), 9, 0))
        return doc

    def _inbound(self, row):
        day = row[1]
        doc = self._make_inbound(row)
        moves = set(StockMovement.objects.values_list('id', flat=True))
        prices = set(PriceHistory.objects.values_list('id', flat=True))
        process_inbound_document(doc.id, user=self.users['storekeeper'])
        _new_ids(StockMovement, moves).update(
            created_at=_at(self.d(day), 9, 30))
        _new_ids(PriceHistory, prices).update(
            recorded_at=_at(self.d(day), 9, 30))

    def _draft(self, row):
        self._make_inbound(row)

    def _trashed(self, row):
        doc = self._make_inbound(row)
        doc.deleted_at = _at(self.d(row[1]), 11, 20)
        doc.deleted_by = self.users['storekeeper']
        doc.save()

    def _produce(self, row):
        key, qty, day, lines = row
        moves = set(StockMovement.objects.values_list('id', flat=True))
        run = produce_product(
            self.products[key].id, qty, self.finished.id,
            [{'material': self.materials[m].id, 'quantity': q}
             for m, q in lines],
            self.raw.id, user=self.users['storekeeper'])
        ProductionRun.objects.filter(pk=run.pk).update(
            created_at=_at(self.d(day), 15, 0))
        _new_ids(StockMovement, moves).update(
            created_at=_at(self.d(day), 15, 0))

    def _writeoff(self, row):
        number, day, lines = row
        doc = OutboundDocument.objects.create(
            doc_number=number, doc_date=self.d(day), warehouse=self.raw,
            purpose='writeoff', created_by=self.users['storekeeper'])
        for key, qty, price in lines:
            OutboundItem.objects.create(
                outbound_doc=doc, material=self.materials[key],
                quantity=D(qty), unit_price=D(price))
        moves = set(StockMovement.objects.values_list('id', flat=True))
        process_outbound_document(doc.id, user=self.users['storekeeper'])
        _new_ids(StockMovement, moves).update(
            created_at=_at(self.d(day), 11, 0))
        OutboundDocument.objects.filter(pk=doc.pk).update(
            created_at=_at(self.d(day), 10, 45))

    def _order(self, row):
        name, phone, email, address, items, status, day = row
        # Заказ оформляет покупатель на витрине — не сотрудник
        token = set_current_user(None)
        try:
            with self._dated(day, 12, 15):
                order = create_order(
                    name, phone,
                    [{'product': self.products[k].id, 'quantity': q}
                     for k, q in items],
                    customer_email=email, address=address)
        finally:
            reset_current_user(token)
        type(order).objects.filter(pk=order.pk).update(
            created_at=_at(self.d(day), 12, 15))
        if status in ('confirmed', 'shipped'):
            with self._dated(day, 14, 5):
                confirm_order(order.id)
        if status == 'shipped':
            moves = set(StockMovement.objects.values_list('id', flat=True))
            token = set_current_user(self.users['storekeeper'])
            try:
                with self._dated(day, 16, 40):
                    ship_order(order.id, self.finished.id,
                               user=self.users['storekeeper'])
            finally:
                reset_current_user(token)
            _new_ids(StockMovement, moves).update(
                created_at=_at(self.d(day), 16, 40))
            OutboundDocument.objects.filter(
                doc_number=f'ОТГ-{order.number}').update(
                doc_date=self.d(day), created_at=_at(self.d(day), 16, 30))
        if status == 'cancelled':
            with self._dated(day, 13, 30):
                cancel_order(order.id)

    def _inventory(self, row):
        number, day, deltas = row
        inv = Inventory.objects.create(
            number=number, warehouse=self.raw,
            created_by=self.users['storekeeper'])
        build_inventory_sheet(inv.id)
        by_material = {self.materials[k].id: D(v) for k, v in deltas.items()}
        for item in inv.items.all():
            item.actual_quantity = (item.system_quantity
                                    + by_material.get(item.material_id,
                                                      D('0')))
            item.save()
        moves = set(StockMovement.objects.values_list('id', flat=True))
        finalize_inventory(inv.id, user=self.users['storekeeper'])
        Inventory.objects.filter(pk=inv.pk).update(
            created_at=_at(self.d(day), 9, 0),
            completed_at=_at(self.d(day), 17, 30))
        _new_ids(StockMovement, moves).update(
            created_at=_at(self.d(day), 17, 30))

    def _economist_edits(self, row=None):
        # Поролон подорожал — отпускная цена мата поднята; минимальный
        # остаток резиновой крошки увеличен под растущий выпуск мешков.
        # Записи перечитываются из базы: у объектов, созданных выше,
        # числа хранятся в том виде, в каком их передали («3500»), а
        # журнал действий сравнивает с сохранённым («3500.00») и увидел
        # бы изменение там, где его нет.
        mat = Product.objects.get(pk=self.products['mat10_blue'].pk)
        mat.selling_price = D('7200.00')
        mat.save()
        crumb = Material.objects.get(pk=self.materials['crumb'].pk)
        crumb.reorder_point = D('500.00')
        crumb.save()
