"""Modèle ProductProposal : valeurs par défaut et validation."""
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import ProductProposal, ProductProposalStatus, ProductType
from tests.factories_catalog import make_proposal

pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def errors_of(obj):
    try:
        obj.full_clean()
    except ValidationError as exc:
        return exc.message_dict
    return {}


def unsaved(**overrides):
    from tests.factories_depots import make_depot

    data = dict(depot=make_depot(), proposed_brand_name="Nouvelle Marque", capacity_kg=Decimal("12.5"),
                product_type=ProductType.BUTANE, name="Bouteille proposée", description="Description")
    data.update(overrides)
    return ProductProposal(**data)


class TestProposalDefaults:
    def test_statuses(self):
        assert {v for v, _ in ProductProposalStatus.choices} == {"PENDING", "APPROVED", "REJECTED"}

    def test_in_memory_defaults(self):
        p = ProductProposal()
        assert p.status == ProductProposalStatus.PENDING
        assert p.reviewed_by_id is None
        assert p.reviewed_at is None
        assert not p.review_note
        assert p.created_product_id is None

    def test_persisted_defaults(self):
        p = ProductProposal.objects.get(pk=make_proposal().pk)
        assert p.status == ProductProposalStatus.PENDING
        assert (p.reviewed_by_id, p.reviewed_at, p.created_product_id) == (None, None, None)

    def test_pk_is_a_uuid_and_str_is_not_empty(self):
        p = make_proposal()
        assert isinstance(p.pk, uuid.UUID)
        assert str(p).strip() != ""


class TestProposalValidation:
    def test_a_well_formed_proposal_passes_full_clean(self):
        assert errors_of(unsaved()) == {}

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-3"), None], ids=["zero", "negatif", "null"])
    def test_capacity_must_be_strictly_positive(self, bad):
        assert "capacity_kg" in errors_of(unsaved(capacity_kg=bad))

    def test_empty_brand_name_is_rejected(self):
        assert "proposed_brand_name" in errors_of(unsaved(proposed_brand_name=""))

    def test_whitespace_only_brand_name_is_rejected(self):
        """Durcissement : '   ' ne doit pas pouvoir devenir une marque à l'approbation."""
        assert "proposed_brand_name" in errors_of(unsaved(proposed_brand_name="   "))

    def test_brand_name_longer_than_max_length_is_rejected(self):
        max_length = ProductProposal._meta.get_field("proposed_brand_name").max_length
        if not max_length:
            pytest.skip("proposed_brand_name sans max_length")
        assert "proposed_brand_name" in errors_of(unsaved(proposed_brand_name="x" * (max_length + 1)))

    def test_empty_name_is_rejected(self):
        assert "name" in errors_of(unsaved(name=""))

    @pytest.mark.parametrize("bad", ["butane", "GAZ", "", "XX"])
    def test_unknown_product_type_is_rejected(self, bad):
        assert "product_type" in errors_of(unsaved(product_type=bad))

    @pytest.mark.parametrize("bad", ["pending", "DONE", "", "XX"])
    def test_unknown_status_is_rejected(self, bad):
        assert "status" in errors_of(unsaved(status=bad))

    def test_depot_is_required(self):
        assert "depot" in errors_of(unsaved(depot=None))

    def test_unicode_brand_name_round_trips(self):
        p = make_proposal(proposed_brand_name="Gaz Étoile Ngoa-Ekélé 🔥")
        assert ProductProposal.objects.get(pk=p.pk).proposed_brand_name == "Gaz Étoile Ngoa-Ekélé 🔥"
