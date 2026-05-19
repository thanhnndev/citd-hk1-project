"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { ExternalLink, Loader2, MapPin, Navigation, Search, ShieldAlert, Star } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { sendChat, type ChatResponse, type PlaceResult } from "@/lib/chat-api";
import { cn } from "@/lib/utils";

type MapProofTranslations = Readonly<{
  title: string;
  intro: string;
  defaultQuery: string;
  queryLabel: string;
  searchPlaceholder: string;
  submit: string;
  loading: string;
  error: string;
  unavailable: string;
  noResults: string;
  fallback: string;
  resultCount: string;
  detailTitle: string;
  selectPlace: string;
  pinReady: string;
  pinUnavailable: string;
  mapsLink: string;
  rating: string;
  reviews: string;
  openNow: string;
  closedNow: string;
  openUnknown: string;
  businessStatus: string;
  type: string;
  accessibility: string;
  address: string;
  coordinates: string;
  unknown: string;
  responseNote: string;
}>;

type PlaceProofMapProps = Readonly<{
  locale: string;
  translations: MapProofTranslations;
}>;

type RequestState = "idle" | "loading" | "ready" | "error";

function hasLocation(place: PlaceResult): place is PlaceResult & { location: { lat: number; lng: number } } {
  return (
    typeof place.location?.lat === "number" &&
    Number.isFinite(place.location.lat) &&
    typeof place.location.lng === "number" &&
    Number.isFinite(place.location.lng)
  );
}

function formatNumber(value: number) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 5 }).format(value);
}

function normalizePercent(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return Math.round(Math.max(0, Math.min(1, value)) * 100);
}

function staticPlotPosition(place: PlaceResult, bounds: { minLat: number; maxLat: number; minLng: number; maxLng: number }) {
  if (!hasLocation(place)) return null;

  const latRange = bounds.maxLat - bounds.minLat || 1;
  const lngRange = bounds.maxLng - bounds.minLng || 1;
  return {
    left: `${((place.location.lng - bounds.minLng) / lngRange) * 82 + 9}%`,
    top: `${(1 - (place.location.lat - bounds.minLat) / latRange) * 72 + 14}%`,
  };
}

