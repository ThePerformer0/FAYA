import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { EmptyState } from "../../design/ui";

export function PortalOrdersPlaceholderPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <EmptyState
      title={t("depotPortal.orders.title")}
      body={t("depotPortal.orders.body")}
      actionLabel={t("depotPortal.orders.goStocks")}
      onAction={() => navigate("/depot/stocks")}
    />
  );
}
