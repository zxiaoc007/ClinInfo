import os, getpass
import re
import uuid
import requests
import json
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Optional
from datetime import datetime, timedelta
from urllib.parse import urlencode
from dotenv import load_dotenv

from langgraph.graph import MessagesState, END
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langgraph.graph import START, StateGraph
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

def _load_prompt(filename: str, **kwargs) -> str:
    with open(os.path.join(_PROMPTS_DIR, filename)) as f:
        text = f.read()
    return text.format_map(kwargs) if kwargs else text

# ClinicalTrials.gov API base URL
CLINICAL_TRIALS_API_BASE = "https://clinicaltrials.gov/api/v2/studies"

# In-memory cache: cache_key → list of pre-formatted study strings
# Allows paginated browsing without re-calling the API
_search_cache: dict = {}

def _format_study(study: dict, index: int) -> str:
    """Format a single study dict into a readable string block."""
    try:
        protocol    = study.get("protocolSection", {})
        id_mod      = protocol.get("identificationModule", {})
        st_mod      = protocol.get("statusModule", {})
        design_mod  = protocol.get("designModule", {})
        sp_mod      = protocol.get("sponsorCollaboratorsModule", {})
        desc_mod    = protocol.get("descriptionModule", {})
        cond_mod    = protocol.get("conditionsModule", {})
        aim_mod     = protocol.get("armsInterventionsModule", {})
        cl_mod      = protocol.get("contactsLocationsModule", {})

        title          = id_mod.get("briefTitle", "N/A")
        nct_id         = id_mod.get("nctId", "N/A")
        other_ids      = [x.get("id", "") for x in id_mod.get("secondaryIdInfos", [])]
        overall_status = st_mod.get("overallStatus", "N/A")
        start_dt       = st_mod.get("startDateStruct", {}).get("date", "N/A")
        primary_comp   = st_mod.get("primaryCompletionDateStruct", {}).get("date", "N/A")
        study_comp     = st_mod.get("completionDateStruct", {}).get("date", "N/A")
        study_phases   = design_mod.get("phases", [])
        study_type_val = design_mod.get("studyType", "N/A")
        enrollment     = design_mod.get("enrollmentInfo", {}).get("count", "N/A")
        conditions     = cond_mod.get("conditions", [])
        lead_sponsor   = sp_mod.get("leadSponsor", {}).get("name", "N/A")
        collaborators  = [c.get("name", "") for c in sp_mod.get("collaborators", [])]
        brief_summary  = desc_mod.get("briefSummary", "")
        interventions  = [
            f"{intr.get('type', '')}: {intr.get('name', '')}"
            for intr in aim_mod.get("interventions", [])
        ]

        # Deduplicated locations
        location_lines, seen_locs = [], set()
        for loc in cl_mod.get("locations", []):
            facility_name = loc.get("facility", "")
            parts = ", ".join(filter(None, [loc.get("city", ""), loc.get("state", ""), loc.get("country", "")]))
            loc_str = f"{facility_name} — {parts}" if facility_name else parts
            if loc_str and loc_str not in seen_locs:
                seen_locs.add(loc_str)
                location_lines.append(loc_str)

        lines = [f"{index}. {title}"]
        lines.append(f"   NCT ID: {nct_id}")
        if nct_id and nct_id != "N/A":
            lines.append(f"   Link: https://clinicaltrials.gov/study/{nct_id}")
        if other_ids:
            lines.append(f"   Other Study IDs: {', '.join(other_ids[:5])}")
        if conditions:
            lines.append(f"   Conditions: {', '.join(conditions)}")
        lines.append(f"   Status: {overall_status}")
        if study_phases:
            lines.append(f"   Phase: {', '.join(study_phases)}")
        if study_type_val != "N/A":
            lines.append(f"   Study Type: {study_type_val}")
        lines.append(f"   Start Date: {start_dt}")
        lines.append(f"   Primary Completion: {primary_comp}")
        lines.append(f"   Study Completion: {study_comp}")
        if enrollment != "N/A":
            lines.append(f"   Enrollment: {enrollment} participants")
        if lead_sponsor and lead_sponsor != "N/A":
            lines.append(f"   Lead Sponsor: {lead_sponsor}")
        if collaborators:
            lines.append(f"   Collaborators: {', '.join(collaborators[:3])}")
        if location_lines:
            shown = location_lines[:5]
            loc_display = "; ".join(shown)
            if len(location_lines) > 5:
                loc_display += f" (+ {len(location_lines) - 5} more sites)"
            lines.append(f"   Locations: {loc_display}")
        if interventions:
            lines.append(f"   Interventions: {'; '.join(interventions[:5])}")
        if brief_summary:
            summary_text = brief_summary[:300] + "..." if len(brief_summary) > 300 else brief_summary
            lines.append(f"   Brief Summary: {summary_text}")
        return "\n".join(lines)
    except Exception as e:
        return f"{index}. [Error formatting study: {str(e)}]"


