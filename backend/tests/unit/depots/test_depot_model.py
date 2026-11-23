from datetime import time

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import UserRole
from apps.depots.models import Depot, DepotStatus
from tests.factories_depots import make_depot, make_depot_manager
from tests.geo import DOUALA_CENTER, point
from tests.helpers import create_user

pytestmark = pytest.mark.unit


@pytest.mark.django_db
class TestDepotModelValidation:
    def test_factory_depot_has_expected_default_status(self):
        depot = make_depot()
        assert depot.status == DepotStatus.ACTIVE

    def test_clean_rejects_manager_with_non_depot_manager_role(self):
        manager = create_user(role=UserRole.CUSTOMER)
        depot = make_depot(manager=manager)
        with pytest.raises(ValidationError):
            depot.clean()

    def test_clean_rejects_blank_name(self):
        manager = make_depot_manager()
        depot = Depot(
            manager=manager,
            name="",
            address="Adresse",
            neighborhood="Akwa",
            phone="+237699123456",
            location=point(*DOUALA_CENTER),
            opening_time=time(8, 0),
            closing_time=time(20, 0),
        )
        with pytest.raises(ValidationError):
            depot.clean()

    @pytest.mark.parametrize("phone", ["237699123456", "+237", "+0237699123456", "+237699123456 ", "abc"])
    def test_clean_rejects_phone_not_in_e164_format(self, phone):
        depot = make_depot(phone=phone)
        with pytest.raises(ValidationError):
            depot.full_clean()

    @pytest.mark.parametrize("opening,closing", [(time(8, 0), time(8, 0)), (time(20, 0), time(8, 0))])
    def test_clean_rejects_closing_time_not_after_opening(self, opening, closing):
        manager = make_depot_manager()
        depot = Depot(
            manager=manager,
            name="Dépôt Horaires",
            address="Adresse",
            neighborhood="Akwa",
            phone="+237699123456",
            location=point(*DOUALA_CENTER),
            opening_time=opening,
            closing_time=closing,
        )
        with pytest.raises(ValidationError):
            depot.clean()

    def test_clean_accepts_valid_e164_phone_and_hours(self):
        depot = make_depot(phone="+237699123456", opening_time=time(8, 0), closing_time=time(20, 0))
        depot.full_clean()
