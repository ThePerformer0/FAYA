"""Modèles Brand et Product (validation Django, enums, PROTECT).

Les assertions de validation ciblent un champ précis (`field in errors`) pour ne
pas dépendre des champs optionnels du modèle. Les tests « durcissement » sont
signalés : un échec est un finding, pas une erreur de test.
"""
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

from apps.catalog.models import Brand, Product, ProductStatus, ProductType
from tests.factories_catalog import make_brand, make_product

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

LOGO = "https://example.com/logo.png"
IMAGE = "https://example.com/bouteille.png"


def errors_of(obj):
    try:
        obj.full_clean()
    except ValidationError as exc:
        return exc.message_dict
    return {}


def valid_product(**overrides):
    overrides.setdefault("description", "Bouteille de gaz")
    overrides.setdefault("characteristics", {"couleur": "bleue"})
    overrides.setdefault("image_url", IMAGE)
    return make_product(**overrides)


def unsaved_product(brand, **overrides):
    data = dict(brand=brand, capacity_kg=Decimal("12.5"), product_type=ProductType.BUTANE,
                name="Produit test", description="Description", characteristics={"a": 1}, image_url=IMAGE)
    data.update(overrides)
    return Product(**data)


# ==========================================================================
# Brand
# ==========================================================================
class TestBrand:
    def test_defaults_and_identity(self):
        assert Brand(name="Total").is_active is True
        assert isinstance(make_brand().pk, uuid.UUID)

    def test_str_is_not_empty(self):
        assert str(make_brand(name="Total")).strip() != ""

    def test_a_well_formed_brand_passes_full_clean(self):
        assert errors_of(make_brand(logo_url=LOGO)) == {}

    def test_empty_name_is_rejected(self):
        assert "name" in errors_of(Brand(name="", logo_url=LOGO))

    def test_whitespace_only_name_is_rejected(self):
        """Durcissement : '   ' passe le CHECK name != '' ; full_clean doit l'attraper."""
        assert "name" in errors_of(Brand(name="   ", logo_url=LOGO))

    def test_name_longer_than_max_length_is_rejected(self):
        max_length = Brand._meta.get_field("name").max_length
        if not max_length:
            pytest.skip("name sans max_length")
        assert "name" in errors_of(Brand(name="x" * (max_length + 1), logo_url=LOGO))

    def test_unicode_name_round_trips(self):
        name = "Éclair Gaz Bonabéri 🔥"
        brand = make_brand(name=name)
        assert Brand.objects.get(pk=brand.pk).name == name

    def test_case_insensitive_duplicate_is_caught_by_full_clean(self):
        make_brand(name="Total")
        assert errors_of(Brand(name="TOTAL", logo_url=LOGO)), "doublon de casse non détecté par full_clean"

    def test_exact_duplicate_is_caught_by_full_clean(self):
        make_brand(name="Total")
        assert errors_of(Brand(name="Total", logo_url=LOGO))

    def test_is_active_toggle_persists(self):
        brand = make_brand()
        brand.is_active = False
        brand.save()
        assert Brand.objects.get(pk=brand.pk).is_active is False

    @pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "pas une url"])
    def test_logo_url_with_a_dangerous_scheme_is_rejected(self, url):
        """Durcissement : logo_url doit être une URL http(s) (XSS via scheme)."""
        assert "logo_url" in errors_of(Brand(name="Marque URL", logo_url=url))


# ==========================================================================
# Product : enums, valeurs par défaut
# ==========================================================================
class TestProductEnums:
    def test_product_types(self):
        assert {v for v, _ in ProductType.choices} == {"BUTANE", "PROPANE", "LPG"}

    def test_product_statuses(self):
        assert {v for v, _ in ProductStatus.choices} == {"DRAFT", "PUBLISHED", "ARCHIVED"}

    def test_default_status_is_draft(self):
        assert Product().status == ProductStatus.DRAFT

    @pytest.mark.parametrize("bad", ["butane", "GAZ", "", "XX"])
    def test_unknown_product_type_is_rejected(self, bad):
        assert "product_type" in errors_of(unsaved_product(make_brand(), product_type=bad))

    @pytest.mark.parametrize("bad", ["published", "ACTIVE", "", "XX"])
    def test_unknown_status_is_rejected(self, bad):
        assert "status" in errors_of(unsaved_product(make_brand(), status=bad))