@tool
def search_clinical_trials(
    condition: str,
    sponsor: Optional[str] = None,
    status: Optional[str] = None,
    phase: Optional[str] = None,
    study_type: Optional[str] = None,
    intervention: Optional[str] = None,
    location: Optional[str] = None,
    facility: Optional[str] = None,
    age_group: Optional[str] = None,
    sex: Optional[str] = None,
    funder_type: Optional[str] = None,
    study_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_results: int = 5
) -> str:
    """
    Search for clinical trials on ClinicalTrials.gov API v2.

    API Schema Reference:
    - Base URL: https://clinicaltrials.gov/api/v2/studies
    - All parameters are optional, but condition is typically required for meaningful results

    Args:
        condition: The medical condition or disease to search for (e.g., "diabetes", "breast cancer")
        sponsor: Optional sponsor/pharmaceutical company name filter (e.g., "Roche", "Pfizer", "Novartis").
                 Searches across both lead sponsors and collaborators (server-side via query.spons).
        status: Optional trial status filter. Valid values: RECRUITING, NOT_YET_RECRUITING,
                ACTIVE_NOT_RECRUITING, COMPLETED, SUSPENDED, TERMINATED, WITHDRAWN,
                ENROLLING_BY_INVITATION, UNKNOWN
        phase: Optional phase filter. Valid values: EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4, NA
        study_type: Optional study type filter. Valid values: INTERVENTIONAL, OBSERVATIONAL, EXPANDED_ACCESS
        intervention: Optional intervention/treatment filter — drugs, medical devices, procedures,
                      vaccines, or other products (e.g., "Trastuzumab", "Surgery", "chemotherapy").
                      Server-side filtered via query.intr.
        location: Optional location filter — address, city, state, zip code, or country
                  (e.g., "New York", "United States", "94103"). Server-side via query.locn.
        facility: Optional facility/institution name filter (e.g., "Mayo Clinic", "Johns Hopkins").
                  Client-side filtered against the facility name in study locations.
        age_group: Optional age group filter. Valid values: CHILD (0-17), ADULT (18-64), OLDER_ADULT (65+)
        sex: Optional sex filter. Valid values: ALL, FEMALE, MALE
        funder_type: Optional funder type filter. Valid values: NIH, FED (other U.S. federal agency),
                     INDUSTRY, OTHER (individuals, universities, organizations). Server-side via filter.funder.
        study_id: Optional other study ID number assigned by sponsor or funders (e.g., "WO40324").
                  Server-side filtered via query.id.
        start_date: Optional start date filter in ISO format YYYY-MM-DD (e.g., "2024-01-01")
        end_date: Optional end date filter in ISO format YYYY-MM-DD (e.g., "2024-12-31")
        max_results: Maximum number of results to return to the user (default: 5, max: 100)

    Returns:
        A formatted string with clinical trial information including NCT ID, title, status, phase,
        study type, conditions, dates, enrollment, sponsor, interventions, and brief summary.

    Examples:
        - Recruiting phase 3 breast cancer trials: condition="breast cancer", status="RECRUITING", phase="PHASE3"
        - Roche breast cancer trials: condition="breast cancer", sponsor="Roche", phase="PHASE3"
        - Pfizer diabetes trials: condition="diabetes", sponsor="Pfizer"
        - Diabetes trials in New York: condition="diabetes", location="New York"
        - Recent cancer trials: condition="cancer", start_date="2024-01-01"
        - NIH-funded lung cancer trials: condition="lung cancer", funder_type="NIH"
        - Trial by sponsor study ID: condition="breast cancer", study_id="WO40324"
        - Trials at Mayo Clinic: condition="cancer", facility="Mayo Clinic"
        - Early phase Alzheimer trials: condition="Alzheimer", phase="EARLY_PHASE1"
    """
    try:
        # Always fetch the API maximum (100) so client-side filters have a large enough
        # pool to work with, regardless of max_results. max_results only limits final output.
        query_params = {
            "query.cond": condition,
            "pageSize": 100,
            "format": "json"
        }

        # --- Native server-side API filters ---
        if sponsor:
            query_params["query.spons"] = sponsor          # lead sponsors + collaborators
        if status:
            query_params["filter.overallStatus"] = status.upper()
        if phase:
            query_params["filter.phase"] = phase.upper()
        if location:
            query_params["query.locn"] = location          # address, city, state, zip, country
        if intervention:
            query_params["query.intr"] = intervention      # drugs, devices, procedures, vaccines
        if funder_type:
            query_params["filter.funder"] = funder_type.upper()  # NIH, FED, INDUSTRY, OTHER
        if study_id:
            query_params["query.id"] = study_id            # sponsor/funder study ID numbers

        # Make API request
        full_url = f"{CLINICAL_TRIALS_API_BASE}?{urlencode(query_params)}"
        print(f"[DEBUG API] Raw API Request URL:")
        print(f"[DEBUG API] {full_url}")
        print(f"[DEBUG API] Query parameters: {query_params}")

        response = requests.get(CLINICAL_TRIALS_API_BASE, params=query_params, timeout=10)
        response.raise_for_status()

        data = response.json()
        print(f"[DEBUG API] Response keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")

        all_studies = data.get("studies", [])
        if not all_studies:
            return f"No clinical trials found for condition: {condition}"

        # --- Client-side filters (no native API support) ---
        filtered_studies = []
        for study in all_studies:
            protocol = study.get("protocolSection", {})
            status_module = protocol.get("statusModule", {})
            design_module = protocol.get("designModule", {})
            eligibility_module = protocol.get("eligibilityModule", {})
            contacts_locations = protocol.get("contactsLocationsModule", {})

            # Filter by study type
            if study_type:
                if design_module.get("studyType", "").upper() != study_type.upper():
                    continue

            # Filter by age group
            if age_group:
                std_ages = eligibility_module.get("stdAges", [])
                if not any(a.upper() == age_group.upper() for a in std_ages):
                    continue

            # Filter by sex
            if sex:
                study_sex = eligibility_module.get("sex", "").upper()
                if study_sex != sex.upper() and study_sex != "ALL":
                    continue

            # Filter by facility name (client-side)
            if facility:
                locations = contacts_locations.get("locations", [])
                facility_lower = facility.lower()
                if not any(facility_lower in loc.get("facility", "").lower() for loc in locations):
                    continue

            # Filter by date range (prefers lastUpdatePostDate → studyFirstPostDate → startDate)
            if start_date or end_date:
                last_update = status_module.get("lastUpdatePostDateStruct", {})
                first_post = status_module.get("studyFirstPostDateStruct", {})
                start_date_struct = status_module.get("startDateStruct", {})

                date_to_check = (
                    last_update.get("date")
                    or first_post.get("date")
                    or start_date_struct.get("date")
                )
                if date_to_check:
                    if start_date and date_to_check < start_date:
                        continue
                    if end_date and date_to_check > end_date:
                        continue

            filtered_studies.append(study)  # collect ALL — max_results only limits display

        if not filtered_studies:
            filter_desc = [f"status={status}"] if status else []
            if phase:
                filter_desc.append(f"phase={phase}")
            if study_type:
                filter_desc.append(f"study_type={study_type}")
            if facility:
                filter_desc.append(f"facility={facility}")
            filter_str = " with " + ", ".join(filter_desc) if filter_desc else ""
            return f"No clinical trials found for condition '{condition}'{filter_str}. Try removing some filters or broadening your search."

        # --- Format ALL filtered studies and store in cache ---
        total_found = len(filtered_studies)
        total_api   = data.get("totalCount", len(all_studies))

        all_formatted = [_format_study(s, i + 1) for i, s in enumerate(filtered_studies)]

        # Store in session cache so the user can page through without re-querying the API
        cache_key = uuid.uuid4().hex[:10]
        _search_cache[cache_key] = all_formatted
        print(f"[DEBUG] Cached {total_found} studies under key '{cache_key}'")

        # Build response: header + first page (max_results) + footer
        page = all_formatted[:max_results]
        end_idx = len(page)
        has_api_more = total_api > 100

        header_parts = [f"Total found: {total_found} matching trials"]
        if has_api_more:
            header_parts.append(f"(API returned top 100 of {total_api} total; refine filters to see others)")
        header = " ".join(header_parts)

        output = [
            header,
            f"Showing results 1–{end_idx} of {total_found}.",
            f"[cache_key: {cache_key}]",
            "",
            *page,
        ]
        if total_found > max_results:
            output.append(f"\n[{total_found - end_idx} more results available — call get_more_trials(cache_key='{cache_key}', offset={end_idx}) to continue.]")

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        error_msg = f"Error fetching clinical trials data: {str(e)}"
        print(f"[DEBUG API] Request error: {error_msg}")
        return error_msg
    except KeyError as e:
        error_msg = f"Error processing API response - missing key: {str(e)}"
        print(f"[DEBUG API] KeyError: {error_msg}")
        return error_msg
    except Exception as e:
        error_msg = f"Error processing clinical trials data: {type(e).__name__}: {str(e)}"
        print(f"[DEBUG API] General error: {error_msg}")
        import traceback
        print(f"[DEBUG API] Traceback: {traceback.format_exc()}")
        return error_msg

@tool
def get_more_trials(cache_key: str, offset: int, count: int = 5) -> str:
    """
    Retrieve the next page of results from a previous search_clinical_trials call.

    Use this tool whenever the user asks to:
    - "show more", "next", "show me the next batch", "see more results"
    - view a specific range of results (e.g., "show me trials 6 to 10")
    - navigate backwards ("previous 5", "go back")

    Args:
        cache_key: The cache key returned by search_clinical_trials (shown as [cache_key: ...]).
        offset: The index of the first result to show (0-based).
                For the next page after seeing results 1–5, use offset=5.
                For results 11–15, use offset=10.
        count: Number of results to show (default: 5).

    Returns:
        A formatted string with the requested batch of clinical trial results.

    Examples:
        - First 5 already shown, user wants next 5: get_more_trials(cache_key="abc123", offset=5)
        - User wants results 11–15: get_more_trials(cache_key="abc123", offset=10)
        - User wants previous 5 (back from offset 10): get_more_trials(cache_key="abc123", offset=5)
    """
    if cache_key not in _search_cache:
        return (
            "The search results for this session have expired or the cache key is incorrect. "
            "Please run a new search to find trials."
        )

    all_studies = _search_cache[cache_key]
    total = len(all_studies)

    if offset >= total:
        return f"No more results. You have already seen all {total} trials from this search."

    batch = all_studies[offset: offset + count]
    end_idx = offset + len(batch)

    lines = [
        f"Showing results {offset + 1}–{end_idx} of {total} total:",
        "",
        *batch,
    ]
    if end_idx < total:
        lines.append(
            f"\n[{total - end_idx} more results available — "
            f"call get_more_trials(cache_key='{cache_key}', offset={end_idx}) for the next batch.]"
        )
    else:
        lines.append(f"\n[You have now seen all {total} results from this search.]")

    return "\n".join(lines)


# FDA RSS feed URLs
FDA_RSS_FEEDS = {
    "press": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
    "drugs": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drugs/rss.xml",
}


