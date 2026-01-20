# ClinicalTrials.gov API v2 Schema

## Base URL
```
https://clinicaltrials.gov/api/v2/studies
```

## Request Method
`GET`

---

## Query Parameters (Inputs)

### Required Parameters
None - All parameters are optional, but at least one query filter is recommended.

### Query Filters

#### Condition Filter
- **Parameter**: `query.cond`
- **Type**: `string`
- **Description**: Search for studies by medical condition or disease
- **Example**: `query.cond=diabetes` or `query.cond=breast+cancer`

#### Overall Status Filter
- **Parameter**: `query.overallStatus`
- **Type**: `string` (enum)
- **Description**: Filter by trial status
- **Valid Values**:
  - `RECRUITING` - Actively recruiting participants
  - `NOT_YET_RECRUITING` - Not yet recruiting
  - `ACTIVE_NOT_RECRUITING` - Active but not recruiting
  - `COMPLETED` - Study has completed
  - `SUSPENDED` - Study is suspended
  - `TERMINATED` - Study has been terminated
  - `WITHDRAWN` - Study has been withdrawn
  - `ENROLLING_BY_INVITATION` - Enrolling by invitation only
  - `UNKNOWN` - Status unknown
- **Example**: `query.overallStatus=RECRUITING`

#### Phase Filter
- **Parameter**: `query.phase`
- **Type**: `string` (enum)
- **Description**: Filter by clinical trial phase
- **Valid Values**:
  - `PHASE1`
  - `PHASE2`
  - `PHASE3`
  - `PHASE4`
  - `NA` - Not applicable
- **Example**: `query.phase=PHASE3`

#### Study Type Filter
- **Parameter**: `query.studyType`
- **Type**: `string` (enum)
- **Description**: Filter by study type
- **Valid Values**:
  - `INTERVENTIONAL`
  - `OBSERVATIONAL`
  - `EXPANDED_ACCESS`
- **Example**: `query.studyType=INTERVENTIONAL`

#### Intervention Filter
- **Parameter**: `query.intr`
- **Type**: `string`
- **Description**: Search by intervention name or type
- **Example**: `query.intr=aspirin`

#### Location Filter
- **Parameter**: `query.locn`
- **Type**: `string`
- **Description**: Filter by location (city, state, country)
- **Example**: `query.locn=New+York`

#### Sponsor Filter
- **Parameter**: `query.spons`
- **Type**: `string`
- **Description**: Filter by sponsor name
- **Example**: `query.spons=National+Cancer+Institute`

#### Age Filter
- **Parameter**: `query.ages`
- **Type**: `string` (enum)
- **Description**: Filter by age group
- **Valid Values**:
  - `CHILD` - 0-17 years
  - `ADULT` - 18-64 years
  - `OLDER_ADULT` - 65+ years
- **Example**: `query.ages=ADULT`

#### Gender Filter
- **Parameter**: `query.gndr`
- **Type**: `string` (enum)
- **Description**: Filter by gender eligibility
- **Valid Values**:
  - `ALL` - All genders
  - `FEMALE` - Female only
  - `MALE` - Male only
- **Example**: `query.gndr=ALL`

#### Date Filters
- **Parameter**: `query.rcv_s` (Received Start Date)
- **Type**: `string` (ISO 8601 date format: YYYY-MM-DD)
- **Description**: Filter studies received on or after this date
- **Example**: `query.rcv_s=2024-01-01`

- **Parameter**: `query.rcv_e` (Received End Date)
- **Type**: `string` (ISO 8601 date format: YYYY-MM-DD)
- **Description**: Filter studies received on or before this date
- **Example**: `query.rcv_e=2024-12-31`

### Pagination Parameters

#### Page Size
- **Parameter**: `pageSize`
- **Type**: `integer`
- **Description**: Number of results per page
- **Default**: Varies
- **Maximum**: 100
- **Example**: `pageSize=20`

#### Page Token
- **Parameter**: `pageToken`
- **Type**: `string`
- **Description**: Token for pagination (returned in response)
- **Example**: `pageToken=ZVNj7o2Elu8o3lptUtuuqbL-mpOQJJxrZfOk0A`

### Response Format

