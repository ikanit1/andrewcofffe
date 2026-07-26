import pytest

from app.services import images

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


@pytest.mark.parametrize("data, expected", [
    (PNG, "image/png"),
    (JPEG, "image/jpeg"),
    (GIF, "image/gif"),
    (WEBP, "image/webp"),
])
def test_detects_real_image_formats(data, expected):
    assert images.detect_image_mime(data) == expected


def test_rejects_svg_even_though_browsers_render_it():
    """SVG — это XML со скриптами внутри. Отдать его обратно с image/svg+xml
    значит получить хранимый XSS на странице, которая показывает фото."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert images.detect_image_mime(svg) is None


def test_rejects_html_disguised_as_image():
    assert images.detect_image_mime(b"<!DOCTYPE html><script>alert(1)</script>") is None


def test_rejects_empty_and_short_input():
    assert images.detect_image_mime(b"") is None
    assert images.detect_image_mime(b"\x89PN") is None


def test_rejects_executable():
    assert images.detect_image_mime(b"MZ\x90\x00" + b"\x00" * 32) is None


def test_png_prefix_alone_is_not_enough():
    """Полная сигнатура PNG — 8 байт; совпадения первых четырёх мало."""
    assert images.detect_image_mime(b"\x89PNG-bytes-and-more") is None


def test_validate_returns_detected_mime_ignoring_client_claim():
    """Тип берём из содержимого: заголовок от клиента подделывается тривиально."""
    assert images.validate_image(PNG, claimed_mime="image/jpeg") == "image/png"


def test_validate_rejects_non_image():
    with pytest.raises(ValueError, match="не изображение"):
        images.validate_image(b"just text", claimed_mime="image/png")


def test_validate_rejects_oversized_file():
    big = JPEG + b"\x00" * images.MAX_IMAGE_BYTES
    with pytest.raises(ValueError, match="слишком большой"):
        images.validate_image(big, claimed_mime="image/jpeg")


def test_validate_accepts_file_at_the_limit():
    exact = JPEG + b"\x00" * (images.MAX_IMAGE_BYTES - len(JPEG))
    assert len(exact) == images.MAX_IMAGE_BYTES
    assert images.validate_image(exact, claimed_mime="image/jpeg") == "image/jpeg"
