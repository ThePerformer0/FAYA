import pytest
from datetime import time


from apps.depots.selectors import OpenStatus, compute_depot_open_state
from tests.factories_depots import make_depot
from tests.time_helpers import douala, at_douala

pytestmark = pytest.mark.unit



@pytest.mark.django_db
class TestComputeDepotOpenState:
    def test_before_opening_is_closed_and_reopens_at_opening(self):
        depot = make_depot(opening_time=time(8, 0), closing_time=time(20, 0))
        state = compute_depot_open_state(depot=depot, at=douala(2026, 1, 12, 7, 59))
        assert state.open_status == OpenStatus.CLOSED
        assert state.can_order is False
        assert state.reopens_at == time(8, 0)

    def test_at_opening_is_open(self):
        depot = make_depot(opening_time=time(8, 0), closing_time=time(20, 0))
        state = compute_depot_open_state(depot=depot, at=douala(2026, 1, 12, 8, 0))
        assert state.open_status == OpenStatus.OPEN
        assert state.can_order is True

    def test_cutoff_boundary_disables_ordering_and_marks_closing_soon(self, platform_setting):
        platform_setting.order_cutoff_before_close_minutes = 30
        platform_setting.closing_soon_threshold_minutes = 60
        depot = make_depot(opening_time=time(8, 0), closing_time=time(20, 0))
        state = compute_depot_open_state(depot=depot, settings_obj=platform_setting, at=douala(2026, 1, 12, 19, 30))
        assert state.can_order is False
        assert state.open_status == OpenStatus.CLOSING_SOON
        assert state.last_order_time == time(19, 30)

    def test_closing_soon_threshold_is_inclusive(self, platform_setting):
        platform_setting.closing_soon_threshold_minutes = 60
        platform_setting.order_cutoff_before_close_minutes = 30
        depot = make_depot(opening_time=time(8, 0), closing_time=time(20, 0))
        state = compute_depot_open_state(depot=depot, settings_obj=platform_setting, at=douala(2026, 1, 12, 19, 0))
        assert state.open_status == OpenStatus.CLOSING_SOON



    def test_at_closing_time_is_closed(self):
        depot = make_depot(opening_time=time(8, 0), closing_time=time(20, 0))
        state = compute_depot_open_state(depot=depot, at=douala(2026, 1, 12, 20, 0))
        assert state.open_status == OpenStatus.CLOSED
        assert state.can_order is False



    def test_last_order_time_and_reopens_at_are_never_none(self):
        depot = make_depot(opening_time=time(8, 0), closing_time=time(20, 0))
        state = compute_depot_open_state(depot=depot, at=douala(2026, 1, 12, 22, 0))
        assert state.last_order_time is not None
        assert state.reopens_at is not None
