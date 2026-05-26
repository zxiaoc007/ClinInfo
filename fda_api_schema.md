# FDA API Schema

This document covers all three APIs used by the FDA (drugs) agent in ClinInfo:

1. [FDA Press Announcements RSS Feeds](#1-fda-press-announcements-rss-feeds)
2. [openFDA Drug Label API](#2-openfda-drug-label-api)
3. [openFDA Complete Response Letters (CRL) API](#3-openfda-complete-response-letters-crl-api)

---

## 1. FDA Press Announcements RSS Feeds

### Feed URLs

| Feed | URL | Content |
|---|---|---|
| Press Announcements | `https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml` | Drug approvals, safety alerts, policy news |
| What's New: Drugs | `https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drugs/rss.xml` | Guidance documents, generic approvals, warning letters |

### Request Method
`GET`

### Authentication
None required. A browser-like `User-Agent` header is required to bypass CDN blocking.

**Required Header:**
```
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36
```

### Response Format
`RSS 2.0 XML` with Dublin Core extension (`dc:` namespace)

### RSS Item Fields (per announcement)

| Field | XML Tag | Type | Description |
|---|---|---|---|
| Title | `<title>` | string | Headline of the announcement |
| Link | `<link>` | string | Full URL to the announcement page on fda.gov |
| Description | `<description>` | string | 1–2 sentence summary of the announcement |
| Publication Date | `<pubDate>` | string (RFC 2822) | Date/time published, e.g. `Fri, 22 May 2026 13:16:56 EDT` |
| Creator | `<dc:creator>` | string | Always `"FDA"` |
| GUID | `<guid>` | string | Unique identifier — same as `<link>` |

### Example RSS Item
```xml
<item>
  <title>FDA Approves First Treatment for Chronic Hepatitis Delta Virus (HDV) Infection</title>
  <link>http://www.fda.gov/news-events/press-announcements/fda-approves-first-treatment-chronic-hepatitis-delta-virus-hdv-infection</link>
  <description>Today, the U.S. Food and Drug Administration approved Hepcludex (bulevirtide-gmod) injection to treat chronic hepatitis delta virus (HDV) infection in adults without cirrhosis or with compensated cirrhosis.</description>
  <pubDate>Fri, 22 May 2026 13:16:56 EDT</pubDate>
  <dc:creator>FDA</dc:creator>
  <guid isPermaLink="true">http://www.fda.gov/news-events/press-announcements/fda-approves-first-treatment-chronic-hepatitis-delta-virus-hdv-infection</guid>
</item>
```

### App-Level Filtering (client-side)

Since RSS feeds have no native query parameters, filtering is applied after fetch:

| Filter | Applied On | Logic |
|---|---|---|
| `keywords` | `title` + `description` | AND — all words must appear |
| `start_date` | `pubDate` (parsed to datetime) | `pubDate >= start_date` |
| `end_date` | `pubDate` (parsed to datetime) | `pubDate <= end_date` |

### Notes
- Feeds are sorted newest-first
- No pagination — entire feed is fetched at once (~10–30 items typically)
- Date format in `pubDate` is RFC 2822; parse with `email.utils.parsedate_to_datetime`

---

## 2. openFDA Drug Label API

### Base URL
```
https://api.fda.gov/drug/label.json
```

### Request Method
`GET`

### Authentication
None required. An optional API key (`api_key` parameter) increases rate limits.

### Query Parameters (Inputs)

#### Search Parameter
- **Parameter**: `search`
- **Type**: `string`
- **Description**: openFDA query string using Lucene-style field:value syntax
- **Operators**: `AND`, `OR`, `+`, parentheses for grouping
- **Example**: `search=openfda.brand_name:"Advil"`

#### Supported Search Fields

| Field | Path | Description | Example |
|---|---|---|---|
| Brand name | `openfda.brand_name` | Commercial/brand name | `openfda.brand_name:"Advil"` |
| Generic name | `openfda.generic_name` | Generic drug name | `openfda.generic_name:"ibuprofen"` |
| Product type | `openfda.product_type` | Drug product type | `openfda.product_type:"HUMAN PRESCRIPTION DRUG"` |
| Route | `openfda.route` | Administration route | `openfda.route:"ORAL"` |
| Free text | (any field) | General search across all text fields | `"diabetes medication"` |

#### Product Type Values
- `HUMAN PRESCRIPTION DRUG`
- `HUMAN OTC DRUG`
- `VETERINARY DRUG`
- `PLASMA DERIVATIVE`
- `NON-STANDARDIZED ALLERGENIC`

#### Pagination Parameters

| Parameter | Type | Description | Default | Max |
|---|---|---|---|---|
| `limit` | integer | Results per page | 1 | 100 |
| `skip` | integer | Number of results to skip | 0 | 25000 |

#### API Key
- **Parameter**: `api_key`
- **Type**: `string`
- **Description**: Optional. Increases rate limit from 240/min to 240/min per key.

### Response Schema (Output)

#### Root Object
```json
{
  "meta": {
    "disclaimer": "string",
    "terms": "string",
    "license": "string",
    "last_updated": "string (YYYY-MM-DD)",
    "results": {
      "skip": 0,
      "limit": 10,
      "total": 42
    }
  },
  "results": [DrugLabelObject]
}
```

#### Drug Label Object Fields

| Field | Type | Description |
|---|---|---|
| `openfda.brand_name` | array of strings | Brand/trade names |
| `openfda.generic_name` | array of strings | Generic drug names |
| `openfda.product_type` | array of strings | Product type (e.g., "HUMAN PRESCRIPTION DRUG") |
| `openfda.route` | array of strings | Administration routes (e.g., "ORAL", "INTRAVENOUS") |
| `openfda.manufacturer_name` | array of strings | Manufacturer names |
| `openfda.application_number` | array of strings | NDA/BLA/ANDA numbers |
| `purpose` | array of strings | Drug purpose (OTC label field) |
| `indications_and_usage` | array of strings | Indications and usage |
| `warnings` | array of strings | Warnings section |
| `boxed_warning` | array of strings | Black box warning (most serious) |
| `dosage_and_administration` | array of strings | Dosage instructions |
| `active_ingredient` | array of strings | Active ingredient(s) |
| `adverse_reactions` | array of strings | Adverse reactions |
| `drug_interactions` | array of strings | Drug interaction information |
| `contraindications` | array of strings | Contraindications |
| `storage_and_handling` | array of strings | Storage instructions |

### Example API Calls

```
# Search by brand name
GET https://api.fda.gov/drug/label.json?search=openfda.brand_name:"Advil"&limit=5

# Search by generic name
GET https://api.fda.gov/drug/label.json?search=openfda.generic_name:"ibuprofen"&limit=10

# Search for prescription drugs only
GET https://api.fda.gov/drug/label.json?search=openfda.brand_name:"Humira"+AND+openfda.product_type:"HUMAN PRESCRIPTION DRUG"&limit=5

# General text search
GET https://api.fda.gov/drug/label.json?search="diabetes medication"&limit=10
```

### Notes
- All label fields are arrays of strings (even if only one value exists)
- `boxed_warning` is the most serious FDA safety warning (black box)
- Fields may be absent if not present on the drug label
- Rate limit: 240 requests/minute without API key

---

## 3. openFDA Complete Response Letters (CRL) API

### Base URL
```
https://api.fda.gov/transparency/crl.json
```

### Request Method
`GET`

### Authentication
None required.

### Dataset Overview
- **Total records**: ~439
- **Year range**: 2002–2026
- **Update frequency**: Infrequently
- **Approval status distribution**: Approved (~309), Unapproved (~130)

### Query Parameters (Inputs)

#### Search Parameter
- **Parameter**: `search`
- **Type**: `string`
- **Description**: openFDA query string (Lucene-style field:value syntax)
- **Multiple conditions**: Join with `+AND+`

#### Supported Search Fields

| Field | Type | Description | Example |
|---|---|---|---|
| `company_name` | string | Pharmaceutical company name | `company_name:"Pfizer"` |
| `application_number` | string | NDA or BLA number (no spaces) | `application_number:"NDA208647"` |
| `approval_status` | string | Outcome: "Approved" or "Unapproved" | `approval_status:"Approved"` |
| `letter_year` | string | Year the letter was issued | `letter_year:"2024"` |
| `letter_type` | string | Type of letter | `letter_type:"COMPLETE RESPONSE"` |
| `text` | string | Full text of the CRL letter body | `text:"manufacturing"` |

#### Approval Status Values
- `Approved` — Application was eventually approved after resolving CRL deficiencies
- `Unapproved` — Application was not approved

#### Sort Parameter
- **Parameter**: `sort`
- **Type**: `string`
- **Format**: `field:asc` or `field:desc`
- **Example**: `sort=letter_date:desc`

#### Pagination Parameters

| Parameter | Type | Description | Default | Max |
|---|---|---|---|---|
| `limit` | integer | Results per page | 1 | 100 |
| `skip` | integer | Number of results to skip | 0 | — |

#### Count Parameter
- **Parameter**: `count`
- **Type**: `string`
- **Description**: Count distinct values of a field (aggregation)
- **Example**: `count=letter_year` → returns counts per year

### Response Schema (Output)

#### Root Object
```json
{
  "meta": {
    "disclaimer": "string",
    "terms": "string",
    "license": "string",
    "last_updated": "string (YYYY-MM-DD)",
    "results": {
      "skip": 0,
      "limit": 10,
      "total": 439
    }
  },
  "results": [CRLObject]
}
```

#### CRL Object Fields

| Field | Type | Description | Example |
|---|---|---|---|
| `application_number` | array of strings | NDA or BLA number(s) | `["NDA 208647"]` |
| `company_name` | string | Pharmaceutical company name | `"Pfizer Inc."` |
| `company_rep` | string | Company representative name and title | `"Scott C. Anderson, MS"` |
| `company_address` | string | Company mailing address | `"235 East 42nd Street, New York, NY 10017"` |
| `letter_date` | string (MM/DD/YYYY) | Date the CRL was issued | `"04/20/2018"` |
| `letter_year` | string | Year extracted from letter_date | `"2018"` |
| `letter_type` | string | Type of letter | `"COMPLETE RESPONSE"` |
| `approval_status` | string | Final outcome | `"Approved"` or `"Unapproved"` |
| `approver_name` | string | FDA reviewer/approver full name | `"Laleh Amiri-Kordestani, MD"` |
| `approver_title` | string | FDA reviewer/approver title | `"Deputy Director"` |
| `approver_center` | array of strings | FDA division/office/center hierarchy | `["Division of Oncology 1", "Office of Oncologic Products", "Center for Drug Evaluation and Research"]` |
| `file_name` | string | Source PDF file name | `"208647_2018_Orig1s000OtherActionLtrs.pdf"` |
| `text` | string | Full extracted text of the CRL (OCR, may contain artifacts) | `"NDA 208647\nCOMPLETE RESPONSE\n..."` |

### Example API Calls

```
# All CRLs (default sort)
GET https://api.fda.gov/transparency/crl.json?limit=5

# CRLs from Pfizer
GET https://api.fda.gov/transparency/crl.json?search=company_name:"Pfizer"&limit=10

# Unapproved applications only
GET https://api.fda.gov/transparency/crl.json?search=approval_status:"Unapproved"&limit=10

# CRLs in 2024, sorted newest first
GET https://api.fda.gov/transparency/crl.json?search=letter_year:"2024"&sort=letter_date:desc&limit=10

# CRLs mentioning manufacturing deficiencies
GET https://api.fda.gov/transparency/crl.json?search=text:"manufacturing"&limit=10

# Specific NDA
GET https://api.fda.gov/transparency/crl.json?search=application_number:"NDA208647"

# Combined filters: Pfizer unapproved CRLs
GET https://api.fda.gov/transparency/crl.json?search=company_name:"Pfizer"+AND+approval_status:"Unapproved"&limit=10

# Count CRLs by year
GET https://api.fda.gov/transparency/crl.json?count=letter_year

# Count CRLs by approval status
GET https://api.fda.gov/transparency/crl.json?count=approval_status
```

### Year Distribution (as of 2026)
| Year | Count |
|---|---|
| 2024 | 69 |
| 2025 | 59 |
| 2021 | 48 |
| 2019 | 38 |
| 2020 | 35 |
| 2018 | 33 |
| 2023 | 29 |
| 2017 | 25 |
| 2022 | 25 |
| 2016 | 20 |
| 2026 | 14 |

### Notes
- `letter_date` is in `MM/DD/YYYY` format — use `letter_year` for year-based filtering via the API
- `text` field contains OCR-extracted content and may include formatting artifacts
- `application_number` is stored with a space (e.g., `"NDA 208647"`) — remove space when searching
- `approver_center` is an array ordered from most specific (division) to least specific (center)
- The API supports `count` for aggregation but not all fields support `.exact` suffix

---

## Error Responses

All openFDA APIs return standard HTTP status codes:

| Code | Meaning |
|---|---|
| `200 OK` | Successful request |
| `400 Bad Request` | Invalid query syntax or parameters |
| `404 Not Found` | No results match the query |
| `429 Too Many Requests` | Rate limit exceeded |
| `500 Internal Server Error` | Server error |

### 404 Error Body Example
```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "No matches found!"
  }
}
```

---

## References

| Resource | URL |
|---|---|
| openFDA API Homepage | https://open.fda.gov/apis/ |
| Drug Label API Docs | https://open.fda.gov/apis/drug/label/ |
| CRL API Docs | https://open.fda.gov/apis/transparency/completeresponseletters/ |
| CRL Searchable Fields | https://open.fda.gov/apis/transparency/completeresponseletters/searchable-fields/ |
| FDA Press Announcements | https://www.fda.gov/news-events/fda-newsroom/press-announcements |
| FDA RSS Feeds | https://www.fda.gov/about-fda/contact-fda/subscribe-podcasts-and-news-feeds |
| openFDA Rate Limits | https://open.fda.gov/apis/authentication/ |
