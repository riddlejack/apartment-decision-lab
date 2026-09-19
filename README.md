# Room & Route

Find an apartment that works for every roommate.

I built this after getting tired of checking rental sites one by one. Finding a place meant comparing rent, bedrooms, bathrooms, space, and several different commutes. Room & Route puts that search in one place.

## Start searching

With Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
uv tool install git+https://github.com/riddlejack/apartment-decision-lab
housing start --city Chicago
```

Open **http://127.0.0.1:8765**. Set your budget and requirements, collect listings, and compare the results. Your search stays in the local `.housing/` folder.

## What it does

- **Find listings.** Automatic collectors plus browser recipes for Domu, Compass, Apartments.com, Zillow, Apartment List, RentCafe, and Baird & Warner. Bring the results into one search.
- **Narrow the search.** Filter rent, bedrooms, bathrooms, square footage, pets, parking, and move-in dates. Missing information stays visible for checking.
- **Compare places.** Browse a map, shortlist apartments, save notes, spot price changes, and compare known costs per roommate.
- **Compare commutes.** Give each roommate destinations and travel options. The optional route engine calculates walking, cycling, and walking plus bus/train trips, then compares outbound and return travel for the household. Saved routes are reused.
- **Take your data.** Export CSV or JSON. Add sources or adapt the search to another city with Codex, Claude Code, or ordinary Python.

Coverage depends on the sources: major portals still have gaps, and this cannot promise every apartment. Driving currently uses uncongested road speeds, **not rush-hour traffic**. [Collection details](docs/COLLECTION.md) · [Commute setup](docs/ROUTING.md)

For browser collection, open this repo in Codex or Claude Code and ask:

> Use collect-browser to search the remaining sites for my saved preferences. Import batches, keep missing facts visible, and save where you stop.

The included recipes read result cards in batches; the agent handles filters, pagination, and exceptions. Automatic collectors run without AI via `housing refresh`. Browser-assisted sources still need a browser session and an agent or person. [How to collect and resume](docs/BROWSER-COLLECTION.md).

## Try it or change it

```sh
housing --workspace demo-search demo
housing --workspace demo-search review
```

The demo works without routing dependencies. For development:

```sh
git clone https://github.com/riddlejack/apartment-decision-lab.git
cd apartment-decision-lab
uv sync --locked
uv run pytest
```

[Agent instructions](AGENTS.md) · [Original Chicago search](docs/CASE-STUDY.md) · [How it works](docs/ARCHITECTURE.md)

Code: MIT. Listing content, map data, and transit feeds retain their own terms. Keep private workspaces and household destinations out of Git; only `.housing/` is ignored by default.