@tool
def get_fda_press_announcements(
    keywords: Optional[str] = None,
    feed: str = "press",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_results: int = 5
) -> str:
    """
    Fetch FDA press announcements from the official FDA RSS feeds.

    Use this tool whenever the user asks about:
    - Recent FDA news, announcements, or press releases
    - FDA drug approvals or new approvals
    - FDA safety alerts, warnings, or recalls
    - FDA policy decisions or guidance documents
    - What the FDA has announced about a specific drug, disease, or topic

    Args:
        keywords: Optional keyword(s) to filter announcements by topic.
                  All words must appear in the title or description (AND logic).
                  Examples: "diabetes", "cancer approval", "safety warning", "Ozempic"
        feed: Which RSS feed to pull from:
              - "press" (default): FDA Press Announcements — drug approvals, safety alerts, policy news
              - "drugs": What's New: Drugs — guidance documents, generic approvals, warning letters, new drug pages
              - "all": Combine both feeds
        start_date: Only show announcements published on or after this date (YYYY-MM-DD)
        end_date: Only show announcements published on or before this date (YYYY-MM-DD)
        max_results: Number of results to display at once (default: 5)

    Returns:
        Formatted list of FDA announcements with title, publication date, summary, and link.

    Examples:
        - Latest FDA press releases: get_fda_press_announcements()
        - Drug approval news: get_fda_press_announcements(keywords="approval")
        - Cancer-related news: get_fda_press_announcements(keywords="cancer")
        - What's new in drugs: get_fda_press_announcements(feed="drugs")
        - Announcements since Jan 2026: get_fda_press_announcements(start_date="2026-01-01")
        - All news about Ozempic: get_fda_press_announcements(keywords="semaglutide", feed="all")
    """
    try:
        # Determine feed URLs
        if feed == "all":
            feed_urls = list(FDA_RSS_FEEDS.values())
            feed_label = "FDA Press Announcements + What's New: Drugs"
        else:
            feed_key = feed if feed in FDA_RSS_FEEDS else "press"
            feed_urls = [FDA_RSS_FEEDS[feed_key]]
            feed_label = {"press": "FDA Press Announcements", "drugs": "What's New: Drugs"}[feed_key]

        # Parse date filters
        start_dt = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
        end_dt   = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59) if end_date else None

        # Parse keyword list (all must match — AND logic)
        keyword_list = [kw.lower().strip() for kw in keywords.split()] if keywords else []

        # Fetch and parse all feeds
        # FDA CDN requires a browser-like User-Agent, otherwise returns 404
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        all_items = []
        for url in feed_urls:
            print(f"[DEBUG FDA RSS] Fetching: {url}")
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)

            for item in root.findall(".//item"):
                title       = (item.findtext("title") or "").strip()
                link        = (item.findtext("link") or "").strip()
                description = (item.findtext("description") or "").strip()
                pub_date_str = (item.findtext("pubDate") or "").strip()

                pub_dt = None
                if pub_date_str:
                    try:
                        pub_dt = parsedate_to_datetime(pub_date_str).replace(tzinfo=None)
                    except Exception:
                        pass

                all_items.append({
                    "title": title,
                    "link": link,
                    "description": description,
                    "pub_date_str": pub_date_str,
                    "pub_dt": pub_dt,
                })

        # Sort newest first
        all_items.sort(key=lambda x: x["pub_dt"] or datetime.min, reverse=True)

        # Apply filters
        filtered = []
        for item in all_items:
            if start_dt and item["pub_dt"] and item["pub_dt"] < start_dt:
                continue
            if end_dt and item["pub_dt"] and item["pub_dt"] > end_dt:
                continue
            if keyword_list:
                text = (item["title"] + " " + item["description"]).lower()
                if not all(kw in text for kw in keyword_list):
                    continue
            filtered.append(item)

        if not filtered:
            kw_msg = f" matching '{keywords}'" if keywords else ""
            return f"No FDA announcements found{kw_msg}. Try broader keywords or a different date range."

        # Format each item as a string block
        def _fmt(item: dict, idx: int) -> str:
            date_str = item["pub_dt"].strftime("%B %d, %Y") if item["pub_dt"] else "N/A"
            desc = item["description"]
            if desc.lower().strip() == item["title"].lower().strip():
                desc = ""  # skip duplicate
            if len(desc) > 350:
                desc = desc[:350] + "..."
            lines = [
                f"{idx}. {item['title']}",
                f"   Date: {date_str}",
                f"   Link: {item['link']}",
            ]
            if desc:
                lines.append(f"   Summary: {desc}")
            return "\n".join(lines)

        all_formatted = [_fmt(item, i + 1) for i, item in enumerate(filtered)]

        # Cache for pagination
        cache_key = uuid.uuid4().hex[:10]
        _search_cache[cache_key] = all_formatted
        print(f"[DEBUG FDA RSS] Cached {len(all_formatted)} items under key '{cache_key}'")

        total   = len(all_formatted)
        page    = all_formatted[:max_results]
        end_idx = len(page)

        output = [
            f"Source: {feed_label}",
            f"Total found: {total} announcement(s)" + (f" matching '{keywords}'" if keywords else ""),
            f"Showing {end_idx} of {total}.",
            f"[cache_key: {cache_key}]",
            "",
            *page,
        ]
        if total > max_results:
            output.append(
                f"\n[{total - end_idx} more available — "
                f"call get_more_announcements(cache_key='{cache_key}', offset={end_idx}) to continue.]"
            )

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"Error fetching FDA announcements: {str(e)}"
    except ET.ParseError as e:
        return f"Error parsing FDA RSS feed: {str(e)}"
    except Exception as e:
        import traceback
        print(f"[DEBUG FDA RSS] Error: {traceback.format_exc()}")
        return f"Error processing FDA announcements: {type(e).__name__}: {str(e)}"


@tool
def get_more_announcements(cache_key: str, offset: int, count: int = 5) -> str:
    """
    Retrieve the next page of FDA announcements from a previous get_fda_press_announcements call.

    Use this tool when the user asks to:
    - "show more announcements", "next", "see more news"
    - view a specific range (e.g., "show announcements 6 to 10")

    Args:
        cache_key: The cache key from the previous get_fda_press_announcements response (shown as [cache_key: ...]).
        offset: 0-based index of the first result to show (e.g., offset=5 for results 6–10).
        count: Number of announcements to return (default: 5).

    Returns:
        Formatted block of the requested FDA announcements.
    """
    if cache_key not in _search_cache:
        return "Announcement results have expired or the cache key is incorrect. Please run a new search."

    all_items = _search_cache[cache_key]
    total = len(all_items)

    if offset >= total:
        return f"No more announcements. You have already seen all {total} results from this search."

    batch   = all_items[offset: offset + count]
    end_idx = offset + len(batch)

    lines = [
        f"Showing announcements {offset + 1}–{end_idx} of {total} total:",
        "",
        *batch,
    ]
    if end_idx < total:
        lines.append(
            f"\n[{total - end_idx} more available — "
            f"call get_more_announcements(cache_key='{cache_key}', offset={end_idx}) for the next batch.]"
        )
    else:
        lines.append(f"\n[You have now seen all {total} announcements from this search.]")

    return "\n".join(lines)


# openFDA Complete Response Letters API
CRL_API_BASE = "https://api.fda.gov/transparency/crl.json"

# Map of common parent-company / brand names → subsidiary names used in the CRL database.
# openFDA uses the exact applicant name from the NDA/BLA submission, which is often a subsidiary.
CRL_COMPANY_ALIASES: dict[str, list[str]] = {
    "roche": ["Genentech"],
    "hoffmann-la roche": ["Genentech"],
    "f. hoffmann": ["Genentech"],
    "genentech": ["Genentech"],           # keep direct form too
    "merck kgaa": ["EMD Serono"],
    "emd serono": ["EMD Serono"],
    "gsk": ["ViiV Healthcare"],           # ViiV is HIV joint-venture
    "glaxosmithkline": ["Sandoz"],        # generic arm sometimes listed separately
    "novartis": ["Sandoz"],
    "j&j": ["Janssen"],
    "johnson & johnson": ["Janssen"],
    "johnson and johnson": ["Janssen"],
    "lilly": ["Eli Lilly"],
    "eli lilly": ["Eli Lilly and Company"],
    "abbvie": ["AbbVie"],
    "astrazeneca": ["AstraZeneca"],
    "pfizer": ["Pfizer"],
    "bms": ["Bristol-Myers Squibb"],
    "bristol myers squibb": ["Bristol-Myers Squibb"],
    "sanofi": ["Sanofi"],
    "amgen": ["Amgen"],
    "biogen": ["Biogen"],
    "regeneron": ["Regeneron"],
    "novo nordisk": ["Novo Nordisk"],
}