# ==========================================================================
# Product : validation
# ==========================================================================
class TestProductValidation:
    def test_a_well_formed_product_passes_full_clean(self):
        assert errors_of(valid_product()) == {}

    def test_pk_is_a_uuid_and_str_is_not_empty(self):
        product = valid_product()
        assert isinstance(product.pk, uuid.UUID)
        assert str(product).strip() != ""

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-1"), Decimal("-0.5"), None], ids=["zero", "moins1", "negatif", "null"])
    def test_capacity_must_be_strictly_positive(self, bad):
        assert "capacity_kg" in errors_of(unsaved_product(make_brand(), capacity_kg=bad))

    @pytest.mark.parametrize("good", ["0.5", "6", "12.5", "35"])
    def test_realistic_capacities_are_accepted(self, good):
        assert "capacity_kg" not in errors_of(unsaved_product(make_brand(), capacity_kg=Decimal(good)))

    def test_capacity_with_too_many_decimal_places_is_rejected(self):
        places = Product._meta.get_field("capacity_kg").decimal_places
        value = Decimal("1." + "5" * (places + 1))
        assert "capacity_kg" in errors_of(unsaved_product(make_brand(), capacity_kg=value))

    def test_capacity_exceeding_max_digits_is_rejected(self):
        field = Product._meta.get_field("capacity_kg")
        value = Decimal(10) ** (field.max_digits - field.decimal_places)
        assert "capacity_kg" in errors_of(unsaved_product(make_brand(), capacity_kg=value))

    def test_empty_name_is_rejected(self):
        assert "name" in errors_of(unsaved_product(make_brand(), name=""))

    def test_brand_is_required(self):
        product = unsaved_product(None)
        assert "brand" in errors_of(product)

    def test_duplicate_brand_capacity_type_is_caught_by_full_clean(self):
        brand = make_brand()
        valid_product(brand=brand, capacity_kg=Decimal("12.5"), product_type=ProductType.BUTANE)
        dup = unsaved_product(brand, capacity_kg=Decimal("12.50"), product_type=ProductType.BUTANE, name="Autre nom")
        assert errors_of(dup), "doublon (marque, capacité, type) non détecté par full_clean"

    def test_same_capacity_with_another_type_or_brand_is_valid(self):
        brand = make_brand()
        valid_product(brand=brand, capacity_kg=Decimal("12.5"), product_type=ProductType.BUTANE)
        other_type = unsaved_product(brand, product_type=ProductType.PROPANE, name="Propane")
        other_brand = unsaved_product(make_brand(), name="Autre marque")
        assert errors_of(other_type) == {} and errors_of(other_brand) == {}

    def test_characteristics_json_round_trips(self):
        data = {"valve": "B", "dimensions": {"h": 48.5, "d": 30}, "tags": ["domestique", "été 🔥"]}
        product = valid_product(characteristics=data)
        assert Product.objects.get(pk=product.pk).characteristics == data

    @pytest.mark.parametrize("url", ["javascript:alert(1)", "data:image/svg+xml,<svg onload=alert(1)>", "pas une url"])
    def test_image_url_with_a_dangerous_scheme_is_rejected(self, url):
        """Durcissement : image_url doit être une URL http(s)."""
        assert "image_url" in errors_of(unsaved_product(make_brand(), image_url=url))


# ==========================================================================
# Product : relation Brand (PROTECT)
# ==========================================================================
class TestBrandProductRelation:
    def test_deleting_a_brand_used_by_a_product_is_protected(self):
        product = valid_product()
        with pytest.raises(ProtectedError):
            product.brand.delete()
        assert Brand.objects.filter(pk=product.brand_id).exists()

    def test_deleting_a_brand_without_products_works(self):
        brand = make_brand()
        brand.delete()
        assert not Brand.objects.filter(pk=brand.pk).exists()

    def test_deactivating_a_brand_does_not_touch_its_products(self):
        product = valid_product()
        Brand.objects.filter(pk=product.brand_id).update(is_active=False)
        assert Product.objects.get(pk=product.pk).status == ProductStatus.PUBLISHED
