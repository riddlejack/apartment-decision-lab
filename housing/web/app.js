(function () {
  "use strict";

  const MODES = ["walk", "bike", "transit", "drive"];
  const els = {
    notice: document.querySelector("#notice"),
    collectButton: document.querySelector("#collect-button"),
    collectionRunButton: document.querySelector("#collection-run-button"),
    collectionSummary: document.querySelector("#collection-summary"),
    sourceRunList: document.querySelector("#source-run-list"),
    assistedPlan: document.querySelector("#assisted-plan"),
    setupForm: document.querySelector("#setup-form"),
    setupCity: document.querySelector("#setup-city"),
    setupResidents: document.querySelector("#setup-residents"),
    setupBudget: document.querySelector("#setup-budget"),
    setupMaxRent: document.querySelector("#setup-max-rent"),
    setupBedrooms: document.querySelector("#setup-bedrooms"),
    setupBathrooms: document.querySelector("#setup-bathrooms"),
    setupSqft: document.querySelector("#setup-sqft"),
    setupMoveIn: document.querySelector("#setup-move-in"),
    setupPets: document.querySelector("#setup-pets"),
    setupParking: document.querySelector("#setup-parking"),
    setupHint: document.querySelector("#setup-hint"),
    setupStatus: document.querySelector("#setup-status"),
    setupButton: document.querySelector("#setup-button"),
    resultSummary: document.querySelector("#result-summary"),
    routeContext: document.querySelector("#route-context"),
    duplicatesNote: document.querySelector("#duplicates-note"),
    listingGrid: document.querySelector("#listing-grid"),
    emptyState: document.querySelector("#empty-state"),
    emptyMessage: document.querySelector("#empty-message"),
    filterForm: document.querySelector("#filter-form"),
    searchInput: document.querySelector("#search-input"),
    maxRentInput: document.querySelector("#max-rent-input"),
    bedroomsSelect: document.querySelector("#bedrooms-select"),
    bathroomsSelect: document.querySelector("#bathrooms-select"),
    minSqftInput: document.querySelector("#min-sqft-input"),
    sourceSelect: document.querySelector("#source-select"),
    petsInput: document.querySelector("#pets-input"),
    parkingInput: document.querySelector("#parking-input"),
    unknownInput: document.querySelector("#unknown-input"),
    shortlistInput: document.querySelector("#shortlist-input"),
    hideRejectedInput: document.querySelector("#hide-rejected-input"),
    sortSelect: document.querySelector("#sort-select"),
    clearFiltersButton: document.querySelector("#clear-filters-button"),
    listViewButton: document.querySelector("#list-view-button"),
    mapViewButton: document.querySelector("#map-view-button"),
    listView: document.querySelector("#list-view"),
    mapView: document.querySelector("#map-view"),
    mapGate: document.querySelector("#map-gate"),
    loadMapButton: document.querySelector("#load-map-button"),
    locateListingsButton: document.querySelector("#locate-listings-button"),
    listingMap: document.querySelector("#listing-map"),
    mapStatus: document.querySelector("#map-status"),
    configForm: document.querySelector("#config-form"),
    cityInput: document.querySelector("#city-input"),
    timezoneInput: document.querySelector("#timezone-input"),
    currencyInput: document.querySelector("#currency-input"),
    routeDateInput: document.querySelector("#route-date-input"),
    routeOutboundInput: document.querySelector("#route-outbound-input"),
    routeReturnInput: document.querySelector("#route-return-input"),
    routeThreadsInput: document.querySelector("#route-threads-input"),
    routeMemoryInput: document.querySelector("#route-memory-input"),
    routingJson: document.querySelector("#routing-json"),
    peopleList: document.querySelector("#people-list"),
    addPersonButton: document.querySelector("#add-person-button"),
    saveConfigButton: document.querySelector("#save-config-button"),
    configStatus: document.querySelector("#config-status"),
    routeButton: document.querySelector("#route-button"),
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
    status: {},
    searchSummary: {},
    duplicateGroups: [],
    sourceCatalog: []
  };
  let configSnapshot = {};
  let generatedId = 0;
  let filtersInitialized = false;
  let visibleListings = [];
  let listingMap = null;
  let markerLayer = null;
  let mapActivated = false;

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
    try {
      const payload = await api("/api/state");
      if (!isRecord(payload)) throw new Error("The state API returned an invalid response.");
      workspace = {
        listings: Array.isArray(payload.listings) ? payload.listings : [],
        config: isRecord(payload.config) ? payload.config : {},
        routes: payload.routes || {},
        rankings: Array.isArray(payload.rankings) ? payload.rankings : [],
        status: isRecord(payload.status) ? payload.status : {},
        searchSummary: isRecord(payload.search_summary) ? payload.search_summary : {},
        duplicateGroups: Array.isArray(payload.duplicate_groups) ? payload.duplicate_groups : [],
        sourceCatalog: Array.isArray(payload.source_catalog) ? payload.source_catalog : [],
        collectionPlan: isRecord(payload.collection_plan) ? payload.collection_plan : {}
      };
      configSnapshot = deepCopy(workspace.config);
      renderSourceOptions();
      renderCollectionStatus();
      renderAssistedPlan();
      renderListings();
      renderRouteContext();
      renderDuplicateGroups();
      if (!options.preserveSetupForm) renderSetup();
      if (!options.preserveConfigForm) renderConfig();
      renderWorkspaceStatus();
    } catch (error) {
      setNotice(`Could not load this workspace: ${errorMessage(error)}`, "error");
      els.resultSummary.textContent = "Workspace unavailable";
      els.collectionSummary.textContent = "Local server unavailable";
      els.listingGrid.replaceChildren();
      els.emptyState.hidden = false;
      els.emptyMessage.textContent = "Start the local server, then reload this page.";
    }
  }

  function renderWorkspaceStatus() {
    const routeStatus = isRecord(workspace.routes) ? workspace.routes.status : null;
    if (workspace.status.routes_stale === true || routeStatus === "stale") {
      setNotice("Commute results are stale. Recompute them before using commute rank.", "warning");
      return;
    }
    if (typeof workspace.status.message === "string" && workspace.status.message.trim()) {
      setNotice(workspace.status.message.trim(), workspace.status.level === "error" ? "error" : undefined);
      return;
    }
    setNotice("");
  }

  function renderSetup() {
    const search = isRecord(workspace.config.search) ? workspace.config.search : {};
    const people = Array.isArray(workspace.config.people) ? workspace.config.people : [];
    const residents = finiteNumber(search.residents) || people.length || 2;
    const maxRent = finiteNumber(search.max_rent);
    const budget = finiteNumber(search.budget_per_person) || (maxRent !== null ? Math.round(maxRent / residents) : null);
    els.setupCity.value = search.city || workspace.config.city || "Chicago";
    els.setupResidents.value = String(residents);
    els.setupBudget.value = budget === null ? "" : String(budget);
    els.setupMaxRent.value = maxRent === null ? "" : String(maxRent);
    els.setupBedrooms.value = finiteNumber(search.min_bedrooms) === null ? String(Math.max(1, residents)) : String(search.min_bedrooms);
    els.setupBathrooms.value = finiteNumber(search.min_bathrooms) === null ? "" : String(search.min_bathrooms);
    els.setupSqft.value = finiteNumber(search.min_sqft) === null ? "" : String(search.min_sqft);
    els.setupMoveIn.value = typeof search.move_in_date === "string" ? search.move_in_date : "";
    els.setupPets.checked = search.pets_required === true;
    els.setupParking.checked = search.parking_required === true;
    updateSetupHint();
    if (!filtersInitialized) {
      els.maxRentInput.value = maxRent === null ? "" : String(maxRent);
      els.bedroomsSelect.value = optionValue(els.bedroomsSelect, search.min_bedrooms);
      els.bathroomsSelect.value = optionValue(els.bathroomsSelect, search.min_bathrooms);
      els.minSqftInput.value = finiteNumber(search.min_sqft) === null ? "" : String(search.min_sqft);
      els.petsInput.checked = search.pets_required === true;
      els.parkingInput.checked = search.parking_required === true;
      filtersInitialized = true;
      renderListings();
    }
    setFormStatus(els.setupStatus, "");
  }

  function optionValue(select, value) {
    const normalized = finiteNumber(value);
    if (normalized === null) return "";
    const exact = [...select.options].find((option) => finiteNumber(option.value) === normalized);
    return exact ? exact.value : "";
  }

  function updateSetupHint() {
    const chicago = els.setupCity.value.trim().toLocaleLowerCase().includes("chicago");
    els.setupHint.textContent = chicago
      ? "Chicago setup adds the current starter source set. Coverage still depends on each source run."
      : "Other cities can use the same workflow, but their source set may need manual configuration.";
  }

  function optionalNumber(input) {
    return input.value.trim() === "" ? null : finiteNumber(input.value);
  }

  async function saveSetup(event) {
    event.preventDefault();
    const city = els.setupCity.value.trim();
    const residents = finiteNumber(els.setupResidents.value);
    const budgetPerPerson = finiteNumber(els.setupBudget.value);
    const minBedrooms = finiteNumber(els.setupBedrooms.value);
    if (!city || residents === null || residents < 1 || budgetPerPerson === null || budgetPerPerson < 0 || minBedrooms === null || minBedrooms < 0) {
      setFormStatus(els.setupStatus, "Add a city, roommate count, budget, and bedroom minimum.", "error");
      return;
    }
    const maxRent = optionalNumber(els.setupMaxRent) ?? residents * budgetPerPerson;
    const search = {
      residents,
      budget_per_person: budgetPerPerson,
      max_rent: maxRent,
      min_bedrooms: minBedrooms,
      min_bathrooms: optionalNumber(els.setupBathrooms),
      min_sqft: optionalNumber(els.setupSqft),
      move_in_date: els.setupMoveIn.value || null,
      pets_required: els.setupPets.checked,
      parking_required: els.setupParking.checked
    };
    setButtonBusy(els.setupButton, true, "Saving search…", "Save search & set up sources");
    setFormStatus(els.setupStatus, "Saving search…");
    try {
      await api("/api/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ city, search, include_sources: true })
      });
      filtersInitialized = false;
      await loadState();
      setFormStatus(els.setupStatus, "Search saved. Run collection when you’re ready.", "success");
    } catch (error) {
      setFormStatus(els.setupStatus, `Could not save: ${errorMessage(error)}`, "error");
    } finally {
      setButtonBusy(els.setupButton, false, "Saving search…", "Save search & set up sources");
    }
  }

  function sourceName(source) {
    if (typeof source === "string") return source;
    if (!isRecord(source)) return "Unknown source";
    return String(source.name || source.id || source.source || source.url || "Unknown source");
  }

  function sourceId(source) {
    if (typeof source === "string") return source;
    if (!isRecord(source)) return "unknown";
    return String(source.id || source.source || source.name || source.url || "unknown");
  }

  function renderCollectionStatus() {
    const sources = Array.isArray(workspace.config.sources) ? workspace.config.sources : [];
    const runs = Array.isArray(workspace.status.runs)
      ? workspace.status.runs
      : Array.isArray(workspace.status.recent_runs) ? workspace.status.recent_runs : [];
    const labelById = new Map(workspace.sourceCatalog.filter(isRecord).map((source) => [sourceId(source), sourceName(source)]));
    sources.forEach((source) => labelById.set(sourceId(source), sourceName(source)));
    const latestBySource = new Map();
    runs.forEach((run) => {
      if (!isRecord(run) || !run.source) return;
      const key = String(run.source);
      const current = latestBySource.get(key);
      if (!current || Date.parse(run.captured_at || "") >= Date.parse(current.captured_at || "")) latestBySource.set(key, run);
    });
    els.sourceRunList.replaceChildren();
    const ids = sources.map(sourceId);
    latestBySource.forEach((_run, id) => { if (!ids.includes(id)) ids.push(id); });
    ids.forEach((id) => {
        const run = latestBySource.get(id);
        let status = run && run.status ? String(run.status).toLocaleLowerCase() : "ready";
        if (run && run.blocked === true) status = "blocked";
        else if (run && run.partial === true) status = "partial";
        const count = run ? finiteNumber(run.count) : null;
        const label = labelById.get(id) || id;
        const chip = createElement("span", "source-run", count === null ? label : `${label} · ${count}`);
        chip.dataset.status = status;
        if (run && run.message) chip.title = String(run.message);
        else if (run && run.captured_at) chip.title = `Last run ${formatDateTime(run.captured_at)}`;
        els.sourceRunList.append(chip);
    });
    const progressById = new Map((workspace.collectionPlan.sources || []).map((item) => [item.source.id, item.progress]));
    const catalogGaps = workspace.sourceCatalog.filter((source) => isRecord(source) && source.enabled === false && !progressById.get(source.id));
    catalogGaps.forEach((source) => {
      const chip = createElement("span", "source-run", `${sourceName(source)} · gap`);
      chip.dataset.status = "blocked";
      chip.title = String(source.disabled_reason || source.assisted_reason || source.permission_note || "Source is not enabled.");
      els.sourceRunList.append(chip);
    });
    if (!ids.length && !catalogGaps.length) els.sourceRunList.append(createElement("span", "source-run", "No sources configured"));
    const failed = [...latestBySource.values()].filter((run) => run.blocked === true || ["error", "failed", "blocked", "unimplemented"].includes(String(run.status).toLocaleLowerCase())).length;
    const partial = [...latestBySource.values()].filter((run) => run.partial === true || String(run.status).toLocaleLowerCase() === "partial").length;
    if (!sources.length) els.collectionSummary.textContent = catalogGaps.length ? `No active sources; ${catalogGaps.length} known coverage gap${catalogGaps.length === 1 ? "" : "s"}.` : "Save a search to set up sources.";
    else if (!runs.length) els.collectionSummary.textContent = `${sources.length} source${sources.length === 1 ? "" : "s"} ready; no run recorded yet.`;
    else if (failed || partial || catalogGaps.length) els.collectionSummary.textContent = `${runs.length} recent run${runs.length === 1 ? "" : "s"}; ${failed} blocked or failed, ${partial} partial, ${catalogGaps.length} catalog gap${catalogGaps.length === 1 ? "" : "s"}.`;
    else els.collectionSummary.textContent = `${runs.length} recent run${runs.length === 1 ? "" : "s"}; configured sources reported no errors.`;
  }

  function renderAssistedPlan() {
    els.assistedPlan.replaceChildren();
    const items = workspace.collectionPlan.sources || [];
    items.filter((item) => item.action !== "none" && item.action !== "collect_http").forEach((item) => {
      const row = createElement("li");
      const source = item.source || {};
      const url = validHttpUrl(item.resume_url || source.url);
      const link = createElement(url ? "a" : "span", "", source.name || source.id);
      if (url) { link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; }
      const progress = item.progress;
      const detail = progress
        ? `${progress.status} · ${progress.pages_visited} page(s) visited${item.resume_url ? " · resume saved" : ""}`
        : item.action === "resume_http" ? "partial automatic run · continue collection" : source.browser_recipe ? "browser recipe ready · not searched yet" : "needs source inspection";
      row.append(link, document.createTextNode(` — ${detail}`));
      els.assistedPlan.append(row);
    });
    if (!els.assistedPlan.children.length) els.assistedPlan.append(createElement("li", "", "No pending sources in this workspace."));
  }

  async function runCollection() {
    [els.collectButton, els.collectionRunButton].forEach((button) => setButtonBusy(button, true, "Collecting…", button === els.collectButton ? "Refresh listings" : "Run collection"));
    setNotice("Collection is running. Source failures will stay visible here.");
    try {
      await api("/api/collect", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      await loadState({ preserveConfigForm: true, preserveSetupForm: true });
      setNotice("Collection finished. New and changed listings are at the top.");
    } catch (error) {
      setNotice(`Collection stopped: ${errorMessage(error)}`, "error");
      await loadState({ preserveConfigForm: true, preserveSetupForm: true });
    } finally {
      setButtonBusy(els.collectButton, false, "Collecting…", "Refresh listings");
      setButtonBusy(els.collectionRunButton, false, "Collecting…", "Run collection");
    }
  }

  function renderSourceOptions() {
    const prior = els.sourceSelect.value;
    const sources = [...new Set(workspace.listings.map((listing) => String(listing.source || "").trim()).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b));
    const all = createElement("option", "", "All sources");
    all.value = "";
    els.sourceSelect.replaceChildren(all);
    sources.forEach((source) => {
      const option = createElement("option", "", source);
      option.value = source;
      els.sourceSelect.append(option);
    });
    els.sourceSelect.value = sources.includes(prior) ? prior : "";
  }

  function annotationFor(listing) {
    if (isRecord(listing.annotation)) {
      return { status: String(listing.annotation.status || "none"), note: String(listing.annotation.note || "") };
    }
    return { status: ["shortlist", "rejected"].includes(listing.status) ? listing.status : "none", note: String(listing.note || "") };
  }

  function changeFor(listing) {
    if (isRecord(listing.change)) return listing.change;
    if (["new", "changed", "unchanged"].includes(listing.status)) return { kind: listing.status };
    return { kind: "unchanged" };
  }

  function rankingMap() {
    const map = new Map();
    workspace.rankings.forEach((record, index) => {
      if (!isRecord(record) || record.listing_id === null || record.listing_id === undefined) return;
      const explicitRank = finiteNumber(record.rank ?? record.commute_rank);
      map.set(String(record.listing_id), { record, rank: explicitRank === null ? index + 1 : explicitRank });
    });
    return map;
  }

  function booleanMatches(value, required, keepUnknown) {
    if (!required) return true;
    if (value === true) return true;
    if (value === false) return false;
    return keepUnknown;
  }

  function filteredListings(rankings) {
    const query = els.searchInput.value.trim().toLocaleLowerCase();
    const maxRent = finiteNumber(els.maxRentInput.value);
    const minBeds = finiteNumber(els.bedroomsSelect.value);
    const minBaths = finiteNumber(els.bathroomsSelect.value);
    const minSqft = finiteNumber(els.minSqftInput.value);
    const source = els.sourceSelect.value;
    const keepUnknown = els.unknownInput.checked;
    const searchConfig = isRecord(workspace.config.search) ? workspace.config.search : {};
    const moveInDate = dateOnlyValue(searchConfig.move_in_date);
    const listings = workspace.listings.filter((listing) => {
      if (!isRecord(listing)) return false;
      const annotation = annotationFor(listing);
      if (els.hideRejectedInput.checked && annotation.status === "rejected") return false;
      if (els.shortlistInput.checked && annotation.status !== "shortlist") return false;
      const haystack = [listing.title, listing.address, listing.unit, listing.source, listing.property_type]
        .concat(Array.isArray(listing.amenities) ? listing.amenities : [])
        .filter((value) => value !== null && value !== undefined).join(" ").toLocaleLowerCase();
      if (query && !haystack.includes(query)) return false;
      const numericChecks = [[listing.rent, maxRent, "max"], [listing.bedrooms, minBeds, "min"], [listing.bathrooms, minBaths, "min"], [listing.sqft, minSqft, "min"]];
      for (const [raw, threshold, direction] of numericChecks) {
        if (threshold === null) continue;
        const value = finiteNumber(raw);
        if (value === null && !keepUnknown) return false;
        if (value !== null && direction === "max" && value > threshold) return false;
        if (value !== null && direction === "min" && value < threshold) return false;
      }
      if (!booleanMatches(listing.pets, els.petsInput.checked, keepUnknown)) return false;
      if (!booleanMatches(listing.parking, els.parkingInput.checked, keepUnknown)) return false;
      if (moveInDate !== null) {
        const availableDate = dateOnlyValue(listing.available_date);
        if (availableDate === null && !keepUnknown) return false;
        if (availableDate !== null && availableDate > moveInDate) return false;
      }
      if (source && String(listing.source || "") !== source) return false;
      return true;
    });
    const sort = els.sortSelect.value;
    listings.sort((a, b) => {
      if (sort === "rent") return compareNullableNumbers(a.rent, b.rent);
      if (sort === "sqft") return compareNullableNumbers(b.sqft, a.sqft);
      if (sort === "rank") {
        const left = rankings.get(String(a.id));
        const right = rankings.get(String(b.id));
        if (left && right) return left.rank - right.rank;
        if (left) return -1;
        if (right) return 1;
        return compareNullableNumbers(a.rent, b.rent);
      }
      const priority = { new: 0, changed: 1, unchanged: 2 };
      const changeDiff = (priority[changeFor(a).kind] ?? 2) - (priority[changeFor(b).kind] ?? 2);
      if (changeDiff) return changeDiff;
      return (Date.parse(b.observed_at || "") || 0) - (Date.parse(a.observed_at || "") || 0);
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

  function currencyCode() {
    return /^[A-Za-z]{3}$/.test(workspace.config.currency || "") ? workspace.config.currency.toUpperCase() : "USD";
  }

  function formatMoney(value) {
    const number = finiteNumber(value);
    if (number === null) return "Unknown";
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency: currencyCode(), maximumFractionDigits: Number.isInteger(number) ? 0 : 2 }).format(number);
    } catch (_error) {
      return `${number.toLocaleString()} ${currencyCode()}`;
    }
  }

  function formatDate(value) {
    const match = typeof value === "string" ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(value) : null;
    const timestamp = match
      ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])).getTime()
      : Date.parse(value || "");
    if (!Number.isFinite(timestamp)) return null;
    return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(timestamp);
  }

  function dateOnlyValue(value) {
    if (typeof value !== "string") return null;
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
    if (!match) return null;
    const number = Number(`${match[1]}${match[2]}${match[3]}`);
    return Number.isFinite(number) ? number : null;
  }

  function formatDateTime(value) {
    const timestamp = Date.parse(value || "");
    if (!Number.isFinite(timestamp)) return "time unknown";
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(timestamp);
  }

  function formatObserved(value, synthetic) {
    const timestamp = Date.parse(value || "");
    if (!Number.isFinite(timestamp)) return "Observation time unknown";
    if (synthetic === true) return `Example dated ${formatDate(value)}`;
    const days = Math.max(0, Math.floor((Date.now() - timestamp) / 86400000));
    if (days === 0) return "Observed today";
    if (days === 1) return "Observed yesterday";
    return `Observed ${days} days ago`;
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

  function feeSummary(value) {
    if (value === null || value === undefined) return { total: 0, provided: false };
    const direct = finiteNumber(value);
    if (direct !== null) return { total: direct, provided: true };
    let total = 0;
    let found = false;
    const add = (candidate) => {
      const number = finiteNumber(candidate);
      if (number !== null) { total += number; found = true; }
    };
    if (Array.isArray(value)) {
      value.forEach((entry) => {
        if (isRecord(entry)) add(entry.amount ?? entry.value ?? entry.cost);
        else add(entry);
      });
    } else if (isRecord(value)) {
      const explicit = finiteNumber(value.total ?? value.amount ?? value.value);
      if (explicit !== null) return { total: explicit, provided: true };
      Object.values(value).forEach((entry) => {
        if (isRecord(entry)) add(entry.amount ?? entry.value ?? entry.cost);
        else add(entry);
      });
    }
    return { total, provided: found || Array.isArray(value) || isRecord(value) };
  }

  function residentCount() {
    const search = isRecord(workspace.config.search) ? workspace.config.search : {};
    const configured = finiteNumber(search.residents);
    if (configured !== null && configured > 0) return configured;
    const people = Array.isArray(workspace.config.people) ? workspace.config.people.length : 0;
    return people || 1;
  }

  function addFact(container, label, value, known = true) {
    const fact = createElement("span", `fact${known ? "" : " fact-unknown"}`);
    if (known) fact.append(createElement("strong", "", `${label} `), document.createTextNode(value));
    else fact.textContent = `${label} unknown`;
    container.append(fact);
  }

  function configuredPerson(personId) {
    const people = Array.isArray(workspace.config.people) ? workspace.config.people : [];
    return people.find((person) => isRecord(person) && String(person.id) === String(personId)) || {};
  }

  function configuredDestination(person, destinationId) {
    const destinations = Array.isArray(person.destinations) ? person.destinations : [];
    return destinations.find((destination) => isRecord(destination) && String(destination.id) === String(destinationId)) || {};
  }

  function minuteValue(value) {
    const number = finiteNumber(value);
    return number === null ? "missing" : `${Math.round(number)} min`;
  }

  function createCommuteDetails(rankEntry) {
    const details = createElement("details", "commute-details");
    if (!rankEntry || !isRecord(rankEntry.record)) {
      details.append(createElement("summary", "", "Commutes not computed"));
      details.append(createElement("p", "commute-empty", "Add household destinations and compute routes to compare each trip."));
      return details;
    }
    const ranking = rankEntry.record;
    const people = Array.isArray(ranking.people) ? ranking.people : [];
    const complete = ranking.complete === true;
    const overCap = finiteNumber(ranking.over_cap_count) || (Array.isArray(ranking.over_cap_people) ? ranking.over_cap_people.length : 0);
    const status = !complete ? "incomplete" : overCap ? `${overCap} over cap` : "complete";
    details.append(createElement("summary", "", `Commutes · rank ${rankEntry.rank} · ${status}`));
    const body = createElement("div", "commute-detail-body");
    people.forEach((personResult) => {
      if (!isRecord(personResult)) return;
      const person = configuredPerson(personResult.person_id);
      const block = createElement("div", "commute-person-block");
      const heading = createElement("p", "commute-person-heading");
      const name = String(person.name || personResult.person_id || "Person");
      const weekly = finiteNumber(personResult.weekly_minutes);
      heading.append(createElement("strong", "", name), document.createTextNode(weekly === null ? " · weekly total missing" : ` · ${Math.round(weekly)} min/week`));
      const personStatus = personResult.complete !== true ? "Incomplete" : personResult.over_cap === true ? "Over cap" : "Within cap";
      heading.append(createElement("span", personResult.complete !== true || personResult.over_cap === true ? "commute-alert" : "", personStatus));
      block.append(heading);
      const destinations = Array.isArray(personResult.destinations) ? personResult.destinations : [];
      destinations.forEach((destinationResult) => {
        if (!isRecord(destinationResult)) return;
        const destination = configuredDestination(person, destinationResult.destination_id);
        const label = String(destination.name || destinationResult.destination_id || "Destination");
        const outboundMode = destinationResult.outbound_mode || destinationResult.best_mode || "mode unknown";
        const returnMode = destinationResult.return_mode || destinationResult.best_mode || "mode unknown";
        const row = createElement("p", "commute-destination");
        row.append(createElement("strong", "", label));
        row.append(document.createTextNode(` · out ${minuteValue(destinationResult.outbound_minutes)} (${outboundMode}) · back ${minuteValue(destinationResult.return_minutes)} (${returnMode})`));
        if (destinationResult.complete !== true) row.append(createElement("span", "commute-alert", "Missing route"));
        block.append(row);
      });
      body.append(block);
    });
    const missing = Array.isArray(ranking.missing_routes) ? ranking.missing_routes : [];
    if (missing.length) body.append(createElement("p", "commute-missing", `${missing.length} route${missing.length === 1 ? "" : "s"} missing. Missing time is never treated as zero.`));
    details.append(body);
    return details;
  }

  function createListingCard(listing, rankEntry) {
    const annotation = annotationFor(listing);
    const change = changeFor(listing);
    const card = createElement("article", "listing-card");
    card.dataset.listingId = String(listing.id);
    card.dataset.status = annotation.status;
    card.dataset.change = change.kind || "unchanged";

    const main = createElement("div", "listing-main");
    const topline = createElement("div", "listing-topline");
    const title = String(listing.title || listing.address || "Untitled listing");
    topline.append(createElement("h3", "listing-title", title));
    if (change.kind === "new") topline.append(createElement("span", "tag tag-new", "New"));
    if (change.kind === "changed") topline.append(createElement("span", "tag tag-changed", "Changed"));
    if (listing.synthetic === true) topline.append(createElement("span", "tag", "Synthetic"));
    if (listing.historical === true) topline.append(createElement("span", "tag tag-warning", "Historical"));
    if (listing.property_type) topline.append(createElement("span", "tag", String(listing.property_type)));
    main.append(topline);
    const address = [listing.address, listing.unit].filter((value) => value !== null && value !== undefined && String(value).trim()).join(" · ");
    main.append(createElement("p", "listing-address", address || "Address unknown"));

    const facts = createElement("div", "facts");
    const beds = finiteNumber(listing.bedrooms);
    const baths = finiteNumber(listing.bathrooms);
    const sqft = finiteNumber(listing.sqft);
    addFact(facts, "Beds", beds === null ? "" : beds.toLocaleString(), beds !== null);
    addFact(facts, "Baths", baths === null ? "" : baths.toLocaleString(), baths !== null);
    addFact(facts, "Space", sqft === null ? "" : `${sqft.toLocaleString()} sq ft`, sqft !== null);
    const available = formatDate(listing.available_date);
    addFact(facts, "Available", available || "", Boolean(available));
    addFact(facts, "Pets", listing.pets === true ? "yes" : listing.pets === false ? "no" : "", listing.pets !== null && listing.pets !== undefined);
    addFact(facts, "Parking", listing.parking === true ? "yes" : listing.parking === false ? "no" : "", listing.parking !== null && listing.parking !== undefined);
    main.append(facts);
    const amenities = Array.isArray(listing.amenities) ? listing.amenities.filter(Boolean).slice(0, 5) : [];
    if (amenities.length) main.append(createElement("p", "amenities", amenities.join(" · ")));
    const evidence = [formatObserved(listing.observed_at, listing.synthetic), listing.source ? `Source: ${listing.source}` : "Source unknown"];
    if (rankEntry) {
      const mean = finiteNumber(rankEntry.record && rankEntry.record.mean_weekly_minutes);
      evidence.push(mean === null ? `Commute rank ${rankEntry.rank}` : `Commute rank ${rankEntry.rank} · ${Math.round(mean)} min/week avg`);
    }
    main.append(createElement("p", "evidence", evidence.join(" · ")));
    main.append(createCommuteDetails(rankEntry));

    const side = createElement("div", "listing-side");
    const rent = finiteNumber(listing.rent);
    side.append(createElement("span", "rent", formatMoney(rent)));
    side.append(createElement("span", "rent-period", rent === null ? "monthly rent unavailable" : "base rent / month"));
    const monthlyFees = feeSummary(listing.monthly_fees);
    const explicitTotal = finiteNumber(listing.total_monthly_cost);
    const knownTotal = explicitTotal ?? (rent === null ? null : rent + monthlyFees.total);
    if (knownTotal !== null) {
      const cost = createElement("p", "cost-line");
      cost.append(createElement("strong", "", formatMoney(knownTotal)), document.createTextNode(" known monthly"));
      cost.append(document.createElement("br"), document.createTextNode(`${formatMoney(knownTotal / residentCount())} each for ${residentCount()}`));
      side.append(cost);
    }
    if (!monthlyFees.provided && explicitTotal === null) side.append(createElement("span", "fee-note", "Base rent only · fees unknown"));
    else if (monthlyFees.total > 0) side.append(createElement("span", "fee-note", `${formatMoney(monthlyFees.total)} known monthly fees`));
    const oneTime = feeSummary(listing.one_time_fees);
    if (oneTime.provided && oneTime.total > 0) side.append(createElement("span", "fee-note", `${formatMoney(oneTime.total)} known move-in fees`));

    const actions = createElement("div", "card-actions");
    const shortlist = createElement("button", `decision-button${annotation.status === "shortlist" ? " is-active" : ""}`, annotation.status === "shortlist" ? "Shortlisted" : "Shortlist");
    shortlist.type = "button";
    shortlist.dataset.action = "shortlist";
    const reject = createElement("button", `decision-button reject${annotation.status === "rejected" ? " is-active" : ""}`, annotation.status === "rejected" ? "Rejected" : "Reject");
    reject.type = "button";
    reject.dataset.action = "rejected";
    const note = createElement("button", "decision-button", annotation.note ? "Edit note" : "Add note");
    note.type = "button";
    note.dataset.action = "note";
    actions.append(shortlist, reject, note);
    const url = validHttpUrl(listing.url);
    if (url) {
      const link = createElement("a", "open-link", "Open ↗");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      actions.append(link);
    }
    side.append(actions);
    card.append(main, side);
    if (annotation.note) card.append(createElement("p", "note-preview", `Note: ${annotation.note}`));
    const editor = createElement("div", "note-editor");
    editor.hidden = true;
    const noteInput = document.createElement("input");
    noteInput.type = "text";
    noteInput.value = annotation.note;
    noteInput.maxLength = 1000;
    noteInput.placeholder = "What matters about this place?";
    noteInput.dataset.role = "note-input";
    const save = createElement("button", "button button-dark button-compact", "Save note");
    save.type = "button";
    save.dataset.action = "save-note";
    editor.append(noteInput, save);
    card.append(editor);
    return card;
  }

  function renderListings() {
    const rankings = rankingMap();
    visibleListings = filteredListings(rankings);
    els.listingGrid.replaceChildren();
    visibleListings.forEach((listing) => els.listingGrid.append(createListingCard(listing, rankings.get(String(listing.id)))));
    const total = workspace.listings.length;
    const shortlistCount = workspace.listings.filter((listing) => annotationFor(listing).status === "shortlist").length;
    const changeCount = workspace.listings.filter((listing) => ["new", "changed"].includes(changeFor(listing).kind)).length;
    els.resultSummary.textContent = `${visibleListings.length} of ${total} shown · ${shortlistCount} shortlisted · ${changeCount} new or changed`;
    els.emptyState.hidden = visibleListings.length > 0;
    if (!total) els.emptyMessage.textContent = "Run collection or import a trusted listing file.";
    else els.emptyMessage.textContent = "Try keeping unknown values or clearing a filter.";
    if (mapActivated) updateMap();
  }

  function renderDuplicateGroups() {
    const count = workspace.duplicateGroups.length;
    els.duplicatesNote.hidden = count === 0;
    els.duplicatesNote.textContent = count ? `${count} possible duplicate group${count === 1 ? "" : "s"} flagged. Records stay separate until reviewed.` : "";
  }

  async function saveAnnotation(listing, status, note, button) {
    const idle = button ? button.textContent : "";
    if (button) setButtonBusy(button, true, "Saving…", idle);
    try {
      await api("/api/annotation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: listing.id, status, note })
      });
      listing.annotation = { status, note };
      renderListings();
    } catch (error) {
      setNotice(`Could not save that decision: ${errorMessage(error)}`, "error");
      if (button) setButtonBusy(button, false, "Saving…", idle);
    }
  }

  function listingByCard(card) {
    return workspace.listings.find((listing) => String(listing.id) === String(card.dataset.listingId));
  }

  function handleListingAction(event) {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const card = button.closest(".listing-card");
    const listing = card && listingByCard(card);
    if (!listing) return;
    const current = annotationFor(listing);
    if (button.dataset.action === "note") {
      const editor = card.querySelector(".note-editor");
      editor.hidden = !editor.hidden;
      if (!editor.hidden) editor.querySelector("input").focus();
      return;
    }
    if (button.dataset.action === "save-note") {
      const value = card.querySelector('[data-role="note-input"]').value.trim();
      saveAnnotation(listing, current.status, value, button);
      return;
    }
    if (["shortlist", "rejected"].includes(button.dataset.action)) {
      const next = current.status === button.dataset.action ? "none" : button.dataset.action;
      saveAnnotation(listing, next, current.note, button);
    }
  }

  function clearFilters() {
    els.filterForm.reset();
    els.unknownInput.checked = true;
    els.hideRejectedInput.checked = true;
    els.sortSelect.value = "newest";
    renderListings();
  }

  function switchView(view) {
    const showMap = view === "map";
    els.listView.hidden = showMap;
    els.mapView.hidden = !showMap;
    els.listViewButton.classList.toggle("is-active", !showMap);
    els.mapViewButton.classList.toggle("is-active", showMap);
    els.listViewButton.setAttribute("aria-pressed", String(!showMap));
    els.mapViewButton.setAttribute("aria-pressed", String(showMap));
    if (showMap && mapActivated && listingMap) {
      setTimeout(() => { listingMap.invalidateSize(); updateMap(); }, 0);
    }
  }

  function listingCoords(listing) {
    const lat = finiteNumber(listing.lat ?? listing.latitude ?? (isRecord(listing.location) ? listing.location.lat ?? listing.location.latitude : null));
    const lon = finiteNumber(listing.lon ?? listing.longitude ?? (isRecord(listing.location) ? listing.location.lon ?? listing.location.longitude : null));
    if (lat === null || lon === null || lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
    return [lat, lon];
  }

  function activateMap() {
    if (!globalThis.L || typeof globalThis.L.map !== "function") {
      els.mapStatus.textContent = "The map library did not load. The listing view still works.";
      setNotice("Map unavailable. Check local static assets, then reload.", "warning");
      return;
    }
    try {
      listingMap = globalThis.L.map(els.listingMap, { zoomControl: true, preferCanvas: true });
      globalThis.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      }).addTo(listingMap);
      markerLayer = globalThis.L.layerGroup().addTo(listingMap);
      mapActivated = true;
      els.mapGate.hidden = true;
      els.listingMap.hidden = false;
      updateMap();
      setTimeout(() => listingMap.invalidateSize(), 0);
    } catch (error) {
      els.mapStatus.textContent = `Map could not start: ${errorMessage(error)}. The list still works.`;
    }
  }

  function updateMap() {
    if (!mapActivated || !listingMap || !markerLayer) return;
    markerLayer.clearLayers();
    const located = [];
    visibleListings.forEach((listing) => {
      const coords = listingCoords(listing);
      if (!coords) return;
      located.push(coords);
      const marker = globalThis.L.marker(coords);
      const popup = createElement("div", "map-popup");
      popup.append(createElement("span", "map-popup-title", String(listing.title || listing.address || "Untitled listing")));
      popup.append(createElement("span", "map-popup-copy", `${formatMoney(listing.rent)} / month · ${finiteNumber(listing.bedrooms) ?? "?"} bed`));
      marker.bindPopup(popup);
      marker.addTo(markerLayer);
    });
    const missing = visibleListings.length - located.length;
    els.mapStatus.textContent = `${located.length} mapped · ${missing} missing coordinates · filters apply to both views`;
    if (located.length === 1) listingMap.setView(located[0], 14);
    else if (located.length > 1) listingMap.fitBounds(located, { padding: [35, 35], maxZoom: 15 });
    else listingMap.setView([41.8781, -87.6298], 11);
  }

  async function locateListings() {
    setButtonBusy(els.locateListingsButton, true, "Locating…", "Locate missing addresses");
    els.mapStatus.textContent = "Sending up to 25 missing listing addresses to the US Census geocoder…";
    try {
      const payload = await api("/api/geocode-listings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 25 })
      });
      await loadState({ preserveConfigForm: true, preserveSetupForm: true });
      const checked = isRecord(payload) ? finiteNumber(payload.addresses_checked) : null;
      const updated = isRecord(payload) ? finiteNumber(payload.listings_updated) : null;
      const unresolved = isRecord(payload) ? finiteNumber(payload.unresolved) : null;
      els.mapStatus.textContent = `${checked ?? 0} checked · ${updated ?? 0} located · ${unresolved ?? 0} unresolved`;
    } catch (error) {
      els.mapStatus.textContent = `Location lookup failed: ${errorMessage(error)}`;
    } finally {
      setButtonBusy(els.locateListingsButton, false, "Locating…", "Locate missing addresses");
    }
  }

  function renderRouteContext() {
    const routes = workspace.routes;
    const status = isRecord(routes) ? routes.status : null;
    if (!isRecord(routes) || (!routes.demo && !["stale", "not_configured", "partial"].includes(status))) {
      els.routeContext.hidden = true;
      els.routeContext.textContent = "";
      return;
    }
    if (routes.demo === true) {
      const message = typeof routes.message === "string" && routes.message.trim() ? routes.message.trim() : "Historical modeled route example.";
      els.routeContext.textContent = `${message} Scheduled estimates are not live predictions.`;
    } else if (status === "not_configured") {
      els.routeContext.textContent = "Commute routing is not configured. Listing comparison still works.";
    } else {
      els.routeContext.textContent = routes.message || "Commute results are incomplete or stale.";
    }
    els.routeContext.hidden = false;
  }

  function inputField(labelText, value, options = {}) {
    const label = createElement("label", "field");
    label.append(createElement("span", "", labelText));
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
    const routing = isRecord(config.routing) ? config.routing : {};
    els.cityInput.value = config.city || "";
    els.timezoneInput.value = config.timezone || "";
    els.currencyInput.value = config.currency || "USD";
    els.routeDateInput.value = typeof routing.date === "string" ? routing.date : "";
    els.routeOutboundInput.value = typeof routing.outbound_time === "string" ? routing.outbound_time : "08:00";
    els.routeReturnInput.value = typeof routing.return_time === "string" ? routing.return_time : "17:30";
    els.routeThreadsInput.value = finiteNumber(routing.threads) === null ? "2" : String(routing.threads);
    els.routeMemoryInput.value = finiteNumber(routing.max_memory_gb) === null ? "4" : String(routing.max_memory_gb);
    els.routingJson.value = JSON.stringify(routing, null, 2);
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
    header.append(inputField("Commute cap (min)", person.max_minutes, { type: "number", min: 1, step: 1, inputMode: "numeric", dataKey: "maxMinutes", placeholder: "Optional" }));
    const remove = createElement("button", "icon-button", "×");
    remove.type = "button";
    remove.dataset.action = "remove-person";
    remove.setAttribute("aria-label", `Remove ${person.name || "person"}`);
    header.append(remove);
    card.append(header);
    const modesFieldset = createElement("fieldset", "mode-fieldset");
    modesFieldset.append(createElement("legend", "group-label", "Allowed travel modes"));
    const options = createElement("div", "mode-options");
    const selected = Array.isArray(person.modes) ? person.modes : [];
    MODES.forEach((mode) => {
      const label = createElement("label", "mode-option");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = mode;
      checkbox.dataset.mode = mode;
      checkbox.checked = selected.includes(mode);
      label.append(checkbox, document.createTextNode(mode === "drive" ? "drive (free flow)" : mode));
      options.append(label);
    });
    modesFieldset.append(options);
    card.append(modesFieldset);
    const destinations = createElement("div", "destinations");
    const heading = createElement("div", "destination-heading");
    heading.append(createElement("span", "group-label", "Destinations"));
    const add = createElement("button", "text-button", "Add destination");
    add.type = "button";
    add.dataset.action = "add-destination";
    heading.append(add);
    destinations.append(heading, createElement("div", "destination-list"));
    card.append(destinations);
    els.peopleList.append(card);
    const personDestinations = Array.isArray(person.destinations) ? person.destinations : [];
    personDestinations.forEach((destination) => appendDestination(card, destination));
  }

  function appendDestination(personCard, destination = {}) {
    const list = personCard.querySelector(".destination-list");
    const row = createElement("div", "destination-row");
    row.dataset.destinationId = destination.id === null || destination.id === undefined ? makeId("destination") : String(destination.id);
    row.append(inputField("Destination", destination.name || "", { dataKey: "name", placeholder: "Office, school…" }));
    row.append(inputField("Latitude", destination.lat, { type: "number", min: -90, max: 90, step: "any", inputMode: "decimal", dataKey: "lat", placeholder: "41.8781" }));
    row.append(inputField("Longitude", destination.lon, { type: "number", min: -180, max: 180, step: "any", inputMode: "decimal", dataKey: "lon", placeholder: "-87.6298" }));
    row.append(inputField("Days / week", destination.days_per_week, { type: "number", min: 0, max: 7, step: .5, inputMode: "decimal", dataKey: "days", placeholder: "5" }));
    const remove = createElement("button", "icon-button", "×");
    remove.type = "button";
    remove.dataset.action = "remove-destination";
    remove.setAttribute("aria-label", `Remove ${destination.name || "destination"}`);
    row.append(remove);
    const lookup = createElement("div", "address-lookup");
    lookup.append(inputField("US address (optional)", destination.address || "", { dataKey: "address", placeholder: "Street, city, state, ZIP" }));
    const lookupButton = createElement("button", "button button-quiet", "Look up via US Census");
    lookupButton.type = "button";
    lookupButton.dataset.action = "geocode-destination";
    lookup.append(lookupButton);
    lookup.append(createElement("p", "address-note", "Sends this address to the US Census geocoder. You can enter coordinates directly instead."));
    const status = createElement("p", "address-status");
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    lookup.append(status);
    row.append(lookup);
    list.append(row);
  }

  function renderPeopleEmptyState() {
    const existing = els.peopleList.querySelector(".person-empty");
    if (els.peopleList.querySelector(".person-card")) {
      if (existing) existing.remove();
    } else if (!existing) {
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
    const routeDate = els.routeDateInput.value;
    const outboundTime = els.routeOutboundInput.value;
    const returnTime = els.routeReturnInput.value;
    const threads = requiredNumber(els.routeThreadsInput, "Routing threads", 1, 32);
    const maxMemoryGb = requiredNumber(els.routeMemoryInput, "Routing memory", 1, 128);
    if (routeDate) routing.date = routeDate;
    else delete routing.date;
    if (outboundTime) routing.outbound_time = outboundTime;
    else delete routing.outbound_time;
    if (returnTime) routing.return_time = returnTime;
    else delete routing.return_time;
    routing.threads = threads;
    routing.max_memory_gb = maxMemoryGb;
    const currency = els.currencyInput.value.trim().toUpperCase();
    if (currency && !/^[A-Z]{3}$/.test(currency)) throw new Error("Currency must be a three-letter code such as USD.");
    const originalPeople = Array.isArray(configSnapshot.people) ? configSnapshot.people : [];
    const people = [...els.peopleList.querySelectorAll(".person-card")].map((card, personIndex) => {
      const original = originalPeople.find((person) => isRecord(person) && String(person.id) === String(card.dataset.personId)) || {};
      const name = card.querySelector('[data-key="name"]').value.trim();
      if (!name) throw new Error(`Person ${personIndex + 1} needs a name.`);
      const capInput = card.querySelector('[data-key="maxMinutes"]');
      const maxMinutes = capInput.value.trim() === "" ? null : requiredNumber(capInput, `${name}'s commute cap`, 1, 1440);
      const modes = [...card.querySelectorAll("[data-mode]:checked")].map((input) => input.value);
      if (!modes.length) throw new Error(`${name} needs at least one allowed travel mode.`);
      const destinations = [...card.querySelectorAll(".destination-row")].map((row, index) => {
        const originals = Array.isArray(original.destinations) ? original.destinations : [];
        const originalDestination = originals.find((item) => isRecord(item) && String(item.id) === String(row.dataset.destinationId)) || {};
        const destinationName = row.querySelector('[data-key="name"]').value.trim();
        const label = destinationName || `destination ${index + 1}`;
        if (!destinationName) throw new Error(`${name}'s destination ${index + 1} needs a name.`);
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
      return { ...original, id: card.dataset.personId, name, destinations, modes, max_minutes: maxMinutes };
    });
    return { ...configSnapshot, city: els.cityInput.value.trim(), timezone: els.timezoneInput.value.trim(), currency: currency || "USD", people, routing };
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
      await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config) });
      await loadState();
      setFormStatus(els.configStatus, "Household saved. Commute results may need recomputing.", "success");
    } catch (error) {
      setFormStatus(els.configStatus, `Could not save: ${errorMessage(error)}`, "error");
    } finally {
      setButtonBusy(els.saveConfigButton, false, "Saving…", "Save household");
    }
  }

  async function computeRoutes() {
    setButtonBusy(els.routeButton, true, "Computing…", "Compute routes");
    setNotice("Computing routes. Local OSM and transit datasets can make this take a while.");
    try {
      await api("/api/routes", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      await loadState();
      setNotice("Routes computed. Check incomplete and over-cap results before deciding.");
    } catch (error) {
      setNotice(`Routes were not computed: ${errorMessage(error)}`, "error");
    } finally {
      setButtonBusy(els.routeButton, false, "Computing…", "Compute routes");
    }
  }

  async function geocodeDestination(button) {
    const row = button.closest(".destination-row");
    const addressInput = row.querySelector('[data-key="address"]');
    const status = row.querySelector(".address-status");
    const address = addressInput.value.trim();
    if (!address) {
      setFormStatus(status, "Enter a US address or coordinates.", "error");
      return;
    }
    setButtonBusy(button, true, "Looking up…", "Look up via US Census");
    try {
      const payload = await api("/api/geocode", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ address }) });
      const matches = isRecord(payload) && Array.isArray(payload.matches) ? payload.matches : [];
      if (matches.length !== 1) {
        setFormStatus(status, matches.length ? `${matches.length} matches found. Refine the address.` : "No match found. Refine the address or enter coordinates.", "error");
        return;
      }
      const match = matches[0];
      const lat = isRecord(match) ? finiteNumber(match.lat) : null;
      const lon = isRecord(match) ? finiteNumber(match.lon) : null;
      if (lat === null || lon === null || lat < -90 || lat > 90 || lon < -180 || lon > 180) throw new Error("The geocoder returned invalid coordinates.");
      row.querySelector('[data-key="lat"]').value = String(lat);
      row.querySelector('[data-key="lon"]').value = String(lon);
      setFormStatus(status, `Matched ${match.address || address}. Review, then save.`, "success");
    } catch (error) {
      setFormStatus(status, `Lookup failed: ${errorMessage(error)}`, "error");
    } finally {
      setButtonBusy(button, false, "Looking up…", "Look up via US Census");
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
    const assisted = isRecord(parsed) && isRecord(parsed.source) && typeof parsed.search_url === "string" && typeof parsed.status === "string";
    if (!listings.length && !assisted) throw new Error("The listings array is empty.");
    if (listings.some((listing) => !isRecord(listing))) throw new Error("Every listing must be a JSON object.");
    return { payload: assisted ? parsed : { listings }, assisted, count: listings.length };
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
    try {
      await api(listings.assisted ? "/api/assisted-import" : "/api/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(listings.payload) });
      els.importJson.value = "";
      els.jsonFileInput.value = "";
      await loadState();
      setFormStatus(els.importStatus, `Imported ${listings.count} listing${listings.count === 1 ? "" : "s"}.${listings.assisted ? " Browser progress saved." : ""}`, "success");
    } catch (error) {
      setFormStatus(els.importStatus, `Could not import: ${errorMessage(error)}`, "error");
    } finally {
      setButtonBusy(els.importButton, false, "Importing…", "Import listings");
    }
  }

  els.setupForm.addEventListener("submit", saveSetup);
  els.setupCity.addEventListener("input", updateSetupHint);
  els.collectButton.addEventListener("click", runCollection);
  els.collectionRunButton.addEventListener("click", runCollection);
  els.filterForm.addEventListener("input", renderListings);
  els.filterForm.addEventListener("change", renderListings);
  els.sortSelect.addEventListener("change", renderListings);
  els.clearFiltersButton.addEventListener("click", clearFilters);
  els.listingGrid.addEventListener("click", handleListingAction);
  els.listViewButton.addEventListener("click", () => switchView("list"));
  els.mapViewButton.addEventListener("click", () => switchView("map"));
  els.loadMapButton.addEventListener("click", activateMap);
  els.locateListingsButton.addEventListener("click", locateListings);
  els.configForm.addEventListener("submit", saveConfig);
  els.routeButton.addEventListener("click", computeRoutes);
  els.addPersonButton.addEventListener("click", () => {
    const empty = els.peopleList.querySelector(".person-empty");
    if (empty) empty.remove();
    appendPerson({ modes: ["walk", "bike", "transit"], max_minutes: 45, destinations: [] });
  });
  els.peopleList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const card = button.closest(".person-card");
    if (button.dataset.action === "remove-person") { card.remove(); renderPeopleEmptyState(); }
    if (button.dataset.action === "add-destination") appendDestination(card);
    if (button.dataset.action === "remove-destination") button.closest(".destination-row").remove();
    if (button.dataset.action === "geocode-destination") geocodeDestination(button);
  });
  els.jsonFileInput.addEventListener("change", async () => {
    const file = els.jsonFileInput.files && els.jsonFileInput.files[0];
    if (!file) return;
    try {
      els.importJson.value = await file.text();
      setFormStatus(els.importStatus, `Loaded ${file.name}. Review, then import.`);
    } catch (error) {
      setFormStatus(els.importStatus, `Could not read the file: ${errorMessage(error)}`, "error");
    }
  });
  els.importButton.addEventListener("click", importListings);

  loadState();
}());