@tool
def search_complete_response_letters(
    company_name: Optional[str] = None,
    application_number: Optional[str] = None,
    approval_status: Optional[str] = None,
    year: Optional[str] = None,
    year_start: Optional[str] = None,
    year_end: Optional[str] = None,
    keywords: Optional[str] = None,
    max_results: int = 5
) -> str:
    """
    Search FDA Complete Response Letters (CRLs) from the openFDA Transparency API.

    A Complete Response Letter (CRL) is issued by the FDA to a drug sponsor when the agency
    has completed its review of a New Drug Application (NDA) or Biologics License Application (BLA)
    but cannot approve it in its current form. The letter details the deficiencies the sponsor
    must address before approval can be granted.

    Use this tool when users ask about:
    - FDA Complete Response Letters for a specific company or drug
    - Why a drug was not approved or what deficiencies were cited
    - CRL history for a specific application number (NDA/BLA)
    - Approved vs unapproved CRL outcomes
    - CRLs issued in a specific year or year range
    - Searching CRL text for specific topics (e.g., safety, manufacturing, clinical)

    Args:
        company_name: Pharmaceutical company name (e.g., "Pfizer", "Roche", "AstraZeneca").
                      Partial matches are supported (e.g., "Pfizer" matches "Pfizer Inc.").
        application_number: NDA or BLA application number (e.g., "NDA208647", "BLA761234").
                            Can include or omit the space (e.g., "NDA 208647" or "NDA208647").
        approval_status: Filter by final outcome. Valid values:
                         - "Approved": Application was eventually approved after the CRL
                         - "Unapproved": Application was not approved
        year: Filter CRLs issued in a specific year (e.g., "2024").
        year_start: Filter CRLs issued on or after this year (e.g., "2022").
        year_end: Filter CRLs issued on or before this year (e.g., "2024").
        keywords: Search within the full text of the CRL letter body
                  (e.g., "manufacturing", "clinical trial", "safety data", "labeling").
        max_results: Number of results to display at once (default: 5).

    Returns:
        Formatted list of CRL records including application number, company, date,
        approval status, approver, FDA center, and a preview of the letter text.

    Examples:
        - Pfizer CRLs: search_complete_response_letters(company_name="Pfizer")
        - Unapproved applications: search_complete_response_letters(approval_status="Unapproved")
        - CRLs in 2024: search_complete_response_letters(year="2024")
        - CRLs from 2022 to 2024: search_complete_response_letters(year_start="2022", year_end="2024")
        - CRLs mentioning manufacturing issues: search_complete_response_letters(keywords="manufacturing")
        - Specific application: search_complete_response_letters(application_number="NDA208647")
    """
    def _fetch_crl(search_parts: list[str]) -> tuple[list, int, int]:
        """Fire one CRL API request; returns (records, total, status_code)."""
        qp: dict = {"limit": 100, "sort": "letter_date:desc"}
        if search_parts:
            qp["search"] = "+AND+".join(search_parts)
        full_url = f"{CRL_API_BASE}?{urlencode(qp)}"
        print(f"[DEBUG CRL] Request: {full_url}")
        r = requests.get(CRL_API_BASE, params=qp, timeout=10)
        if r.status_code == 404:
            return [], 0, 404
        r.raise_for_status()
        d = r.json()
        recs = d.get("results", [])
        total = d.get("meta", {}).get("results", {}).get("total", len(recs))
        return recs, total, r.status_code

    try:
        # Build openFDA search query parts
        other_parts: list[str] = []  # filters other than company_name (reused in retries)

        if application_number:
            # Normalise: remove spaces so "NDA 208647" → "NDA208647" for search
            app_num_clean = application_number.replace(" ", "")
            other_parts.append(f'application_number:"{app_num_clean}"')
        if approval_status:
            other_parts.append(f'approval_status:"{approval_status.capitalize()}"')
        if year:
            other_parts.append(f'letter_year:"{year}"')
        if keywords:
            other_parts.append(f'text:"{keywords}"')

        # --- company_name search with alias fallback ---
        all_records: list = []
        total_api: int = 0
        alias_note: str = ""   # shown when an alias was used

        if company_name:
            # 1st attempt: exact company name as supplied
            first_parts = [f'company_name:"{company_name}"'] + other_parts
            all_records, total_api, status = _fetch_crl(first_parts)

            if not all_records:
                # 2nd attempt: check known alias map
                aliases = CRL_COMPANY_ALIASES.get(company_name.lower(), [])
                for alias in aliases:
                    alias_parts = [f'company_name:"{alias}"'] + other_parts
                    all_records, total_api, status = _fetch_crl(alias_parts)
                    if all_records:
                        alias_note = (
                            f'_(Note: No CRLs were found under "{company_name}" directly. '
                            f"Results shown are for **{alias}**, the FDA applicant name used by "
                            f"{company_name} for these submissions.)_\n\n"
                        )
                        break
        else:
            all_records, total_api, status = _fetch_crl(other_parts)

        if status == 404 or not all_records:
            suggestion = ""
            if company_name:
                known = CRL_COMPANY_ALIASES.get(company_name.lower(), [])
                if known:
                    suggestion = f" The company may submit applications under a subsidiary name such as **{', '.join(known)}** — try searching with that name instead."
                else:
                    suggestion = " The CRL database uses exact applicant names from NDA/BLA filings, which are often subsidiary company names. Try a different spelling or subsidiary name."
            return (
                f'No Complete Response Letters found for "{company_name or "your query"}".'
                + suggestion
            )

        # Client-side year range filter (letter_year is a string field)
        if year_start or year_end:
            filtered = []
            for r in all_records:
                ly = r.get("letter_year", "")
                if year_start and ly < year_start:
                    continue
                if year_end and ly > year_end:
                    continue
                filtered.append(r)
            all_records = filtered

        if not all_records:
            return f"No Complete Response Letters found in the year range {year_start or ''}–{year_end or ''}."

        # Format each record as a string block
        def _fmt_crl(rec: dict, idx: int) -> str:
            app_nums     = rec.get("application_number", [])
            company      = rec.get("company_name", "N/A")
            letter_date  = rec.get("letter_date", "N/A")
            letter_yr    = rec.get("letter_year", "N/A")
            status       = rec.get("approval_status", "N/A")
            ltype        = rec.get("letter_type", "N/A")
            approver     = rec.get("approver_name", "N/A")
            approver_ttl = rec.get("approver_title", "")
            centers      = rec.get("approver_center", [])
            rep          = rec.get("company_rep", "")
            text_preview = rec.get("text", "")

            # Clean up text preview — strip OCR artifacts, take first meaningful lines
            text_lines = [l.strip() for l in text_preview.splitlines() if len(l.strip()) > 30]
            preview = " ".join(text_lines[:3])[:400] + "..." if text_lines else ""

            lines = [f"{idx}. Application: {', '.join(app_nums) if app_nums else 'N/A'}"]
            lines.append(f"   Company: {company}")
            if rep:
                lines.append(f"   Company Representative: {rep}")
            lines.append(f"   Letter Date: {letter_date} ({letter_yr})")
            lines.append(f"   Letter Type: {ltype}")
            lines.append(f"   Approval Status: {status}")
            lines.append(f"   Approver: {approver}" + (f", {approver_ttl}" if approver_ttl else ""))
            if centers:
                lines.append(f"   FDA Center: {' / '.join(centers)}")
            if preview:
                lines.append(f"   Letter Preview: {preview}")
            return "\n".join(lines)

        all_formatted = [_fmt_crl(r, i + 1) for i, r in enumerate(all_records)]

        # Cache for pagination
        cache_key = uuid.uuid4().hex[:10]
        _search_cache[cache_key] = all_formatted
        print(f"[DEBUG CRL] Cached {len(all_formatted)} records under key '{cache_key}'")

        total   = len(all_formatted)
        page    = all_formatted[:max_results]
        end_idx = len(page)

        header_parts = [f"Total found: {total} Complete Response Letter(s)"]
        if total_api > 100:
            header_parts.append(f"(API returned top 100 of {total_api}; refine your search to narrow results)")

        output = [
            "Source: openFDA Transparency — Complete Response Letters",
            alias_note + " ".join(header_parts),
            f"Showing {end_idx} of {total}.",
            f"[cache_key: {cache_key}]",
            "",
            *page,
        ]
        if total > max_results:
            output.append(
                f"\n[{total - end_idx} more available — "
                f"call get_more_crls(cache_key='{cache_key}', offset={end_idx}) to continue.]"
            )

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"Error fetching Complete Response Letters: {str(e)}"
    except Exception as e:
        import traceback
        print(f"[DEBUG CRL] Error: {traceback.format_exc()}")
        return f"Error processing Complete Response Letters: {type(e).__name__}: {str(e)}"


