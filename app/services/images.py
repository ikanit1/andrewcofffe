"""Проверка загружаемых изображений.

Тип определяется по сигнатуре файла, а не по заголовку от клиента: заголовок
подделывается тривиально, а маршрут /product-image отдаёт файл обратно именно
с этим типом. Пустив сюда image/svg+xml, мы бы отдавали XML со скриптами внутри
с того же origin, что и касса, — то есть получили бы хранимый XSS.
"""

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # фото лежат в SQLite и уезжают в каждый бэкап

# (сигнатура, смещение, mime). WEBP проверяется отдельно — у него метка после размера.
_SIGNATURES: list[tuple[bytes, int, str]] = [
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
]


def detect_image_mime(data: bytes) -> str | None:
    """MIME по содержимому. None — формат не распознан как растровое изображение."""
    for signature, offset, mime in _SIGNATURES:
        if data[offset:offset + len(signature)] == signature:
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(data: bytes, *, claimed_mime: str | None = None) -> str:
    """Проверяет размер и формат. Возвращает настоящий MIME; claimed_mime игнорируется.

    Аргумент claimed_mime принимается только чтобы вызывающий код не соблазнялся
    использовать его напрямую — в возвращаемое значение он не попадает.
    """
    if len(data) > MAX_IMAGE_BYTES:
        limit_mb = MAX_IMAGE_BYTES // (1024 * 1024)
        raise ValueError(f"Файл слишком большой: максимум {limit_mb} МБ")
    mime = detect_image_mime(data)
    if mime is None:
        raise ValueError("Файл не изображение: поддерживаются JPEG, PNG, GIF и WEBP")
    return mime
