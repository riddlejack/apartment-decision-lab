# Room & Route

**Scrape ~every apartment listing in your city. Filter listings by any characteristic (commute time, rent, sqft, # of bathrooms, etc.)**

Built this while apartment hunting in Chicago. Manual browsing was slow, & every apartment had trade-offs (too expensive, too few bathrooms, long commute, etc.). Built scripts to scrape ~every apt listing in Chicago, built an algorithm to calculate each roommate's commute to work. 

This repo turns that work into tools other people can use.

![Original Chicago search: 32,242 listing captures, 16,581 consolidated records, 2,930 records retained for review; commute modeling for 7,013 locations across 672 weekly departure slots.](docs/assets/chicago-search.svg)

Historical captures include repeats; the records are not all unique, available apartments. The 2,930 were a broad review pool. The housing outcome is my own report. [Numbers and methods](docs/CASE-STUDY.md).

## Search beyond one site

Compare listings from property managers and rental sites in one place. Browser recipes cover **Domu, Compass, Apartments.com, Zillow, Apartment List, RentCafe, and Baird & Warner**. Codex or Claude Code can collect whole pages and resume where the search stops.

Filter by rent, bedrooms, bathrooms, square footage, pets, parking, and move-in date. Keep missing facts visible. Explore the map, shortlist places, track price changes, and export CSV or JSON.

## Compare everyone's commute

A place farther away can still get you to work faster. Enter each roommate's destinations, schedule, travel modes, and commute limit. R5 uses OpenStreetMap and transit schedules to calculate walking, cycling, and bus/train trips—including the walk at each end.

The household algorithm compares outbound and return routes, selects the fastest valid round trip within each person's commute cap when possible, and totals weekly travel time. Saved routes are reused.

Driving estimates exclude rush-hour traffic. Routing needs the optional R/Java setup; [setup and algorithm details](docs/ROUTING.md).

## Run your search

With Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
uv tool install git+https://github.com/riddlejack/apartment-decision-lab
housing start --city Chicago
```

Open **http://127.0.0.1:8765**, enter your requirements, and collect. Automatic sources refresh with `housing refresh`, without AI usage. Your data and destinations stay in your local `.housing/` folder.

For browser sources, open a clone of this repo in Codex or Claude Code and ask:

> Use collect-browser to search for my saved preferences. Import batches, check promising listings, and save where you stop.

Chicago has the maintained source catalog. Other cities can reuse the collectors and browser recipes with local sources added. Coverage has gaps; this cannot guarantee every listing. [Browser workflow](docs/BROWSER-COLLECTION.md) · [Source coverage](docs/COLLECTION.md) · [Agent instructions](AGENTS.md)

<details>
<summary>Try the demo or develop locally</summary>

```sh
housing --workspace demo-search demo
housing --workspace demo-search review

git clone https://github.com/riddlejack/apartment-decision-lab.git
cd apartment-decision-lab
uv sync --locked
uv run pytest
```

The demo needs no routing setup. [Architecture](docs/ARCHITECTURE.md).

</details>

Code: MIT. Listings, maps, and transit feeds retain their source terms. Keep private workspaces out of Git; only `.housing/` is ignored by default.