@tool
def get_more_crls(cache_key: str, offset: int, count: int = 5) -> str:
    """
    Retrieve the next page of Complete Response Letters from a previous search_complete_response_letters call.

    Use when the user asks to:
    - "show more CRLs", "next batch", "see more letters"
    - view a specific range (e.g., "show CRLs 6 to 10")

    Args:
        cache_key: The cache key from the previous search_complete_response_letters response.
        offset: 0-based index of the first result to show (e.g., offset=5 for results 6–10).
        count: Number of results to return (default: 5).

    Returns:
        Formatted block of the requested Complete Response Letter records.
    """
    if cache_key not in _search_cache:
        return "CRL search results have expired or the cache key is incorrect. Please run a new search."

    all_items = _search_cache[cache_key]
    total = len(all_items)

    if offset >= total:
        return f"No more results. You have already seen all {total} Complete Response Letters from this search."

    batch   = all_items[offset: offset + count]
    end_idx = offset + len(batch)

    lines = [
        f"Showing Complete Response Letters {offset + 1}–{end_idx} of {total} total:",
        "",
        *batch,
    ]
    if end_idx < total:
        lines.append(
            f"\n[{total - end_idx} more available — "
            f"call get_more_crls(cache_key='{cache_key}', offset={end_idx}) for the next batch.]"
        )
    else:
        lines.append(f"\n[You have now seen all {total} records from this search.]")

    return "\n".join(lines)