#### Format
- **Parameter**: `format`
- **Type**: `string` (enum)
- **Description**: Response format
- **Valid Values**:
  - `json` - JSON format (recommended)
- **Default**: `json`
- **Example**: `format=json`

#### Fields (Optional)
- **Parameter**: `fields`
- **Type**: `string` (comma-separated)
- **Description**: Specify which fields to include in response
- **Example**: `fields=NCTId,Condition,BriefTitle,OverallStatus`

---

## Response Schema (Output)

### Root Object
```json
{
  "studies": [StudyObject],
  "nextPageToken": "string (optional)",
  "totalCount": integer
}
```

### Study Object Structure

```json
{
  "protocolSection": {
    "identificationModule": {
      "nctId": "string (e.g., NCT12345678)",
      "orgStudyIdInfo": {
        "id": "string"
      },
      "secondaryIdInfos": [SecondaryIdObject],
      "organization": {
        "fullName": "string",
        "class": "string"
      },
      "briefTitle": "string",
      "officialTitle": "string",
      "acronym": "string (optional)"
    },
    "statusModule": {
      "statusVerifiedDate": "string (YYYY-MM)",
      "overallStatus": "string (enum)",
      "expandedAccessInfo": {
        "hasExpandedAccess": boolean
      },
      "startDateStruct": {
        "date": "string (YYYY-MM-DD)",
        "type": "ACTUAL | ESTIMATED"
      },
      "primaryCompletionDateStruct": {
        "date": "string (YYYY-MM-DD)",
        "type": "ACTUAL | ESTIMATED"
      },
      "completionDateStruct": {
        "date": "string (YYYY-MM-DD)",
        "type": "ACTUAL | ESTIMATED"
      },
      "studyFirstSubmitDate": "string (YYYY-MM-DD)",
      "studyFirstPostDateStruct": {
        "date": "string (YYYY-MM-DD)",
        "type": "ACTUAL | ESTIMATED"
      },
      "lastUpdateSubmitDate": "string (YYYY-MM-DD)",
      "lastUpdatePostDateStruct": {
        "date": "string (YYYY-MM-DD)",
        "type": "ACTUAL | ESTIMATED"
      }
    },
    "sponsorCollaboratorsModule": {
      "responsibleParty": {
        "type": "string",
        "investigatorFullName": "string",
        "investigatorTitle": "string",
        "investigatorAffiliation": "string"
      },
      "leadSponsor": {
        "name": "string",
        "class": "string"
      },
      "collaborators": [CollaboratorObject]
    },
    "oversightModule": {
      "oversightHasDmc": boolean,
      "isFdaRegulatedDrug": boolean,
      "isFdaRegulatedDevice": boolean
    },
    "descriptionModule": {
      "briefSummary": "string",
      "detailedDescription": "string"
    },
    "conditionsModule": {
      "conditions": ["string"],
      "keywords": ["string"]
    },
    "designModule": {
      "studyType": "string (enum)",
      "phases": ["string (enum)"],
      "designInfo": {
        "allocation": "string",
        "interventionModel": "string",
        "primaryPurpose": "string",
        "maskingInfo": {
          "masking": "string"
        }
      },
      "enrollmentInfo": {
        "count": integer,
        "type": "ACTUAL | ESTIMATED"
      }
    },
    "armsInterventionsModule": {
      "armGroups": [ArmGroupObject],
      "interventions": [InterventionObject]
    },
    "outcomesModule": {
      "primaryOutcomes": [OutcomeObject],
      "secondaryOutcomes": [OutcomeObject],
      "otherOutcomes": [OutcomeObject]
    },
    "eligibilityModule": {
      "eligibilityCriteria": "string",
      "healthyVolunteers": boolean,
      "sex": "string (enum)",
      "minimumAge": "string",
      "maximumAge": "string (optional)",
      "stdAges": ["string (enum)"]
    },
    "contactsLocationsModule": {
      "centralContacts": [ContactObject],
      "overallOfficials": [OfficialObject],
      "locations": [LocationObject]
    },
    "referencesModule": {
      "references": [ReferenceObject],
      "seeAlsoLinks": [LinkObject]
    },
    "ipdSharingStatementModule": {
      "ipdSharing": "string (enum)",
      "description": "string (optional)"
    }
  },
  "derivedSection": {
    "miscInfoModule": {
      "versionHolder": "string (YYYY-MM-DD)"
    },
    "conditionBrowseModule": {
      "meshes": [MeshObject],
      "ancestors": [MeshObject]
    },
    "interventionBrowseModule": {
      "meshes": [MeshObject],
      "ancestors": [MeshObject]
    }
  },
  "hasResults": boolean
}
```

