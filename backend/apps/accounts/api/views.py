"""Vues API fines pour l'authentification JWT hybride et le profil utilisateur."""

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services
from apps.accounts.api.cookies import clear_refresh_cookie, set_refresh_cookie
from apps.accounts.api.serializers import (
    AuthResponseSerializer,
    LoginSerializer,
    RegisterSerializer,
    TokenRefreshResponseSerializer,
    UpdateProfileSerializer,
    UserMeSerializer,
)
from apps.core.api.serializers import ApiErrorSerializer


class NoStoreResponseMixin:
    """Empêche la mise en cache des réponses contenant des jetons ou données personnelles."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class RegisterView(NoStoreResponseMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["Auth"],
        summary="Inscription d'un nouveau client",
        request=RegisterSerializer,
        responses={
            201: AuthResponseSerializer,
            400: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def post(self, request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = services.register_customer(**serializer.validated_data)
        tokens = services.issue_auth_tokens(user=user)

        response = Response(
            {
                "access_token": tokens.access_token,
                "user": UserMeSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )
        set_refresh_cookie(response, tokens.refresh_token)
        return response


class LoginView(NoStoreResponseMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["Auth"],
        summary="Connexion par e-mail et mot de passe",
        request=LoginSerializer,
        responses={
            200: AuthResponseSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
        },
    )
    def post(self, request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = services.authenticate_user(**serializer.validated_data)
        tokens = services.issue_auth_tokens(user=user)

        response = Response(
            {
                "access_token": tokens.access_token,
                "user": UserMeSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )
        set_refresh_cookie(response, tokens.refresh_token)
        return response


class RefreshView(NoStoreResponseMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["Auth"],
        summary="Renouvellement de l'Access Token via le cookie HttpOnly",
        request=None,
        responses={
            200: TokenRefreshResponseSerializer,
            401: ApiErrorSerializer,
        },
    )
    def post(self, request) -> Response:
        raw_refresh = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        tokens = services.rotate_refresh_token(raw_refresh_token=raw_refresh)

        response = Response(
            {"access_token": tokens.access_token},
            status=status.HTTP_200_OK,
        )
        set_refresh_cookie(response, tokens.refresh_token)
        return response


class LogoutView(NoStoreResponseMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["Auth"],
        summary="Déconnexion et révocation du cookie refresh",
        request=None,
        responses={204: None},
    )
    def post(self, request) -> Response:
        raw_refresh = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        services.revoke_refresh_token(raw_refresh_token=raw_refresh)

        response = Response(status=status.HTTP_204_NO_CONTENT)
        clear_refresh_cookie(response)
        return response


class MeView(NoStoreResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Auth"],
        summary="Consulter le profil de l'utilisateur connecté",
        responses={200: UserMeSerializer, 401: ApiErrorSerializer},
    )
    def get(self, request) -> Response:
        return Response(UserMeSerializer(request.user).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Auth"],
        summary="Mettre à jour le profil de l'utilisateur connecté",
        request=UpdateProfileSerializer,
        responses={
            200: UserMeSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def patch(self, request) -> Response:
        serializer = UpdateProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = services.update_profile(user=request.user, **serializer.validated_data)
        return Response(UserMeSerializer(user).data, status=status.HTTP_200_OK)
