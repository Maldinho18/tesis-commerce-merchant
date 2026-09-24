"""Ficha técnica por modelo.

Wikidata no sirve como fuente: la propiedad de memoria mezcla RAM y almacenamiento, el
sistema operativo vuelve sin etiqueta y la mayoría de los Samsung no declara nada. La tabla
se cura a mano y **solo incluye lo que se puede afirmar del modelo**: un producto sin entrada
conserva su almacenamiento y su color, que sí son ciertos, en vez de mostrar datos inventados.

Cada entrada es (chip, RAM, pantalla, batería, sistema operativo de lanzamiento).
"""

from typing import Final, NamedTuple


class Spec(NamedTuple):
    chip: str
    ram: str
    screen: str
    battery: str
    os: str


def _s(chip: str, ram: str, screen: str, battery: str, os: str) -> Spec:
    return Spec(chip, ram, screen, battery, os)


SPECS: Final[dict[str, Spec]] = {
    # Apple
    "iPhone 7": _s("Apple A10 Fusion", "2 GB", "4.7 pulgadas", "1960 mAh", "iOS 10"),
    "iPhone 7 Plus": _s("Apple A10 Fusion", "3 GB", "5.5 pulgadas", "2900 mAh", "iOS 10"),
    "iPhone 11": _s("Apple A13 Bionic", "4 GB", "6.1 pulgadas", "3110 mAh", "iOS 13"),
    "iPhone 11 Pro": _s("Apple A13 Bionic", "4 GB", "5.8 pulgadas", "3046 mAh", "iOS 13"),
    "iPhone 12 mini": _s("Apple A14 Bionic", "4 GB", "5.4 pulgadas", "2227 mAh", "iOS 14"),
    "iPhone 12": _s("Apple A14 Bionic", "4 GB", "6.1 pulgadas", "2815 mAh", "iOS 14"),
    "iPhone 12 Pro": _s("Apple A14 Bionic", "6 GB", "6.1 pulgadas", "2815 mAh", "iOS 14"),
    "iPhone 12 Pro Max": _s("Apple A14 Bionic", "6 GB", "6.7 pulgadas", "3687 mAh", "iOS 14"),
    "iPhone 13 mini": _s("Apple A15 Bionic", "4 GB", "5.4 pulgadas", "2438 mAh", "iOS 15"),
    "iPhone 13": _s("Apple A15 Bionic", "4 GB", "6.1 pulgadas", "3240 mAh", "iOS 15"),
    "iPhone 13 Pro": _s("Apple A15 Bionic", "6 GB", "6.1 pulgadas", "3095 mAh", "iOS 15"),
    "iPhone 13 Pro Max": _s("Apple A15 Bionic", "6 GB", "6.7 pulgadas", "4352 mAh", "iOS 15"),
    "iPhone SE (2022)": _s("Apple A15 Bionic", "4 GB", "4.7 pulgadas", "2018 mAh", "iOS 15"),
    "iPhone 14": _s("Apple A15 Bionic", "6 GB", "6.1 pulgadas", "3279 mAh", "iOS 16"),
    "iPhone 14 Plus": _s("Apple A15 Bionic", "6 GB", "6.7 pulgadas", "4325 mAh", "iOS 16"),
    "iPhone 14 Pro": _s("Apple A16 Bionic", "6 GB", "6.1 pulgadas", "3200 mAh", "iOS 16"),
    "iPhone 14 Pro Max": _s("Apple A16 Bionic", "6 GB", "6.7 pulgadas", "4323 mAh", "iOS 16"),
    "iPhone 15": _s("Apple A16 Bionic", "6 GB", "6.1 pulgadas", "3349 mAh", "iOS 17"),
    "iPhone 15 Plus": _s("Apple A16 Bionic", "6 GB", "6.7 pulgadas", "4383 mAh", "iOS 17"),
    "iPhone 15 Pro": _s("Apple A17 Pro", "8 GB", "6.1 pulgadas", "3274 mAh", "iOS 17"),
    "iPhone 15 Pro Max": _s("Apple A17 Pro", "8 GB", "6.7 pulgadas", "4441 mAh", "iOS 17"),
    "iPhone 16e": _s("Apple A18", "8 GB", "6.1 pulgadas", "4005 mAh", "iOS 18"),
    "iPhone 16": _s("Apple A18", "8 GB", "6.1 pulgadas", "3561 mAh", "iOS 18"),
    "iPhone 16 Plus": _s("Apple A18", "8 GB", "6.7 pulgadas", "4674 mAh", "iOS 18"),
    "iPhone 16 Pro": _s("Apple A18 Pro", "8 GB", "6.3 pulgadas", "3582 mAh", "iOS 18"),
    "iPhone 16 Pro Max": _s("Apple A18 Pro", "8 GB", "6.9 pulgadas", "4685 mAh", "iOS 18"),
    "iPhone 17": _s("Apple A19", "8 GB", "6.3 pulgadas", "3692 mAh", "iOS 26"),
    "iPhone 17e": _s("Apple A19", "8 GB", "6.1 pulgadas", "4005 mAh", "iOS 26"),
    "iPhone 17 Pro": _s("Apple A19 Pro", "12 GB", "6.3 pulgadas", "3988 mAh", "iOS 26"),
    "iPhone 17 Pro Max": _s("Apple A19 Pro", "12 GB", "6.9 pulgadas", "4823 mAh", "iOS 26"),
    "iPhone Air": _s("Apple A19 Pro", "12 GB", "6.5 pulgadas", "3149 mAh", "iOS 26"),
    # Google
    "Google Pixel 7a": _s("Google Tensor G2", "8 GB", "6.1 pulgadas", "4385 mAh", "Android 13"),
    "Google Pixel 8": _s("Google Tensor G3", "8 GB", "6.2 pulgadas", "4575 mAh", "Android 14"),
    "Google Pixel 8a": _s("Google Tensor G3", "8 GB", "6.1 pulgadas", "4492 mAh", "Android 14"),
    "Google Pixel 8 Pro": _s("Google Tensor G3", "12 GB", "6.7 pulgadas", "5050 mAh", "Android 14"),
    "Google Pixel 9": _s("Google Tensor G4", "12 GB", "6.3 pulgadas", "4700 mAh", "Android 14"),
    "Google Pixel 9 Pro": _s("Google Tensor G4", "16 GB", "6.3 pulgadas", "4700 mAh", "Android 14"),
    "Google Pixel 9 Pro XL": _s(
        "Google Tensor G4", "16 GB", "6.8 pulgadas", "5060 mAh", "Android 14"
    ),
    # OnePlus
    "OnePlus 7": _s("Snapdragon 855", "8 GB", "6.41 pulgadas", "3700 mAh", "Android 9"),
    "OnePlus 7 Pro": _s("Snapdragon 855", "8 GB", "6.67 pulgadas", "4000 mAh", "Android 9"),
    "OnePlus 8 Pro": _s("Snapdragon 865", "12 GB", "6.78 pulgadas", "4510 mAh", "Android 10"),
    "OnePlus 8T": _s("Snapdragon 865", "8 GB", "6.55 pulgadas", "4500 mAh", "Android 11"),
    "OnePlus 9 Pro": _s("Snapdragon 888", "12 GB", "6.7 pulgadas", "4500 mAh", "Android 11"),
    "OnePlus 11": _s("Snapdragon 8 Gen 2", "16 GB", "6.7 pulgadas", "5000 mAh", "Android 13"),
    "OnePlus 12": _s("Snapdragon 8 Gen 3", "16 GB", "6.82 pulgadas", "5400 mAh", "Android 14"),
    "OnePlus Nord": _s("Snapdragon 765G", "8 GB", "6.44 pulgadas", "4115 mAh", "Android 10"),
    # Sony
    "Sony Xperia 1": _s("Snapdragon 855", "6 GB", "6.5 pulgadas", "3330 mAh", "Android 9"),
    "Sony Xperia 1 II": _s("Snapdragon 865", "8 GB", "6.5 pulgadas", "4000 mAh", "Android 10"),
    "Sony Xperia 1 IV": _s("Snapdragon 8 Gen 1", "12 GB", "6.5 pulgadas", "5000 mAh", "Android 12"),
    "Sony Xperia 1 VI": _s("Snapdragon 8 Gen 3", "12 GB", "6.5 pulgadas", "5000 mAh", "Android 14"),
    "Sony Xperia 5 II": _s("Snapdragon 865", "8 GB", "6.1 pulgadas", "4000 mAh", "Android 10"),
    "Sony Xperia 5 IV": _s("Snapdragon 8 Gen 1", "8 GB", "6.1 pulgadas", "5000 mAh", "Android 12"),
    "Sony Xperia 10 VI": _s("Snapdragon 6 Gen 1", "8 GB", "6.1 pulgadas", "5000 mAh", "Android 14"),
    "Xperia XZ2 Premium": _s("Snapdragon 845", "6 GB", "5.8 pulgadas", "3540 mAh", "Android 8"),
    # Motorola
    "Moto G54 5G": _s("Dimensity 7020", "8 GB", "6.5 pulgadas", "5000 mAh", "Android 13"),
    "Motorola Edge 50 Pro": _s(
        "Snapdragon 7 Gen 3", "12 GB", "6.7 pulgadas", "4500 mAh", "Android 14"
    ),
    "Motorola Moto G Power": _s("Dimensity 6300", "8 GB", "6.7 pulgadas", "5000 mAh", "Android 14"),
    "Motorola Razr 50 Ultra": _s(
        "Snapdragon 8s Gen 3", "12 GB", "6.9 pulgadas", "4000 mAh", "Android 14"
    ),
    # Samsung
    "Samsung Galaxy A12": _s("Helio P35", "4 GB", "6.5 pulgadas", "5000 mAh", "Android 10"),
    "Samsung Galaxy A15": _s("Helio G99", "6 GB", "6.5 pulgadas", "5000 mAh", "Android 14"),
    "Samsung Galaxy A16": _s("Exynos 1330", "6 GB", "6.7 pulgadas", "5000 mAh", "Android 14"),
    "Samsung Galaxy A25 5G": _s("Exynos 1280", "8 GB", "6.5 pulgadas", "5000 mAh", "Android 14"),
    "Samsung Galaxy A33 5G": _s("Exynos 1280", "6 GB", "6.4 pulgadas", "5000 mAh", "Android 12"),
    "Samsung Galaxy A34 5G": _s("Dimensity 1080", "8 GB", "6.6 pulgadas", "5000 mAh", "Android 13"),
    "Samsung Galaxy A35 5G": _s("Exynos 1380", "8 GB", "6.6 pulgadas", "5000 mAh", "Android 14"),
    "Samsung Galaxy A36 5G": _s(
        "Snapdragon 6 Gen 3", "8 GB", "6.7 pulgadas", "5000 mAh", "Android 15"
    ),
    "Samsung Galaxy A52": _s("Snapdragon 720G", "6 GB", "6.5 pulgadas", "4500 mAh", "Android 11"),
    "Samsung Galaxy A52 5G": _s(
        "Snapdragon 750G", "6 GB", "6.5 pulgadas", "4500 mAh", "Android 11"
    ),
    "Samsung Galaxy A52s 5G": _s(
        "Snapdragon 778G", "8 GB", "6.5 pulgadas", "4500 mAh", "Android 11"
    ),
    "Samsung Galaxy A53 5G": _s("Exynos 1280", "8 GB", "6.5 pulgadas", "5000 mAh", "Android 12"),
    "Samsung Galaxy A54 5G": _s("Exynos 1380", "8 GB", "6.4 pulgadas", "5000 mAh", "Android 13"),
    "Samsung Galaxy A55 5G": _s("Exynos 1480", "8 GB", "6.6 pulgadas", "5000 mAh", "Android 14"),
    "Samsung Galaxy A56 5G": _s("Exynos 1580", "8 GB", "6.7 pulgadas", "5000 mAh", "Android 15"),
    "Samsung Galaxy S21 Ultra": _s(
        "Exynos 2100", "12 GB", "6.8 pulgadas", "5000 mAh", "Android 11"
    ),
    "Samsung Galaxy S23 Ultra": _s(
        "Snapdragon 8 Gen 2", "12 GB", "6.8 pulgadas", "5000 mAh", "Android 13"
    ),
    "Samsung Galaxy S24 Ultra": _s(
        "Snapdragon 8 Gen 3", "12 GB", "6.8 pulgadas", "5000 mAh", "Android 14"
    ),
    "Samsung Galaxy S25 Ultra": _s(
        "Snapdragon 8 Elite", "12 GB", "6.9 pulgadas", "5000 mAh", "Android 15"
    ),
    "Samsung Galaxy Z Fold 3": _s(
        "Snapdragon 888", "12 GB", "7.6 pulgadas", "4400 mAh", "Android 11"
    ),
    "Samsung Galaxy Z Fold 6": _s(
        "Snapdragon 8 Gen 3", "12 GB", "7.6 pulgadas", "4400 mAh", "Android 14"
    ),
    "Samsung Galaxy Z Flip 6": _s(
        "Snapdragon 8 Gen 3", "12 GB", "6.7 pulgadas", "4000 mAh", "Android 14"
    ),
}


def spec_attributes(title: str) -> dict[str, str]:
    """Atributos de ficha técnica del modelo, o vacío si no se tiene certeza."""
    entry = SPECS.get(title) or SPECS.get(title.removeprefix("Samsung ").removeprefix("Sony "))
    if entry is None:
        return {}
    return {
        "chip": entry.chip,
        "ram": entry.ram,
        "screen": entry.screen,
        "battery": entry.battery,
        "os": entry.os,
    }
