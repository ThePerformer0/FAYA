"""Contraintes PostgreSQL du catalogue, indépendantes de la validation Django.

On contourne full_clean() (create, bulk_create, update, SQL brut) pour prouver que
la base protège ses invariants. Pattern : `pytest.raises` à l'extérieur,
`transaction.atomic()` à l'intérieur.
"""
import uuid
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError

from apps.accounts.models import UserRole
from apps.catalog.models import (
    Brand,
    Product,
    ProductProposal,
    ProductProposalStatus,
    ProductStatus,
    ProductType,
)
from tests.factories_catalog import make_brand, make_product, make_proposal
from tests.helpers import create_user

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

BRAND_TABLE = Brand._meta.db_table
PRODUCT_TABLE = Product._meta.db_table
PROPOSAL_TABLE = ProductProposal._meta.db_table


def immediate_constraints(cursor):
    """Les FK Django sont DEFERRABLE INITIALLY DEFERRED : on force la vérification immédiate."""
    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


# ==========================================================================
# Brand
# ==========================================================================
class TestBrandConstraints:
    def test_exact_duplicate_name_is_refused(self):
        make_brand(name="Total")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_brand(name="Total")

    @pytest.mark.parametrize("variant", ["TOTAL", "total", "tOtAl"])
    def test_case_insensitive_duplicate_is_refused(self, variant):
        make_brand(name="Total")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_brand(name=variant)

    def test_accented_case_variants_are_refused(self):
        """Durcissement : dépend de la locale PostgreSQL (LOWER() est inopérant hors ASCII en locale C)."""
        make_brand(name="Éclair")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_brand(name="éclair")

    def test_renaming_to_an_existing_name_in_another_case_is_refused(self):
        make_brand(name="Total")
        other = make_brand(name="Oryx")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Brand.objects.filter(pk=other.pk).update(name="TOTAL")
        assert Brand.objects.get(pk=other.pk).name == "Oryx"

    def test_a_brand_can_be_renamed_to_a_new_case_of_its_own_name(self):
        brand = make_brand(name="total")
        Brand.objects.filter(pk=brand.pk).update(name="TOTAL")
        assert Brand.objects.get(pk=brand.pk).name == "TOTAL"

    def test_distinct_names_coexist(self):
        make_brand(name="Total"), make_brand(name="Oryx"), make_brand(name="Shell")
        assert Brand.objects.count() == 3

    def test_empty_name_is_refused_on_create(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_brand(name="")

    def test_empty_name_is_refused_on_update(self):
        brand = make_brand(name="Total")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Brand.objects.filter(pk=brand.pk).update(name="")
        assert Brand.objects.get(pk=brand.pk).name == "Total"

    def test_empty_name_is_refused_via_raw_sql(self):
        brand = make_brand(name="Total")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE "{BRAND_TABLE}" SET name = %s WHERE id = %s', ["", brand.pk])

    def test_null_name_is_refused(self):
        brand = make_brand()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Brand.objects.filter(pk=brand.pk).update(name=None)


# ==========================================================================
# Product
# ==========================================================================
class TestProductConstraints:
    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-1"), Decimal("-0.01")])
    def test_non_positive_capacity_is_refused_on_create(self, bad):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_product(capacity_kg=bad)

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-5")])
    def test_non_positive_capacity_is_refused_on_update(self, bad):
        product = make_product(capacity_kg="12.5")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Product.objects.filter(pk=product.pk).update(capacity_kg=bad)
        assert Product.objects.get(pk=product.pk).capacity_kg == Decimal("12.5")

    def test_non_positive_capacity_is_refused_via_raw_sql(self):
        product = make_product()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE "{PRODUCT_TABLE}" SET capacity_kg = 0 WHERE id = %s', [product.pk])

    def test_smallest_positive_capacity_is_accepted(self):
        places = Product._meta.get_field("capacity_kg").decimal_places
        smallest = Decimal(1).scaleb(-places)
        assert make_product(capacity_kg=smallest).capacity_kg == smallest

    def test_unique_brand_capacity_type(self):
        brand = make_brand()
        make_product(brand=brand, capacity_kg="12.5", product_type=ProductType.BUTANE)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_product(brand=brand, capacity_kg="12.5", product_type=ProductType.BUTANE)

    def test_uniqueness_is_numeric_12_5_equals_12_50(self):
        brand = make_brand()
        make_product(brand=brand, capacity_kg=Decimal("12.5"))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_product(brand=brand, capacity_kg=Decimal("12.50"))

    def test_uniqueness_ignores_status_archived_and_draft_still_conflict(self):
        """Conséquence pour l'approbation : il faut réutiliser le produit existant, pas en créer un autre."""
        brand = make_brand()
        make_product(brand=brand, capacity_kg="12.5", status=ProductStatus.ARCHIVED)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_product(brand=brand, capacity_kg="12.5", status=ProductStatus.PUBLISHED)

    def test_uniqueness_ignores_the_product_name(self):
        brand = make_brand()
        make_product(brand=brand, capacity_kg="12.5", name="Nom A")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_product(brand=brand, capacity_kg="12.5", name="Nom B")

    def test_bulk_create_cannot_bypass_uniqueness(self):
        brand = make_brand()
        rows = [Product(brand=brand, capacity_kg=Decimal("6"), product_type=ProductType.BUTANE, name=f"P{i}",
                        description="", characteristics={}, image_url="") for i in range(2)]
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Product.objects.bulk_create(rows)
        assert Product.objects.count() == 0

    def test_update_into_a_duplicate_is_refused(self):
        brand = make_brand()
        make_product(brand=brand, capacity_kg="12.5")
        other = make_product(brand=brand, capacity_kg="6")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Product.objects.filter(pk=other.pk).update(capacity_kg=Decimal("12.5"))

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"capacity_kg": "6", "product_type": ProductType.PROPANE},
            {"capacity_kg": "35", "product_type": ProductType.BUTANE},
        ],
        ids=["autre_type", "autre_capacite"],
    )
    def test_same_brand_with_another_type_or_capacity_is_allowed(self, kwargs):
        brand = make_brand()
        make_product(brand=brand, capacity_kg="12.5", product_type=ProductType.BUTANE)
        make_product(brand=brand, **kwargs)
        assert Product.objects.filter(brand=brand).count() == 2

    def test_same_capacity_and_type_for_another_brand_is_allowed(self):
        make_product(capacity_kg="12.5")
        make_product(capacity_kg="12.5")
        assert Product.objects.count() == 2

    @pytest.mark.parametrize("field", ["capacity_kg", "name", "product_type", "status"])
    def test_required_columns_reject_null(self, field):
        product = make_product()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Product.objects.filter(pk=product.pk).update(**{field: None})

    def test_brand_foreign_key_is_enforced_by_the_database(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    immediate_constraints(cursor)
                make_product_with_brand_id(uuid.uuid4())

    def test_database_refuses_to_delete_a_brand_used_by_a_product(self):
        """PROTECT est une règle Python : on vérifie aussi la clé étrangère SQL."""
        product = make_product()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    immediate_constraints(cursor)
                    cursor.execute(f'DELETE FROM "{BRAND_TABLE}" WHERE id = %s', [product.brand_id])
        assert Brand.objects.filter(pk=product.brand_id).exists()

    def test_orm_protect_on_brand_with_products(self):
        product = make_product()
        with pytest.raises(ProtectedError):
            product.brand.delete()


def make_product_with_brand_id(brand_id):
    return Product.objects.create(
        brand_id=brand_id, capacity_kg=Decimal("12.5"), product_type=ProductType.BUTANE,
        name="Orpheline", description="", characteristics={}, image_url="")


# ==========================================================================
# ProductProposal
# ==========================================================================
class TestProposalConstraints:
    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-1")])
    def test_non_positive_capacity_is_refused_on_create(self, bad):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                make_proposal(capacity_kg=bad)

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-5")])
    def test_non_positive_capacity_is_refused_on_update(self, bad):
        proposal = make_proposal(capacity_kg="12.5")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ProductProposal.objects.filter(pk=proposal.pk).update(capacity_kg=bad)

    def test_non_positive_capacity_is_refused_via_raw_sql(self):
        proposal = make_proposal()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE "{PROPOSAL_TABLE}" SET capacity_kg = 0 WHERE id = %s', [proposal.pk])

    @pytest.mark.parametrize("field", ["proposed_brand_name", "capacity_kg", "name", "product_type", "status"])
    def test_required_columns_reject_null(self, field):
        proposal = make_proposal()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ProductProposal.objects.filter(pk=proposal.pk).update(**{field: None})

    def test_depot_foreign_key_is_enforced_by_the_database(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    immediate_constraints(cursor)
                ProductProposal.objects.create(
                    depot_id=uuid.uuid4(), proposed_brand_name="Orpheline", capacity_kg=Decimal("12.5"),
                    product_type=ProductType.BUTANE, name="Orpheline", description="")

    def test_duplicate_pending_proposals_are_allowed(self, ):
        """Plusieurs dépôts (ou le même) peuvent proposer le même produit : pas de contrainte."""
        a = make_proposal(proposed_brand_name="Même Marque", capacity_kg="12.5")
        b = make_proposal(proposed_brand_name="Même Marque", capacity_kg="12.5")
        assert a.pk != b.pk

    def test_proposal_survives_deletion_of_its_reviewer(self):
        admin = create_user(role=UserRole.ADMIN, is_staff=True)
        proposal = make_proposal(status=ProductProposalStatus.REJECTED, reviewed_by=admin, review_note="non")
        try:
            with transaction.atomic():
                admin.delete()
        except ProtectedError:
            pass  # PROTECT acceptable
        assert ProductProposal.objects.filter(pk=proposal.pk).exists(), (
            "supprimer le relecteur a détruit l'historique des propositions (CASCADE ?)")

    def test_proposal_survives_deletion_of_its_created_product(self):
        product = make_product()
        proposal = make_proposal(status=ProductProposalStatus.APPROVED, created_product=product)
        try:
            with transaction.atomic():
                product.delete()
        except ProtectedError:
            pass
        assert ProductProposal.objects.filter(pk=proposal.pk).exists(), (
            "supprimer le produit créé a détruit la proposition (CASCADE ?)")