export function PlaceProofMap({ locale, translations }: PlaceProofMapProps) {
  const language = locale === "en" ? "en" : "vi";
  const [query, setQuery] = useState(translations.defaultQuery);
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [selectedPlaceId, setSelectedPlaceId] = useState<string | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [sessionId] = useState(() => crypto.randomUUID());

  const places = response?.places ?? [];
  const selectedPlace = places.find((place) => place.place_id === selectedPlaceId) ?? places[0] ?? null;
  const pinnedPlaces = places.filter(hasLocation);
  const bounds = useMemo(() => {
    if (pinnedPlaces.length === 0) return null;
    const lats = pinnedPlaces.map((place) => place.location.lat);
    const lngs = pinnedPlaces.map((place) => place.location.lng);
    return {
      minLat: Math.min(...lats),
      maxLat: Math.max(...lats),
      minLng: Math.min(...lngs),
      maxLng: Math.max(...lngs),
    };
  }, [pinnedPlaces]);

  async function runSearch(nextQuery: string) {
    const prompt = nextQuery.trim() || translations.defaultQuery;
    setRequestState("loading");
    setErrorMessage(null);

    try {
      const nextResponse = await sendChat(prompt, sessionId, language);
      setResponse(nextResponse);
      setSelectedPlaceId(nextResponse.places[0]?.place_id ?? null);
      setRequestState("ready");
    } catch (error) {
      setResponse(null);
      setSelectedPlaceId(null);
      setErrorMessage(error instanceof Error ? error.message : translations.error);
      setRequestState("error");
    }
  }

  useEffect(() => {
    void runSearch(translations.defaultQuery);
    // Run once per mounted locale page; manual queries drive subsequent POSTs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, translations.defaultQuery]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runSearch(query);
  }

  const hasNoResults = requestState === "ready" && places.length === 0;
  const showFallback = requestState === "ready" && Boolean(response?.fallback);

  return (
    <main className="min-h-screen overflow-hidden bg-[radial-gradient(circle_at_top_left,hsl(var(--secondary)/0.28),transparent_34%),linear-gradient(135deg,hsl(var(--background)),hsl(var(--muted)))] px-4 py-8 text-foreground md:px-8">
      <section className="mx-auto flex w-full max-w-7xl flex-col gap-6">
        <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr] lg:items-end">
          <div className="space-y-5">
            <Badge className="w-fit bg-primary/10 text-primary shadow-none">/api/chat proof</Badge>
            <div className="space-y-3">
              <h1 className="max-w-3xl text-4xl font-semibold tracking-tight md:text-6xl">{translations.title}</h1>
              <p className="max-w-2xl text-base leading-7 text-muted-foreground md:text-lg">{translations.intro}</p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="rounded-[2rem] border bg-card/90 p-3 shadow-xl shadow-primary/10 backdrop-blur">
            <label htmlFor="map-query" className="sr-only">{translations.queryLabel}</label>
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="relative flex-1">
                <Search className="absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                <input
                  id="map-query"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={translations.searchPlaceholder}
                  className="h-12 w-full rounded-2xl border bg-background pl-11 pr-4 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
              </div>
              <Button type="submit" size="lg" disabled={requestState === "loading" || !query.trim()} className="h-12 rounded-2xl">
                {requestState === "loading" ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Navigation aria-hidden="true" />}
                {requestState === "loading" ? translations.loading : translations.submit}
              </Button>
            </div>
          </form>
        </div>

        {(requestState === "error" || showFallback || hasNoResults) && (
          <Card className="border-dashed bg-card/80">
            <CardContent className="flex flex-col gap-2 p-5 md:flex-row md:items-center">
              <ShieldAlert className="size-5 text-primary" aria-hidden="true" />
              <p className="text-sm text-muted-foreground">
                {requestState === "error" ? `${translations.unavailable} ${errorMessage ?? translations.error}` : showFallback ? `${translations.fallback} ${response?.message ?? ""}` : `${translations.noResults} ${response?.message ?? ""}`}
              </p>
            </CardContent>
          </Card>
        )}

        <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold">{translations.resultCount.replace("{count}", String(places.length))}</h2>
              <Badge variant="secondary">{pinnedPlaces.length}/{places.length} {translations.pinReady}</Badge>
            </div>
            {requestState === "loading" && <SkeletonList label={translations.loading} />}
            {requestState !== "loading" && places.map((place, index) => (
              <PlaceCard key={place.place_id} index={index} place={place} selected={selectedPlace?.place_id === place.place_id} translations={translations} onSelect={() => setSelectedPlaceId(place.place_id)} />
            ))}
          </div>

          <div className="space-y-4">
            <Card className="overflow-hidden bg-card/90 shadow-xl shadow-primary/10">
              <div className="relative h-80 overflow-hidden bg-[linear-gradient(135deg,hsl(var(--primary)/0.18),hsl(var(--accent)/0.16)),radial-gradient(circle_at_28%_30%,hsl(var(--secondary)/0.42),transparent_24%)]">
                <div className="absolute inset-6 rounded-[2rem] border border-primary/20 bg-background/35" />
                <div className="absolute left-8 top-8 rounded-full bg-card/90 px-3 py-1 text-xs font-medium text-muted-foreground shadow">Hàm Ninh</div>
                {bounds && places.map((place, index) => {
                  const position = staticPlotPosition(place, bounds);
                  if (!position) return null;
                  return (
                    <button
                      key={place.place_id}
                      type="button"
                      onClick={() => setSelectedPlaceId(place.place_id)}
                      className={cn("absolute grid size-10 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border-2 shadow-lg transition hover:scale-110", selectedPlace?.place_id === place.place_id ? "border-secondary bg-primary text-primary-foreground" : "border-card bg-secondary text-secondary-foreground")}
                      style={position}
                      aria-label={`${translations.selectPlace}: ${place.display_name}`}
                    >
                      {index + 1}
                    </button>
                  );
                })}
                {pinnedPlaces.length === 0 && <div className="absolute inset-0 grid place-items-center p-8 text-center text-sm font-medium text-muted-foreground">{translations.pinUnavailable}</div>}
              </div>
              <CardContent className="p-5">
                <div className="grid gap-3 sm:grid-cols-2">
                  {places.map((place, index) => (
                    <div key={place.place_id} className="rounded-2xl border bg-background/70 p-3 text-sm">
                      <span className="font-semibold">#{index + 1} {place.display_name}</span>
                      <p className="mt-1 text-xs text-muted-foreground">{hasLocation(place) ? `${translations.coordinates}: ${formatNumber(place.location.lat)}, ${formatNumber(place.location.lng)}` : translations.pinUnavailable}</p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {selectedPlace && <PlaceDetail place={selectedPlace} translations={translations} />}
          </div>
        </div>
      </section>
    </main>
  );
}

function SkeletonList({ label }: { label: string }) {
  return <div className="rounded-3xl border bg-card p-6 text-sm text-muted-foreground"><Loader2 className="mr-2 inline size-4 animate-spin" aria-hidden="true" />{label}</div>;
}

function PlaceCard({ index, place, selected, translations, onSelect }: { index: number; place: PlaceResult; selected: boolean; translations: MapProofTranslations; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} className={cn("w-full rounded-3xl border bg-card p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg", selected && "border-primary shadow-primary/20")}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-primary">#{index + 1}</p>
          <h3 className="mt-2 text-lg font-semibold">{place.display_name}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{place.formatted_address ?? translations.unknown}</p>
        </div>
        <Badge variant={hasLocation(place) ? "secondary" : "outline"}>{hasLocation(place) ? translations.pinReady : translations.pinUnavailable}</Badge>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted-foreground">
        <span><Star className="mr-1 inline size-3" aria-hidden="true" />{translations.rating}: {place.rating ?? translations.unknown}</span>
        <span>{translations.reviews}: {place.user_rating_count ?? translations.unknown}</span>
        <span>{translations.type}: {place.primary_type ?? place.types?.[0] ?? translations.unknown}</span>
      </div>
    </button>
  );
}

function PlaceDetail({ place, translations }: { place: PlaceResult; translations: MapProofTranslations }) {
  const accessibility = normalizePercent(place.accessibility_score);
  return (
    <Card className="bg-card/95">
      <CardHeader>
        <CardTitle>{translations.detailTitle}: {place.display_name}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <dl className="grid gap-3 sm:grid-cols-2">
          <Detail label={translations.address} value={place.formatted_address ?? translations.unknown} />
          <Detail label={translations.coordinates} value={hasLocation(place) ? `${formatNumber(place.location.lat)}, ${formatNumber(place.location.lng)}` : translations.pinUnavailable} />
          <Detail label={translations.rating} value={place.rating?.toFixed(1) ?? translations.unknown} />
          <Detail label={translations.reviews} value={place.user_rating_count?.toString() ?? translations.unknown} />
          <Detail label={translations.businessStatus} value={place.business_status ?? translations.unknown} />
          <Detail label={translations.openNow} value={place.open_now === true ? translations.openNow : place.open_now === false ? translations.closedNow : translations.openUnknown} />
          <Detail label={translations.type} value={place.primary_type ?? (place.types.join(", ") || translations.unknown)} />
          <Detail label={translations.accessibility} value={accessibility === null ? (place.accessibility_warning ?? translations.unknown) : `${accessibility}%`} />
        </dl>
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant="secondary">local_factor {place.local_factor.toFixed(2)}</Badge>
          <Badge variant="secondary">final_score {place.final_score.toFixed(2)}</Badge>
          {place.google_maps_uri ? (
            <Button asChild variant="outline" className="rounded-2xl">
              <a href={place.google_maps_uri} target="_blank" rel="noreferrer">
                <ExternalLink aria-hidden="true" />{translations.mapsLink}
              </a>
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function Detail({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-2xl border bg-background/70 p-3"><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt><dd className="mt-1 font-medium">{value}</dd></div>;
}
