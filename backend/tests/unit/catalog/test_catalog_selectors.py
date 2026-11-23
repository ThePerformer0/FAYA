"""Selectors catalogue : list_active_brands / list_published_products."""
import uuid
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Brand, ProductStatus, ProductType
from apps.catalog.selectors import list_active_brands, list_published_products
from tests.factories_catalog import make_brand, make_product

pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def ids(queryset):
    return {obj.pk for obj in queryset}


# ==========================================================================
# list_active_brands
# ==========================================================================
class TestListActiveBrands:
    def test_empty_when_no_brand(self):
        assert list(list_active_brands()) == []

    def test_only_active_brands_are_returned(self):
        active, inactive = make_brand(), make_brand(is_active=False)
        result = ids(list_active_brands())
        assert active.pk in result and inactive.pk not in result

    def test_brand_without_any_product_is_still_listed(self):
        brand = make_brand()
        assert brand.pk in ids(list_active_brands())

    def test_deactivation_and_reactivation_are_reflected_immediately(self):
        brand = make_brand()
        Brand.objects.filter(pk=brand.pk).update(is_active=False)
        assert brand.pk not in ids(list_active_brands())
        Brand.objects.filter(pk=brand.pk).update(is_active=True)
        assert brand.pk in ids(list_active_brands())

    def test_ordering_is_explicit_and_stable(self):
        for name in ("Zeta", "alpha", "Bravo", "Éclair"):
            make_brand(name=name)
        queryset = list_active_brands()
        if hasattr(queryset, "ordered"):
            assert queryset.ordered, "pas d'ORDER BY explicite : ordre non déterministe"
        assert [b.pk for b in list_active_brands()] == [b.pk for b in list_active_brands()]

    def test_no_duplicates(self):
        for _ in range(5):
            make_brand()
        listed = list(list_active_brands())
        assert len(listed) == len({b.pk for b in listed}) == 5

    def test_runs_a_single_query(self, django_assert_num_queries):
        make_brand(), make_brand()
        with django_assert_num_queries(1):
            list(list_active_brands())

    def test_returns_brand_instances(self):
        make_brand()
        assert all(isinstance(b, Brand) for b in list_active_brands())


# ==========================================================================
# list_published_products : périmètre
# ==========================================================================
class TestPublishedProductsScope:
    def test_empty_when_no_product(self):
        assert list(list_published_products()) == []

    def test_only_published_products_of_active_brands(self):
        published = make_product(status=ProductStatus.PUBLISHED)
        draft = make_product(status=ProductStatus.DRAFT)
        archived = make_product(status=ProductStatus.ARCHIVED)
        inactive_brand = make_product(status=ProductStatus.PUBLISHED, brand=make_brand(is_active=False))
        result = ids(list_published_products())
        assert result == {published.pk}
        assert not ({draft.pk, archived.pk, inactive_brand.pk} & result)

    def test_brand_deactivation_hides_its_published_products_immediately(self):
        product = make_product()
        Brand.objects.filter(pk=product.brand_id).update(is_active=False)
        assert product.pk not in ids(list_published_products())
        Brand.objects.filter(pk=product.brand_id).update(is_active=True)
        assert product.pk in ids(list_published_products())

    def test_status_change_is_reflected_immediately(self):
        product = make_product(status=ProductStatus.DRAFT)
        assert product.pk not in ids(list_published_products())
        type(product).objects.filter(pk=product.pk).update(status=ProductStatus.PUBLISHED)
        assert product.pk in ids(list_published_products())

    def test_no_duplicates(self):
        brand = make_brand()
        for capacity in ("6", "12.5", "35"):
            make_product(brand=brand, capacity_kg=capacity)
        listed = list(list_published_products())
        assert len(listed) == len({p.pk for p in listed}) == 3

    def test_arguments_are_keyword_only(self):
        with pytest.raises(TypeError):
            list_published_products(uuid.uuid4())


