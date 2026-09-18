(function () {
  "use strict";

  const MODES = ["walk", "bike", "transit", "drive"];
  const els = {
    notice: document.querySelector("#notice"),
    refreshButton: document.querySelector("#refresh-button"),
    openImportButton: document.querySelector("#open-import-button"),
    routeButton: document.querySelector("#route-button"),
    resultSummary: document.querySelector("#result-summary"),
    routeContext: document.querySelector("#route-context"),
    listingRows: document.querySelector("#listing-rows"),
    emptyState: document.querySelector("#empty-state"),
    emptyMessage: document.querySelector("#empty-message"),
    filterForm: document.querySelector("#filter-form"),
    searchInput: document.querySelector("#search-input"),
    minRentInput: document.querySelector("#min-rent-input"),
    maxRentInput: document.querySelector("#max-rent-input"),
    bedroomsSelect: document.querySelector("#bedrooms-select"),
    bathroomsSelect: document.querySelector("#bathrooms-select"),
    sourceSelect: document.querySelector("#source-select"),
    historicalInput: document.querySelector("#historical-input"),
    unknownInput: document.querySelector("#unknown-input"),
    sortSelect: document.querySelector("#sort-select"),
    clearFiltersButton: document.querySelector("#clear-filters-button"),
    configForm: document.querySelector("#config-form"),
    cityInput: document.querySelector("#city-input"),
    timezoneInput: document.querySelector("#timezone-input"),
    currencyInput: document.querySelector("#currency-input"),
    routingJson: document.querySelector("#routing-json"),
    peopleList: document.querySelector("#people-list"),
    addPersonButton: document.querySelector("#add-person-button"),
    saveConfigButton: document.querySelector("#save-config-button"),
    configStatus: document.querySelector("#config-status"),
    importPanel: document.querySelector("#import-panel"),
    jsonFileInput: document.querySelector("#json-file-input"),
    importJson: document.querySelector("#import-json"),
    importButton: document.querySelector("#import-button"),
    importStatus: document.querySelector("#import-status")
  };

  let workspace = {
    listings: [],
    config: {},
    routes: {},
    rankings: [],
    status: {}
  };
  let configSnapshot = {};
  let generatedId = 0;

  function makeId(prefix) {
    generatedId += 1;
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
      return `${prefix}-${globalThis.crypto.randomUUID()}`;
    }
    return `${prefix}-${Date.now()}-${generatedId}`;
  }

  function finiteNumber(value) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() !== "") {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
    return null;
  }

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function deepCopy(value) {
    if (typeof structuredClone === "function") return structuredClone(value);
    return JSON.parse(JSON.stringify(value));
  }

  function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function setNotice(message, tone) {
    els.notice.textContent = message || "";
    els.notice.hidden = !message;
    if (tone) els.notice.dataset.tone = tone;
    else delete els.notice.dataset.tone;
  }

  function setFormStatus(element, message, tone) {
    element.textContent = message || "";
    if (tone) element.dataset.tone = tone;
    else delete element.dataset.tone;
  }

  function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (_error) {
        payload = text;
      }
    }
    if (!response.ok) {
      const detail = isRecord(payload) && (payload.detail || payload.message || payload.error);
      throw new Error(detail || `${response.status} ${response.statusText}`);
    }
    return payload;
  }

  function setButtonBusy(button, busy, busyLabel, idleLabel) {
    button.disabled = busy;
    button.textContent = busy ? busyLabel : idleLabel;
  }

  async function loadState(options = {}) {
    setButtonBusy(els.refreshButton, true, "Refreshing…", "Refresh");
    try {
      const payload = await api("/api/state");
      if (!isRecord(payload)) throw new Error("The state API returned an invalid response.");
      workspace = {
        listings: Array.isArray(payload.listings) ? payload.listings : [],
        config: isRecord(payload.config) ? payload.config : {},
        routes: payload.routes || {},
        rankings: Array.isArray(payload.rankings) ? payload.rankings : [],
        status: payload.status || {}
      };
      configSnapshot = deepCopy(workspace.config);
      renderSourceOptions();
      renderListings();
      renderRouteContext();
      if (!options.preserveConfigForm) renderConfig();
      renderWorkspaceStatus();
    } catch (error) {
      setNotice(`Could not load the workspace: ${errorMessage(error)}`, "error");
      els.resultSummary.textContent = "Workspace unavailable";
      els.listingRows.replaceChildren();
      els.emptyState.hidden = false;
      els.emptyMessage.textContent = "Start the local server and refresh this page.";
    } finally {
      setButtonBusy(els.refreshButton, false, "Refreshing…", "Refresh");
    }
  }

  function renderWorkspaceStatus() {
    const status = workspace.status;
    const routeStatus = isRecord(workspace.routes) ? workspace.routes.status : null;
    if (isRecord(status) && status.routes_stale === true) {
      setNotice("Route results are stale because listings or household settings changed. Compute routes again before comparing commutes.", "warning");
      return;
    }
    if (routeStatus === "stale") {
      const message = isRecord(workspace.routes) && workspace.routes.message
        ? String(workspace.routes.message)
        : "Route results are stale because listings or household settings changed.";
      setNotice(`${message} Compute routes again before comparing commutes.`, "warning");
      return;
    }
    if (routeStatus === "not_configured") {
      setNotice("Routing is optional and is not configured yet. Listing comparisons still work; open the routing setup guide below when you want commute results.", "warning");
      return;
    }
    if (isRecord(status) && typeof status.message === "string" && status.message) {
      setNotice(status.message, status.level === "error" ? "error" : undefined);
      return;
    }
    setNotice("");
  }

  function renderSourceOptions() {
    const prior = els.sourceSelect.value;
    const sources = [...new Set(workspace.listings.map((listing) => String(listing.source || "").trim()).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b));
    const all = createElement("option", "", "All");
    all.value = "";
    els.sourceSelect.replaceChildren(all);
    sources.forEach((source) => {
      const option = createElement("option", "", source);
      option.value = source;
      els.sourceSelect.append(option);
    });
    els.sourceSelect.value = sources.includes(prior) ? prior : "";
  }

  function renderRouteContext() {
    const routes = workspace.routes;
    if (!isRecord(routes) || routes.demo !== true) {
      els.routeContext.hidden = true;
      els.routeContext.textContent = "";
      return;
    }
    const message = typeof routes.message === "string" && routes.message.trim()
      ? routes.message.trim()
      : "Historical modeled route example.";
    els.routeContext.textContent = `${message} These are scheduled estimates, not live predictions.`;
    els.routeContext.hidden = false;
  }

  function rankingMap() {
    const map = new Map();
    workspace.rankings.forEach((record, index) => {
      if (!isRecord(record) || record.listing_id === null || record.listing_id === undefined) return;
      const explicitRank = finiteNumber(record.rank ?? record.commute_rank);
      map.set(String(record.listing_id), {
        record,
        rank: explicitRank === null ? index + 1 : explicitRank
      });
    });
    return map;
  }

  function filteredListings(rankings) {
    const query = els.searchInput.value.trim().toLocaleLowerCase();
    const minRent = finiteNumber(els.minRentInput.value);
    const maxRent = finiteNumber(els.maxRentInput.value);
    const minBeds = finiteNumber(els.bedroomsSelect.value);
    const minBaths = finiteNumber(els.bathroomsSelect.value);
    const source = els.sourceSelect.value;

    const listings = workspace.listings.filter((listing) => {
      if (!isRecord(listing)) return false;
      if (!els.historicalInput.checked && listing.historical === true) return false;
      const haystack = [listing.title, listing.address, listing.unit, listing.source]
        .filter((value) => value !== null && value !== undefined)
        .join(" ")
        .toLocaleLowerCase();
      if (query && !haystack.includes(query)) return false;
      const rent = finiteNumber(listing.rent);
      if (minRent !== null && ((rent === null && !els.unknownInput.checked) || (rent !== null && rent < minRent))) return false;
      if (maxRent !== null && ((rent === null && !els.unknownInput.checked) || (rent !== null && rent > maxRent))) return false;
      const bedrooms = finiteNumber(listing.bedrooms);
      if (minBeds !== null && ((bedrooms === null && !els.unknownInput.checked) || (bedrooms !== null && bedrooms < minBeds))) return false;
      const bathrooms = finiteNumber(listing.bathrooms);
      if (minBaths !== null && ((bathrooms === null && !els.unknownInput.checked) || (bathrooms !== null && bathrooms < minBaths))) return false;
      if (source && String(listing.source || "") !== source) return false;
      return true;
    });

    const sort = els.sortSelect.value;
    listings.sort((a, b) => {
      if (sort === "rent") return compareNullableNumbers(a.rent, b.rent);
      if (sort === "newest") {
        const aDate = Date.parse(a.observed_at || "");
        const bDate = Date.parse(b.observed_at || "");
        const aValid = Number.isFinite(aDate);
        const bValid = Number.isFinite(bDate);
        if (aValid && bValid) return bDate - aDate;
        if (aValid) return -1;
        if (bValid) return 1;
        return 0;
      }
      const aRank = rankings.get(String(a.id));
      const bRank = rankings.get(String(b.id));
      if (aRank && bRank) return aRank.rank - bRank.rank;
      if (aRank) return -1;
      if (bRank) return 1;
      return compareNullableNumbers(a.rent, b.rent);
    });
    return listings;
  }

  function compareNullableNumbers(a, b) {
    const left = finiteNumber(a);
    const right = finiteNumber(b);
    if (left !== null && right !== null) return left - right;
    if (left !== null) return -1;
    if (right !== null) return 1;
    return 0;
  }

  function formatRent(value) {
    const number = finiteNumber(value);
    if (number === null) return "Unknown";
    const currency = /^[A-Za-z]{3}$/.test(workspace.config.currency || "")
      ? workspace.config.currency.toUpperCase()
      : "USD";
    try {
      return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency,
        maximumFractionDigits: Number.isInteger(number) ? 0 : 2
      }).format(number);
    } catch (_error) {
      return `${number.toLocaleString()} ${currency}`;
    }
  }

  function formatMinutes(value) {
    const number = finiteNumber(value);
    if (number === null) return null;
    return `${Math.round(number)} min`;
  }

  function formatDimension(value, singular, plural) {
    const number = finiteNumber(value);
    if (number === null) return `Unknown ${plural}`;
    return `${number.toLocaleString()} ${number === 1 ? singular : plural}`;
  }

  function formatObserved(value, synthetic) {
    const timestamp = Date.parse(value || "");
    if (!Number.isFinite(timestamp)) return { relative: "Age unknown", exact: "Observation time unavailable" };
    if (synthetic === true) {
      return {
        relative: "Example timestamp",
        exact: new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(timestamp)
      };
    }
    const days = Math.max(0, Math.floor((Date.now() - timestamp) / 86400000));
    let relative = "Observed today";
    if (days === 1) relative = "Observed 1 day ago";
    else if (days > 1) relative = `Observed ${days} days ago`;
    return {
      relative,
      exact: new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(timestamp)
    };
  }

  function validHttpUrl(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      const url = new URL(value);
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
    } catch (_error) {
      return null;
    }
  }

  function personName(personId) {
    const people = Array.isArray(workspace.config.people) ? workspace.config.people : [];
    const person = people.find((candidate) => String(candidate.id) === String(personId));
    return person && person.name ? String(person.name) : String(personId || "Unknown person");
  }

  function createListingRow(listing, rankEntry) {
    const row = document.createElement("tr");
    const homeCell = document.createElement("td");
    const title = String(listing.title || listing.address || "Untitled listing");
    homeCell.append(createElement("span", "listing-title", title));
    const addressParts = [listing.address, listing.unit].filter((value) => value !== null && value !== undefined && String(value).trim());
    homeCell.append(createElement("span", "listing-address", addressParts.length ? addressParts.join(" · ") : "Address unknown"));
    const tags = createElement("div", "tag-row");
    if (listing.synthetic === true) tags.append(createElement("span", "tag", "Synthetic"));
    if (listing.historical === true) tags.append(createElement("span", "tag tag-warning", "Historical"));
    if (listing.grain) tags.append(createElement("span", "tag", String(listing.grain)));
    homeCell.append(tags);

    const rentCell = document.createElement("td");
    rentCell.append(createElement("span", "rent-value", formatRent(listing.rent)));
    rentCell.append(createElement("span", "cell-muted", finiteNumber(listing.rent) === null ? "Monthly rent unavailable" : "per month gross"));
    const totalMonthlyCost = finiteNumber(listing.total_monthly_cost);
    if (totalMonthlyCost !== null) {
      rentCell.append(createElement("span", "cell-muted", `${formatRent(totalMonthlyCost)} total monthly cost`));
    }

    const spaceCell = document.createElement("td");
    spaceCell.append(createElement("span", "listing-title", formatDimension(listing.bedrooms, "bed", "beds")));
    spaceCell.append(createElement("span", "cell-muted", formatDimension(listing.bathrooms, "bath", "baths")));

    const evidenceCell = document.createElement("td");
    const observed = formatObserved(listing.observed_at, listing.synthetic);
    const age = createElement("span", "evidence-line", observed.relative);
    age.title = observed.exact;
    evidenceCell.append(age);
    evidenceCell.append(createElement("span", "evidence-line", listing.source ? `Source: ${listing.source}` : "Source unknown"));
    if (listing.source_id) evidenceCell.append(createElement("span", "evidence-line", `ID: ${listing.source_id}`));

    const commuteCell = document.createElement("td");
    renderCommute(commuteCell, rankEntry);

    const linkCell = document.createElement("td");
    const url = validHttpUrl(listing.url);
    if (url) {
      const link = createElement("a", "open-link", "↗");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.setAttribute("aria-label", `Open ${title}`);
      link.title = "Open source listing";
      linkCell.append(link);
    } else {
      const missing = createElement("span", "cell-muted", "—");
      missing.title = "Listing URL unavailable";
      linkCell.append(missing);
    }

    row.append(homeCell, rentCell, spaceCell, evidenceCell, commuteCell, linkCell);
    return row;
  }

  function renderCommute(cell, rankEntry) {
    if (!rankEntry || !isRecord(rankEntry.record)) {
      cell.append(createElement("span", "listing-title", "Not computed"));
      cell.append(createElement("span", "cell-muted", "Configure routing, then compute routes."));
      return;
    }
    const ranking = rankEntry.record;
    const people = Array.isArray(ranking.people) ? ranking.people : [];
    const noScheduledHousehold = people.length > 0 && people.every((person) => {
      const destinations = isRecord(person) && Array.isArray(person.destinations) ? person.destinations : [];
      return destinations.length > 0
        && destinations.every((destination) => isRecord(destination) && destination.ignored_zero_weight === true);
    });
    const headline = createElement("div", "commute-rank");
    headline.append(createElement("strong", "", `Rank ${rankEntry.rank}`));
    const meanWeekly = formatMinutes(ranking.mean_weekly_minutes);
    const worstWeekly = formatMinutes(ranking.worst_person_weekly_minutes);
    const summary = [];
    if (noScheduledHousehold) summary.push("No scheduled commute days");
    else {
      if (meanWeekly) summary.push(`${meanWeekly}/week average per person`);
      if (worstWeekly) summary.push(`${worstWeekly}/week highest person`);
    }
    headline.append(createElement("span", "", summary.length ? summary.join(" · ") : "Commute summary incomplete"));
    cell.append(headline);

    people.forEach((person) => {
      if (!isRecord(person)) return;
      const line = createElement("div", "commute-person");
      line.append(createElement("strong", "", personName(person.person_id)));
      const metrics = [];
      const destinations = Array.isArray(person.destinations) ? person.destinations : [];
      const noScheduledDays = destinations.length > 0
        && destinations.every((destination) => isRecord(destination) && destination.ignored_zero_weight === true);
      const daily = formatMinutes(person.daily_minutes);
      const weekly = formatMinutes(person.weekly_minutes);
      const worst = formatMinutes(person.worst_leg_minutes);
      const cap = formatMinutes(person.max_minutes);
      if (noScheduledDays) {
        metrics.push("no scheduled commute days");
      } else {
        if (daily) metrics.push(`${daily}/day`);
        if (weekly) metrics.push(`${weekly}/week`);
        if (worst) metrics.push(`worst leg ${worst}`);
        if (cap) metrics.push(`cap ${cap}`);
        if (person.best_mode) metrics.push(formatModeSummary(person.best_mode));
        if (person.over_cap === true) metrics.push("over cap");
      }
      if (person.complete === false || !metrics.length) metrics.push("route unavailable");
      line.append(createElement("span", "", metrics.join(" · ")));
      cell.append(line);
    });

    if (ranking.complete === false) {
      const missingCount = Array.isArray(ranking.missing_routes)
        ? ranking.missing_routes.length
        : finiteNumber(ranking.missing_routes);
      const detail = missingCount ? ` · ${missingCount} missing` : "";
      const warning = createElement("div", "tag-row");
      warning.append(createElement("span", "tag tag-warning", `Incomplete routes${detail}`));
      cell.append(warning);
    }
  }

  function formatModeSummary(value) {
    const mode = String(value);
    if (mode === "drive") return "drive · free flow";
    if (mode === "mixed") return "mode varies by destination";
    const directional = mode.split("/");
    if (directional.length === 2) return `${directional[0]} out · ${directional[1]} back`;
    return mode;
  }

  function renderListings() {
    const rankings = rankingMap();
    const listings = filteredListings(rankings);
    els.listingRows.replaceChildren(...listings.map((listing) => createListingRow(listing, rankings.get(String(listing.id)))));
    const total = workspace.listings.length;
    els.resultSummary.textContent = `${listings.length} shown · ${total} total`;
    els.emptyState.hidden = listings.length > 0;
    if (!listings.length) {
      els.emptyMessage.textContent = total
        ? "No listings match these filters. Clear filters to see the full workspace."
        : "Import a JSON file or use the CLI to add listing evidence.";
    }
  }

  function field(labelText, className) {
    const label = createElement("label", `field${className ? ` ${className}` : ""}`);
    label.append(createElement("span", "", labelText));
    return label;
  }

  function inputField(labelText, value, options = {}) {
    const label = field(labelText, options.className);
    const input = document.createElement("input");
    input.type = options.type || "text";
    input.value = value === null || value === undefined ? "" : String(value);
    if (options.placeholder) input.placeholder = options.placeholder;
    if (options.min !== undefined) input.min = String(options.min);
    if (options.max !== undefined) input.max = String(options.max);
    if (options.step !== undefined) input.step = String(options.step);
    if (options.inputMode) input.inputMode = options.inputMode;
    if (options.dataKey) input.dataset.key = options.dataKey;
    label.append(input);
    return label;
  }

  function renderConfig() {
    const config = workspace.config;
    els.cityInput.value = config.city || "";
    els.timezoneInput.value = config.timezone || "";
    els.currencyInput.value = config.currency || "USD";
    els.routingJson.value = JSON.stringify(isRecord(config.routing) ? config.routing : {}, null, 2);
    const people = Array.isArray(config.people) ? config.people : [];
    els.peopleList.replaceChildren();
    people.forEach((person) => appendPerson(person));
    renderPeopleEmptyState();
    setFormStatus(els.configStatus, "");
  }

  function appendPerson(person = {}) {
    const personId = person.id === null || person.id === undefined ? makeId("person") : String(person.id);
    const card = createElement("section", "person-card");
    card.dataset.personId = personId;

    const header = createElement("div", "person-header");
    header.append(inputField("Person name", person.name || "", { dataKey: "name", placeholder: "Name" }));
    header.append(inputField("Commute cap (min, optional)", person.max_minutes, {
      type: "number",
      min: 1,
      step: 1,
      inputMode: "numeric",
      dataKey: "maxMinutes",
      placeholder: "No cap"
    }));
    const remove = createElement("button", "icon-button", "×");
    remove.type = "button";
    remove.dataset.action = "remove-person";
    remove.setAttribute("aria-label", `Remove ${person.name || "person"}`);
    remove.title = "Remove person";
    header.append(remove);
    card.append(header);

    const modeFieldset = createElement("fieldset", "mode-fieldset");
    modeFieldset.append(createElement("legend", "group-label", "Allowed travel modes"));
    const modeOptions = createElement("div", "mode-options");
    const selectedModes = Array.isArray(person.modes) ? person.modes : [];
    MODES.forEach((mode) => {
      const label = createElement("label", "mode-option");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = mode;
      checkbox.dataset.mode = mode;
      checkbox.checked = selectedModes.includes(mode);
      label.append(checkbox, document.createTextNode(mode === "drive" ? "drive (free flow)" : mode));
      modeOptions.append(label);
    });
    modeFieldset.append(modeOptions);
    card.append(modeFieldset);

    const destinations = createElement("div", "destinations");
    const destinationHeading = createElement("div", "destination-heading");
    destinationHeading.append(createElement("span", "group-label", "Destinations"));
    const add = createElement("button", "text-button", "Add destination");
    add.type = "button";
    add.dataset.action = "add-destination";
    destinationHeading.append(add);
    destinations.append(destinationHeading);
    const list = createElement("div", "destination-list");
    destinations.append(list);
    card.append(destinations);
    els.peopleList.append(card);

    const personDestinations = Array.isArray(person.destinations) ? person.destinations : [];
    personDestinations.forEach((destination) => appendDestination(card, destination));
  }

  function appendDestination(personCard, destination = {}) {
    const list = personCard.querySelector(".destination-list");
    const row = createElement("div", "destination-row");
    row.dataset.destinationId = destination.id === null || destination.id === undefined
      ? makeId("destination")
      : String(destination.id);
    row.append(inputField("Destination", destination.name || "", { dataKey: "name", placeholder: "Office, school…" }));
    row.append(inputField("Latitude", destination.lat, {
      type: "number",
      min: -90,
      max: 90,
      step: "any",
      inputMode: "decimal",
      dataKey: "lat",
      placeholder: "41.8781"
    }));
    row.append(inputField("Longitude", destination.lon, {
      type: "number",
      min: -180,
      max: 180,
      step: "any",
      inputMode: "decimal",
      dataKey: "lon",
      placeholder: "-87.6298"
    }));
    row.append(inputField("Days / week", destination.days_per_week, {
      type: "number",
      min: 0,
      max: 7,
      step: 0.5,
      inputMode: "decimal",
      dataKey: "days",
      placeholder: "5"
    }));
    const remove = createElement("button", "icon-button", "×");
    remove.type = "button";
    remove.dataset.action = "remove-destination";
    remove.setAttribute("aria-label", `Remove ${destination.name || "destination"}`);
    remove.title = "Remove destination";
    row.append(remove);
    const lookup = createElement("div", "address-lookup");
    lookup.append(inputField("US address (optional)", destination.address || "", {
      dataKey: "address",
      placeholder: "Street, city, state, ZIP"
    }));
    const lookupButton = createElement("button", "button button-quiet", "Look up via US Census");
    lookupButton.type = "button";
    lookupButton.dataset.action = "geocode-destination";
    lookup.append(lookupButton);
    lookup.append(createElement("p", "address-note", "Sends this address to the US Census geocoder; US addresses only. Or enter coordinates directly."));
    const lookupStatus = createElement("p", "address-status");
    lookupStatus.setAttribute("role", "status");
    lookupStatus.setAttribute("aria-live", "polite");
    lookup.append(lookupStatus);
    row.append(lookup);
    list.append(row);
  }

  function renderPeopleEmptyState() {
    const existing = els.peopleList.querySelector(".person-empty");
    if (els.peopleList.querySelector(".person-card")) {
      if (existing) existing.remove();
      return;
    }
    if (!existing) {
      els.peopleList.append(createElement("div", "person-empty", "Add a person to compare household commutes."));
    }
  }

  function requiredNumber(input, label, min, max) {
    const value = finiteNumber(input.value);
    if (value === null || (min !== undefined && value < min) || (max !== undefined && value > max)) {
      throw new Error(`${label} must be a number${min !== undefined && max !== undefined ? ` from ${min} to ${max}` : ""}.`);
    }
    return value;
  }

  function collectConfig() {
    let routing;
    try {
      routing = JSON.parse(els.routingJson.value || "{}");
    } catch (_error) {
      throw new Error("Advanced routing configuration is not valid JSON.");
    }
    if (!isRecord(routing)) throw new Error("Advanced routing configuration must be a JSON object.");

    const currency = els.currencyInput.value.trim().toUpperCase();
    if (currency && !/^[A-Z]{3}$/.test(currency)) throw new Error("Currency must be a three-letter code such as USD.");

    const originalPeople = Array.isArray(configSnapshot.people) ? configSnapshot.people : [];
    const people = [...els.peopleList.querySelectorAll(".person-card")].map((card, personIndex) => {
      const originalPerson = originalPeople.find((person) => isRecord(person) && String(person.id) === String(card.dataset.personId)) || {};
      const name = card.querySelector('[data-key="name"]').value.trim();
      if (!name) throw new Error(`Person ${personIndex + 1} needs a name.`);
      const maxInput = card.querySelector('[data-key="maxMinutes"]');
      const maxMinutes = maxInput.value.trim() === ""
        ? null
        : requiredNumber(maxInput, `${name}'s commute cap`, 1, 1440);
      const modes = [...card.querySelectorAll("[data-mode]:checked")].map((input) => input.value);
      if (!modes.length) throw new Error(`${name} needs at least one allowed travel mode.`);

      const destinations = [...card.querySelectorAll(".destination-row")].map((row, destinationIndex) => {
        const originalDestinations = Array.isArray(originalPerson.destinations) ? originalPerson.destinations : [];
        const originalDestination = originalDestinations.find((destination) => isRecord(destination) && String(destination.id) === String(row.dataset.destinationId)) || {};
        const destinationName = row.querySelector('[data-key="name"]').value.trim();
        const label = destinationName || `destination ${destinationIndex + 1}`;
        if (!destinationName) throw new Error(`${name}'s destination ${destinationIndex + 1} needs a name.`);
        return {
          ...originalDestination,
          id: row.dataset.destinationId,
          name: destinationName,
          address: row.querySelector('[data-key="address"]').value.trim() || undefined,
          lat: requiredNumber(row.querySelector('[data-key="lat"]'), `${label} latitude`, -90, 90),
          lon: requiredNumber(row.querySelector('[data-key="lon"]'), `${label} longitude`, -180, 180),
          days_per_week: requiredNumber(row.querySelector('[data-key="days"]'), `${label} days per week`, 0, 7)
        };
      });
      if (!destinations.length) throw new Error(`${name} needs at least one destination.`);

      return {
        ...originalPerson,
        id: card.dataset.personId,
        name,
        destinations,
        modes,
        max_minutes: maxMinutes
      };
    });

    return {
      ...configSnapshot,
      city: els.cityInput.value.trim(),
      timezone: els.timezoneInput.value.trim(),
      currency: currency || "USD",
      people,
      routing
    };
  }

  async function saveConfig(event) {
    event.preventDefault();
    let config;
    try {
      config = collectConfig();
    } catch (error) {
      setFormStatus(els.configStatus, errorMessage(error), "error");
      return;
    }
    setButtonBusy(els.saveConfigButton, true, "Saving…", "Save household");
    setFormStatus(els.configStatus, "Saving household…");
    try {
      await api("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config)
      });
      await loadState();
      setFormStatus(els.configStatus, "Household saved. Route results may need recomputing.", "success");
    } catch (error) {
      setFormStatus(els.configStatus, `Could not save: ${errorMessage(error)}`, "error");
    } finally {
      setButtonBusy(els.saveConfigButton, false, "Saving…", "Save household");
    }
  }

  async function computeRoutes() {
    setButtonBusy(els.routeButton, true, "Computing routes…", "Compute routes");
    setNotice("Computing routes. OSM and transit datasets can make this take a while.");
    try {
      await api("/api/routes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      });
      await loadState();
      setNotice("Routes computed. Review incomplete or over-cap results before deciding.");
    } catch (error) {
      setNotice(`Routes were not computed: ${errorMessage(error)} Open the routing setup guide below for optional engine setup.`, "error");
    } finally {
      setButtonBusy(els.routeButton, false, "Computing routes…", "Compute routes");
    }
  }

  function parseImportPayload() {
    let parsed;
    try {
      parsed = JSON.parse(els.importJson.value);
    } catch (_error) {
      throw new Error("Import payload is not valid JSON.");
    }
    const listings = Array.isArray(parsed) ? parsed : isRecord(parsed) ? parsed.listings : null;
    if (!Array.isArray(listings)) throw new Error("Use a JSON array or an object with a listings array.");
    if (!listings.length) throw new Error("The listings array is empty.");
    if (listings.some((listing) => !isRecord(listing))) throw new Error("Every listing must be a JSON object.");
    return listings;
  }

  async function importListings() {
    let listings;
    try {
      listings = parseImportPayload();
    } catch (error) {
      setFormStatus(els.importStatus, errorMessage(error), "error");
      return;
    }
    setButtonBusy(els.importButton, true, "Importing…", "Import listings");
    setFormStatus(els.importStatus, `Importing ${listings.length} listing${listings.length === 1 ? "" : "s"}…`);
    try {
      await api("/api/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ listings })
      });
      els.importJson.value = "";
      els.jsonFileInput.value = "";
      setFormStatus(els.importStatus, `Imported ${listings.length} listing${listings.length === 1 ? "" : "s"}.`, "success");
      await loadState();
    } catch (error) {
      setFormStatus(els.importStatus, `Could not import: ${errorMessage(error)}`, "error");
    } finally {
      setButtonBusy(els.importButton, false, "Importing…", "Import listings");
    }
  }

  async function geocodeDestination(button) {
    const row = button.closest(".destination-row");
    const addressInput = row.querySelector('[data-key="address"]');
    const status = row.querySelector(".address-status");
    const address = addressInput.value.trim();
    if (!address) {
      setFormStatus(status, "Enter a US address or use coordinates directly.", "error");
      return;
    }
    setButtonBusy(button, true, "Looking up…", "Look up via US Census");
    setFormStatus(status, "Looking up this address with the US Census geocoder…");
    try {
      const payload = await api("/api/geocode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address })
      });
      const matches = isRecord(payload) && Array.isArray(payload.matches) ? payload.matches : [];
      if (matches.length === 0) {
        setFormStatus(status, "No match found. Coordinates were left unchanged; refine the address or enter them directly.", "error");
        return;
      }
      if (matches.length !== 1) {
        setFormStatus(status, `${matches.length} matches found. Coordinates were left unchanged; refine the address or enter them directly.`, "error");
        return;
      }
      const match = matches[0];
      const latitude = isRecord(match) ? finiteNumber(match.lat) : null;
      const longitude = isRecord(match) ? finiteNumber(match.lon) : null;
      if (latitude === null || longitude === null || latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
        throw new Error("The geocoder returned invalid coordinates.");
      }
      row.querySelector('[data-key="lat"]').value = String(latitude);
      row.querySelector('[data-key="lon"]').value = String(longitude);
      const matchedAddress = match.address ? String(match.address) : address;
      setFormStatus(status, `Matched ${matchedAddress}. Review the coordinates, then save the household.`, "success");
    } catch (error) {
      setFormStatus(status, `Address lookup failed: ${errorMessage(error)} Coordinates were left unchanged.`, "error");
    } finally {
      setButtonBusy(button, false, "Looking up…", "Look up via US Census");
    }
  }

  function clearFilters() {
    els.filterForm.reset();
    els.sortSelect.value = "rank";
    renderListings();
  }

  els.refreshButton.addEventListener("click", () => loadState({ preserveConfigForm: true }));
  els.openImportButton.addEventListener("click", () => {
    els.importPanel.scrollIntoView({ behavior: "smooth", block: "center" });
    els.importPanel.focus({ preventScroll: true });
  });
  els.routeButton.addEventListener("click", computeRoutes);
  els.filterForm.addEventListener("input", renderListings);
  els.filterForm.addEventListener("change", renderListings);
  els.sortSelect.addEventListener("change", renderListings);
  els.clearFiltersButton.addEventListener("click", clearFilters);
  els.configForm.addEventListener("submit", saveConfig);
  els.addPersonButton.addEventListener("click", () => {
    const empty = els.peopleList.querySelector(".person-empty");
    if (empty) empty.remove();
    appendPerson({ modes: ["walk", "bike", "transit"], max_minutes: 45, destinations: [] });
  });
  els.peopleList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const card = button.closest(".person-card");
    if (button.dataset.action === "remove-person") {
      card.remove();
      renderPeopleEmptyState();
    }
    if (button.dataset.action === "add-destination") appendDestination(card);
    if (button.dataset.action === "remove-destination") button.closest(".destination-row").remove();
    if (button.dataset.action === "geocode-destination") geocodeDestination(button);
  });
  els.jsonFileInput.addEventListener("change", async () => {
    const file = els.jsonFileInput.files && els.jsonFileInput.files[0];
    if (!file) return;
    try {
      els.importJson.value = await file.text();
      setFormStatus(els.importStatus, `Loaded ${file.name}. Review the payload, then import.`);
    } catch (error) {
      setFormStatus(els.importStatus, `Could not read the file: ${errorMessage(error)}`, "error");
    }
  });
  els.importButton.addEventListener("click", importListings);

  loadState();
}());
