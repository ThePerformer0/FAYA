import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { EmptyState } from "../../design/ui";

export function OrdersPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className="flex flex-1 flex-col">
      <div className="bg-header-bg px-4 pt-3 pb-5 text-text-inverse">
        <div className="mx-auto max-w-xl">
          <h1 className="font-display text-2xl font-bold uppercase tracking-[0.5px]">
            {t("orders.title")}
          </h1>
        </div>
      </div>
      <div className="mx-auto w-full max-w-xl px-4 py-5">
        <EmptyState
          title={t("orders.emptyTitle")}
          body={t("orders.emptyBody")}
          actionLabel={t("orders.findDepot")}
          onAction={() => navigate("/")}
        />
      </div>
    </div>
  );
}
