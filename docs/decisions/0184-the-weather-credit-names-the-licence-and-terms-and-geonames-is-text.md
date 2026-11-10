# 0184. The weather credit links the licence and terms; GeoNames is credited as text

Status: accepted

Context: Task W1-web keeps the Open-Meteo CC-BY attribution in the footer and adds a link to their terms. The pinned anchor (`tests/test_web_pages.py:68`) must stay. `tests/test_web_pages.py::test_pages_load_nothing_from_outside` allows only `open-meteo.com` as an external host on `/settings` and the agenda pages.
Decision:
- The Today weather strip footer keeps `<a href="https://open-meteo.com/">Weather data by Open-Meteo.com</a>` unchanged and adds `(CC BY 4.0)` linking `https://open-meteo.com/en/licence` and `Open-Meteo terms` linking `https://open-meteo.com/en/terms`.
- The weather card on `/settings` (the only place the city search shows place names) gets a `<footer class="attribution">` with the same three links, plus the text "Place names from the GeoNames database (CC BY 4.0), through Open-Meteo." GeoNames is not linked, because linking it would add a second external host that the existing test refuses.
- Wording checked against the live pages: the terms page says "The data obtained through the API is provided under the terms of the CC-BY 4.0 licence"; the licence page requires "a link next to any location Open-Meteo data are displayed" with the example "Weather data by Open-Meteo.com", and lists "Location database from GeoNames" as CC BY. Neither page gives separate terms for the geocoding API.
Alternative: Link GeoNames (needs the existing test's host list widened, an edit not approved); put one site-wide footer in `base.html` (the credit would then show on pages with no weather data, and the pinned test looks for it inside the weather section).
Reason: The licence asks for the credit next to the data, so it sits in the two places the data and place names appear.
Where: `web/templates/today.html`, `web/templates/_card.html` (shown when `card.city_search`); tests `tests/test_web_city_search.py` (the last two tests).
Revisit when: Open-Meteo changes its licence text, or the host test is widened to allow geonames.org.
Sources (checked 2026-11-09): https://open-meteo.com/en/terms ("The data obtained through the API is provided under the terms of the CC-BY 4.0 licence"); https://open-meteo.com/en/licence ("Attribution 4.0 International (CC BY 4.0)"; "You must include a link next to any location Open-Meteo data are displayed"; GeoNames listed under Data Sources).
