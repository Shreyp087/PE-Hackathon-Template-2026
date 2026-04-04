# API Documentation

This document describes the REST API endpoints available in the URL Shortener service.

## Endpoints Summary
- `POST /shorten` - Create a new shortened URL
- `GET /:shortCode` - Redirect to the original URL
- `GET /metrics` - Retrieve application metrics
- `GET /health` - Application health check

---

### `POST /shorten`
Generates a new shortened URL for a provided long URL.

- **Method**: `POST`
- **Path**: `/shorten`
- **Content-Type**: `application/json`

#### Request Body Example
```json
{
  "url": "https://mlh.io/seasons/2026/events"
}
```

#### Response Example (201 Created)
```json
{
  "short_url": "http://localhost:5000/r/aB3dE",
  "short_code": "aB3dE",
  "original_url": "https://mlh.io/seasons/2026/events"
}
```

---

### `GET /r/:shortCode`
Redirects the client to the original long URL associated with the provided short code.

- **Method**: `GET`
- **Path**: `/r/<shortCode>`

#### Request Example
```bash
curl -i http://localhost:5000/r/aB3dE
```

#### Response Example (302 Found)
```http
HTTP/1.1 302 FOUND
Location: https://mlh.io/seasons/2026/events
Content-Type: text/html; charset=utf-8
```

#### Response Example (404 Not Found)
```json
{
  "error": "URL not found"
}
```

---

### `GET /metrics`
Exposes application and infrastructure metrics in Prometheus-compatible format. This endpoint is primarily used by the Prometheus scraper.

- **Method**: `GET`
- **Path**: `/metrics`

#### Request Example
```bash
curl http://localhost:5000/metrics
```

#### Response Example (200 OK)
```text
# HELP flask_http_request_total Total number of HTTP requests
# TYPE flask_http_request_total counter
flask_http_request_total{method="GET",status="200"} 1530
# HELP flask_http_request_duration_seconds HTTP request duration
# TYPE flask_http_request_duration_seconds histogram
flask_http_request_duration_seconds_bucket{le="0.1"} 1200
...
```

---

### `GET /health`
Returns the status of the application, ensuring it is ready to accept traffic and can properly connect to the database.

- **Method**: `GET`
- **Path**: `/health`

#### Request Example
```bash
curl http://localhost:5000/health
```

#### Response Example (200 OK)
```json
{
  "status": "ok",
  "database": "connected"
}
```
