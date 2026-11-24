"""Peuple la base locale avec des données réalistes de démonstration à Douala (idempotent)."""

from datetime import time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.catalog.models import Brand, Product, ProductStatus, ProductType
from apps.core.models import PlatformSetting
from apps.depots.models import (
    Depot,
    DepotProductOffer,
    DepotStatus,
    OfferExchangeBrand,
    OfferOperation,
    OperationType,
)
from apps.inventory.models import DepotStock, StockCategory
from apps.inventory.services import restock_depot_stock


class Command(BaseCommand):
    help = "Crée un jeu de démonstration réaliste à Douala (marques, produits, dépôts, offres)."

    @transaction.atomic
    def handle(self, *args, **options):
        cfg = PlatformSetting.load()
        local_now = timezone.now().astimezone(ZoneInfo(cfg.timezone))

        # Calcule une heure de fermeture dans ~45 min pour illustrer le badge « Ferme bientôt »
        soon_dt = local_now + timedelta(minutes=45)
        if soon_dt.date() == local_now.date() and soon_dt.hour >= 9:
            closing_soon_time = time(soon_dt.hour, soon_dt.minute)
        else:
            closing_soon_time = time(23, 45)

        # 1. Compte client de démo
        customer, created = User.objects.get_or_create(
            email="client@faya.cm",
            defaults={
                "phone": "+237690112233",
                "full_name": "Nadia Kouam",
                "role": UserRole.CUSTOMER,
            },
        )
        if created:
            customer.set_password("FayaDemo2026!")
            customer.save(update_fields=["password"])

        # 2. Marques du catalogue central
        brand_names = ["Total", "Camgaz", "Oryx", "Tradex"]
        brands: dict[str, Brand] = {}
        for name in brand_names:
            brand, _ = Brand.objects.get_or_create(name=name, defaults={"is_active": True})
            brands[name] = brand

        # 3. Produits publiés
        product_specs = [
            ("Total", Decimal("12.50"), ProductType.BUTANE, "Bouteille Total 12,5 kg"),
            ("Total", Decimal("6.00"), ProductType.BUTANE, "Bouteille Total 6 kg"),
            ("Camgaz", Decimal("12.50"), ProductType.BUTANE, "Bouteille Camgaz 12,5 kg"),
            ("Camgaz", Decimal("6.00"), ProductType.BUTANE, "Bouteille Camgaz 6 kg"),
            ("Oryx", Decimal("12.50"), ProductType.BUTANE, "Bouteille Oryx 12,5 kg"),
            ("Tradex", Decimal("35.00"), ProductType.PROPANE, "Bouteille Tradex 35 kg"),
        ]
        products: dict[tuple[str, str], Product] = {}
        for brand_name, cap, ptype, pname in product_specs:
            product, _ = Product.objects.update_or_create(
                brand=brands[brand_name],
                capacity_kg=cap,
                product_type=ptype,
                defaults={
                    "name": pname,
                    "status": ProductStatus.PUBLISHED,
                },
            )
            products[(brand_name, str(cap))] = product

        # 4. Dépôts de démonstration à Douala (3 ouverts/ferme bientôt, 1 fermé, 1 suspendu)
        depot_specs = [
            {
                "email": "gerant.akwa@faya.cm",
                "manager_name": "Paul Mbarga",
                "manager_phone": "+237699100001",
                "name": "Dépôt Akwa Centre",
                "description": "Face Pharmacie du Centre, accès facile véhicules et motos.",
                "address": "Boulevard de la Liberté, Carrefour Equinoxe",
                "neighborhood": "Akwa",
                "phone": "+237699100001",
                "lat": 4.0483,
                "lng": 9.7050,
                "opening_time": time(6, 30),
                "closing_time": time(21, 0),
                "status": DepotStatus.ACTIVE,
                "offers": [
                    (
                        ("Total", "12.50"),
                        "Vérification étanchéité sur place.",
                        [
                            (OperationType.REFILL, 6500, 0, 0),
                            (OperationType.EXCHANGE, 7000, 0, 0),
                            (OperationType.FIRST_ACQUISITION, 6500, 18000, 4000),
                        ],
                        ["Camgaz", "Oryx"],
                    ),
                    (
                        ("Camgaz", "6.00"),
                        "",
                        [
                            (OperationType.REFILL, 3200, 0, 0),
                            (OperationType.FIRST_ACQUISITION, 3200, 12000, 2000),
                        ],
                        [],
                    ),
                    (
                        ("Oryx", "12.50"),
                        "",
                        [
                            (OperationType.REFILL, 6500, 0, 0),
                            (OperationType.EXCHANGE, 7000, 0, 0),
                        ],
                        ["Total", "Camgaz"],
                    ),
                ],
            },
            {
                "email": "gerant.bonanjo@faya.cm",
                "manager_name": "Amina Bello",
                "manager_phone": "+237699100002",
                "name": "Dépôt Bonanjo Express",
                "description": "Retrait rapide près de la poste centrale.",
                "address": "Rue Joss, Immeuble Sud",
                "neighborhood": "Bonanjo",
                "phone": "+237699100002",
                "lat": 4.0436,
                "lng": 9.6933,
                "opening_time": time(7, 0),
                "closing_time": closing_soon_time,
                "status": DepotStatus.ACTIVE,
                "offers": [
                    (
                        ("Camgaz", "12.50"),
                        "",
                        [
                            (OperationType.REFILL, 6500, 0, 0),
                            (OperationType.EXCHANGE, 6800, 0, 0),
                        ],
                        ["Total", "Oryx"],
                    ),
                    (
                        ("Total", "6.00"),
                        "",
                        [(OperationType.REFILL, 3250, 0, 0)],
                        [],
                    ),
                ],
            },
            {
                "email": "gerant.bonapriso@faya.cm",
                "manager_name": "Jean-Marc Ndi",
                "manager_phone": "+237699100003",
                "name": "Dépôt Bonapriso Gaz",
                "description": "Bouteilles domestiques et professionnelles 35 kg.",
                "address": "Avenue de Gaulle, Carrefour Armée de l'Air",
                "neighborhood": "Bonapriso",
                "phone": "+237699100003",
                "lat": 4.0310,
                "lng": 9.6980,
                "opening_time": time(7, 0),
                "closing_time": time(20, 30),
                "status": DepotStatus.ACTIVE,
                "offers": [
                    (
                        ("Total", "12.50"),
                        "",
                        [
                            (OperationType.REFILL, 6500, 0, 0),
                            (OperationType.FIRST_ACQUISITION, 6500, 19000, 3500),
                        ],
                        [],
                    ),
                    (
                        ("Tradex", "35.00"),
                        "Idéal restaurants et boulangeries.",
                        [
                            (OperationType.REFILL, 18500, 0, 0),
                            (OperationType.FIRST_ACQUISITION, 18500, 42000, 10000),
                        ],
                        [],
                    ),
                ],
            },
            {
                "email": "gerant.deido@faya.cm",
                "manager_name": "Claire Fotso",
                "manager_phone": "+237699100004",
                "name": "Dépôt Deïdo Rond-Point",
                "description": "Ouverture matinale uniquement pour illustrer un dépôt fermé.",
                "address": "Rond-Point Deïdo, côté Grand Moulin",
                "neighborhood": "Deïdo",
                "phone": "+237699100004",
                "lat": 4.0690,
                "lng": 9.7110,
                "opening_time": time(6, 0),
                "closing_time": time(12, 0),
                "status": DepotStatus.ACTIVE,
                "offers": [
                    (
                        ("Oryx", "12.50"),
                        "",
                        [(OperationType.REFILL, 6500, 0, 0)],
                        [],
                    ),
                ],
            },
            {
                "email": "gerant.bonaberi@faya.cm",
                "manager_name": "Samuel Tchoua",
                "manager_phone": "+237699100005",
                "name": "Dépôt Bonabéri Rail (Suspendu)",
                "description": "Dépôt suspendu : visible dans Django Admin, masqué du public.",
                "address": "Ancienne Route Bonabéri",
                "neighborhood": "Bonabéri",
                "phone": "+237699100005",
                "lat": 4.0720,
                "lng": 9.6840,
                "opening_time": time(7, 0),
                "closing_time": time(19, 30),
                "status": DepotStatus.SUSPENDED,
                "offers": [],
            },
        ]

        for spec in depot_specs:
            manager, m_created = User.objects.get_or_create(
                email=spec["email"],
                defaults={
                    "phone": spec["manager_phone"],
                    "full_name": spec["manager_name"],
                    "role": UserRole.DEPOT_MANAGER,
                },
            )
            if m_created:
                manager.set_password("FayaDemo2026!")
                manager.save(update_fields=["password"])

            depot, _ = Depot.objects.update_or_create(
                manager=manager,
                defaults={
                    "name": spec["name"],
                    "description": spec["description"],
                    "address": spec["address"],
                    "neighborhood": spec["neighborhood"],
                    "phone": spec["phone"],
                    "location": Point(spec["lng"], spec["lat"], srid=4326),
                    "opening_time": spec["opening_time"],
                    "closing_time": spec["closing_time"],
                    "status": spec["status"],
                },
            )

            for product_key, notes, ops, exchange_names in spec["offers"]:
                offer, _ = DepotProductOffer.objects.update_or_create(
                    depot=depot,
                    product=products[product_key],
                    defaults={"is_active": True, "notes": notes},
                )
                for op_type, gas_price, bottle_price, deposit_amount in ops:
                    OfferOperation.objects.update_or_create(
                        offer=offer,
                        operation_type=op_type,
                        defaults={
                            "is_active": True,
                            "gas_price": gas_price,
                            "bottle_price": bottle_price,
                            "deposit_amount": deposit_amount,
                        },
                    )
                for ex_name in exchange_names:
                    OfferExchangeBrand.objects.get_or_create(
                        offer=offer,
                        accepted_brand=brands[ex_name],
                    )

                if spec["status"] == DepotStatus.ACTIVE and not DepotStock.objects.filter(
                    depot=depot, product=products[product_key]
                ).exists():
                    restock_depot_stock(
                        depot=depot,
                        product=products[product_key],
                        category=StockCategory.FULL,
                        quantity=14,
                        actor=manager,
                        reason="Stock initial de démonstration",
                    )
                    restock_depot_stock(
                        depot=depot,
                        product=products[product_key],
                        category=StockCategory.EMPTY,
                        quantity=6,
                        actor=manager,
                        reason="Stock initial vides",
                    )
                    if any(op[0] == OperationType.FIRST_ACQUISITION for op in ops):
                        restock_depot_stock(
                            depot=depot,
                            product=products[product_key],
                            category=StockCategory.NEW,
                            quantity=4,
                            actor=manager,
                            reason="Stock initial bouteilles neuves",
                        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Jeu de démo Douala prêt : {len(brands)} marques, {len(products)} produits, "
                f"{len(depot_specs)} dépôts (dont 4 actifs et 1 suspendu). "
                "Compte client démo : client@faya.cm / FayaDemo2026!"
            )
        )
