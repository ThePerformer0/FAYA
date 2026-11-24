import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";

import { ApiError } from "../../api/client";
import { Button, ErrorBanner, TextField } from "../../design/ui";
import { useAuth } from "./AuthContext";

interface LoginFormValues {
  email: string;
  password: string;
}

export function LoginPage() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [serverError, setServerError] = useState<string | null>(null);

  const loginSchema = useMemo(
    () =>
      z.object({
        email: z.string().email(t("auth.validation.emailInvalid")),
        password: z.string().min(1, t("auth.validation.passwordRequired")),
      }),
    [t],
  );

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
  });

  const onSubmit = async (values: LoginFormValues) => {
    setServerError(null);
    try {
      const loggedUser = await login(values);
      const from = (location.state as { from?: string } | null)?.from;
      if (from) {
        navigate(from, { replace: true });
      } else if (loggedUser.role === "DEPOT_MANAGER") {
        navigate("/depot", { replace: true });
      } else {
        navigate("/", { replace: true });
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setServerError(err.message);
      } else {
        setServerError(t("errors.networkBody"));
      }
    }
  };

  return (
    <div className="flex flex-1 flex-col">
      <div className="bg-header-bg px-4 pt-3 pb-6 text-text-inverse">
        <div className="mx-auto max-w-md">
          <h1 className="font-display text-2xl font-bold uppercase tracking-[0.5px]">
            {t("auth.loginTitle")}
          </h1>
          <p className="mt-1 text-sm text-text-inverse-muted">{t("auth.loginSubtitle")}</p>
        </div>
      </div>

      {/* Formulaire posé directement sur le sable (zéro boîte blanche encadrée 1px) */}
      <div className="mx-auto w-full max-w-md px-4 py-6">
        {serverError && (
          <div className="mb-5">
            <ErrorBanner message={serverError} />
          </div>
        )}

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5" noValidate>
          <TextField
            id="email"
            type="email"
            autoComplete="email"
            label={t("auth.fields.email")}
            error={errors.email?.message}
            {...register("email")}
          />

          <TextField
            id="password"
            type="password"
            autoComplete="current-password"
            label={t("auth.fields.password")}
            error={errors.password?.message}
            {...register("password")}
          />

          <div className="pt-2">
            <Button
              type="submit"
              variant="primary"
              fullWidth
              isLoading={isSubmitting}
              loadingLabel={t("auth.loginSubmitting")}
            >
              {t("auth.loginAction")}
            </Button>
          </div>
        </form>

        <p className="mt-6 text-center text-sm text-text-secondary">
          {t("auth.noAccount")}{" "}
          <Link to="/register" className="font-bold text-text-brand underline">
            {t("auth.createAccountLink")}
          </Link>
        </p>
      </div>
    </div>
  );
}