@tool
def search_drugs_fda(
    drug_name: Optional[str] = None,
    brand_name: Optional[str] = None,
    generic_name: Optional[str] = None,
    product_type: Optional[str] = None,
    search_term: Optional[str] = None,
    max_results: int = 10
) -> str:
    """
    Search for drug information from Drugs@FDA using the openFDA API.
    
    The openFDA API provides access to FDA drug data including:
    - Drug labels (brand names, generic names, warnings, usage instructions)
    - Drugs@FDA dataset (approved drugs, application numbers, marketing status)
    - Drug adverse events
    
    Args:
        drug_name: General drug name to search for (searches both brand and generic names)
        brand_name: Specific brand name to search for (e.g., "Advil", "Tylenol")
        generic_name: Generic drug name (e.g., "ibuprofen", "acetaminophen")
        product_type: Filter by product type (e.g., "HUMAN PRESCRIPTION DRUG", "HUMAN OTC DRUG", "VETERINARY DRUG")
        search_term: Free-text search term to search across all fields
        max_results: Maximum number of results to return (default: 10, max: 100)
    
    Returns:
        A formatted string with drug information including brand name, generic name, 
        indications, warnings, dosage, and other relevant details.
    
    Examples:
        - Search by brand name: brand_name="Advil"
        - Search by generic name: generic_name="ibuprofen"
        - Search for prescription drugs: drug_name="aspirin", product_type="HUMAN PRESCRIPTION DRUG"
        - General search: search_term="diabetes medication"
    """
    try:
        OPENFDA_API_BASE = "https://api.fda.gov/drug/label.json"
        
        # Build search query
        search_parts = []
        
        if brand_name:
            search_parts.append(f'openfda.brand_name:"{brand_name}"')
        if generic_name:
            search_parts.append(f'openfda.generic_name:"{generic_name}"')
        if product_type:
            search_parts.append(f'openfda.product_type:"{product_type}"')
        if drug_name:
            # Search in both brand and generic names
            search_parts.append(f'(openfda.brand_name:"{drug_name}" OR openfda.generic_name:"{drug_name}")')
        if search_term:
            # General search across multiple fields
            search_parts.append(f'"{search_term}"')
        
        # If no specific search, return a helpful message
        if not search_parts:
            return "Please provide at least one search parameter: drug_name, brand_name, generic_name, or search_term."
        
        search_query = " AND ".join(search_parts)
        
        # Build query parameters
        query_params = {
            "search": search_query,
            "limit": min(max_results, 100)  # API max is 100
        }
        
        # Add API key if available (optional, but recommended for higher rate limits)
        OPENFDA_API_KEY = os.getenv("OPENFDA_API_KEY")
        if OPENFDA_API_KEY:
            query_params["api_key"] = OPENFDA_API_KEY
        
        # Make API request
        full_url = f"{OPENFDA_API_BASE}?{urlencode(query_params)}"
        print(f"[DEBUG openFDA] API Request URL: {full_url}")
        
        response = requests.get(OPENFDA_API_BASE, params=query_params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Check if we have results
        results = data.get("results", [])
        if not results or len(results) == 0:
            return f"No drug information found. Try a different search term or check the spelling."
        
        # Format the results
        formatted_results = []
        formatted_results.append(f"Found {len(results)} drug result(s):\n")
        
        for i, drug in enumerate(results, 1):
            try:
                openfda = drug.get("openfda", {})
                brand_names = openfda.get("brand_name", [])
                generic_names = openfda.get("generic_name", [])
                product_types = openfda.get("product_type", [])
                route = openfda.get("route", [])
                
                # Get label information
                purpose = drug.get("purpose", [])
                indications = drug.get("indications_and_usage", [])
                warnings = drug.get("warnings", [])
                boxed_warning = drug.get("boxed_warning", [])
                dosage = drug.get("dosage_and_administration", [])
                active_ingredient = drug.get("active_ingredient", [])
                
                formatted_results.append(f"{i}. {' / '.join(brand_names) if brand_names else 'N/A'}")
                if generic_names:
                    formatted_results.append(f"   Generic Name(s): {', '.join(set(generic_names))}")
                if product_types:
                    formatted_results.append(f"   Product Type: {', '.join(set(product_types))}")
                if route:
                    formatted_results.append(f"   Route: {', '.join(set(route))}")
                if active_ingredient:
                    formatted_results.append(f"   Active Ingredient: {', '.join(set(active_ingredient))}")
                
                if boxed_warning:
                    warning_text = boxed_warning[0][:300] if len(boxed_warning[0]) > 300 else boxed_warning[0]
                    formatted_results.append(f"   ⚠️ BOXED WARNING: {warning_text}...")
                
                if purpose:
                    purpose_text = purpose[0][:200] if len(purpose[0]) > 200 else purpose[0]
                    formatted_results.append(f"   Purpose: {purpose_text}...")
                elif indications:
                    indication_text = indications[0][:200] if len(indications[0]) > 200 else indications[0]
                    formatted_results.append(f"   Indications: {indication_text}...")
                
                if warnings:
                    warning_text = warnings[0][:200] if len(warnings[0]) > 200 else warnings[0]
                    formatted_results.append(f"   Warnings: {warning_text}...")
                
                if dosage:
                    dosage_text = dosage[0][:200] if len(dosage[0]) > 200 else dosage[0]
                    formatted_results.append(f"   Dosage: {dosage_text}...")
                
                formatted_results.append("")
                
            except Exception as e:
                print(f"[DEBUG openFDA] Error processing drug {i}: {str(e)}")
                formatted_results.append(f"{i}. [Error processing drug data]")
                formatted_results.append("")
        
        return "\n".join(formatted_results)
    
    except requests.exceptions.RequestException as e:
        error_msg = f"Error fetching drug information from openFDA: {str(e)}"
        print(f"[DEBUG openFDA] Request error: {error_msg}")
        return error_msg
    except Exception as e:
        error_msg = f"Error processing drug information: {type(e).__name__}: {str(e)}"
        print(f"[DEBUG openFDA] General error: {error_msg}")
        import traceback
        print(f"[DEBUG openFDA] Traceback: {traceback.format_exc()}")
        return error_msg

@tool
def get_clinical_trial_details(nct_id: str) -> str:
    """
    Fetch comprehensive details for a specific clinical trial by its NCT ID.

    Use this tool whenever the user references a specific NCT number (e.g., NCT02586025)
    or asks a question about a particular trial. Returns all structured data for the trial
    so you can answer any follow-up question (enrollment, eligibility, outcomes, etc.).

    Args:
        nct_id: The ClinicalTrials.gov identifier (e.g., "NCT02586025"). Case-insensitive.

    Returns:
        A comprehensive structured text covering identification, status, design, enrollment,
        eligibility, interventions, outcomes, locations, sponsor, and study results (if available).
    """
    try:
        nct_id = nct_id.strip().upper()
        url = f"{CLINICAL_TRIALS_API_BASE}/{nct_id}"
        print(f"[DEBUG detail] Fetching: {url}")
        response = requests.get(url, params={"format": "json"}, timeout=10)
        if response.status_code == 404:
            return f"No clinical trial found with ID {nct_id}. Please check the NCT number."
        response.raise_for_status()
        data = response.json()

        p = data.get("protocolSection", {})
        results_section = data.get("resultsSection", {})

        # --- Identification ---
        id_mod = p.get("identificationModule", {})
        nct_id_out = id_mod.get("nctId", nct_id)
        brief_title = id_mod.get("briefTitle", "N/A")
        official_title = id_mod.get("officialTitle", "N/A")
        org = id_mod.get("organization", {}).get("fullName", "N/A")

        # --- Status ---
        st_mod = p.get("statusModule", {})
        overall_status = st_mod.get("overallStatus", "N/A")
        start_date = st_mod.get("startDateStruct", {}).get("date", "N/A")
        primary_completion = st_mod.get("primaryCompletionDateStruct", {}).get("date", "N/A")
        completion_date = st_mod.get("completionDateStruct", {}).get("date", "N/A")
        first_post = st_mod.get("studyFirstPostDateStruct", {}).get("date", "N/A")
        last_update = st_mod.get("lastUpdatePostDateStruct", {}).get("date", "N/A")

        # --- Sponsor ---
        sp_mod = p.get("sponsorCollaboratorsModule", {})
        lead_sponsor = sp_mod.get("leadSponsor", {}).get("name", "N/A")
        collaborators = [c.get("name", "") for c in sp_mod.get("collaborators", [])]

        # --- Description ---
        desc_mod = p.get("descriptionModule", {})
        brief_summary = desc_mod.get("briefSummary", "N/A")
        # --- Conditions ---
        cond_mod = p.get("conditionsModule", {})
        conditions = cond_mod.get("conditions", [])
        keywords = cond_mod.get("keywords", [])

        # --- Design ---
        design_mod = p.get("designModule", {})
        study_type = design_mod.get("studyType", "N/A")
        phases = design_mod.get("phases", [])
        enrollment_info = design_mod.get("enrollmentInfo", {})
        enrollment_count = enrollment_info.get("count", "N/A")
        enrollment_type = enrollment_info.get("type", "")
        design_info = design_mod.get("designInfo", {})
        allocation = design_info.get("allocation", "N/A")
        intervention_model = design_info.get("interventionModel", "N/A")
        primary_purpose = design_info.get("primaryPurpose", "N/A")
        masking = design_info.get("maskingInfo", {}).get("masking", "N/A")

        # --- Arms & Interventions ---
        aim = p.get("armsInterventionsModule", {})
        interventions = aim.get("interventions", [])
        arm_groups = aim.get("armGroups", [])

        # --- Outcomes ---
        out_mod = p.get("outcomesModule", {})
        primary_outcomes = out_mod.get("primaryOutcomes", [])
        secondary_outcomes = out_mod.get("secondaryOutcomes", [])

        # --- Eligibility ---
        elig_mod = p.get("eligibilityModule", {})
        eligibility_criteria = elig_mod.get("eligibilityCriteria", "N/A")
        min_age = elig_mod.get("minimumAge", "N/A")
        max_age = elig_mod.get("maximumAge", "Not specified")
        sex = elig_mod.get("sex", "N/A")
        healthy_volunteers = elig_mod.get("healthyVolunteers", False)
        std_ages = elig_mod.get("stdAges", [])

        # --- Locations ---
        cl_mod = p.get("contactsLocationsModule", {})
        locations = cl_mod.get("locations", [])
        overall_officials = cl_mod.get("overallOfficials", [])

        # --- Build output ---
        out = []
        out.append(f"=== Clinical Trial: {nct_id_out} ===")
        out.append(f"Link: https://clinicaltrials.gov/study/{nct_id_out}")
        out.append(f"Title: {brief_title}")
        if official_title and official_title != brief_title:
            out.append(f"Official Title: {official_title}")
        out.append(f"Organization: {org}")
        out.append("")

        out.append("--- STATUS ---")
        out.append(f"Overall Status: {overall_status}")
        out.append(f"Start Date: {start_date}")
        out.append(f"Primary Completion Date: {primary_completion}")
        out.append(f"Study Completion Date: {completion_date}")
        out.append(f"First Posted: {first_post}")
        out.append(f"Last Updated: {last_update}")
        out.append("")

        out.append("--- SPONSOR ---")
        out.append(f"Lead Sponsor: {lead_sponsor}")
        if collaborators:
            out.append(f"Collaborators: {', '.join(collaborators)}")
        out.append("")

        out.append("--- DESIGN ---")
        out.append(f"Study Type: {study_type}")
        out.append(f"Phase(s): {', '.join(phases) if phases else 'N/A'}")
        out.append(f"Enrollment: {enrollment_count} participants ({enrollment_type})")
        out.append(f"Allocation: {allocation}")
        out.append(f"Intervention Model: {intervention_model}")
        out.append(f"Primary Purpose: {primary_purpose}")
        out.append(f"Masking: {masking}")
        out.append("")

        out.append("--- CONDITIONS ---")
        out.append(f"Conditions: {', '.join(conditions) if conditions else 'N/A'}")
        if keywords:
            out.append(f"Keywords: {', '.join(keywords[:10])}")
        out.append("")

        out.append("--- INTERVENTIONS ---")
        for intr in interventions:
            name = intr.get("name", "N/A")
            itype = intr.get("type", "N/A")
            desc = intr.get("description", "")
            out.append(f"  [{itype}] {name}")
            if desc:
                out.append(f"    Description: {desc[:200]}")
        out.append("")

        out.append("--- ARMS ---")
        for arm in arm_groups:
            label = arm.get("label", "N/A")
            atype = arm.get("type", "N/A")
            adesc = arm.get("description", "")
            out.append(f"  {label} ({atype}): {adesc[:150]}")
        out.append("")

        out.append("--- PRIMARY OUTCOMES ---")
        for po in primary_outcomes:
            out.append(f"  Measure: {po.get('measure', 'N/A')}")
            tf = po.get("timeFrame", "")
            if tf:
                out.append(f"  Time Frame: {tf}")
        out.append("")

        if secondary_outcomes:
            out.append("--- SECONDARY OUTCOMES ---")
            for so in secondary_outcomes[:5]:
                out.append(f"  Measure: {so.get('measure', 'N/A')}")
            if len(secondary_outcomes) > 5:
                out.append(f"  ... and {len(secondary_outcomes) - 5} more")
            out.append("")

        out.append("--- ELIGIBILITY ---")
        out.append(f"Age Range: {min_age} to {max_age}")
        out.append(f"Sex: {sex}")
        out.append(f"Age Groups: {', '.join(std_ages)}")
        out.append(f"Accepts Healthy Volunteers: {'Yes' if healthy_volunteers else 'No'}")
        out.append(f"Eligibility Criteria:\n{eligibility_criteria[:1500]}")
        if len(eligibility_criteria) > 1500:
            out.append("[...criteria truncated...]")
        out.append("")

        out.append("--- LOCATIONS ---")
        out.append(f"Total Sites: {len(locations)}")
        for loc in locations[:8]:
            facility = loc.get("facility", "N/A")
            city = loc.get("city", "")
            country = loc.get("country", "")
            status = loc.get("status", "")
            out.append(f"  {facility} — {city}, {country} [{status}]")
        if len(locations) > 8:
            out.append(f"  ... and {len(locations) - 8} more sites")
        out.append("")

        if overall_officials:
            out.append("--- OVERALL OFFICIALS ---")
            for off in overall_officials[:3]:
                out.append(f"  {off.get('name','N/A')} ({off.get('role','')}) — {off.get('affiliation','')}")
            out.append("")

        out.append("--- BRIEF SUMMARY ---")
        out.append(brief_summary[:800])
        if len(brief_summary) > 800:
            out.append("[...truncated...]")
        out.append("")

        # --- Results (if available) ---
        if results_section:
            out.append("--- STUDY RESULTS ---")
            # Participant flow
            flow = results_section.get("participantFlowModule", {})
            groups = flow.get("groups", [])
            if groups:
                out.append("Participant Flow Groups:")
                for g in groups:
                    out.append(f"  {g.get('title','')}: {g.get('description','')[:100]}")

            # Outcome measures (first primary outcome result)
            outcome_measures = results_section.get("outcomeMeasuresModule", {}).get("outcomeMeasures", [])
            for om in outcome_measures[:2]:
                out.append(f"Outcome: {om.get('title','N/A')} (Type: {om.get('type','N/A')})")
                classes = om.get("classes", [])
                for cls in classes[:3]:
                    for cat in cls.get("categories", [])[:3]:
                        for meas in cat.get("measurements", [])[:4]:
                            val = meas.get("value", "N/A")
                            grp = meas.get("groupId", "")
                            out.append(f"  Group {grp}: {val}")

            # Adverse events summary
            ae_mod = results_section.get("adverseEventsModule", {})
            if ae_mod:
                freq_threshold = ae_mod.get("frequencyThreshold", "")
                out.append(f"Adverse Events Frequency Threshold: {freq_threshold}")

            out.append("")

        return "\n".join(out)

    except requests.exceptions.RequestException as e:
        return f"Error fetching trial {nct_id}: {str(e)}"
    except Exception as e:
        import traceback
        print(f"[DEBUG detail] Error: {traceback.format_exc()}")
        return f"Error processing trial {nct_id}: {type(e).__name__}: {str(e)}"


# Initialize LLM with tools
llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    api_key=OPENAI_API_KEY,
)

