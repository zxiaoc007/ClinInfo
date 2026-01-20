import os, getpass
import requests
import json
from typing import Optional
from datetime import datetime, timedelta
from urllib.parse import urlencode
from dotenv import load_dotenv

from langgraph.graph import MessagesState
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langgraph.graph import START, StateGraph
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ClinicalTrials.gov API base URL
CLINICAL_TRIALS_API_BASE = "https://clinicaltrials.gov/api/v2/studies"

@tool
def search_clinical_trials(
    condition: str,
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
        - Search for diabetes trials in New York: condition="diabetes", location="New York"
        - Search for recent cancer trials: condition="cancer", start_date="2024-01-01"
    """
    try:
        # Build query parameters - API v2 only supports basic condition search
        # Other filters must be applied client-side
        # Fetch 3x the requested amount to account for filtering, but API max is 100
        api_fetch_limit = min(max_results * 3, 100)
        query_params = {
            "query.cond": condition,
            "pageSize": api_fetch_limit,
            "format": "json"
        }
        
        # Note: API v2 doesn't support query.phase, query.overallStatus, etc.
        # We'll filter client-side after fetching
        
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

# Initialize LLM with tools
llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    api_key=OPENAI_API_KEY,
)

# Bind tools to the LLM - create separate LLMs for different purposes
llm_with_trials_tools = llm.bind_tools([search_clinical_trials])
llm_with_drugs_tools = llm.bind_tools([search_drugs_fda])
llm_with_all_tools = llm.bind_tools([search_clinical_trials, search_drugs_fda])

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

# System messages for different assistants
sys_msg_trials = SystemMessage(content=f"""You are a helpful medical assistant with access to clinical trials information from ClinicalTrials.gov API v2.

CURRENT DATE INFORMATION:
- Today's date: {CURRENT_DATE} (YYYY-MM-DD format)
- Current year: {CURRENT_YEAR}
- Current month: {CURRENT_MONTH}
- Current day: {CURRENT_DAY}

IMPORTANT: When users ask about:
- Clinical trials for any medical condition (e.g., "diabetes", "cancer", "Alzheimer's")
- Medical research or studies
- Treatments or experimental therapies
- Finding trials for specific diseases
- Phase-specific trials (Phase 1, 2, 3, or 4)
- Recruiting or active trials
- Trials by location, age group, or gender
- Recent trials or trials from a specific time period

You MUST use the search_clinical_trials tool to search for relevant information. Do not provide general information without searching first.

API Schema Reference for constructing queries:
- Condition (required for meaningful results): Use the medical condition or disease name
- Status filters: RECRUITING, NOT_YET_RECRUITING, ACTIVE_NOT_RECRUITING, COMPLETED, SUSPENDED, TERMINATED, WITHDRAWN
- Phase filters: PHASE1, PHASE2, PHASE3, PHASE4, NA
- Study type: INTERVENTIONAL, OBSERVATIONAL, EXPANDED_ACCESS
- Age groups: CHILD (0-17), ADULT (18-64), OLDER_ADULT (65+)
- Gender: ALL, FEMALE, MALE
- Dates: Use ISO format YYYY-MM-DD (e.g., "{CURRENT_DATE}")

DATE CALCULATION RULES (CRITICAL - Use current date: {CURRENT_DATE}):
- "recent" or "recently" → use start_date="{ONE_MONTH_AGO}" (last 30 days from today)
- "last month" or "past month" → use start_date="{ONE_MONTH_AGO}" (30 days ago from {CURRENT_DATE})
- "last 3 months" or "past 3 months" → use start_date="{THREE_MONTHS_AGO}" (90 days ago from {CURRENT_DATE})
- "last 6 months" or "past 6 months" → use start_date="{SIX_MONTHS_AGO}" (180 days ago from {CURRENT_DATE})
- "last year" or "past year" → use start_date="{ONE_YEAR_AGO}" (365 days ago from {CURRENT_DATE})
- "this year" → use start_date="{CURRENT_YEAR}-01-01"
- "this month" → use start_date="{CURRENT_YEAR}-{CURRENT_MONTH:02d}-01"
- For specific dates mentioned by user, convert to YYYY-MM-DD format
- Always use start_date for "since" or "from" queries
- Always use end_date for "until" or "before" queries
- For date ranges, use both start_date and end_date

When users mention:
- "phase 3" or "phase III" → use phase="PHASE3"
- "recruiting" or "actively recruiting" → use status="RECRUITING"
- "recent", "last month", "past month" → calculate start_date based on current date ({CURRENT_DATE})
- Location names → use location parameter
- Age groups → use age_group parameter (CHILD, ADULT, OLDER_ADULT)
- Specific interventions → use intervention parameter

Always provide accurate, helpful information and cite the NCT IDs when discussing specific trials.""")

sys_msg_drugs = SystemMessage(content=f"""You are a helpful medical assistant with access to drug information from Drugs@FDA via the openFDA API.

IMPORTANT: When users ask about:
- Drug information, medications, or pharmaceuticals
- Brand names or generic names of drugs
- Drug labels, warnings, indications, or dosages
- FDA-approved drugs
- Drug interactions or side effects (from labels)
- Finding information about specific medications

You MUST use the search_drugs_fda tool to search for relevant information. Do not provide general information without searching first.

Search Guidelines:
- Use brand_name parameter for brand names (e.g., "Advil", "Tylenol")
- Use generic_name parameter for generic drug names (e.g., "ibuprofen", "acetaminophen")
- Use drug_name parameter for general searches that should check both brand and generic names
- Use product_type to filter (e.g., "HUMAN PRESCRIPTION DRUG", "HUMAN OTC DRUG")
- Use search_term for free-text searches across all fields

Always provide accurate, helpful information about drugs and cite sources when available.""")

sys_msg_unified = SystemMessage(content=f"""You are a helpful medical assistant with access to both clinical trials information from ClinicalTrials.gov and drug information from Drugs@FDA via openFDA.

CURRENT DATE INFORMATION:
- Today's date: {CURRENT_DATE} (YYYY-MM-DD format)
- Current year: {CURRENT_YEAR}
- Current month: {CURRENT_MONTH}
- Current day: {CURRENT_DAY}

You have access to two tools:
1. search_clinical_trials - For finding clinical trials from ClinicalTrials.gov
2. search_drugs_fda - For finding drug information from Drugs@FDA

Use the appropriate tool based on what the user is asking about. If the user asks about both, you can use both tools.

For clinical trials queries, use search_clinical_trials.
For drug information queries, use search_drugs_fda.

Always provide accurate, helpful information and cite sources when available.""")

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

def assistant_unified(state: MessagesState):
    messages = [sys_msg_unified] + state["messages"]
    response = llm_with_all_tools.invoke(messages)
    
    return _process_tool_calls(response, messages, llm)

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

builder_unified = StateGraph(MessagesState)
builder_unified.add_node("assistant", assistant_unified)
builder_unified.add_edge(START, "assistant")
react_graph_unified = builder_unified.compile()

# Default graph for backward compatibility
react_graph = react_graph_trials

# Function to get the right graph based on mode
def get_graph(mode="trials"):
    if mode == "trials":
        return react_graph_trials
    elif mode == "drugs":
        return react_graph_drugs
    elif mode == "unified":
        return react_graph_unified
    else:
        return react_graph_trials

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