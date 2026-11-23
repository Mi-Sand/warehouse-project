"""Порядок размеров в карточке товара на витрине.

Размеры сравнивались как строки, и у одежды выходило «L, M, S, XL»:
покупатель искал свой размер по всему списку.
"""
from rest_framework.test import APITestCase

from warehouse.models import Product, Stock, Warehouse
from warehouse.shop import size_order


class SizeOrderTest(APITestCase):
    def sizes_on_shop(self, name, sizes):
        wh = Warehouse.objects.create(name='Склад', type='finished')
        for number, size in enumerate(sizes):
            p = Product.objects.create(
                article_number=f'{name[:2]}-{number}', name=name,
                category='clothing', size=size, color='серый', cost=100,
                selling_price=200)
            Stock.objects.create(warehouse=wh, product=p, quantity=1)
        data = self.client.get('/api/shop/products/').data
        card = next(c for c in data['products'] if c['name'] == name)
        return [v['size'] for v in card['colors'][0]['variants']]

    def test_clothing_sizes_from_small_to_large(self):
        self.assertEqual(
            self.sizes_on_shop('Толстовка', ['XL', 'S', 'XXL', 'M', 'L']),
            ['S', 'M', 'L', 'XL', 'XXL'])

    def test_shoe_sizes_by_number(self):
        # Строкой «9» оказывался бы после «45»
        self.assertEqual(
            self.sizes_on_shop('Кеды', ['45', '9', '39', '42.5', '40']),
            ['9', '39', '40', '42.5', '45'])

    def test_ranges_by_first_number(self):
        self.assertEqual(
            sorted(['41–43', '35–37', '38–40'], key=size_order),
            ['35–37', '38–40', '41–43'])

    def test_unknown_sizes_go_last(self):
        self.assertEqual(
            sorted(['—', 'M', '42', 'S'], key=size_order),
            ['42', 'S', 'M', '—'])
