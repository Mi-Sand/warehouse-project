"""
Рисунки товаров для демонстрационной витрины.

Настоящих фотографий у демонстрационной базы нет, а пустые карточки
«фото готовится» плохо показывают, как выглядит витрина. Поэтому
товары получают простые плоские иллюстрации, нарисованные здесь же
средствами Pillow — той же библиотеки, что сжимает загружаемые фото.
Рисунок строится в двойном размере и уменьшается: так края выходят
сглаженными.
"""
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

W, H = 1200, 900
S = 2  # запас для сглаживания

COLORS = {
    'синий': ((38, 92, 170), (27, 66, 128)),
    'красный': ((196, 48, 43), (148, 33, 30)),
    'чёрный': ((46, 48, 54), (24, 25, 29)),
    'серый': ((128, 134, 142), (92, 97, 104)),
    'жёлтый': ((240, 190, 40), (205, 150, 20)),
}


def _canvas():
    img = Image.new('RGB', (W * S, H * S), (241, 243, 246))
    d = ImageDraw.Draw(img)
    # мягкий вертикальный градиент фона
    for y in range(H * S):
        t = y / (H * S)
        c = int(248 - 18 * t)
        d.line([(0, y), (W * S, y)], fill=(c, c + 1, c + 4))
    return img


def _shadow(img, box, radius=60):
    """Размытая тень под предметом."""
    layer = Image.new('L', img.size, 0)
    ImageDraw.Draw(layer).ellipse(box, fill=110)
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    dark = Image.new('RGB', img.size, (60, 64, 72))
    img.paste(dark, (0, 0), layer)


def _p(*pts):
    return [(x * S, y * S) for x, y in pts]


def _finish(img):
    img = img.resize((W, H), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, 'JPEG', quality=88)
    return buf.getvalue()


def draw_mat(color, folded=True):
    img = _canvas()
    face, side = COLORS.get(color, COLORS['синий'])
    _shadow(img, _p((170, 610), (1030, 800)))
    d = ImageDraw.Draw(img)
    if folded:
        # две сложенные секции мата в изометрии
        for dy in (0, -95):
            top = _p((250, 470 + dy), (760, 410 + dy), (980, 520 + dy),
                     (470, 580 + dy))
            front = _p((250, 470 + dy), (470, 580 + dy), (470, 670 + dy),
                       (250, 560 + dy))
            right = _p((470, 580 + dy), (980, 520 + dy), (980, 610 + dy),
                       (470, 670 + dy))
            d.polygon(front, fill=side)
            d.polygon(right, fill=tuple(int(c * 0.85) for c in face))
            d.polygon(top, fill=face)
            # строчка по краю
            d.line(_p((275, 478 + dy), (752, 422 + dy)), fill=(230, 230, 235),
                   width=3 * S)
        # ручки
        d.arc(_p((600, 560), (700, 640)), 0, 180, fill=(20, 20, 24),
              width=10 * S)
    else:
        top = _p((200, 520), (760, 450), (1010, 560), (450, 630))
        front = _p((200, 520), (450, 630), (450, 680), (200, 570))
        right = _p((450, 630), (1010, 560), (1010, 610), (450, 680))
        d.polygon(front, fill=side)
        d.polygon(right, fill=tuple(int(c * 0.85) for c in face))
        d.polygon(top, fill=face)
        d.line(_p((225, 528), (752, 462)), fill=(230, 230, 235), width=3 * S)
    return _finish(img)


def draw_bag(color, height=1.0):
    img = _canvas()
    face, side = COLORS.get(color, COLORS['чёрный'])
    h = int(470 * height)
    top_y = 250 + (470 - h)
    _shadow(img, _p((440, 700), (760, 780)))
    d = ImageDraw.Draw(img)
    # цепи к кольцу
    ring = (600, 120)
    for x in (470, 545, 655, 730):
        d.line(_p(ring, (x, top_y + 20)), fill=(150, 152, 158), width=5 * S)
    d.ellipse(_p((580, 100), (620, 140)), outline=(150, 152, 158),
              width=6 * S)
    # корпус мешка
    d.rectangle(_p((460, top_y + 20), (740, top_y + h)), fill=face)
    d.ellipse(_p((460, top_y + h - 40), (740, top_y + h + 40)), fill=face)
    d.ellipse(_p((460, top_y - 10), (740, top_y + 50)), fill=side)
    # блик и швы
    d.rectangle(_p((505, top_y + 40), (525, top_y + h - 10)),
                fill=tuple(min(255, c + 45) for c in face))
    for k in (0.33, 0.66):
        y = top_y + 20 + int((h - 20) * k)
        d.arc(_p((460, y - 30), (740, y + 30)), 0, 180,
              fill=tuple(min(255, c + 25) for c in face), width=3 * S)
    return _finish(img)