# ==========================================================================
# list_published_products : filtres
# ==========================================================================
class TestPublishedProductsFilters:
    @pytest.fixture
    def catalog(self):
        total, oryx = make_brand(name="Total"), make_brand(name="Oryx")
        return {
            "total_6": make_product(brand=total, capacity_kg="6", product_type=ProductType.BUTANE),
            "total_12_butane": make_product(brand=total, capacity_kg="12.5", product_type=ProductType.BUTANE),
            "total_12_propane": make_product(brand=total, capacity_kg="12.5", product_type=ProductType.PROPANE),
            "oryx_12": make_product(brand=oryx, capacity_kg="12.5", product_type=ProductType.BUTANE),
            "oryx_35": make_product(brand=oryx, capacity_kg="35", product_type=ProductType.LPG),
            "total": total, "oryx": oryx,
        }

    def names(self, catalog, *keys):
        return {catalog[k].pk for k in keys}

    @pytest.mark.parametrize("as_type", [uuid.UUID, str], ids=["uuid", "str"])
    def test_brand_filter(self, catalog, as_type):
        result = ids(list_published_products(brand_id=as_type(str(catalog["oryx"].pk)) if as_type is str else catalog["oryx"].pk))
        assert result == self.names(catalog, "oryx_12", "oryx_35")

    @pytest.mark.parametrize(
        "capacity",
        [Decimal("12.5"), Decimal("12.50"), Decimal("12.500"), "12.5", "12.50", 12.5],
        ids=["dec", "dec2", "dec3", "str", "str2", "float"],
    )
    def test_capacity_filter_accepts_equivalent_representations(self, catalog, capacity):
        result = ids(list_published_products(capacity_kg=capacity))
        assert result == self.names(catalog, "total_12_butane", "total_12_propane", "oryx_12")

    def test_float_capacity_with_binary_representation_error(self):
        product = make_product(capacity_kg="12.1")
        assert product.pk in ids(list_published_products(capacity_kg=12.1))

    @pytest.mark.parametrize("as_enum", [True, False], ids=["enum", "str"])
    def test_product_type_filter(self, catalog, as_enum):
        value = ProductType.LPG if as_enum else "LPG"
        assert ids(list_published_products(product_type=value)) == self.names(catalog, "oryx_35")

    def test_combined_filters(self, catalog):
        result = ids(list_published_products(
            brand_id=catalog["total"].pk, capacity_kg="12.5", product_type=ProductType.PROPANE))
        assert result == self.names(catalog, "total_12_propane")

    def test_no_filter_returns_everything_published(self, catalog):
        assert len(ids(list_published_products())) == 5

    def test_filters_that_match_nothing_return_empty(self, catalog):
        assert list(list_published_products(brand_id=catalog["oryx"].pk, capacity_kg="6")) == []

    def test_unknown_brand_returns_empty(self, catalog):
        assert list(list_published_products(brand_id=uuid.uuid4())) == []

    def test_filtering_on_an_inactive_brand_returns_empty(self, catalog):
        Brand.objects.filter(pk=catalog["oryx"].pk).update(is_active=False)
        assert list(list_published_products(brand_id=catalog["oryx"].pk)) == []

    def test_filters_never_resurrect_unpublished_products(self):
        draft = make_product(status=ProductStatus.DRAFT, capacity_kg="9")
        assert list(list_published_products(capacity_kg="9", brand_id=draft.brand_id)) == []

    @pytest.mark.parametrize("zero", [0, Decimal("0"), "0", 0.0], ids=["int", "decimal", "str", "float"])
    def test_zero_capacity_is_a_filter_not_an_absent_filter(self, catalog, zero):
        """Piège `if capacity_kg:` : 0 est falsy et renverrait tout le catalogue."""
        assert list(list_published_products(capacity_kg=zero)) == []

    @pytest.mark.parametrize("bad", ["abc", "12,5", "NaN", "Infinity"])
    def test_garbage_capacity_never_returns_unrelated_products(self, catalog, bad):
        try:
            result = list(list_published_products(capacity_kg=bad))
        except Exception:
            return  # refus explicite : acceptable (l'API valide en amont)
        assert result == []

    def test_unknown_product_type_never_returns_unrelated_products(self, catalog):
        try:
            result = list(list_published_products(product_type="XXX"))
        except Exception:
            return
        assert result == []


# ==========================================================================
# list_published_products : performance et ordre
# ==========================================================================
class TestPublishedProductsQueries:
    def test_single_query_and_no_n_plus_one_on_brand(self):
        for i in range(6):
            make_product(capacity_kg=str(5 + i))
        with CaptureQueriesContext(connection) as ctx:
            names = [p.brand.name for p in list_published_products()]
        assert len(names) == 6
        assert len(ctx) == 1, f"{len(ctx)} requêtes : brand non préchargée"

    def test_ordering_is_explicit_and_stable(self):
        for i in range(5):
            make_product(capacity_kg=str(5 + i))
        queryset = list_published_products()
        if hasattr(queryset, "ordered"):
            assert queryset.ordered, "pas d'ORDER BY explicite : pagination instable"
        first = [p.pk for p in list_published_products()]
        second = [p.pk for p in list_published_products()]
        assert first == second

    def test_ordering_is_total_even_for_identical_sort_keys(self):
        """Mêmes noms : l'ordre doit rester déterministe (départage par une clé unique)."""
        brand = make_brand()
        for capacity in ("6", "9", "12.5", "35"):
            make_product(brand=brand, capacity_kg=capacity, name="Bouteille")
        runs = {tuple(p.pk for p in list_published_products()) for _ in range(5)}
        assert len(runs) == 1
