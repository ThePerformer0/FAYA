"""Vues API privées du portail Responsable de dépôt (/api/v1/depot/...)."""

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.core.api.mixins import NoStoreResponseMixin
from apps.core.api.serializers import ApiErrorSerializer
from apps.core.exceptions import NotFoundDomainError
from apps.core.models import PlatformSetting
from apps.depots import selectors, services
from apps.depots.api.permissions import IsDepotManagerWithDepot, get_request_managed_depot
from apps.depots.api.portal_serializers import (
    ManagedDepotSerializer,
    ManagedDepotUpdateSerializer,
    ManagedOfferCreateSerializer,
    ManagedOfferSerializer,
    ManagedOfferUpdateSerializer,
    ManagedProductProposalCreateSerializer,
    ManagedProductProposalSerializer,
)


class ManagedDepotView(NoStoreResponseMixin, APIView):
    permission_classes = [IsDepotManagerWithDepot]

    def _serialize(self, request, depot) -> dict:
        return ManagedDepotSerializer(
            depot,
            context={
                "request": request,
                "platform_settings": PlatformSetting.load(),
                "reference_now": timezone.now(),
            },
        ).data

    @extend_schema(
        tags=["Depot Portal"],
        summary="Consulter les informations et horaires de son dépôt",
        responses={
            200: ManagedDepotSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
        },
    )
    def get(self, request) -> Response:
        depot = get_request_managed_depot(request)
        return Response(self._serialize(request, depot), status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Depot Portal"],
        summary="Mettre à jour les informations et horaires de son dépôt",
        request=ManagedDepotUpdateSerializer,
        responses={
            200: ManagedDepotSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
        },
    )
    def patch(self, request) -> Response:
        depot = get_request_managed_depot(request)
        serializer = ManagedDepotUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = services.update_managed_depot(
            depot=depot,
            data=serializer.validated_data,
            actor=request.user,
        )
        return Response(self._serialize(request, updated), status=status.HTTP_200_OK)


class ManagedOfferListCreateView(NoStoreResponseMixin, ListAPIView):
    permission_classes = [IsDepotManagerWithDepot]
    serializer_class = ManagedOfferSerializer

    def get_queryset(self):
        depot = get_request_managed_depot(self.request)
        return selectors.list_managed_depot_offers(depot=depot)

    @extend_schema(
        tags=["Depot Portal"],
        summary="Lister toutes les offres commerciales de son dépôt",
        responses={
            200: ManagedOfferSerializer(many=True),
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=["Depot Portal"],
        summary="Créer une offre produit pour son dépôt",
        request=ManagedOfferCreateSerializer,
        responses={
            201: ManagedOfferSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def post(self, request) -> Response:
        depot = get_request_managed_depot(request)
        serializer = ManagedOfferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        product = Product.objects.select_related("brand").filter(pk=data["product_id"]).first()
        if product is None:
            raise NotFoundDomainError("Produit introuvable.", code="NOT_FOUND")

        offer = services.create_depot_offer(
            depot=depot,
            product=product,
            is_active=data.get("is_active", True),
            notes=data.get("notes", ""),
            operations=data.get("operations"),
            exchange_brand_ids=data.get("exchange_brand_ids"),
        )
        hydrated = selectors.get_managed_depot_offer(depot=depot, offer_id=offer.pk)
        return Response(ManagedOfferSerializer(hydrated).data, status=status.HTTP_201_CREATED)


class ManagedOfferDetailView(NoStoreResponseMixin, APIView):
    permission_classes = [IsDepotManagerWithDepot]

    @extend_schema(
        tags=["Depot Portal"],
        summary="Consulter une offre de son dépôt",
        responses={
            200: ManagedOfferSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
        },
    )
    def get(self, request, offer_id) -> Response:
        depot = get_request_managed_depot(request)
        offer = selectors.get_managed_depot_offer(depot=depot, offer_id=offer_id)
        return Response(ManagedOfferSerializer(offer).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Depot Portal"],
        summary="Modifier une offre, ses prix/opérations et ses marques d'échange",
        request=ManagedOfferUpdateSerializer,
        responses={
            200: ManagedOfferSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
        },
    )
    def patch(self, request, offer_id) -> Response:
        depot = get_request_managed_depot(request)
        serializer = ManagedOfferUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        offer = services.update_depot_offer(
            depot=depot,
            offer_id=offer_id,
            data=serializer.validated_data,
        )
        hydrated = selectors.get_managed_depot_offer(depot=depot, offer_id=offer.pk)
        return Response(ManagedOfferSerializer(hydrated).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Depot Portal"],
        summary="Supprimer une offre de son dépôt",
        responses={
            204: None,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
        },
    )
    def delete(self, request, offer_id) -> Response:
        depot = get_request_managed_depot(request)
        services.delete_depot_offer(depot=depot, offer_id=offer_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManagedProposalListCreateView(NoStoreResponseMixin, ListAPIView):
    permission_classes = [IsDepotManagerWithDepot]
    serializer_class = ManagedProductProposalSerializer

    def get_queryset(self):
        depot = get_request_managed_depot(self.request)
        return selectors.list_managed_depot_proposals(depot=depot)

    @extend_schema(
        tags=["Depot Portal"],
        summary="Lister les propositions de produits soumises par son dépôt",
        responses={
            200: ManagedProductProposalSerializer(many=True),
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=["Depot Portal"],
        summary="Proposer un nouveau produit au catalogue central",
        request=ManagedProductProposalCreateSerializer,
        responses={
            201: ManagedProductProposalSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
        },
    )
    def post(self, request) -> Response:
        depot = get_request_managed_depot(request)
        serializer = ManagedProductProposalCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        proposal = services.create_depot_product_proposal(
            depot=depot,
            proposed_brand_name=data["proposed_brand_name"],
            capacity_kg=data["capacity_kg"],
            product_type=data["product_type"],
            name=data["name"],
            description=data.get("description", ""),
        )
        return Response(
            ManagedProductProposalSerializer(proposal).data,
            status=status.HTTP_201_CREATED,
        )
