"""Infrastructure PostGIS réelle : extension, type geography, SRID, index GiST, mètres vs degrés.

Rien n'est simulé : ces tests prouvent que la colonne `Depot.location` se comporte
bien comme une géographie sur l'ellipsoïde WGS84 (distances en mètres, antiméridien).
"""
import pytest
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import LineString, Point
from django.contrib.gis.measure import D
from django.db import connection, transaction

from apps.depots.models import Depot
from tests.factories_depots import make_depot
from tests.geo import METERS_PER_DEGREE_EQUATOR, equator_point, point

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TABLE = Depot._meta.db_table


def fetch(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


def meters(value):
    return value.m if hasattr(value, "m") else float(value)


def depot_at(lat, lng, **extra):
    return make_depot(location=point(lat, lng), **extra)


def distance_between(depot, ref):
    return meters(
        Depot.objects.filter(pk=depot.pk).annotate(d=Distance("location", ref)).get().d
    )


# ==========================================================================
# Installation
# ==========================================================================
class TestPostgisSetup:
    def test_database_engine_is_postgis(self):
        assert settings.DATABASES["default"]["ENGINE"] == "django.contrib.gis.db.backends.postgis"

    def test_postgis_extension_is_installed(self):
        assert fetch("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")

    def test_postgis_major_version_is_3(self):
        assert fetch("SELECT PostGIS_Lib_Version()")[0][0].startswith("3.")

    def test_postgresql_server_is_recent(self):
        assert connection.pg_version >= 140000


# ==========================================================================
# Colonne Depot.location
# ==========================================================================
class TestLocationColumn:
    def test_field_declaration(self):
        field = Depot._meta.get_field("location")
        assert isinstance(field, gis_models.PointField)
        assert field.srid == 4326
        assert field.geography is True
        assert field.spatial_index is True

    def test_column_is_a_geography_in_srid_4326(self):
        rows = fetch(
            "SELECT srid, type FROM geography_columns "
            "WHERE f_table_name = %s AND f_geography_column = 'location'", [TABLE])
        assert rows == [(4326, "Point")]

    def test_column_is_not_a_plain_geometry(self):
        """Une colonne geometry ferait calculer les distances en degrés."""
        rows = fetch(
            "SELECT count(*) FROM geometry_columns "
            "WHERE f_table_name = %s AND f_geometry_column = 'location'", [TABLE])
        assert rows[0][0] == 0

    def test_a_gist_index_exists_on_location(self):
        defs = [row[0].lower() for row in fetch(
            "SELECT indexdef FROM pg_indexes WHERE tablename = %s", [TABLE])]
        assert any("gist" in d and "location" in d for d in defs), defs

    def test_the_index_is_usable_by_st_dwithin(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL enable_seqscan = off")
                cursor.execute(
                    f'EXPLAIN SELECT id FROM "{TABLE}" WHERE ST_DWithin(location, '
                    "ST_SetSRID(ST_MakePoint(9.7679, 4.0511), 4326)::geography, 5000)")
                plan = " ".join(row[0] for row in cursor.fetchall())
        assert "Index" in plan, plan


# ==========================================================================
# Sémantique géographique : mètres, ellipsoïde, antiméridien, pôles
# ==========================================================================
class TestGeographySemantics:
    def test_database_distance_across_the_antimeridian(self):
        d = fetch(
            "SELECT ST_Distance('SRID=4326;POINT(179.9999 0)'::geography, "
            "'SRID=4326;POINT(-179.9999 0)'::geography)")[0][0]
        assert d == pytest.approx(0.0002 * METERS_PER_DEGREE_EQUATOR, abs=0.01)  # ~22,26 m

    def test_orm_distance_is_in_meters_on_the_equator(self):
        depot = depot_at(0.0, 0.001)
        assert distance_between(depot, point(0.0, 0.0)) == pytest.approx(
            0.001 * METERS_PER_DEGREE_EQUATOR, abs=0.01)  # ~111,32 m, pas 0,001

    def test_same_point_is_at_distance_zero(self):
        depot = depot_at(4.0511, 9.7679)
        assert distance_between(depot, point(4.0511, 9.7679)) == pytest.approx(0.0, abs=1e-6)

    def test_dwithin_boundary_is_in_meters(self):
        depot = make_depot(location=equator_point(100.0))
        origin = point(0.0, 0.0)
        assert Depot.objects.filter(pk=depot.pk, location__dwithin=(origin, D(m=100.01))).exists()
        assert not Depot.objects.filter(pk=depot.pk, location__dwithin=(origin, D(m=99.99))).exists()

    def test_dwithin_works_across_the_antimeridian(self):
        depot = depot_at(0.0, 179.9999)
        ref = point(0.0, -179.9999)
        assert Depot.objects.filter(pk=depot.pk, location__dwithin=(ref, D(m=30))).exists()
        assert not Depot.objects.filter(pk=depot.pk, location__dwithin=(ref, D(m=20))).exists()

    def test_distance_across_the_antimeridian_is_short_not_planetary(self):
        depot = depot_at(0.0, 179.9999)
        assert distance_between(depot, point(0.0, -179.9999)) < 30

    def test_poles_do_not_break_distance_computation(self):
        depot = depot_at(90.0, 0.0)
        d = distance_between(depot, point(89.9, 0.0))
        assert 11_100 < d < 11_250  # 0,1° de méridien ≈ 11,17 km

    def test_distance_is_symmetric(self):
        a, b = depot_at(4.0511, 9.7679), depot_at(4.0310, 9.6980)
        ab = distance_between(a, b.location)
        ba = distance_between(b, a.location)
        assert ab == pytest.approx(ba, rel=1e-9)


# ==========================================================================
# Aller-retour des coordonnées et SRID
# ==========================================================================
class TestLocationRoundTrip:
    def test_coordinates_round_trip_without_loss(self):
        depot = depot_at(4.0511, 9.7679)
        stored = Depot.objects.get(pk=depot.pk).location
        assert stored.srid == 4326
        assert stored.x == pytest.approx(9.7679, abs=1e-9)  # x = longitude
        assert stored.y == pytest.approx(4.0511, abs=1e-9)  # y = latitude

    def test_point_without_srid_is_assumed_to_be_wgs84(self):
        depot = make_depot(location=Point(9.7679, 4.0511))
        stored = Depot.objects.get(pk=depot.pk).location
        assert stored.srid == 4326
        assert (stored.x, stored.y) == pytest.approx((9.7679, 4.0511), abs=1e-9)

    def test_other_srid_is_transformed_or_rejected_never_stored_as_degrees(self):
        mercator = point(4.0511, 9.7679).transform(3857, clone=True)  # x ~ 1,09e6 m
        try:
            with transaction.atomic():
                depot = make_depot(location=mercator)
        except Exception:
            return  # rejeté : acceptable
        stored = Depot.objects.get(pk=depot.pk).location
        assert stored.srid == 4326
        assert stored.x == pytest.approx(9.7679, abs=1e-6)
        assert stored.y == pytest.approx(4.0511, abs=1e-6)

    def test_non_point_geometry_is_refused(self):
        with pytest.raises(Exception):
            with transaction.atomic():
                make_depot(location=LineString((9.7, 4.0), (9.8, 4.1), srid=4326))

    def test_out_of_range_coordinates_never_come_back_out_of_range(self):
        """PostGIS peut coercer silencieusement une géographie hors plage : le rejet
        doit donc être fait par clean() / l'API (lot dépôts), pas par la base."""
        try:
            with transaction.atomic():
                depot = make_depot(location=Point(200.0, 95.0, srid=4326))
        except Exception:
            return
        stored = Depot.objects.get(pk=depot.pk).location
        assert -180 <= stored.x <= 180 and -90 <= stored.y <= 90
