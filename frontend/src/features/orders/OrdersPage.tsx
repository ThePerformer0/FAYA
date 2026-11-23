import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { EmptyState } from "../../design/ui";

export function OrdersPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className="mx-auto w-full max-w-xl px-4 py-6">
      <h1 className="mb-4 font-display text-2xl font-bold uppercase tracking-[0.5px] text-text">
        {t("orders.title")}
      </h1>
      <EmptyState
        title={t("orders.emptyTitle")}
        body={t("orders.emptyBody")}
        actionLabel={t("orders.findDepot")}
        onAction={() => navigate("/")}
      />
    </div>
  );
}
