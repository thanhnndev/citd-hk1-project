# Homepage Redesign Design

## Goal

Redesign the localized homepage to closely match the supplied Hàm Ninh Guide AI reference while preserving the recently completed site header, existing routes, internationalization, and backend behavior.

## Scope

The change applies only to the homepage content rendered below the shared header at `/{locale}`.

Included:

- Hero section
- AI question example panel
- Hero image and information overlays
- Statistics strip
- Benefits section
- Three-step section
- Final call-to-action section
- Homepage-specific footer
- Responsive behavior for desktop, tablet, and mobile
- Existing Vietnamese and English localized content

Excluded:

- Shared header components and header styling
- Authentication pages
- Chat, map, and architecture pages
- API contracts, backend code, database code, and authentication behavior
- New search, booking, notification, or account features

## Design Direction

Use the supplied reference as the primary visual target and `DESIGN.md` as the design-token source. The result should feel like a polished tourism SaaS landing page: clean white space, Oceanic Blue actions, Deep Navy typography, subtle blue surfaces, and restrained borders and shadows.

The existing Next.js and `next-intl` implementation remains in place. The reference HTML is a visual specification, not code to copy directly.

## Page Structure

### Hero

Use a two-column desktop layout:

- Left: AI assistant eyebrow, large Hàm Ninh headline, supporting paragraph, example question panel, suggestion chips, primary CTA, secondary CTA, and free-use note.
- Right: the supplied Hàm Ninh landscape image inside a dark framed mockup with realtime and destination-count overlays.

On mobile, stack the content vertically. Keep the headline and primary action first, followed by the image. The layout must not create horizontal overflow.

### Statistics

Place a full-width Oceanic Blue strip directly below the hero. Display four localized statistics in a two-column mobile grid and four-column desktop grid.

### Benefits

Show the localized section title and three equal cards for intelligent consultation, local food knowledge, and instant responses. Use Lucide icons, subtle borders, light blue surfaces, and restrained hover elevation.

### Steps

Show three numbered steps on a pale blue background. Desktop uses a horizontal connector; mobile stacks the steps without relying on the connector.

### Final CTA

Use a blue gradient section with white text, a subtle decorative circle, and one prominent link to the chat page.

### Footer

Retain the homepage-specific light footer shown in the reference. It includes localized brand text, quick links, support labels, copyright, and the AI accuracy disclaimer.

## Components And Data

Keep `frontend/src/app/[locale]/page.tsx` as the server entry point. It continues loading `Landing.homepage` through `next-intl` and passes typed content to `TourismHomepage`.

Refine `frontend/src/components/landing/tourism-homepage.tsx` rather than introducing a separate page implementation. Small internal presentational components may be extracted only when they materially improve readability.

Continue using:

- Locale-aware `Link` from `@/i18n/routing`
- `next/image`
- Existing `/images/ham-ninh-homepage.jpg`
- Existing `TourismHomepageContent`
- Lucide icons

No client-side state is required.

## Interaction

- Primary hero CTA links to `/chat`.
- Secondary hero CTA links to `/architecture`.
- Final CTA links to `/chat`.
- Suggestion chips remain illustrative and non-interactive unless they already have established behavior.
- Hover effects are visual only and must not shift surrounding layout.

## Responsive Requirements

- No horizontal overflow at 375px viewport width.
- Header remains untouched and functional.
- Hero switches from two columns to one column below the desktop breakpoint.
- Statistics remain legible in two columns on small screens.
- Cards and steps stack into one column on mobile.
- Overlay cards remain inside the hero image boundary.
- Text maintains readable line length and sufficient contrast.

## Accessibility

- Preserve semantic section headings.
- Keep meaningful image alternative text.
- Decorative elements are hidden from assistive technologies.
- Links remain keyboard accessible with visible focus treatment.
- Text and controls meet practical contrast requirements against their backgrounds.
- Do not encode essential information through color alone.

## Testing

Add or update focused homepage tests to verify:

- Required homepage section identifiers remain present.
- Header files are not part of the homepage implementation diff.
- CTA routes remain locale-aware.
- The supplied image asset is used through `next/image`.
- TypeScript compilation passes.
- Focused ESLint passes.
- Production build passes.
- Desktop and mobile browser checks show no page errors or horizontal overflow.

## Acceptance Criteria

1. The homepage closely matches the supplied reference in hierarchy, spacing, color, and section order.
2. The recently redesigned header is visually and functionally unchanged.
3. Vietnamese and English routes render without missing translation errors.
4. Existing CTA routes continue working.
5. Desktop and mobile layouts have no horizontal overflow.
6. No backend files or backend contracts are modified.
7. TypeScript, focused lint, build, and homepage visual checks pass.
