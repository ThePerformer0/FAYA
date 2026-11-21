import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { apiClient, extractApiError } from "../../api/client";
import { useAuth } from "./AuthContext";

const profileSchema = z.object({
  full_name: z.string().min(2, "Veuillez indiquer votre nom complet."),
  phone: z
    .string()
    .regex(/^\+[1-9]\d{7,14}$/, "Format international requis (ex. +2250701020304)."),
});

type ProfileFormValues = z.infer<typeof profileSchema>;

export function ProfilePage() {
  const { user, refreshUser, logout } = useAuth();
  const navigate = useNavigate();
  const [feedback, setFeedback] = useState<{ type: "ok" | "err"; text: string } | null>(null);

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
    setFeedback({ type: "ok", text: "Profil mis à jour." });
  };

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="mx-auto max-w-lg rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Mon profil</h1>
          <p className="text-sm text-slate-500">{user.email}</p>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
          {user.role}
        </span>
      </div>

      {user.active_suspension && (
        <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          Votre capacité de commande est temporairement suspendue jusqu&apos;au{" "}
          <strong>{new Date(user.active_suspension.ends_at).toLocaleString("fr-FR")}</strong>.
        </div>
      )}

      {feedback && (
        <div
          role="status"
          className={`mt-4 rounded-lg px-3 py-2 text-sm ${
            feedback.type === "ok"
              ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {feedback.text}
        </div>
      )}

      <form onSubmit={handleSubmit(onSubmit)} className="mt-5 space-y-4" noValidate>
        <div>
          <label htmlFor="full_name" className="block text-sm font-medium text-slate-700">
            Nom complet
          </label>
          <input
            id="full_name"
            type="text"
            {...register("full_name")}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-200"
          />
          {errors.full_name && (
            <p className="mt-1 text-xs text-red-600">{errors.full_name.message}</p>
          )}
        </div>

        <div>
          <label htmlFor="phone" className="block text-sm font-medium text-slate-700">
            Téléphone
          </label>
          <input
            id="phone"
            type="tel"
            {...register("phone")}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-orange-500 focus:outline-none focus:ring-2 focus:ring-orange-200"
          />
          {errors.phone && <p className="mt-1 text-xs text-red-600">{errors.phone.message}</p>}
        </div>

        <div className="flex items-center justify-between pt-2">
          <button
            type="submit"
            disabled={isSubmitting}
            className="rounded-lg bg-orange-600 px-4 py-2 text-sm font-semibold text-white hover:bg-orange-700 disabled:opacity-50"
          >
            {isSubmitting ? "Enregistrement..." : "Enregistrer"}
          </button>

          <button
            type="button"
            onClick={handleLogout}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            Se déconnecter
          </button>
        </div>
      </form>
    </div>
  );
}
