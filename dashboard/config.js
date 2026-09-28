// Base URL of the API. Empty string means same-origin, which is correct
// when the dashboard is served by the API itself (api/app.py mounts this
// directory - the default deployment). Override by editing this file, or
// by setting `window.SEEKLY_API_BASE` before this script loads, only if
// you're hosting the dashboard separately from the API (see
// dashboard/README.md).
window.SEEKLY_API_BASE = window.SEEKLY_API_BASE || "";
