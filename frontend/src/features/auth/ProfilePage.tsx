import { zodResolver } from "@hookform/resolvers/zod";
import { IconCheck } from "@tabler/icons-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { apiClient, extractApiError } from "../../api/client";
import { formatShortDate } from "../../design/formatters";
import { Button, ErrorBanner, FilterChip, TextField } from "../../design/ui";
import { getActiveLanguage, setAppLanguage } from "../../i18n";
import { useAuth } from "./AuthContext";

interface ProfileFormValues {
  full_name: string;
  phone: string;
}

export function ProfilePage() {
  const { t, i18n } = useTranslation();
  const { user, refreshUser, logout } = useAuth();
  const navigate = useNavigate();
  const [feedback, setFeedback] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const activeLang = getActiveLanguage();

  const profileSchema = useMemo(
    () =>
      z.object({
        full_name: z.string().min(2, t("auth.validation.fullNameRequired")),
        phone: z.string().regex(/^\+[1-9]\d{7,14}$/, t("auth.validation.phoneInvalid")),
      }),
    [t],
  );

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ProfileFormValues>({
    resolver: zodResolver(profileSchema),
    values: {
      full_name: user?.full_name ?? "",
      phone: user?.phone ?? "",
    },
  });

  if (!user) return null;

  const onSubmit = async (values: ProfileFormValues) => {
    setFeedback(null);
    const { error, response } = await apiClient.PATCH("/api/v1/auth/me/", { body: values });
    if (error) {
      const apiErr = extractApiError(error, response.status);
      setFeedback({ type: "err", text: apiErr.message });
      return;
    }
    await refreshUser();
    setFeedback({ type: "ok", text: t("auth.profileUpdated") });
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex flex-1 flex-col">
      <div className="bg-header-bg px-4 pt-3 pb-6 text-text-inverse">
        <div className="mx-auto flex max-w-lg flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="font-display text-2xl font-bold uppercase tracking-[0.5px]">
              {t("auth.profileTitle")}
            </h1>
            <p className="mt-0.5 text-sm text-text-inverse-muted">{user.email}</p>
          </div>
          <span className="inline-flex min-h-7 items-center rounded-sm bg-header-surface px-3 text-xs font-bold uppercase text-text-inverse">
            {t(`auth.roles.${user.role}`)}
          </span>
        </div>
      </div>

      <div className="mx-auto w-full max-w-lg space-y-6 px-4 py-6">
        {user.active_suspension && (
          <ErrorBanner
            message={t("auth.suspensionBanner", {
              date: formatShortDate(user.active_suspension.ends_at, i18n.language),
            })}
          />
        )}

        {feedback?.type === "err" && <ErrorBanner message={feedback.text} />}

        {feedback?.type === "ok" && (
          <div
            role="status"
            className="flex items-center gap-2 border-l-4 border-open bg-open-bg px-3.5 py-2.5 text-sm font-bold text-open"
          >
            <IconCheck size={18} stroke={2} aria-hidden="true" />
            <span>{feedback.text}</span>
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
            id="phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            label={t("auth.fields.phone")}
            hint={t("auth.fields.phoneHint")}
            error={errors.phone?.message}
            {...register("phone")}
          />

          <div className="flex flex-col gap-3 pt-2">
            <Button
              type="submit"
              variant="primary"
              fullWidth
              isLoading={isSubmitting}
              loadingLabel={t("auth.saving")}
            >
              {t("auth.saveAction")}
            </Button>

            <Button type="button" variant="secondary" fullWidth onClick={handleLogout}>
              {t("auth.logout")}
            </Button>
          </div>
        </form>

        {/* Sélecteur de langue FR / EN séparé par un simple filet horizontal */}
        <section className="border-t border-border pt-5">
          <h2 className="font-display text-lg font-bold uppercase tracking-[0.5px] text-text">
            {t("language.label")}
          </h2>
          <div className="mt-2 flex flex-wrap gap-2">
            <FilterChip
              tone="light"
              label={t("language.fr")}
              selected={activeLang === "fr"}
              onClick={() => setAppLanguage("fr")}
            />
            <FilterChip
              tone="light"
              label={t("language.en")}
              selected={activeLang === "en"}
              onClick={() => setAppLanguage("en")}
            />
          </div>
        </section>
      </div>
    </div>
  );
}
