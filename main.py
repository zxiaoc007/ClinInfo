import os, getpass
import re
import requests
import json
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

@tool
def search_clinical_trials(
    condition: str,
    sponsor: Optional[str] = None,
    status: Optional[str] = None,
    phase: Optional[str] = None,
    study_type: Optional[str] = None,
    intervention: Optional[str] = None,
    location: Optional[str] = None,
    age_group: Optional[str] = None,
    gender: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_results: int = 25
) -> str:
    """
    Search for clinical trials on ClinicalTrials.gov API v2.

    API Schema Reference:
    - Base URL: https://clinicaltrials.gov/api/v2/studies
    - All parameters are optional, but condition is typically required for meaningful results

    Args:
        condition: The medical condition or disease to search for (e.g., "diabetes", "breast cancer")
        sponsor: Optional sponsor/pharmaceutical company name filter (e.g., "Roche", "Pfizer", "Novartis").
                 Searches across both lead sponsors and collaborators (server-side filtering via query.spons).
        status: Optional trial status filter. Valid values: RECRUITING, NOT_YET_RECRUITING, ACTIVE_NOT_RECRUITING,
                COMPLETED, SUSPENDED, TERMINATED, WITHDRAWN, ENROLLING_BY_INVITATION, UNKNOWN
        phase: Optional phase filter. Valid values: PHASE1, PHASE2, PHASE3, PHASE4, NA
        study_type: Optional study type filter. Valid values: INTERVENTIONAL, OBSERVATIONAL, EXPANDED_ACCESS
        intervention: Optional intervention name or type (e.g., "aspirin", "chemotherapy")
        location: Optional location filter (city, state, or country, e.g., "New York", "United States")
        age_group: Optional age group filter. Valid values: CHILD (0-17), ADULT (18-64), OLDER_ADULT (65+)
        gender: Optional gender filter. Valid values: ALL, FEMALE, MALE
        start_date: Optional start date filter in ISO format YYYY-MM-DD (e.g., "2024-01-01")
        end_date: Optional end date filter in ISO format YYYY-MM-DD (e.g., "2024-12-31")
        max_results: Maximum number of results to return (default: 25, max: 100 due to API limit)

    Returns:
        A formatted string with clinical trial information including NCT ID, title, status, and eligibility

    Examples:
        - Search for recruiting phase 3 breast cancer trials: condition="breast cancer", status="RECRUITING", phase="PHASE3"
        - Search for Roche phase 3 breast cancer trials: condition="breast cancer", sponsor="Roche", phase="PHASE3"
        - Search for Pfizer diabetes trials: condition="diabetes", sponsor="Pfizer"
        - Search for diabetes trials in New York: condition="diabetes", location="New York"
        - Search for recent cancer trials: condition="cancer", start_date="2024-01-01"
    """
    try:
        # Build query parameters
        # query.spons is supported server-side; phase/status/etc. are filtered client-side
        # Fetch 3x the requested amount to account for client-side filtering, but API max is 100
        api_fetch_limit = min(max_results * 3, 100)
        query_params = {
            "query.cond": condition,
            "pageSize": api_fetch_limit,
            "format": "json"
        }

        # Sponsor is a native API filter (query.spons searches lead sponsors + collaborators)
        if sponsor:
            query_params["query.spons"] = sponsor
        
        # Make API request
        # Build the full URL to show the raw query
        full_url = f"{CLINICAL_TRIALS_API_BASE}?{urlencode(query_params)}"
        print(f"[DEBUG API] Raw API Request URL:")
        print(f"[DEBUG API] {full_url}")
        print(f"[DEBUG API] Query parameters: {query_params}")
        
        response = requests.get(CLINICAL_TRIALS_API_BASE, params=query_params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        print(f"[DEBUG API] Response keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
        
        # Check if we have studies in the response
        all_studies = data.get("studies", [])
        if not all_studies or len(all_studies) == 0:
            return f"No clinical trials found for condition: {condition}"
        
        # Apply client-side filters
        filtered_studies = []
        for study in all_studies:
            protocol = study.get("protocolSection", {})
            status_module = protocol.get("statusModule", {})
            design_module = protocol.get("designModule", {})
            eligibility_module = protocol.get("eligibilityModule", {})
            contacts_locations = protocol.get("contactsLocationsModule", {})
            
            # Filter by status
            if status:
                study_status = status_module.get("overallStatus", "").upper()
                if study_status != status.upper():
                    continue
            
            # Filter by phase
            if phase:
                study_phases = design_module.get("phases", [])
                phase_upper = phase.upper()
                # Check if any phase matches (studies can have multiple phases)
                if not any(p.upper() == phase_upper for p in study_phases):
                    continue
            
            # Filter by study type
            if study_type:
                study_type_value = design_module.get("studyType", "").upper()
                if study_type_value != study_type.upper():
                    continue
            
            # Filter by age group
            if age_group:
                std_ages = eligibility_module.get("stdAges", [])
                age_upper = age_group.upper()
                if not any(a.upper() == age_upper for a in std_ages):
                    continue
            
            # Filter by gender
            if gender:
                study_gender = eligibility_module.get("sex", "").upper()
                if study_gender != gender.upper() and study_gender != "ALL":
                    continue
            
            # Filter by location (check in locations array)
            if location:
                locations = contacts_locations.get("locations", [])
                location_found = False
                location_lower = location.lower()
                for loc in locations:
                    city = loc.get("city", "").lower()
                    state = loc.get("state", "").lower()
                    country = loc.get("country", "").lower()
                    if (location_lower in city or location_lower in state or 
                        location_lower in country):
                        location_found = True
                        break
                if not location_found:
                    continue
            
            # Filter by date range (check multiple date fields)
            if start_date or end_date:
                # Check multiple date fields: lastUpdatePostDate, studyFirstPostDate, startDate
                last_update = status_module.get("lastUpdatePostDateStruct", {})
                first_post = status_module.get("studyFirstPostDateStruct", {})
                start_date_struct = status_module.get("startDateStruct", {})
                
                # Try to get a date to compare - prefer last update, then first post, then start date
                date_to_check = None
                if last_update.get("date"):
                    date_to_check = last_update.get("date")
                elif first_post.get("date"):
                    date_to_check = first_post.get("date")
                elif start_date_struct.get("date"):
                    date_to_check = start_date_struct.get("date")
                
                if date_to_check:
                    # Compare dates (they should be in YYYY-MM-DD format)
                    if start_date and date_to_check < start_date:
                        continue
                    if end_date and date_to_check > end_date:
                        continue
            
            # Filter by intervention (check in interventions)
            if intervention:
                arms_interventions = protocol.get("armsInterventionsModule", {})
                interventions = arms_interventions.get("interventions", [])
                intervention_found = False
                intervention_lower = intervention.lower()
                for intr in interventions:
                    intr_name = intr.get("name", "").lower()
                    intr_desc = intr.get("description", "").lower()
                    if (intervention_lower in intr_name or 
                        intervention_lower in intr_desc):
                        intervention_found = True
                        break
                if not intervention_found:
                    continue
            
            filtered_studies.append(study)
            if len(filtered_studies) >= max_results:
                break
        
        if not filtered_studies:
            filter_desc = []
            if status:
                filter_desc.append(f"status={status}")
            if phase:
                filter_desc.append(f"phase={phase}")
            if study_type:
                filter_desc.append(f"study_type={study_type}")
            filter_str = " with " + ", ".join(filter_desc) if filter_desc else ""
            return f"No clinical trials found for condition '{condition}'{filter_str}. Try removing some filters or broadening your search."
        
        # Format the results
        results = []
        total_count = data.get('totalCount', len(all_studies))
        
        # Check if we might have more results available
        has_more = (len(all_studies) >= api_fetch_limit and len(filtered_studies) < max_results) or total_count > api_fetch_limit
        
        if has_more:
            results.append(f"Found {len(filtered_studies)} clinical trials for '{condition}' (showing {len(filtered_studies)} of {total_count} total available). More results may be available.\n")
        else:
            results.append(f"Found {len(filtered_studies)} clinical trials for '{condition}' (filtered from {total_count} total):\n")
        
        for i, study in enumerate(filtered_studies, 1):
            try:
                protocol = study.get("protocolSection", {})
                identification = protocol.get("identificationModule", {})
                status_module = protocol.get("statusModule", {})
                design_module = protocol.get("designModule", {})
                eligibility = protocol.get("eligibilityModule", {})
                
                title = identification.get("briefTitle", "N/A")
                nct_id = identification.get("nctId", "N/A")
                overall_status = status_module.get("overallStatus", "N/A")
                study_phases = design_module.get("phases", [])
                study_type = design_module.get("studyType", "N/A")
                eligibility_criteria = eligibility.get("eligibilityCriteria", "N/A")
                sponsor_info = protocol.get("sponsorCollaboratorsModule", {})
                lead_sponsor = sponsor_info.get("leadSponsor", {}).get("name", "N/A")
                collaborators = [c.get("name", "") for c in sponsor_info.get("collaborators", [])]

                # Truncate eligibility criteria if too long
                if len(eligibility_criteria) > 200:
                    eligibility_criteria = eligibility_criteria[:200] + "..."

                results.append(f"{i}. {title}")
                results.append(f"   NCT ID: {nct_id}")
                if nct_id and nct_id != "N/A":
                    study_url = f"https://clinicaltrials.gov/study/{nct_id}"
                    results.append(f"   Link: {study_url}")
                results.append(f"   Status: {overall_status}")
                if study_phases:
                    phases_str = ", ".join(study_phases) if study_phases else "N/A"
                    results.append(f"   Phase: {phases_str}")
                if study_type != "N/A":
                    results.append(f"   Study Type: {study_type}")
                if lead_sponsor and lead_sponsor != "N/A":
                    results.append(f"   Lead Sponsor: {lead_sponsor}")
                if collaborators:
                    results.append(f"   Collaborators: {', '.join(collaborators[:3])}")
                if eligibility_criteria and eligibility_criteria != "N/A":
                    results.append(f"   Eligibility: {eligibility_criteria[:150]}...")
                results.append("")
            except Exception as e:
                print(f"[DEBUG API] Error processing study {i}: {str(e)}")
                results.append(f"{i}. [Error processing study data]")
                results.append("")
        
        return "\n".join(results)
    
    except requests.exceptions.RequestException as e:
        error_msg = f"Error fetching clinical trials data: {str(e)}"
        print(f"[DEBUG API] Request error: {error_msg}")
        return error_msg
    except KeyError as e:
        error_msg = f"Error processing API response - missing key: {str(e)}"
        print(f"[DEBUG API] KeyError: {error_msg}")
        print(f"[DEBUG API] Response data structure: {list(data.keys()) if 'data' in locals() and isinstance(data, dict) else 'N/A'}")
        return error_msg
    except Exception as e:
        error_msg = f"Error processing clinical trials data: {type(e).__name__}: {str(e)}"
        print(f"[DEBUG API] General error: {error_msg}")
        import traceback
        print(f"[DEBUG API] Traceback: {traceback.format_exc()}")
        return error_msg

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
        detailed_desc = desc_mod.get("detailedDescription", "")

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
llm_with_trials_tools = llm.bind_tools([search_clinical_trials])
llm_with_drugs_tools = llm.bind_tools([search_drugs_fda])
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
sys_msg_drugs   = SystemMessage(content=_load_prompt("drugs_agent.txt"))
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