def draw_step(color):
    img = _canvas()
    face, side = COLORS.get(color, COLORS['серый'])
    _shadow(img, _p((200, 600), (1000, 760)))
    d = ImageDraw.Draw(img)
    top = _p((250, 430), (760, 380), (960, 460), (450, 520))
    d.polygon(_p((250, 430), (450, 520), (450, 640), (270, 560)),
              fill=side)
    d.polygon(_p((450, 520), (960, 460), (940, 580), (450, 640)),
              fill=tuple(int(c * 0.9) for c in face))
    d.polygon(top, fill=(40, 42, 46))
    for i in range(1, 9):  # рифление покрытия
        t = i / 9
        a = (250 + (760 - 250) * t, 430 + (380 - 430) * t)
        b = (450 + (960 - 450) * t, 520 + (460 - 520) * t)
        d.line(_p(a, b), fill=(70, 72, 78), width=3 * S)
    return _finish(img)


def draw_puzzle():
    img = _canvas()
    _shadow(img, _p((260, 660), (940, 800)))
    d = ImageDraw.Draw(img)
    size = 280
    tiles = [((320, 370), (213, 60, 60)), ((610, 370), (40, 120, 200)),
             ((320, 660), (250, 200, 40)), ((610, 660), (60, 160, 90))]
    for (x, y), c in tiles:
        d.rectangle(_p((x, y - size), (x + size, y)), fill=c)
    for (x, y), c in tiles:  # «замки» между плитками
        if x == 320:
            for k in (0.3, 0.7):
                cy = y - size + int(size * k)
                d.ellipse(_p((x + size - 22, cy - 22), (x + size + 22, cy + 22)),
                          fill=c)
        if y == 370:
            for k in (0.3, 0.7):
                cx = x + int(size * k)
                d.ellipse(_p((cx - 22, y - 22), (cx + 22, y + 22)), fill=c)
    return _finish(img)


def draw_cube(color):
    img = _canvas()
    face, side = COLORS.get(color, COLORS['жёлтый'])
    _shadow(img, _p((300, 640), (900, 780)))
    d = ImageDraw.Draw(img)
    top = _p((600, 180), (870, 300), (600, 420), (330, 300))
    left = _p((330, 300), (600, 420), (600, 720), (330, 600))
    right = _p((600, 420), (870, 300), (870, 600), (600, 720))
    d.polygon(left, fill=side)
    d.polygon(right, fill=tuple(int(c * 0.9) for c in face))
    d.polygon(top, fill=tuple(min(255, c + 12) for c in face))
    d.line(_p((360, 330), (600, 440), (840, 330)), fill=(90, 70, 20),
           width=3 * S)  # молния чехла
    return _finish(img)


def draw_trampoline(color):
    img = _canvas()
    face, _ = COLORS.get(color, COLORS['синий'])
    _shadow(img, _p((200, 700), (1000, 820)))
    d = ImageDraw.Draw(img)
    for x in (300, 900, 460, 740):  # ноги
        d.line(_p((x, 560), (x - 20, 760)), fill=(90, 94, 100), width=12 * S)
    d.ellipse(_p((200, 470), (1000, 650)), fill=face)
    d.ellipse(_p((260, 495), (940, 625)), fill=(30, 32, 36))
    for x in (230, 400, 600, 800, 970):  # стойки сетки
        d.line(_p((x, 560), (x, 200)), fill=(90, 94, 100), width=8 * S)
    net = Image.new('RGBA', img.size, (0, 0, 0, 0))
    nd = ImageDraw.Draw(net)
    nd.rectangle(_p((230, 210), (970, 560)), fill=(40, 40, 50, 40))
    for x in range(230, 971, 30):
        nd.line(_p((x, 210), (x, 560)), fill=(40, 40, 50, 70), width=S)
    for y in range(210, 561, 30):
        nd.line(_p((230, y), (970, y)), fill=(40, 40, 50, 70), width=S)
    img = Image.alpha_composite(img.convert('RGBA'), net).convert('RGB')
    return _finish(img)


def draw_cover(color):
    img = _canvas()
    face, side = COLORS.get(color, COLORS['чёрный'])
    _shadow(img, _p((260, 620), (940, 760)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(_p((300, 300), (900, 660)), radius=40 * S, fill=face)
    d.rounded_rectangle(_p((330, 250), (870, 330)), radius=30 * S, fill=side)
    d.line(_p((330, 480), (870, 480)), fill=(170, 170, 176), width=6 * S)
    d.rectangle(_p((840, 468), (880, 492)), fill=(200, 200, 206))
    return _finish(img)


def picture_for(product):
    """Байты JPEG-рисунка для товара — по его артикулу."""
    art = product.article_number
    if art.startswith('МГ-10'):
        return draw_mat(product.color, folded=True)
    if art.startswith('МГ-5'):
        return draw_mat(product.color, folded=False)
    if art.startswith('МБ'):
        height = {'МБ-35-120': 1.0, 'МБ-30-100': 0.85}.get(art, 0.7)
        return draw_bag(product.color, height)
    if art.startswith('СП'):
        return draw_step(product.color)
    if art.startswith('ПП'):
        return draw_puzzle()
    if art.startswith('ММ'):
        return draw_cube(product.color)
    if art.startswith('БТ'):
        return draw_trampoline(product.color)
    if art.startswith('ЧХ'):
        return draw_cover(product.color)
    return None
