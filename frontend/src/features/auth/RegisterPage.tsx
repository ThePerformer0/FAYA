import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { z } from "zod";

import { ApiError } from "../../api/client";
import { Button, ErrorBanner, TextField } from "../../design/ui";
import { useAuth } from "./AuthContext";

interface RegisterFormValues {
  full_name: string;
  email: string;
  phone: string;
  password: string;
}

export function RegisterPage() {
  const { t } = useTranslation();
  const { register: registerCustomer } = useAuth();
  const navigate = useNavigate();
  const [serverError, setServerError] = useState<string | null>(null);

  const registerSchema = useMemo(
    () =>
      z.object({
        full_name: z.string().min(2, t("auth.validation.fullNameRequired")),
        email: z.string().email(t("auth.validation.emailInvalid")),
        phone: z.string().regex(/^\+[1-9]\d{7,14}$/, t("auth.validation.phoneInvalid")),
        password: z.string().min(8, t("auth.validation.passwordMin")),
      }),
    [t],
  );

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
  });

  const onSubmit = async (values: RegisterFormValues) => {
    setServerError(null);
    try {
      await registerCustomer(values);
      navigate("/", { replace: true });
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
            {t("auth.registerTitle")}
          </h1>
          <p className="mt-1 text-sm text-text-inverse-muted">{t("auth.registerSubtitle")}</p>
        </div>
      </div>

      {/* Formulaire directement posé sur le sable (zéro boîte encadrée 1px) */}
      <div className="mx-auto w-full max-w-md px-4 py-6">
        {serverError && (
          <div className="mb-5">
            <ErrorBanner message={serverError} />
          </div>
        )}

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5" noValidate>
          <TextField
            id="full_name"
            type="text"
            autoComplete="name"
            label={t("auth.fields.fullName")}
            error={errors.full_name?.message}
            {...register("full_name")}
          />

          <TextField
            id="email"
            type="email"
            autoComplete="email"
            label={t("auth.fields.email")}
            error={errors.email?.message}
            {...register("email")}
          />

          <TextField
            id="phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="+237699123456"
            label={t("auth.fields.phone")}
            hint={t("auth.fields.phoneHint")}
            error={errors.phone?.message}
            {...register("phone")}
          />

          <TextField
            id="password"
            type="password"
            autoComplete="new-password"
            label={t("auth.fields.password")}
            hint={t("auth.fields.passwordHint")}
            error={errors.password?.message}
            {...register("password")}
          />

          <div className="pt-2">
            <Button
              type="submit"
              variant="primary"
              fullWidth
              isLoading={isSubmitting}
              loadingLabel={t("auth.registerSubmitting")}
            >
              {t("auth.registerAction")}
            </Button>
          </div>
        </form>

        <p className="mt-6 text-center text-sm text-text-secondary">
          {t("auth.alreadyAccount")}{" "}
          <Link to="/login" className="font-bold text-text-brand underline">
            {t("auth.loginLink")}
          </Link>
        </p>
      </div>
    </div>
  );
}
