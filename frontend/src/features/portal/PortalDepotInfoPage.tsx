/**
 * Édition des informations opérationnelles, horaires et coordonnées GPS du dépôt (/depot/info).
 * Formulaire posé directement sur le sable chaud (zéro carte grise encadrée).
 */

import { IconCheck, IconCurrentLocation } from "@tabler/icons-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { formatTimeHHMM } from "../../design/formatters";
import { Button, ErrorBanner, TextField } from "../../design/ui";
import { useNetworkStatus } from "../../shared/NetworkContext";
import { usePortalDepot } from "./PortalShell";
import { useUpdateManagedDepot } from "./useDepotPortal";

export function PortalDepotInfoPage() {
  const { t } = useTranslation();
  const { isOnline } = useNetworkStatus();
  const depot = usePortalDepot();
  const updateDepot = useUpdateManagedDepot();
  const canEdit = depot.is_editable && isOnline;

  const [name, setName] = useState(depot.name);
  const [description, setDescription] = useState(depot.description);
  const [phone, setPhone] = useState(depot.phone);
  const [openingTime, setOpeningTime] = useState(formatTimeHHMM(depot.opening_time));
  const [closingTime, setClosingTime] = useState(formatTimeHHMM(depot.closing_time));
  const [address, setAddress] = useState(depot.address);
  const [neighborhood, setNeighborhood] = useState(depot.neighborhood);
  const [latitude, setLatitude] = useState(String(depot.latitude));
  const [longitude, setLongitude] = useState(String(depot.longitude));
  const [geoBusy, setGeoBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [savedNotice, setSavedNotice] = useState(false);

  useEffect(() => {
    setName(depot.name);
    setDescription(depot.description);
    setPhone(depot.phone);
    setOpeningTime(formatTimeHHMM(depot.opening_time));
    setClosingTime(formatTimeHHMM(depot.closing_time));
    setAddress(depot.address);
    setNeighborhood(depot.neighborhood);
    setLatitude(String(depot.latitude));
    setLongitude(String(depot.longitude));
  }, [depot]);

  const fillCurrentGps = () => {
    if (!("geolocation" in navigator)) {
      setErrorMessage(t("geo.unsupported"));
      return;
    }
    setGeoBusy(true);
    setErrorMessage(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLatitude(pos.coords.latitude.toFixed(6));
        setLongitude(pos.coords.longitude.toFixed(6));
        setGeoBusy(false);
      },
      () => {
        setGeoBusy(false);
        setErrorMessage(t("geo.denied"));
      },
      { enableHighAccuracy: true, timeout: 8000 },
    );
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setErrorMessage(null);
    setSavedNotice(false);

    const parsedLat = Number.parseFloat(latitude);
    const parsedLng = Number.parseFloat(longitude);
    if (Number.isNaN(parsedLat) || Number.isNaN(parsedLng)) {
      setErrorMessage(t("depotPortal.info.sectionLocation"));
      return;
    }

    try {
      await updateDepot.mutateAsync({
        name: name.trim(),
        description: description.trim(),
        phone: phone.trim(),
        opening_time: openingTime,
        closing_time: closingTime,
        address: address.trim(),
        neighborhood: neighborhood.trim(),
        latitude: parsedLat,
        longitude: parsedLng,
      });
      setSavedNotice(true);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : t("errors.serverBody"));
    }
  };

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-6">
      {errorMessage && <ErrorBanner message={errorMessage} />}

      {savedNotice && (
        <div
          role="status"
          className="flex items-center gap-2 border-l-4 border-open bg-open-bg px-3.5 py-2.5 text-sm font-bold text-open"
        >
          <IconCheck size={18} stroke={2.2} aria-hidden="true" />
          <span>{t("depotPortal.info.saved")}</span>
        </div>
      )}

      {/* Identité & contact */}
      <section className="space-y-4">
        <h2 className="font-display text-lg font-bold uppercase tracking-[0.5px] text-text">
          {t("depotPortal.info.sectionIdentity")}
        </h2>

        <TextField
          id="depot-name"
          required
          disabled={!canEdit}
          label={t("depotPortal.info.fields.name")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />

        <TextField
          id="depot-description"
          disabled={!canEdit}
          label={t("depotPortal.info.fields.description")}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />

        <TextField
          id="depot-phone"
          required
          disabled={!canEdit}
          label={t("depotPortal.info.fields.phone")}
          hint={t("auth.fields.phoneHint")}
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
      </section>

      {/* Horaires */}
      <section className="space-y-4 border-t border-border pt-5">
        <h2 className="font-display text-lg font-bold uppercase tracking-[0.5px] text-text">
          {t("depotPortal.info.sectionHours")}
        </h2>

        <div className="grid grid-cols-2 gap-3">
          <TextField
            id="depot-open"
            type="time"
            required
            disabled={!canEdit}
            label={t("depotPortal.info.fields.openingTime")}
            value={openingTime}
            onChange={(e) => setOpeningTime(e.target.value)}
          />

          <TextField
            id="depot-close"
            type="time"
            required
            disabled={!canEdit}
            label={t("depotPortal.info.fields.closingTime")}
            value={closingTime}
            onChange={(e) => setClosingTime(e.target.value)}
          />
        </div>
      </section>

      {/* Localisation */}
      <section className="space-y-4 border-t border-border pt-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-lg font-bold uppercase tracking-[0.5px] text-text">
            {t("depotPortal.info.sectionLocation")}
          </h2>
          {canEdit && (
            <button
              type="button"
              disabled={geoBusy}
              onClick={fillCurrentGps}
              className="inline-flex min-h-10 items-center gap-1.5 rounded-sm bg-ink-900 px-3 text-xs font-bold text-text-inverse hover:bg-ink-700 disabled:opacity-60"
            >
              <IconCurrentLocation size={15} stroke={2} aria-hidden="true" />
              <span>{geoBusy ? t("geo.locating") : t("depotPortal.info.useCurrentLocation")}</span>
            </button>
          )}
        </div>

        <TextField
          id="depot-address"
          required
          disabled={!canEdit}
          label={t("depotPortal.info.fields.address")}
          value={address}
          onChange={(e) => setAddress(e.target.value)}
        />

        <TextField
          id="depot-neighborhood"
          disabled={!canEdit}
          label={t("depotPortal.info.fields.neighborhood")}
          value={neighborhood}
          onChange={(e) => setNeighborhood(e.target.value)}
        />

        <div className="grid grid-cols-2 gap-3">
          <TextField
            id="depot-lat"
            type="number"
            step="0.000001"
            required
            disabled={!canEdit}
            label={t("depotPortal.info.fields.latitude")}
            value={latitude}
            onChange={(e) => setLatitude(e.target.value)}
          />
          <TextField
            id="depot-lng"
            type="number"
            step="0.000001"
            required
            disabled={!canEdit}
            label={t("depotPortal.info.fields.longitude")}
            value={longitude}
            onChange={(e) => setLongitude(e.target.value)}
          />
        </div>
      </section>

      <Button
        type="submit"
        variant="primary"
        fullWidth
        disabled={!canEdit}
        isLoading={updateDepot.isPending}
        loadingLabel={t("auth.saving")}
      >
        {t("auth.saveAction")}
      </Button>
    </form>
  );
}