# Bind tools to the LLM - create separate LLMs for different purposes
llm_with_trials_tools = llm.bind_tools([search_clinical_trials, get_more_trials])
llm_with_drugs_tools = llm.bind_tools([search_drugs_fda, get_fda_press_announcements, get_more_announcements, search_complete_response_letters, get_more_crls])
llm_with_detail_tools = llm.bind_tools([get_clinical_trial_details])

# Get current date for date calculations
CURRENT_DATE = datetime.now().strftime("%Y-%m-%d")
CURRENT_YEAR = datetime.now().year
CURRENT_MONTH = datetime.now().month
CURRENT_DAY = datetime.now().day

# Calculate common date ranges
ONE_MONTH_AGO = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
THREE_MONTHS_AGO = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
SIX_MONTHS_AGO = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
ONE_YEAR_AGO = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

# Load system messages from prompt files
_date_vars = dict(
    CURRENT_DATE=CURRENT_DATE,
    CURRENT_YEAR=CURRENT_YEAR,
    CURRENT_MONTH=CURRENT_MONTH,
    CURRENT_DAY=CURRENT_DAY,
    ONE_MONTH_AGO=ONE_MONTH_AGO,
    THREE_MONTHS_AGO=THREE_MONTHS_AGO,
    SIX_MONTHS_AGO=SIX_MONTHS_AGO,
    ONE_YEAR_AGO=ONE_YEAR_AGO,
)

sys_msg_trials  = SystemMessage(content=_load_prompt("trials_agent.txt",  **_date_vars))
sys_msg_drugs   = SystemMessage(content=_load_prompt("drugs_agent.txt",   **_date_vars))
sys_msg_detail  = SystemMessage(content=_load_prompt("detail_agent.txt"))
sys_msg_chat    = SystemMessage(content=_load_prompt("chat_agent.txt"))

# State shared across the orchestrated graph
class OrchestratorState(MessagesState):
    next_agent: str  # "trials" | "drugs" | "detail" | "chat"

# Keep original sys_msg for backward compatibility
sys_msg = sys_msg_trials

# Node with tool calling support - can use different tools based on mode
def assistant_trials(state: MessagesState):
    messages = [sys_msg_trials] + state["messages"]
    response = llm_with_trials_tools.invoke(messages)
    
    return _process_tool_calls(response, messages, llm)

def assistant_drugs(state: MessagesState):
    messages = [sys_msg_drugs] + state["messages"]
    response = llm_with_drugs_tools.invoke(messages)
    
    return _process_tool_calls(response, messages, llm)

def assistant_detail(state: MessagesState):
    messages = [sys_msg_detail] + state["messages"]
    response = llm_with_detail_tools.invoke(messages)

    return _process_tool_calls(response, messages, llm)

def chat_agent(state: OrchestratorState):
    messages = [sys_msg_chat] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}

_NCT_RE = re.compile(r'\bNCT\d{6,8}\b', re.IGNORECASE)

_ORCHESTRATOR_PROMPT = _load_prompt("orchestrator.txt")

def orchestrator(state: OrchestratorState):
    messages = state["messages"]
    last_msg = messages[-1].content if messages else ""

    # Hard-coded fast path — NCT IDs always go to detail without an LLM call
    if _NCT_RE.search(last_msg):
        print("[ORCHESTRATOR] → detail (NCT ID detected)")
        return {"next_agent": "detail"}

    # Ask the LLM to classify intent using full conversation history as context
    classification_messages = [
        SystemMessage(content=_ORCHESTRATOR_PROMPT),
        *messages,
    ]
    response = llm.invoke(classification_messages)
    raw = response.content.strip().lower()

    match = re.search(r'\b(trials|drugs|detail|chat)\b', raw)
    intent = match.group(1) if match else "trials"
    print(f"[ORCHESTRATOR] → {intent} (raw: '{raw}')")
    return {"next_agent": intent}

def route_after_orchestrator(state: OrchestratorState) -> str:
    return state.get("next_agent", "trials")

