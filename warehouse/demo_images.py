"""Картинки товаров для тестовых данных.

Рисуются здесь же, средствами Pillow, а не берутся из интернета. Тому
есть две причины. Чужие фотографии нельзя класть в репозиторий без
права на них. А скачивать их при наполнении базы негде: система
ставится на складской компьютер, у которого интернета нет.

Рисунок упрощённый — силуэт товара его цветом на светлом фоне, — но
витрина, карточка товара и этикетки с ним выглядят так, как будут
выглядеть с настоящими снимками.

Рисуется с запасом по размеру и затем уменьшается: у Pillow нет
сглаживания краёв, и без запаса фигуры выходят «лесенкой».
"""
import io

from PIL import Image, ImageDraw, ImageFilter

SIZE = 900
SCALE = 2
S = SIZE * SCALE

COLORS = {
    'чёрный': (52, 54, 60),
    'белый': (236, 236, 232),
    'коричневый': (128, 78, 44),
    'серый': (146, 150, 156),
    'синий': (46, 96, 172),
    'зелёный': (64, 150, 98),
    'бежевый': (214, 196, 166),
}
BACKGROUNDS = [
    ((244, 241, 236), (226, 221, 212)),
    ((236, 241, 245), (214, 224, 232)),
]


def shade(color, factor):
    """Тот же цвет светлее (factor > 1) или темнее (factor < 1)."""
    if factor >= 1:
        return tuple(int(c + (255 - c) * (factor - 1)) for c in color)
    return tuple(int(c * factor) for c in color)


def accent(color):
    """Цвет отделки: на тёмном товаре светлый, на светлом тёмный."""
    return (230, 230, 226) if sum(color) < 380 else (60, 62, 68)


def pt(*coords):
    """Координаты в долях стороны → точки увеличенного холста."""
    return [int(c * S) for c in coords]


def poly(*pairs):
    return [(int(x * S), int(y * S)) for x, y in pairs]


def canvas(variant):
    """Фон с мягким вертикальным переходом."""
    top, bottom = BACKGROUNDS[variant % len(BACKGROUNDS)]
    img = Image.new('RGB', (S, S), top)
    draw = ImageDraw.Draw(img)
    for y in range(S):
        k = y / S
        draw.line([(0, y), (S, y)], fill=tuple(
            int(a + (b - a) * k) for a, b in zip(top, bottom)))
    return img


