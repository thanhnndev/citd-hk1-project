"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ExternalLink, Loader2, Navigation, Search, ShieldAlert, Star } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GooglePlaceMap } from "@/components/map/google-place-map";
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
  missingMapToken: string;
  mapUnavailable: string;
  noPins: string;
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
  apiKey: string;
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

export function PlaceProofMap({ locale, translations, apiKey }: PlaceProofMapProps) {
  const language = locale === "en" ? "en" : "vi";
  const [query, setQuery] = useState(translations.defaultQuery);
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [selectedPlaceId, setSelectedPlaceId] = useState<string | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [sessionId] = useState(() => crypto.randomUUID());

  const places = response?.places ?? [];
  const selectedPlace = places.find((place) => place.place_id === selectedPlaceId) ?? places[0] ?? null;
  const pinnedPlaces = useMemo(() => places.filter(hasLocation), [places]);

  const runSearch = useCallback(async (nextQuery: string) => {
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
  }, [language, sessionId, translations.defaultQuery, translations.error]);

  useEffect(() => {
    void runSearch(translations.defaultQuery);
  }, [runSearch, translations.defaultQuery]);

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
            <Badge className="w-fit bg-primary/10 text-primary shadow-none">{locale === "vi" ? "Bản đồ tương tác" : "Interactive Map"}</Badge>
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
            <GooglePlaceMap
              places={places}
              selectedPlaceId={selectedPlaceId}
              onMarkerSelect={setSelectedPlaceId}
              missingTokenLabel={translations.missingMapToken}
              unavailableLabel={translations.mapUnavailable}
              emptyLabel={translations.noPins}
              selectPlaceLabel={translations.selectPlace}
              apiKey={apiKey}
            />

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
          <Detail label={translations.openNow === "Đang mở cửa" ? "Giờ hoạt động" : "Opening hours"} value={place.open_now === true ? translations.openNow : place.open_now === false ? translations.closedNow : translations.openUnknown} />
          <Detail label={translations.type} value={place.primary_type ?? (place.types.join(", ") || translations.unknown)} />
          <Detail label={translations.accessibility} value={accessibility === null ? (place.accessibility_warning ?? translations.unknown) : `${accessibility}%`} />
        </dl>
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant="secondary">local_factor {place.local_factor == null ? translations.unknown : place.local_factor.toFixed(2)}</Badge>
          <Badge variant="secondary">final_score {place.final_score.toFixed(2)}</Badge>
          {place.map_uri ? (
            <Button asChild variant="outline" className="rounded-2xl">
              <a href={place.map_uri} target="_blank" rel="noreferrer">
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
