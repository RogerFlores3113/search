# Vendored Client-Side Dependencies

These three scripts are vendored (not loaded from a CDN) so the app
works offline AND so the runtime cannot be compromised by an unpkg
breach or a DNS-level attack on the user's network. They ship inside
`agent/static/vendor/` and are served from `/static/vendor/` by the
FastAPI static mount in `agent/main.py`.

If `templates/index.html` ever references `https://unpkg.com/...` again
it should fail the regression assertion in
`tests/unit/test_no_cdn_scripts.py`.

## Pinned versions

| File                | Version  | License | Source                                                                  | SHA-256                                                            |
|---------------------|----------|---------|-------------------------------------------------------------------------|--------------------------------------------------------------------|
| `htmx.min.js`       | 2.0.10   | BSD-2   | <https://unpkg.com/htmx.org@2.0.10/dist/htmx.min.js>                    | `71ea67185bfa8c98c39d31717c6fce5d852370fcdfd129db4543774d3145c0de` |
| `htmx-ext-sse.js`   | 2.2.4    | BSD-2   | <https://unpkg.com/htmx-ext-sse@2.2.4/sse.js>                           | `3b5992a541619babefc4c169505af474df5c3039da51e59b96ccf9241ecd61d2` |
| `alpinejs.min.js`   | 3.15.12  | MIT     | <https://unpkg.com/alpinejs@3.15.12/dist/cdn.min.js>                    | `57b37d7cae9a27d965fdae4adcc844245dfdc407e655aee85dcfff3a08036a3f` |

## Refresh procedure

When you bump a version, re-fetch and update the table above:

```bash
cd agent/static/vendor
curl -fsSL https://unpkg.com/htmx.org@<VERSION>/dist/htmx.min.js     -o htmx.min.js
curl -fsSL https://unpkg.com/htmx-ext-sse@<VERSION>/sse.js           -o htmx-ext-sse.js
curl -fsSL https://unpkg.com/alpinejs@<VERSION>/dist/cdn.min.js      -o alpinejs.min.js
sha256sum *.js
```

Then update both this README and `agent/templates/index.html`. Commit
the vendored files alongside the template change so each version bump
is a single atomic, auditable diff.