def shadow(img, box):
    """Размытая тень под предметом."""
    layer = Image.new('L', (S, S), 0)
    ImageDraw.Draw(layer).ellipse(pt(*box), fill=90)
    layer = layer.filter(ImageFilter.GaussianBlur(S // 60))
    img.paste((0, 0, 0), mask=layer)


# --- Предметы ---------------------------------------------------------------
def sneaker(draw, color):
    trim = accent(color)
    # верх
    upper = poly((.16, .61), (.17, .44), (.24, .36), (.36, .34), (.46, .40),
                 (.56, .47), (.70, .50), (.82, .53), (.88, .58), (.87, .61))
    draw.polygon(upper, fill=color)
    # задник и язычок
    draw.polygon(poly((.16, .61), (.17, .44), (.24, .36), (.25, .61)),
                 fill=shade(color, .8))
    draw.polygon(poly((.33, .35), (.38, .25), (.46, .27), (.46, .40)),
                 fill=shade(color, 1.15))
    # носок
    draw.ellipse(pt(.66, .49, .90, .67), fill=color)
    draw.chord(pt(.74, .51, .90, .65), 200, 330, fill=shade(color, 1.12))
    # сетка
    for i in range(7):
        x = .50 + i * .045
        draw.line(pt(x, .47 + i * .006, x + .03, .60), fill=shade(color, .85),
                  width=4)
    # полосы отделки
    for i, dx in enumerate((0, .05)):
        draw.line(pt(.30 + dx, .58, .44 + dx, .42), fill=trim, width=16)
    # шнурки
    for i in range(4):
        x, y = .40 + i * .04, .37 + i * .03
        draw.line(pt(x - .015, y, x + .035, y + .02), fill=trim, width=10)
    # подошва — поверх нижнего края верха
    draw.rounded_rectangle(pt(.14, .60, .91, .70), radius=int(.05 * S),
                           fill=(245, 245, 242), outline=(200, 200, 196),
                           width=6)
    draw.line(pt(.17, .665, .88, .665), fill=(205, 205, 200), width=8)


def boot(draw, color):
    trim = accent(color)
    # голенище и союзка
    body = poly((.20, .70), (.21, .22), (.47, .20), (.49, .48), (.66, .52),
                (.80, .57), (.85, .65), (.84, .70))
    draw.polygon(body, fill=color)
    draw.polygon(poly((.20, .70), (.21, .22), (.27, .22), (.28, .70)),
                 fill=shade(color, .8))
    draw.ellipse(pt(.62, .52, .86, .76), fill=color)
    draw.chord(pt(.68, .55, .84, .71), 200, 330, fill=shade(color, 1.12))
    # мех по верху
    draw.rounded_rectangle(pt(.19, .16, .49, .25), radius=int(.04 * S),
                           fill=(232, 222, 204))
    # строчка
    draw.line(pt(.48, .50, .80, .60), fill=shade(color, 1.35), width=5)
    # люверсы и шнуровка
    for i in range(6):
        y = .28 + i * .045
        x = .44 + i * .006
        draw.ellipse(pt(x - .012, y - .012, x + .012, y + .012),
                     fill=(200, 200, 200))
        if i < 5:
            draw.line(pt(x, y, x - .09, y + .045), fill=trim, width=9)
    # подошва с протектором — поверх нижнего края союзки
    draw.rounded_rectangle(pt(.18, .70, .86, .80), radius=int(.03 * S),
                           fill=(48, 44, 40))
    for i in range(12):
        x = .21 + i * .053
        draw.rectangle(pt(x, .78, x + .025, .81), fill=(48, 44, 40))
    draw.rectangle(pt(.18, .69, .86, .715), fill=(210, 190, 150))


def hoodie(draw, color):
    dark, light = shade(color, .8), shade(color, 1.12)
    # рукава
    draw.polygon(poly((.30, .27), (.15, .40), (.10, .78), (.21, .80),
                      (.27, .50)), fill=dark)
    draw.polygon(poly((.70, .27), (.85, .40), (.90, .78), (.79, .80),
                      (.73, .50)), fill=dark)
    draw.rounded_rectangle(pt(.09, .76, .22, .83), radius=int(.02 * S),
                           fill=shade(color, .7))
    draw.rounded_rectangle(pt(.78, .76, .91, .83), radius=int(.02 * S),
                           fill=shade(color, .7))
    # капюшон
    draw.ellipse(pt(.33, .10, .67, .36), fill=dark)
    draw.ellipse(pt(.38, .15, .62, .33), fill=shade(color, .55))
    # корпус
    draw.polygon(poly((.30, .26), (.70, .26), (.74, .82), (.26, .82)),
                 fill=color)
    draw.rounded_rectangle(pt(.26, .80, .74, .87), radius=int(.02 * S),
                           fill=shade(color, .75))
    # молния
    draw.line(pt(.50, .30, .50, .86), fill=(70, 72, 76), width=10)
    draw.rounded_rectangle(pt(.488, .36, .512, .41), radius=6,
                           fill=(200, 200, 204))
    # шнурки капюшона
    for x in (.45, .55):
        draw.line(pt(x, .31, x, .46), fill=light, width=8)
        draw.ellipse(pt(x - .01, .455, x + .01, .475), fill=light)
    # карманы
    draw.polygon(poly((.33, .58), (.48, .58), (.48, .74), (.30, .74)),
                 fill=shade(color, .9))
    draw.polygon(poly((.52, .58), (.67, .58), (.70, .74), (.52, .74)),
                 fill=shade(color, .9))


def bag(draw, color):
    trim = accent(color)
    # ремень
    draw.arc(pt(.17, .08, .83, .82), 180, 360, fill=shade(color, .75),
             width=int(.025 * S))
    # ручки
    draw.arc(pt(.34, .20, .66, .52), 180, 360, fill=shade(color, .7),
             width=int(.03 * S))
    # корпус
    draw.rounded_rectangle(pt(.12, .38, .88, .78), radius=int(.12 * S),
                           fill=color)
    draw.rounded_rectangle(pt(.12, .66, .88, .78), radius=int(.06 * S),
                           fill=shade(color, .82))
    # торцы
    draw.ellipse(pt(.10, .42, .24, .76), fill=shade(color, .88))
    draw.ellipse(pt(.76, .42, .90, .76), fill=shade(color, .88))
    # молния
    draw.line(pt(.22, .42, .78, .42), fill=trim, width=8)
    draw.rounded_rectangle(pt(.62, .41, .66, .48), radius=6, fill=trim)
    # карман и нашивка
    draw.rounded_rectangle(pt(.34, .52, .66, .64), radius=int(.03 * S),
                           outline=shade(color, 1.3), width=6)
    draw.rounded_rectangle(pt(.45, .555, .55, .595), radius=6, fill=trim)


def insoles(draw, color):
    light, dark = shade(color, 1.25), shade(color, .8)
    for dx, flip in ((-.14, True), (.14, False)):
        def foot(x, y):
            return (.5 + dx + (-x if flip else x), y)
        shape = [foot(x, y) for x, y in (
            (-.02, .12), (.07, .14), (.11, .24), (.11, .40), (.08, .55),
            (.09, .70), (.07, .84), (0, .89), (-.07, .86), (-.09, .72),
            (-.08, .52), (-.11, .36), (-.11, .22), (-.07, .14))]
        draw.polygon(poly(*shape), fill=color, outline=dark)
        # пятка и свод
        hx = .5 + dx
        draw.ellipse(pt(hx - .055, .70, hx + .055, .84), fill=dark)
        draw.ellipse(pt(hx - .06, .22, hx + .06, .40), fill=light)
        for i in range(5):
            y = .45 + i * .045
            draw.line(pt(hx - .05, y, hx + .05, y), fill=dark, width=4)


def yoga_mat(draw, color):
    light, dark = shade(color, 1.2), shade(color, .7)
    # развёрнутая часть
    draw.polygon(poly((.18, .74), (.58, .52), (.90, .62), (.50, .86)),
                 fill=color)
    for i in range(1, 6):
        k = i / 6
        a = (.18 + (.58 - .18) * k, .74 + (.52 - .74) * k)
        b = (.50 + (.90 - .50) * k, .86 + (.62 - .86) * k)
        draw.line(poly(a, b), fill=shade(color, .9), width=4)
    # рулон
    draw.polygon(poly((.10, .50), (.50, .28), (.58, .52), (.18, .74)),
                 fill=dark)
    draw.polygon(poly((.10, .50), (.50, .28), (.52, .33), (.12, .55)),
                 fill=light)
    draw.ellipse(pt(.04, .46, .24, .78), fill=color)
    for r in (.08, .055, .03):
        draw.ellipse(pt(.14 - r, .62 - r * 1.6, .14 + r, .62 + r * 1.6),
                     outline=dark, width=6)
    # ремешок
    draw.line(pt(.30, .40, .38, .64), fill=(60, 60, 64), width=14)


# Где под предметом лежит тень: прямо под нижним краем, иначе он висит
SHADOWS = {
    'sneaker': (.12, .65, .92, .75), 'boot': (.14, .75, .88, .85),
    'hoodie': (.18, .80, .82, .90), 'bag': (.10, .72, .90, .84),
    'insoles': (.22, .84, .78, .94), 'mat': (.06, .70, .92, .90),
}

DRAWERS = {
    'sneaker': sneaker, 'boot': boot, 'hoodie': hoodie, 'bag': bag,
    'insoles': insoles, 'mat': yoga_mat,
}


def render(kind, color_name, variant=0):
    """Нарисовать предмет и вернуть JPEG байтами.

    variant — второй ракурс для галереи: зеркальный рисунок на другом
    фоне.
    """
    color = COLORS.get(color_name, COLORS['серый'])
    img = canvas(variant)
    shadow(img, SHADOWS[kind])
    DRAWERS[kind](ImageDraw.Draw(img), color)
    if variant % 2:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=86, optimize=True)
    return buffer.getvalue()