def _process_tool_calls(response, messages, llm):
    
    # Check if the model wants to call a tool
    tool_calls = []
    if isinstance(response, AIMessage):
        tool_calls = response.tool_calls if hasattr(response, 'tool_calls') and response.tool_calls else []
    elif hasattr(response, 'tool_calls'):
        tool_calls = response.tool_calls if response.tool_calls else []
    
    # Debug: print tool calls if any
    if tool_calls:
        print(f"[DEBUG] Tool calls detected: {len(tool_calls)} call(s)")
        for tc in tool_calls:
            print(f"[DEBUG] - Tool: {tc.get('name') if isinstance(tc, dict) else getattr(tc, 'name', 'unknown')}")
    else:
        print(f"[DEBUG] No tool calls. Response type: {type(response)}, has tool_calls: {hasattr(response, 'tool_calls')}")
        if hasattr(response, 'tool_calls'):
            print(f"[DEBUG] tool_calls value: {response.tool_calls}")
    
    if tool_calls:
        # Execute tool calls
        tool_messages = []
        for tool_call in tool_calls:
            # Handle both dict and object formats
            if isinstance(tool_call, dict):
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})
                tool_call_id = tool_call.get("id")
            else:
                tool_name = getattr(tool_call, "name", None)
                tool_args = getattr(tool_call, "args", {})
                tool_call_id = getattr(tool_call, "id", None)
            
            # CRITICAL: We must respond to EVERY tool call, even if we don't handle it
            if tool_name == "search_clinical_trials":
                print(f"[DEBUG] Executing search_clinical_trials with args: {tool_args}, tool_call_id: {tool_call_id}")
                try:
                    result = search_clinical_trials.invoke(tool_args)
                    tool_messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call_id
                    ))
                except Exception as e:
                    tool_messages.append(ToolMessage(
                        content=f"Error executing tool: {str(e)}",
                        tool_call_id=tool_call_id
                    ))
            elif tool_name == "get_clinical_trial_details":
                print(f"[DEBUG] Executing get_clinical_trial_details with args: {tool_args}, tool_call_id: {tool_call_id}")
                try:
                    result = get_clinical_trial_details.invoke(tool_args)
                    tool_messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call_id
                    ))
                except Exception as e:
                    tool_messages.append(ToolMessage(
                        content=f"Error executing tool: {str(e)}",
                        tool_call_id=tool_call_id
                    ))
            elif tool_name == "get_more_trials":
                print(f"[DEBUG] Executing get_more_trials with args: {tool_args}, tool_call_id: {tool_call_id}")
                try:
                    result = get_more_trials.invoke(tool_args)
                    tool_messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call_id
                    ))
                except Exception as e:
                    tool_messages.append(ToolMessage(
                        content=f"Error executing tool: {str(e)}",
                        tool_call_id=tool_call_id
                    ))
            elif tool_name == "search_drugs_fda":
                print(f"[DEBUG] Executing search_drugs_fda with args: {tool_args}, tool_call_id: {tool_call_id}")
                try:
                    result = search_drugs_fda.invoke(tool_args)
                    tool_messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call_id
                    ))
                except Exception as e:
                    tool_messages.append(ToolMessage(
                        content=f"Error executing tool: {str(e)}",
                        tool_call_id=tool_call_id
                    ))
            elif tool_name == "get_fda_press_announcements":
                print(f"[DEBUG] Executing get_fda_press_announcements with args: {tool_args}, tool_call_id: {tool_call_id}")
                try:
                    result = get_fda_press_announcements.invoke(tool_args)
                    tool_messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call_id
                    ))
                except Exception as e:
                    tool_messages.append(ToolMessage(
                        content=f"Error executing tool: {str(e)}",
                        tool_call_id=tool_call_id
                    ))
            elif tool_name == "get_more_announcements":
                print(f"[DEBUG] Executing get_more_announcements with args: {tool_args}, tool_call_id: {tool_call_id}")
                try:
                    result = get_more_announcements.invoke(tool_args)
                    tool_messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call_id
                    ))
                except Exception as e:
                    tool_messages.append(ToolMessage(
                        content=f"Error executing tool: {str(e)}",
                        tool_call_id=tool_call_id
                    ))
            elif tool_name == "search_complete_response_letters":
                print(f"[DEBUG] Executing search_complete_response_letters with args: {tool_args}, tool_call_id: {tool_call_id}")
                try:
                    result = search_complete_response_letters.invoke(tool_args)
                    tool_messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call_id
                    ))
                except Exception as e:
                    tool_messages.append(ToolMessage(
                        content=f"Error executing tool: {str(e)}",
                        tool_call_id=tool_call_id
                    ))
            elif tool_name == "get_more_crls":
                print(f"[DEBUG] Executing get_more_crls with args: {tool_args}, tool_call_id: {tool_call_id}")
                try:
                    result = get_more_crls.invoke(tool_args)
                    tool_messages.append(ToolMessage(
                        content=result,
                        tool_call_id=tool_call_id
                    ))
                except Exception as e:
                    tool_messages.append(ToolMessage(
                        content=f"Error executing tool: {str(e)}",
                        tool_call_id=tool_call_id
                    ))
            else:
                # Handle unknown tools - still must respond
                print(f"[WARNING] Unknown tool: {tool_name}, tool_call_id: {tool_call_id}")
                tool_messages.append(ToolMessage(
                    content=f"Unknown tool: {tool_name}",
                    tool_call_id=tool_call_id
                ))
        
        # Ensure we have a response for every tool call
        print(f"[DEBUG] Tool calls: {len(tool_calls)}, Tool messages: {len(tool_messages)}")
        if len(tool_messages) != len(tool_calls):
            print(f"[ERROR] Mismatch: {len(tool_calls)} tool calls but {len(tool_messages)} responses")
            # Create placeholder responses for missing tool calls
            for i, tool_call in enumerate(tool_calls):
                if isinstance(tool_call, dict):
                    tool_call_id = tool_call.get("id")
                else:
                    tool_call_id = getattr(tool_call, "id", None)
                
                # Check if we already have a response for this tool_call_id
                existing_ids = []
                for tm in tool_messages:
                    if hasattr(tm, 'tool_call_id'):
                        existing_ids.append(tm.tool_call_id)
                    elif isinstance(tm, ToolMessage):
                        existing_ids.append(tm.tool_call_id)
                
                print(f"[DEBUG] Tool call {i} ID: {tool_call_id}, Existing IDs: {existing_ids}")
                if tool_call_id and tool_call_id not in existing_ids:
                    print(f"[DEBUG] Creating placeholder response for tool_call_id: {tool_call_id}")
                    tool_messages.append(ToolMessage(
                        content="Tool execution failed",
                        tool_call_id=tool_call_id
                    ))
        
        # Get final response after tool execution
        # Use regular llm (not llm_with_tools) for final response
        messages.append(response)
        messages.extend(tool_messages)
        final_response = llm.invoke(messages)
        
        return {"messages": [response] + tool_messages + [final_response]}
    
    return {"messages": [response]}

# Build Graphs for different modes
builder_trials = StateGraph(MessagesState)
builder_trials.add_node("assistant", assistant_trials)
builder_trials.add_edge(START, "assistant")
react_graph_trials = builder_trials.compile()

builder_drugs = StateGraph(MessagesState)
builder_drugs.add_node("assistant", assistant_drugs)
builder_drugs.add_edge(START, "assistant")
react_graph_drugs = builder_drugs.compile()

builder_detail = StateGraph(MessagesState)
builder_detail.add_node("assistant", assistant_detail)
builder_detail.add_edge(START, "assistant")
react_graph_detail = builder_detail.compile()

# Orchestrated graph — single entry point, routes internally
builder_orch = StateGraph(OrchestratorState)
builder_orch.add_node("orchestrator", orchestrator)
builder_orch.add_node("trials_agent", assistant_trials)
builder_orch.add_node("drugs_agent", assistant_drugs)
builder_orch.add_node("detail_agent", assistant_detail)
builder_orch.add_node("chat_agent", chat_agent)

builder_orch.add_edge(START, "orchestrator")
builder_orch.add_conditional_edges(
    "orchestrator",
    route_after_orchestrator,
    {
        "trials": "trials_agent",
        "drugs":  "drugs_agent",
        "detail": "detail_agent",
        "chat":   "chat_agent",
    },
)
builder_orch.add_edge("trials_agent", END)
builder_orch.add_edge("drugs_agent",  END)
builder_orch.add_edge("detail_agent", END)
builder_orch.add_edge("chat_agent",   END)
react_graph_orchestrated = builder_orch.compile()

# Default graph for backward compatibility
react_graph = react_graph_orchestrated

def get_graph(mode="orchestrated"):
    if mode == "orchestrated":
        return react_graph_orchestrated
    elif mode == "trials":
        return react_graph_trials
    elif mode == "drugs":
        return react_graph_drugs
    elif mode == "detail":
        return react_graph_detail
    else:
        return react_graph_orchestrated

# Interactive chat loop
def chat():
    print("=" * 60)
    print("Medical Assistant Chatbot")
    print("=" * 60)
    print("Type your questions below. Type 'quit', 'exit', or 'q' to end.\n")
    
    conversation_history = []
    
    while True:
        # Get user input
        user_input = input("You: ").strip()
        
        # Check for exit commands
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("\nGoodbye! Stay healthy! 👋")
            break
        
        # Skip empty inputs
        if not user_input:
            continue
        
        # Add user message to history
        conversation_history.append(HumanMessage(content=user_input))
        
        # Get response from chatbot
        try:
            result = react_graph.invoke({"messages": conversation_history})
            
            # Get the assistant's response (last message)
            assistant_message = result['messages'][-1]
            
            # Update conversation history
            conversation_history = result['messages']
            
            # Print assistant's response
            print(f"\nAssistant: {assistant_message.content}\n")
            
        except Exception as e:
            print(f"\nError: {e}\n")
            print("Please try again or type 'quit' to exit.\n")

if __name__ == "__main__":
    chat()