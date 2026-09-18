"""Сертификат Минцифры.

Без него запросы к MAX не проходят проверку в контейнере, а на Windows проходят —
значит ошибка проявится только при развёртывании. Поэтому проверяем здесь.
"""
import hashlib
import ssl

import certifi

from bot.tls import ROOT_CA, build_ssl_context

# Отпечаток закреплён нарочно: подмена или порча файла должна вскрыться тестом,
# а не отказом запросов в проде.
ROOT_CA_SHA256 = "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31"


def test_certificate_is_present():
    assert ROOT_CA.is_file(), f"нет файла сертификата {ROOT_CA}"


def test_certificate_is_the_expected_one():
    """Считается отпечаток самого сертификата, а не файла.

    Хеш файла сломался бы от нормализации переводов строк в git, а отпечаток
    сертификата — это его каноническая личность, публикуемая удостоверяющим
    центром, и его можно сверить глазами.
    """
    der = ssl.PEM_cert_to_DER_cert(ROOT_CA.read_text(encoding="ascii"))
    assert hashlib.sha256(der).hexdigest() == ROOT_CA_SHA256


def test_certificate_is_a_readable_pem():
    text = ROOT_CA.read_text(encoding="ascii")
    assert text.lstrip().startswith("-----BEGIN CERTIFICATE-----")
    assert "-----END CERTIFICATE-----" in text


def test_context_still_verifies_certificates():
    """Отключение проверки недопустимо: в каждом запросе уходит токен бота."""
    context = build_ssl_context()
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_context_adds_the_root_to_the_usual_bundle():
    """Корня Минцифры нет в наборе certifi — он должен добавляться поверх."""
    ours = build_ssl_context()

    plain = ssl.create_default_context(cafile=certifi.where())
    assert len(ours.get_ca_certs()) > len(plain.get_ca_certs())

    subjects = [
        value
        for certificate in ours.get_ca_certs()
        for pair in certificate.get("subject", ())
        for key, value in pair
    ]
    assert any("Russian Trusted Root CA" in subject for subject in subjects)
    assert not any(
        "Russian Trusted Root CA" in value
        for certificate in plain.get_ca_certs()
        for pair in certificate.get("subject", ())
        for _, value in pair
    ), "если корень появился в certifi, приложенный файл можно убрать"
