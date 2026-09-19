(options) => {
  "use strict";

  if (!options || typeof options !== "object") throw new Error("browser capture options are required");
  const sourceId = typeof options.source === "string" ? options.source.trim() : "";
  if (!sourceId) throw new Error("browser capture source is required");
  const recipe = typeof options.recipe === "string" ? options.recipe.trim().toLowerCase() : "";
  if (!recipe) throw new Error("browser capture recipe is required");

  const configuredLimit = Number(options.limit == null ? 200 : options.limit);
  if (!Number.isInteger(configuredLimit) || configuredLimit < 1 || configuredLimit > 1000) {
    throw new Error("browser capture limit must be an integer from 1 to 1000");
  }
  const criteria = options.criteria && typeof options.criteria === "object" && !Array.isArray(options.criteria)
    ? options.criteria
    : {};
  const observedAt = new Date().toISOString();
  const clean = (value) => String(value == null ? "" : value).replace(/\s+/g, " ").trim();
  const selector = (name, required = false) => {
    const value = clean(options[name]);
    if (required && !value) throw new Error(`generic browser capture requires options.${name}`);
    return value;
  };
  const text = (node, css) => {
    if (!node || !css) return "";
    const match = node.matches && node.matches(css) ? node : node.querySelector(css);
    return clean(match && match.textContent);
  };
  const texts = (node, css) => !node || !css
    ? []
    : Array.from(new Set(Array.from(node.querySelectorAll(css)).map((match) => clean(match.textContent)).filter(Boolean)));
  const canonicalUrl = (value) => {
    if (!value) return null;
    const parsed = new URL(value, location.href);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    parsed.hash = "";
    return parsed.href;
  };
  const exactNumber = (value, unitPattern) => {
    const normalized = clean(value);
    if (!normalized || /(?:\+|\bfrom\b|\bstarting\b|\bup to\b|\bto\b|\d\s*[-–—]\s*\d)/i.test(normalized)) return null;
    const match = normalized.match(new RegExp(`^\\s*(\\d+(?:\\.\\d+)?)\\s*(?:${unitPattern})?\\s*$`, "i"));
    return match ? Number(match[1]) : null;
  };
  const exactMoney = (value) => {
    const normalized = clean(value);
    if (!normalized || /(?:\+|\bfrom\b|\bstarting\b|\bup to\b|\bto\b|\d\s*[-–—]\s*\$?\s*\d)/i.test(normalized)) return null;
    const match = normalized.match(/^\s*\$?\s*(\d[\d,]*)(?:\.00)?\s*(?:(?:\/|per\s+)?mo(?:nth(?:ly)?)?)?\s*$/i);
    return match ? Number(match[1].replace(/,/g, "")) : null;
  };
  const exactBedsFromTitle = (value) => {
    const normalized = clean(value);
    if (/^studio\s*(?:[-–—]|\bto\b)\s*\d/i.test(normalized)) return null;
    if (/^studio\b/i.test(normalized)) return 0;
    if (/(?:\+|\bto\b|\d\s*[-–—]\s*\d)/i.test(normalized)) return null;
    const matches = Array.from(normalized.matchAll(/\b(\d+(?:\.\d+)?)\s*(?:bed(?:room)?s?|br)\b/gi));
    return matches.length === 1 ? Number(matches[0][1]) : null;
  };
  const exactBeds = (value) => /^\s*studio(?:\s+apartment)?\s*$/i.test(clean(value))
    ? 0
    : exactNumber(value, "beds?|bedrooms?|br|bd");
  const notes = (facts) => {
    const values = [];
    if (facts.priceText && facts.rent == null) values.push(`Advertised rent text: ${facts.priceText}; exact point rent not established`);
    if (facts.bedText && facts.bedrooms == null) values.push(`Advertised bedroom text: ${facts.bedText}; exact count not established`);
    if (facts.bathText && facts.bathrooms == null) values.push(`Advertised bathroom text: ${facts.bathText}; exact count not established`);
    if (facts.sqftText && facts.sqft == null) values.push(`Advertised square-foot text: ${facts.sqftText}; exact area not established`);
    if (facts.positionText && (facts.lat == null || facts.lon == null)) values.push(`Advertised position was not a valid coordinate pair: ${facts.positionText}`);
    if (facts.inventoryText) values.push(`Advertised inventory text: ${facts.inventoryText}`);
    return values.length ? values.join("; ") : null;
  };

  let config;
  if (recipe === "domu") {
    config = {
      cards: "#map-listings .domu-search-listing",
      link: ".listing-item-image[href], .listing-title a[href], a.listing-title[href]",
      title: ".listing-title",
      address: ".listing-address",
      next: "a[rel~='next'][href]",
      idAttribute: "data-nid",
      urlAttribute: "",
      unitAttribute: "",
      domu: true,
      compass: false,
      apartments: false,
      zillow: false,
      apartmentlist: false,
      rentcafe: false,
    };
  } else if (recipe === "compass") {
    config = {
      cards: "[data-testid='cx-react-listingCard']",
      link: "[data-testid='cx-react-listingCard-subtitlesAnchor'][href]",
      title: "[data-testid='cx-react-listingCard-subtitlesAnchor']",
      address: "[data-testid='cx-react-listingCard-subtitlesAnchor']",
      price: "p[data-testid='cx-react-listingCard-title']",
      next: "a[aria-label^='Page '][href]",
      idAttribute: "",
      urlAttribute: "",
      unitAttribute: "",
      domu: false,
      compass: true,
      apartments: false,
      zillow: false,
      apartmentlist: false,
      rentcafe: false,
    };
  } else if (recipe === "apartments") {
    config = {
      cards: "article[data-listingid]",
      link: "",
      title: ".property-title, .js-placardTitle",
      address: ".property-address",
      price: ".property-pricing, .price-range, .starting-price",
      beds: ".bedTextBox",
      next: "a.next[href]",
      idAttribute: "data-listingid",
      urlAttribute: "data-url",
      unitAttribute: "data-unitnumber",
      domu: false,
      compass: false,
      apartments: true,
      zillow: false,
      apartmentlist: false,
      rentcafe: false,
    };
  } else if (recipe === "zillow") {
    config = {
      cards: "article[data-testid='property-card']",
      link: "a[data-testid='property-card-address-link'][href], a[data-testid='property-card-title-link'][href]",
      title: "address",
      address: "address",
      price: "[data-testid='property-card-price']",
      next: "a[aria-label='Next page'][href]",
      idAttribute: "",
      urlAttribute: "",
      unitAttribute: "",
      domu: false,
      compass: false,
      apartments: false,
      zillow: true,
      apartmentlist: false,
      rentcafe: false,
    };
  } else if (recipe === "apartmentlist") {
    config = {
      cards: "article",
      link: "h3 a[href]",
      title: "h3 a[href]",
      address: "address",
      price: "",
      next: "a[aria-label='Go to next page'][href]",
      idAttribute: "",
      urlAttribute: "",
      unitAttribute: "",
      domu: false,
      compass: false,
      apartments: false,
      zillow: false,
      apartmentlist: true,
      rentcafe: false,
    };
  } else if (recipe === "rentcafe") {
    config = {
      cards: "article.listing-details[data-value]",
      link: "h2 a[href]",
      title: "h2 a[href]",
      address: "",
      price: ".listing-price",
      beds: ".listing-bed",
      next: "a[aria-label='Next page'][href]",
      idAttribute: "data-value",
      urlAttribute: "",
      unitAttribute: "",
      domu: false,
      compass: false,
      apartments: false,
      zillow: false,
      apartmentlist: false,
      rentcafe: true,
    };
  } else if (recipe === "generic") {
    config = {
      cards: selector("cards", true),
      link: selector("link", true),
      title: selector("title") || selector("link", true),
      address: selector("address"),
      price: selector("price"),
      beds: selector("beds"),
      baths: selector("baths"),
      sqft: selector("sqft"),
      unit: selector("unit"),
      next: selector("next"),
      idAttribute: selector("idAttribute"),
      urlAttribute: "",
      unitAttribute: "",
      domu: false,
      compass: false,
      apartments: false,
      zillow: false,
      apartmentlist: false,
      rentcafe: false,
    };
  } else {
    throw new Error(`unsupported browser capture recipe: ${recipe}`);
  }

  let cards;
  try {
    cards = Array.from(document.querySelectorAll(config.cards));
  } catch (error) {
    throw new Error(`invalid card selector for ${recipe}: ${error.message}`);
  }
  if (!cards.length) throw new Error(`browser capture found no cards for ${recipe}; rendered schema may have changed`);
  let observedCardCount = cards.length;
  let privateExcluded = 0;
  if (config.compass) {
    const beforePublicFilter = cards.length;
    cards = cards.filter((card) => !/compass\s+private\s+exclusive/i.test(clean(card.textContent)));
    privateExcluded = beforePublicFilter - cards.length;
    if (!cards.length) throw new Error("Compass capture found no public listing cards after excluding Private Exclusives");
  }
  if (config.apartmentlist) {
    cards = cards.filter((card) => card.querySelector(config.link));
    observedCardCount = cards.length;
    if (!cards.length) throw new Error("Apartment List capture found no property cards with public detail links");
  }

  const selected = cards.slice(0, configuredLimit);
  const extractedListings = selected.map((card, index) => {
    const linkNode = config.link ? (card.matches(config.link) ? card : card.querySelector(config.link)) : null;
    const rawListingUrl = config.urlAttribute ? card.getAttribute(config.urlAttribute) : linkNode && linkNode.getAttribute("href");
    const listingUrl = canonicalUrl(rawListingUrl);
    if (!listingUrl) throw new Error(`browser capture card ${index + 1} has no canonical HTTP(S) listing URL`);
    const attributeId = config.idAttribute ? clean(card.getAttribute(config.idAttribute)) : "";
    const providerId = attributeId || listingUrl;
    if (!providerId) throw new Error(`browser capture card ${index + 1} has no stable source identity`);

    let title = text(card, config.title);
    if (config.apartmentlist) title = title.replace(/\s*\(opens in new tab\)\s*$/i, "");
    const labelledAddress = config.rentcafe ? clean(card.getAttribute("aria-label")).split("|").slice(1).join("|").trim() : "";
    const address = labelledAddress || text(card, config.address);
    const compassFact = (label) => {
      if (!config.compass) return "";
      const term = Array.from(card.querySelectorAll("dl dt")).find((node) => clean(node.textContent).toLowerCase().includes(label));
      const valueNode = term && term.previousElementSibling && term.previousElementSibling.tagName === "DD"
        ? term.previousElementSibling
        : null;
      return text(valueNode, "span[aria-hidden='true']") || clean(valueNode && valueNode.textContent);
    };
    const apartmentListPriceNode = config.apartmentlist
      ? Array.from(card.querySelectorAll("span")).find((node) => !node.querySelector("span") && /^\$[\d,]+(?:\+)?\/mo$/i.test(clean(node.textContent)))
      : null;
    const apartmentListTotalPrice = Boolean(
      apartmentListPriceNode && /\btotal\s+price\b/i.test(clean(apartmentListPriceNode.parentElement && apartmentListPriceNode.parentElement.textContent))
    );
    const configuredPriceValues = config.apartments || config.rentcafe ? texts(card, config.price) : [];
    const leafPriceValues = config.apartments
      ? Array.from(card.querySelectorAll("span"))
        .filter((node) => !node.querySelector("span") && /^\$[\d,]+(?:\+)?(?:\/mo)?$/i.test(clean(node.textContent)))
        .map((node) => clean(node.textContent))
      : [];
    const priceValues = Array.from(new Set([...configuredPriceValues, ...leafPriceValues]));
    const bedValues = config.apartments || config.rentcafe ? texts(card, config.beds) : [];
    const priceText = config.domu
      ? clean(card.getAttribute("data-price"))
      : (config.apartments || config.rentcafe
        ? priceValues.join(" | ")
        : (config.apartmentlist ? clean(apartmentListPriceNode && apartmentListPriceNode.textContent) : text(card, config.price)));
    const bedText = config.domu
      ? title
      : (config.compass
        ? compassFact("bedroom")
        : (config.apartments || config.rentcafe ? bedValues.join(" | ") : text(card, config.beds)));
    const bathText = config.compass ? compassFact("bathroom") : (config.domu ? "" : text(card, config.baths));
    const sqftText = config.compass ? compassFact("square feet") : (config.domu ? "" : text(card, config.sqft));
    const inventoryText = config.zillow ? text(card, "[data-testid='PropertyCardInventorySet']") : "";
    const rent = config.apartments || config.rentcafe || apartmentListTotalPrice ? null : exactMoney(priceText);
    const bedrooms = config.domu
      ? exactBedsFromTitle(bedText)
      : (config.rentcafe || config.apartments && bedValues.length !== 1 ? null : exactBeds(bedText));
    const bathrooms = exactNumber(bathText, "baths?|bathrooms?|ba");
    const sqft = exactNumber(sqftText.replace(/,/g, ""), "sq(?:uare)?\\.?\\s*(?:feet|ft)\\.?|sq\\.?\\s*ft\\.?|sf");
    const positionText = config.domu ? clean(card.getAttribute("data-position")) : "";
    const coordinateParts = positionText.split(",").map((part) => Number(part.trim()));
    const validPosition = coordinateParts.length === 2 && Number.isFinite(coordinateParts[0])
      && Number.isFinite(coordinateParts[1]) && Math.abs(coordinateParts[0]) <= 90
      && Math.abs(coordinateParts[1]) <= 180;
    const amenityRoots = config.domu
      ? Array.from(card.querySelectorAll(".amenities_items"))
      : (config.rentcafe ? Array.from(card.querySelectorAll(".listing-amenities")) : []);
    const amenityNodes = amenityRoots.flatMap((root) => root.children.length ? Array.from(root.children) : [root]);
    const amenities = Array.from(new Set(amenityNodes.map((node) => clean(node.textContent)).filter(Boolean)));
    const factSet = {
      priceText, rent, bedText, bedrooms, bathText, bathrooms, sqftText, sqft,
      positionText, inventoryText, lat: validPosition ? coordinateParts[0] : null,
      lon: validPosition ? coordinateParts[1] : null,
    };
    const explicitCompassUnit = config.compass ? address.match(/,\s*Unit\s+([^,]+)(?:,|$)/i) : null;
    const unit = config.domu
      ? null
      : (config.compass
        ? clean(explicitCompassUnit && explicitCompassUnit[1]) || null
        : (config.unitAttribute ? clean(card.getAttribute(config.unitAttribute)) || null : text(card, config.unit) || null));
    return {
      source: sourceId,
      source_id: providerId,
      url: listingUrl,
      title: title || null,
      address: address || null,
      unit,
      grain: unit
        ? "unit"
        : (config.apartments || config.zillow || config.apartmentlist || config.rentcafe
          || config.domu && card.querySelector(".building-unit") ? "property" : "unknown"),
      rent,
      bedrooms,
      bathrooms,
      sqft,
      amenities,
      pets: config.domu && card.querySelector(".amenities_items .pet, .amenities_items.pet") ? true : null,
      parking: config.domu && card.querySelector(".amenities_items .parking, .amenities_items.parking") ? true : null,
      lat: factSet.lat,
      lon: factSet.lon,
      observed_at: observedAt,
      historical: false,
      synthetic: false,
      notes: notes(factSet),
    };
  });

  const listings = [];
  const listingByKey = new Map();
  const urlBySourceId = new Map();
  const coreFields = ["address", "unit", "grain", "rent", "bedrooms", "bathrooms", "sqft", "lat", "lon", "pets", "parking"];
  let duplicateCards = 0;
  for (const row of extractedListings) {
    const priorUrl = urlBySourceId.get(row.source_id);
    if (priorUrl && priorUrl !== row.url) {
      throw new Error(`browser capture found source_id ${row.source_id} on differing listing URLs; operator review required`);
    }
    urlBySourceId.set(row.source_id, row.url);
    const key = `${row.source_id}\n${row.url}`;
    const prior = listingByKey.get(key);
    if (!prior) {
      listingByKey.set(key, row);
      listings.push(row);
      continue;
    }
    duplicateCards += 1;
    for (const field of coreFields) {
      const before = prior[field];
      const after = row[field];
      if (before == null && after != null) prior[field] = after;
      else if (before != null && after != null && before !== after) {
        throw new Error(`duplicate card ${row.source_id} disagrees on ${field}; operator review required`);
      }
    }
    prior.amenities = Array.from(new Set([...(prior.amenities || []), ...(row.amenities || [])]));
    if (!prior.title && row.title) prior.title = row.title;
    else if (prior.title && row.title && prior.title !== row.title) {
      const titleNote = `Duplicate rendered card title: ${row.title}`;
      prior.notes = prior.notes ? `${prior.notes}; ${titleNote}` : titleNote;
    }
    if (row.notes && row.notes !== prior.notes && !String(prior.notes || "").includes(row.notes)) {
      prior.notes = prior.notes ? `${prior.notes}; ${row.notes}` : row.notes;
    }
  }

  const pageVerified = !config.zillow || options.page_verified === true;
  const fullPageCaptured = selected.length === cards.length && pageVerified;
  let nextNode = config.next ? document.querySelector(config.next) : null;
  if (config.compass) {
    const pathPage = location.pathname.match(/\/p-(\d+)\/?$/i);
    const currentPage = pathPage ? Number(pathPage[1]) : 1;
    nextNode = Array.from(document.querySelectorAll(config.next)).find((node) => {
      const match = clean(node.getAttribute("aria-label")).match(/^Page\s+(\d+)$/i);
      return match && Number(match[1]) === currentPage + 1;
    }) || null;
  }
  const nextButtonNeedsNavigation = Boolean(
    config.compass && document.querySelector("[aria-label='Next Page']:not([disabled])") && !nextNode
  );
  const observedNextUrl = canonicalUrl(nextNode && nextNode.getAttribute("href"));
  const originalSearchUrl = canonicalUrl(options.search_url || location.href);
  if (!originalSearchUrl) throw new Error("browser capture search_url must be an absolute HTTP(S) URL");
  const evidenceParts = [
    `Read-only rendered-DOM capture of ${listings.length} card(s)`,
    "operator verification is required before marking coverage complete",
  ];
  if (privateExcluded) evidenceParts.push(`${privateExcluded} Compass Private Exclusive card(s) excluded from public scope`);
  if (nextButtonNeedsNavigation) evidenceParts.push("an enabled next-page control requires operator navigation before another capture");
  if (config.zillow && !pageVerified) evidenceParts.push("Zillow cards are lazy-loaded and page_verified was not set, so the current page remains the resume point");
  if (config.zillow && pageVerified) evidenceParts.push("the operator marked the lazy-loaded Zillow page verified after scrolling");
  return {
    source: {id: sourceId},
    search_url: originalSearchUrl,
    observed_at: observedAt,
    status: "partial",
    pages_visited: [location.href],
    next_url: fullPageCaptured && observedNextUrl ? observedNextUrl : location.href,
    evidence_note: `${evidenceParts.join("; ")}.`,
    criteria,
    listings,
    counts: {
      cards_observed: observedCardCount,
      listings_captured: listings.length,
      duplicate_cards: duplicateCards,
      cards_excluded_private: privateExcluded,
      limit: configuredLimit,
      full_page_captured: fullPageCaptured,
    },
  };
}
