"""Рисует иконку для ярлыка кассы: чашка на фирменном кофейном фоне.

Запускается один раз при установке ярлыков; результат — deploy/coffee-pos.ico.
Пересоздавать при каждом запуске не нужно, файл лежит в репозитории.
"""
from pathlib import Path

from PIL import Image, ImageDraw

BG = (107, 66, 38)       # coffee-700 из дизайн-системы
CUP = (245, 236, 224)    # coffee-100
SAUCER = (220, 189, 151)  # coffee-300
SIZE = 256


def draw(size: int = SIZE) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = size / 256

    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(56 * k), fill=BG)

    # чашка
    body = [int(58 * k), int(88 * k), int(168 * k), int(184 * k)]
    d.rounded_rectangle(body, radius=int(14 * k), fill=CUP)
    # ручка
    d.ellipse([int(160 * k), int(104 * k), int(214 * k), int(158 * k)],
              outline=CUP, width=int(16 * k))
    # блюдце
    d.rounded_rectangle([int(40 * k), int(190 * k), int(200 * k), int(206 * k)],
                        radius=int(8 * k), fill=SAUCER)
    # пар
    for x in (int(88 * k), int(113 * k), int(138 * k)):
        d.rounded_rectangle([x, int(46 * k), x + int(10 * k), int(76 * k)],
                            radius=int(5 * k), fill=SAUCER)
    return img


def main() -> None:
    out = Path(__file__).with_name("coffee-pos.ico")
    img = draw()
    img.save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"иконка: {out}")


if __name__ == "__main__":
    main()
