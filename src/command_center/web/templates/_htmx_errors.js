// htmx swaps no 4xx or 5xx reply, so a refused edit (409), a deleted item (404) or a failed CSRF
// check (403) would do nothing. This shows the server's own text in the nearest flash area instead.
(function () {
  "use strict";

  function messageOf(xhr) {
    try {
      var body = JSON.parse(xhr.responseText);
      if (body && typeof body.detail === "string" && body.detail) {
        return body.detail;
      }
    } catch (ignored) {
      // not JSON: fall through to the fixed text
    }
    return "The server refused the request (" + xhr.status + ").";
  }

  document.addEventListener("htmx:responseError", function (event) {
    var detail = event.detail || {};
    var source = detail.elt || event.target;
    var scope = source && source.closest ? source.closest("li, .card, .panel") : null;
    var flash = scope ? scope.querySelector(".flash") : null;
    if (!flash || !detail.xhr) {
      return;
    }
    flash.textContent = messageOf(detail.xhr);
    flash.classList.add("bad");
    var panel = flash.closest("details");
    if (panel) {
      panel.open = true;
    }
  });
})();
