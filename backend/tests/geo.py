"""Helpers géographiques : points, constantes WGS84, distances de référence.

À l'équateur, la distance géodésique sur l'ellipsoïde WGS84 entre deux points de
même latitude 0 vaut exactement a * Δλ (a = 6 378 137 m) : c'est ce qui permet de
tester des rayons au mètre près, sans dépendre d'une approximation sphérique.
"""
import math

from django.contrib.gis.geos import Point

WGS84_A = 6378137.0
METERS_PER_DEGREE_EQUATOR = WGS84_A * math.pi / 180.0  # 111 319.4908 m
EARTH_MEAN_RADIUS_M = 6371008.8


def point(lat, lng):
    """Point WGS84. ATTENTION : GeoDjango attend (x=lng, y=lat)."""
    return Point(lng, lat, srid=4326)


def haversine_m(lat1, lng1, lat2, lng2):
    """Distance sphérique de référence (écart <= ~0,5 % avec l'ellipsoïde)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MEAN_RADIUS_M * math.asin(math.sqrt(a))


def equator_lng_for_meters(meters):
    return meters / METERS_PER_DEGREE_EQUATOR


def equator_point(meters_east_of_origin, *, origin_lng=0.0):
    """Point sur l'équateur situé exactement à N mètres à l'est de (0, origin_lng)."""
    return point(0.0, origin_lng + equator_lng_for_meters(meters_east_of_origin))


# Lieux (coordonnées approximatives de Douala, suffisantes pour des tests)
DOUALA_CENTER = (4.0511, 9.7679)  # (lat, lng)
AKWA = (4.0483, 9.7050)
BONANJO = (4.0436, 9.6933)
BONAPRISO = (4.0310, 9.6980)
DEIDO = (4.0690, 9.7110)
MAKEPE = (4.0630, 9.7420)
BONABERI = (4.0720, 9.6840)