### Supporting Object Schemas

#### Location Object
```json
{
  "facility": "string",
  "status": "string (enum)",
  "city": "string",
  "state": "string (optional)",
  "zip": "string (optional)",
  "country": "string",
  "contacts": [ContactObject],
  "geoPoint": {
    "lat": number,
    "lon": number
  }
}
```

#### Contact Object
```json
{
  "name": "string",
  "role": "string (enum)",
  "phone": "string (optional)",
  "email": "string (optional)"
}
```

#### Intervention Object
```json
{
  "type": "string (enum: DRUG | DEVICE | BIOLOGICAL | PROCEDURE | BEHAVIORAL | GENETIC | DIETARY_SUPPLEMENT | COMBINATION_PRODUCT | DIAGNOSTIC_TEST | OTHER)",
  "name": "string",
  "description": "string (optional)",
  "armGroupLabels": ["string"]
}
```

#### Outcome Object
```json
{
  "measure": "string",
  "description": "string",
  "timeFrame": "string"
}
```

---

## Example API Calls

### Basic Search by Condition
```
GET https://clinicaltrials.gov/api/v2/studies?query.cond=diabetes&format=json&pageSize=10
```

### Search with Multiple Filters
```
GET https://clinicaltrials.gov/api/v2/studies?query.cond=breast+cancer&query.overallStatus=RECRUITING&query.phase=PHASE3&format=json&pageSize=20
```

### Search by Intervention
```
GET https://clinicaltrials.gov/api/v2/studies?query.intr=aspirin&format=json&pageSize=10
```

### Search with Date Range
```
GET https://clinicaltrials.gov/api/v2/studies?query.cond=cancer&query.rcv_s=2024-01-01&query.rcv_e=2024-12-31&format=json
```

### Pagination Example
```
# First page
GET https://clinicaltrials.gov/api/v2/studies?query.cond=diabetes&format=json&pageSize=20

# Next page (using token from previous response)
GET https://clinicaltrials.gov/api/v2/studies?query.cond=diabetes&format=json&pageSize=20&pageToken=ZVNj7o2Elu8o3lptUtuuqbL-mpOQJJxrZfOk0A
```

---

## Status Enum Values

### Overall Status
- `RECRUITING`
- `NOT_YET_RECRUITING`
- `ACTIVE_NOT_RECRUITING`
- `COMPLETED`
- `SUSPENDED`
- `TERMINATED`
- `WITHDRAWN`
- `ENROLLING_BY_INVITATION`
- `UNKNOWN`

### Study Type
- `INTERVENTIONAL`
- `OBSERVATIONAL`
- `EXPANDED_ACCESS`

### Phase
- `PHASE1`
- `PHASE2`
- `PHASE3`
- `PHASE4`
- `NA` (Not Applicable)

### Age Groups
- `CHILD` (0-17 years)
- `ADULT` (18-64 years)
- `OLDER_ADULT` (65+ years)

### Gender
- `ALL`
- `FEMALE`
- `MALE`

---

## Notes

1. **Date Format**: All dates use ISO 8601 format (YYYY-MM-DD)
2. **URL Encoding**: Use `+` or `%20` for spaces in query parameters
3. **Rate Limiting**: Be respectful of API rate limits
4. **Pagination**: Use `nextPageToken` from response for subsequent pages
5. **Maximum Page Size**: Limited to 100 results per page
6. **Combining Filters**: Multiple query parameters can be combined with `&`
7. **Case Sensitivity**: Status and enum values are case-sensitive (use uppercase)

---

## Error Responses

The API may return standard HTTP status codes:
- `200 OK` - Successful request
- `400 Bad Request` - Invalid parameters
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

---

## References

- Official API Documentation: https://clinicaltrials.gov/data-api/api
- API Migration Guide: https://www.nlm.nih.gov/pubs/techbull/ma24/ma24_clinicaltrials_api_beta.html

