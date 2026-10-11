# Product

## Register

brand

## Users

Hackathon judges (WeMakeDevs × AWS Environmental Hacks, Heat & Water track) and AWS Builder Center readers. They read on a laptop in daylight, often skimming in five to ten minutes. They are deciding whether the team did real, honest engineering work, whether it addresses a real problem, and where AWS fits. A secondary audience is city officials and civic-tech people who want to know if the approach is trustworthy.

## Product Purpose

A long-form, interactive field report on HeatRelief: a heat decision system for Indian cities that goes from satellite surface temperature to a ranked list of wards, a budgeted cooling plan, a bilingual ward brief and a morning alert. The blog must cover the problem, the stack, where AWS fits and "what fought back". Success: a reader leaves knowing what was built, believing the numbers, and seeing the limits stated plainly.

## Brand Personality

Field report. Sober, evidence-first, candid. Like a Reuters Graphics or The Pudding investigation: the data carries the drama, the copy stays calm. Three words: measured, candid, physical (it's about hot ground and real streets).

## Anti-references

- SaaS landing pages: hero-metric tiles, gradient text, glass cards, identical icon-card grids.
- The editorial-magazine lane (italic display serif, mono metadata, ruled columns) used as a costume.
- AI-generated "dashboard" blogs where every section is a card with a tracked uppercase kicker and a number.
- Any figure the repo cannot back up. A number in the blog must come from the model card, the pipeline or the optimizer.

## Design Principles

1. Every number is sourced. Figures come from exported repo data, never typed by hand.
2. Show the real ground. Imagery is the actual Landsat surface-temperature grid, not decoration.
3. Say the limit next to the claim. Caveats sit beside the result they qualify, not in a footer.
4. One idea per screen. Long scroll, deliberate pacing, interactives only where they change understanding.
5. Readable first. Body text is comfortable for a five-minute skim and a twenty-minute read.

## Accessibility & Inclusion

WCAG 2.2 AA. Sequential heat colour ramp is perceptually uniform (inferno) and every map has a numeric readout, so colour is never the only signal. Respect prefers-reduced-motion. Hindi text must render correctly (Devanagari font fallback).
