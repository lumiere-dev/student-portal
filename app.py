import os
import streamlit as st
import streamlit.components.v1 as components
from pyairtable import Api
import pandas as pd
from datetime import datetime, timedelta, timezone
import resend
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import re
from streamlit_cookies_controller import CookieController


# This is the "silent" tracker
posthog_snippet = """
<script>
    !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}var l=t;for(void 0!==a?l=t[a]=[]:a="posthog",l.people=l.people||[],l.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},l.people.toString=function(){return l.toString(1)+".people (stub)"},p="capture identify alias people.set people.set_once set_config register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled onFeatureFlags getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures onSessionId getSurveys getActiveMatchingSurveys renderSurvey getNextSurveyStep identifyAndSetDistinctId".split(" "),r=0;r<p.length;r++)g(l,p[r]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
    posthog.init('phc_oVPvA5P5XDgN389qFX9pUrZykk7ykhRHLJUJ6PKHNMFF', {
    api_host: 'https://webhook.site/57ed48c8-530e-4006-9d63-f999bb7d8057',
    person_profiles: 'identified_only',
    capture_pageview: true,
    property_blacklist: ['$device_id'] 
})
</script>
"""

# Inject the snippet into the frontend
components.html(posthog_snippet, height=0, width=0)


def get_secret(key, default=None):
    """Get config value from env var (Railway) or st.secrets (local), with optional default."""
    val = os.environ.get(key)
    if val is not None:
        return val
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return default

# Page config
st.set_page_config(
    page_title="Student Portal - Lumiere Education",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ──────────────────────────────────────────────
# Airtable Connection
# ──────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def get_airtable_api():
    return Api(get_secret("AIRTABLE_API_KEY"), timeout=(10, 30), retry_strategy=False)

@st.cache_resource(show_spinner=False)
def get_application_api():
    return Api(get_secret("AIRTABLE_API_KEY"), timeout=(10, 30), retry_strategy=False)

@st.cache_resource(show_spinner=False)
def get_tables():
    api = get_airtable_api()
    base = api.base(get_secret("STUDENT_MENTOR_DATA_ID"))
    return {
        "students": base.table(get_secret("STUDENT_TABLE")),
        "deadlines": base.table(get_secret("DEADLINES_TABLE")),
        "mentors": base.table(get_secret("MENTOR_TABLE"))
    }

@st.cache_resource(show_spinner=False)
def get_application_table():
    api = get_application_api()
    base = api.base(get_secret("PUBLICATION_BASE_ID"))
    return base.table(get_secret("PUBLICATION_TABLE"))

@st.cache_resource(show_spinner=False)
def get_wc_requests_table():
    api = get_airtable_api()
    base = api.base(get_secret("PUBLICATION_BASE_ID"))
    return base.table(get_secret("WC_REQUESTS"))

@st.cache_data(ttl=300, show_spinner=False)
def fetch_wc_requests(email):
    try:
        table = get_wc_requests_table()
        safe_email = email.lower().replace("'", "\\'")
        formula = f"LOWER({{Student Email Final}}) = '{safe_email}'"
        fields = [
            "Created Time",
            "Responded by Writing Coach",
            "Writing Center Request Type",
            "Response Recorded [Created Time] (from Writing Centre Responses & Recording)",
            "Written Feedback Upload (from Writing Centre Responses & Recording)",
        ]
        records = table.all(formula=formula, fields=fields)
        records.sort(key=lambda r: r["fields"].get("Created Time", ""), reverse=True)
        return records
    except Exception:
        return []

# ──────────────────────────────────────────────
# Magic Link Authentication
# ──────────────────────────────────────────────

def get_serializer():
    return URLSafeTimedSerializer(get_secret("MAGIC_LINK_SECRET"))

def generate_magic_token(email):
    """Generate a signed token containing the email"""
    serializer = get_serializer()
    return serializer.dumps(email, salt="student-magic-link")

def verify_magic_token(token, max_age=3600):
    """Verify token and return email if valid (default 1 hour expiry)"""
    serializer = get_serializer()
    try:
        email = serializer.loads(token, salt="student-magic-link", max_age=max_age)
        return email
    except (SignatureExpired, BadSignature):
        return None

def generate_session_token(email):
    """Generate a long-lived signed token for persistent session cookie"""
    return get_serializer().dumps(email, salt="student-session")

def verify_session_token(token):
    """Verify session cookie token (30-day expiry)"""
    try:
        return get_serializer().loads(token, salt="student-session", max_age=30 * 24 * 3600)
    except (SignatureExpired, BadSignature):
        return None

def send_magic_link(email, student_name):
    """Send magic link email to student"""
    resend.api_key = get_secret("RESEND_API_KEY")

    token = generate_magic_token(email)
    base_url = get_secret("APP_URL", "http://localhost:8502")
    magic_link = f"{base_url}?token={token}"

    # Extract first name from "Name | Cohort | Program" format
    first_name = student_name.split("|")[0].strip().split()[0] if student_name else "Student"

    try:
        resend.Emails.send({
            "from": get_secret("FROM_EMAIL", "Student Portal <onboarding@resend.dev>"),
            "to": [email],
            "subject": "Your Student Portal Login Link",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #BE1E2D;">Welcome to the Student Portal</h2>
                <p>Hi {first_name},</p>
                <p>Click the button below to access your student dashboard:</p>
                <p style="margin: 30px 0;">
                    <a href="{magic_link}"
                       style="background: linear-gradient(135deg, #BE1E2D 0%, #8B1520 100%);
                              color: white;
                              padding: 12px 30px;
                              text-decoration: none;
                              border-radius: 6px;
                              display: inline-block;">
                        Access Student Portal
                    </a>
                </p>
                <p style="color: #64748B; font-size: 14px;">
                    This link will expire in 1 hour for security reasons.<br>
                    If you didn't request this link, you can safely ignore this email.
                </p>
            </div>
            """
        })
        return True
    except Exception as e:
        st.error(f"Failed to send email: {e}")
        return False

# ──────────────────────────────────────────────
# Field Mappings
# ──────────────────────────────────────────────

STUDENT_FIELDS = {
    "name": "Student Cohort Application Tracker",
    "mentor": "Mentor Name_Text",
    "mentor_email": "Mentor Email",
    "research_area": "Research Area - First Preference",
    "city": "City of Residence",
    "graduation_year": "Graduation Year",
    "mentor_confirmation": "Mentor Confirmation",
    "background_shared": "OB: Mentor Background Shared",
    "expected_meetings": "Number of Expected Meetings - Student/Mentor",
    "completed_meetings": "[Current + Archived] No. of Meetings Completed",
    "notes_summary": "Mentor-Student Notes Summary",
    "hours_recorded": "[Current + Archived] No. of Hours Recorded",
    "foundation_student": "Foundation Student",
    "pub_foundation_student": "Publication Foundation Student Y/N",
    "tuition_paid": "OB: Full Tuition Paid",
    "program_manager_name": "Program Manager (Text)",
    "program_manager_email": "Program Manager Email",
    "pm_facts": "PM: Facts about PM (used for Intro Email)",
    "writing_coach_name": "Writing Coach Name (Text)",
    "writing_coach_email": "Writing Coach Email",
    "revised_final_paper_due": "PM: Student's Revised Final Paper - Due date",
    "student_no_shows": "[Current + Archived] No. of Student No Shows in Mentor Meetings",
    "reason_for_interest": "Reason for Interest in Areas",
    "publication_specialist": "Publication Specialist (Text)",
    "publication_target": "Publication Target (Text)",
    "publication_specialist_email": "Publication Specialist Email",
    "publication_outcome": "PS: Latest Publication Outcome - (latest)",
    "submission_portal": "Student Submission Portal Lookup",
    "publication_marker": "Publication Marker",
    "white_label_or_partner": "White Label or Partner Payment Program",
    "program_status": "PM: Student Status in Program",
    "program_pause_end_date": "Program Pause End Date",
    "student_confirmed_launched": "Student Confirmed & Launched"
}

DEADLINE_FIELDS = {
    "name": "Deadline Name",
    "type": "Deadline Type",
    "due_date": "Due Date (in use, updated to reflect student's timeline)",
    "status": "Deadline Status",
    "date_submitted": "Date Submitted",
    "student_link": "Student Application & Cohort Tracker"
}

SUBMISSION_FIELDS = [
    "Syllabus Submission (From Mentor)",
    "Research Question",
    "Research Proposal",
    "Research Outline",
    "Milestone",
    "Milestone Submission (from Mentor-Student Progress Table)",
    "Milestone 1 Submission (from Mentor-Student Progress Table)",
    "Final Paper",
    "First Draft",
    "Revised Final Paper",
    "Final Draft",
    "Target Publication Submission",
]

# Maps deadline types to guidebook resource links (title, url)
GUIDEBOOK_LINKS = {
    "Research Question": [
        ("Developing a Research Question", "https://misty-music-eb4.notion.site/Developing-a-Research-Question-dd1ab52205aa43998da57cc7fd44f8df"),
    ],
    "Research Proposal": [
        ("Research Proposal Format", "https://misty-music-eb4.notion.site/Research-Proposal-Format-cb4908948dad4d0ca4a065b3e14e8c66"),
    ],
    "Research Outline": [
        ("Paper Outline Format", "https://misty-music-eb4.notion.site/Paper-Outline-Format-8dff9c11b8a0428b9ff8b3d59fbfde94"),
    ],
    "Paper Outline": [
        ("Paper Outline Format", "https://misty-music-eb4.notion.site/Paper-Outline-Format-8dff9c11b8a0428b9ff8b3d59fbfde94"),
    ],
    "Research Paper Outline": [
        ("Paper Outline Format", "https://misty-music-eb4.notion.site/Paper-Outline-Format-8dff9c11b8a0428b9ff8b3d59fbfde94"),
    ],
    "Milestone": [
        ("Milestone Submissions", "https://misty-music-eb4.notion.site/Milestone-Submissions-33235699f82c4cf88e640d830799b24e"),
    ],
    "Revised Final Paper": [
        ("Editing & Revising Guide", "https://misty-music-eb4.notion.site/Editing-Revising-Guide-05fa87864bde44a3b634a64fd5be7c9c"),
        ("Final Research Paper Guide", "https://misty-music-eb4.notion.site/Final-Research-Paper-35b244db93284cf399bae728956e1e9a"),
    ],
    "First Draft": [
        ("Citations 101", "https://misty-music-eb4.notion.site/Citations-101-3211af35f82f4eb7a7a2f6fd6125b9e7"),
    ],
}


GUIDEBOOK_HELPER = {
    "Research Question": "Start here — this guide walks you through scoping and refining your research question.",
    "Research Proposal": "Covers what to include and how to structure your proposal before submitting.",
    "Research Outline": "Follow this template when building out the outline for your paper.",
    "Paper Outline": "Follow this template when building out the outline for your paper.",
    "Research Paper Outline": "Follow this template when building out the outline for your paper.",
    "Milestone": "What to include in your milestone submission and how it will be reviewed.",
    "Revised Final Paper": "Editing tips and paper formatting requirements to review before your final submission.",
    "First Draft": "Before you submit, make sure your citations are correctly formatted.",
}


def get_guidebook_links(dtype):
    """Return guidebook links for a deadline type, with prefix fallback for variants like 'Milestone 1'."""
    if dtype in GUIDEBOOK_LINKS:
        return GUIDEBOOK_LINKS[dtype]
    for key, links in GUIDEBOOK_LINKS.items():
        if dtype.startswith(key):
            return links
    return []


def get_guidebook_helper(dtype):
    """Return helper text for a deadline type, with prefix fallback."""
    if dtype in GUIDEBOOK_HELPER:
        return GUIDEBOOK_HELPER[dtype]
    for key, text in GUIDEBOOK_HELPER.items():
        if dtype.startswith(key):
            return text
    return "Helpful reference for this deadline."

# ──────────────────────────────────────────────
# Custom CSS — Lumiere Brand Theme
# ──────────────────────────────────────────────

st.markdown("""
<style>
    /* Header styles */
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #333333;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #666666;
        margin-bottom: 2rem;
    }
    .student-name-header {
        font-size: 1.6rem;
        font-weight: 600;
        color: #1E293B;
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #BE1E2D;
    }

    /* Cards */
    .student-card {
        background: #FFFFFF;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        margin-bottom: 1rem;
        border-left: 4px solid #BE1E2D;
    }
    .metric-card {
        background: linear-gradient(135deg, #BE1E2D 0%, #8B1520 100%);
        border-radius: 12px;
        padding: 1.5rem;
        color: white;
        margin-bottom: 0.75rem;
    }
    .metric-label {
        font-size: 0.8rem;
        opacity: 0.9;
    }
    .metric-value {
        font-size: 1.5rem;
        font-weight: 700;
        margin-top: 0.15rem;
    }
    .info-card {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        margin-bottom: 1rem;
    }

    /* Status badges */
    .status-confirmed {
        background-color: #ECFDF5;
        color: #065F46;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 500;
        display: inline-block;
    }
    .status-pending {
        background-color: #FFFBEB;
        color: #92400E;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 500;
        display: inline-block;
    }
    .status-overdue {
        background-color: #FEF2F2;
        color: #991B1B;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 500;
        display: inline-block;
    }
    .deadline-submitted {
        background-color: #ECFDF5;
        border-left: 4px solid #10B981;
    }
    .deadline-pending {
        background-color: #FFFBEB;
        border-left: 4px solid #F59E0B;
    }
    .deadline-overdue {
        background-color: #FEF2F2;
        border-left: 4px solid #EF4444;
    }

    /* Preview mode */
    .preview-banner {
        background-color: #FFFBEB;
        border: 1px solid #F59E0B;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        margin-bottom: 1rem;
        color: #92400E;
    }

    /* Dark navy sidebar */
    [data-testid="stSidebar"] {
        background-color: #1A1A2E;
        color: #FFFFFF;
    }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label {
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] .stCaption p {
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] hr {
        border-color: rgba(255,255,255,0.2);
    }
    [data-testid="stSidebar"] .stButton button {
        background-color: rgba(255,255,255,0.1);
        color: #FFFFFF !important;
        border: 1px solid rgba(255,255,255,0.3);
    }
    [data-testid="stSidebar"] .stButton button:hover {
        background-color: rgba(255,255,255,0.2);
        border-color: rgba(255,255,255,0.5);
    }
    /* Rectangular nav style for sidebar radio */
    [data-testid="stSidebar"] .stRadio > div {
        gap: 0.25rem !important;
    }
    [data-testid="stSidebar"] .stRadio > div > label {
        background-color: transparent !important;
        border-radius: 6px !important;
        padding: 0.6rem 1rem !important;
        margin: 0 !important;
        cursor: pointer;
        transition: background-color 0.2s;
    }
    [data-testid="stSidebar"] .stRadio > div > label:hover {
        background-color: rgba(255,255,255,0.1) !important;
    }
    [data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
        background-color: rgba(255,255,255,0.15) !important;
        border-left: 3px solid #DC1E35 !important;
    }
    /* Hide radio circle */
    [data-testid="stSidebar"] .stRadio > div > label > div:first-child {
        display: none !important;
    }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# Session State
# ──────────────────────────────────────────────

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "student_name" not in st.session_state:
    st.session_state.student_name = None
if "student_email" not in st.session_state:
    st.session_state.student_email = None
if "student_record" not in st.session_state:
    st.session_state.student_record = None
if "is_preview" not in st.session_state:
    st.session_state.is_preview = False
if "magic_link_sent" not in st.session_state:
    st.session_state.magic_link_sent = False
if "team_unlocked" not in st.session_state:
    st.session_state.team_unlocked = False
if "student_records" not in st.session_state:
    st.session_state.student_records = []
if "program_selected" not in st.session_state:
    st.session_state.program_selected = False

cookies = CookieController()

# ──────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────

def unwrap(val, default=""):
    """Unwrap Airtable lookup fields (returned as arrays)"""
    if isinstance(val, list):
        return val[0] if val else default
    return val if val is not None else default

def format_duration(value):
    """Format a duration value (seconds from Airtable API) as h:mm"""
    if not value and value != 0:
        return "N/A"
    if isinstance(value, str):
        return value if value else "N/A"
    try:
        total_seconds = int(value)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}:{minutes:02d}"
    except (ValueError, TypeError):
        return str(value)

def format_date(date_str):
    """Format date string as 'Month Dth, YYYY' (e.g. July 4th, 2025)"""
    if not date_str:
        return "Not set"
    if isinstance(date_str, list):
        date_str = date_str[0] if date_str else ""
    if not date_str:
        return "Not set"
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        day = date_obj.day
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{date_obj.strftime('%B')} {day}{suffix}, {date_obj.year}"
    except Exception:
        return date_str

def format_datetime_ist(date_str):
    """Format an ISO datetime string to a friendly format in IST (UTC+5:30)"""
    if not date_str:
        return "Not set"
    if isinstance(date_str, list):
        date_str = date_str[0] if date_str else ""
    if not date_str:
        return "Not set"
    try:
        date_str = date_str.strip("'\"")
        date_obj = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        ist = timezone(timedelta(hours=5, minutes=30))
        date_obj = date_obj.replace(tzinfo=timezone.utc).astimezone(ist)
        return date_obj.strftime("%b %#d, %Y %#I:%M %p IST")
    except Exception:
        return format_date(date_str)

def format_notes_summary(text):
    """Parse and format notes summary text for better display"""
    if not text:
        return ""

    lines = text.strip().split('\n')
    formatted_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.isupper() and len(line) > 2:
            formatted_lines.append(f"**{line.title()}**")
        elif line.endswith(':') and len(line) < 50:
            formatted_lines.append(f"**{line}**")
        elif line.startswith(('-', '\u2022', '*', '\u2013')):
            formatted_lines.append(line)
        elif re.match(r'^\d+[\.\)]\s', line):
            formatted_lines.append(line)
        else:
            formatted_lines.append(line)

    return '\n\n'.join(formatted_lines)

def is_overdue(due_date_str, status):
    """Check if deadline is overdue"""
    if status in ("Submitted", "Deadline Waived"):
        return False
    if not due_date_str:
        return False
    try:
        due_date = datetime.strptime(due_date_str, "%Y-%m-%d")
        return due_date < datetime.now()
    except Exception:
        return False

# ──────────────────────────────────────────────
# Data Functions
# ──────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_student_publication_record(tracker_value):
    """Look up the student's record in appOhh4711y4cXSfj/tbluBNu4xfwOWMgr0
    by matching the 'Student Cohort Application Tracker' field value."""
    if not tracker_value:
        return None
    try:
        table = get_application_table()
        name = str(tracker_value).split("|")[0].strip()
        records = table.all(
            formula=f"FIND('{name}', {{Student Cohort Application Tracker}})",
            fields=[
                "Student Cohort Application Tracker",
                "Publication Specialist (Text)",
                "Publication Specialist Email",
                "Publication Target (text)",
                "PS: Latest Publication Outcome - (latest)",
                "Target Submission Workshop",
                "Target Intro Workshop",
                "Target One-Pager",
                "Checkpoint: Quiz 1 Status (Automated)",
                "Checkpoint: Quiz 2 Status (Automated)",
                "Checkpoint: Quiz 3 Status (Automated)",
            ]
        )
        return records[0] if records else None
    except Exception as e:
        st.error(f"Error fetching student application: {e}")
        return None

def _build_student_dict(record, email):
    """Build a student dict from a raw Airtable record."""
    email_field = get_secret("STUDENT_EMAIL_FIELD", "Email")
    fields = record["fields"]
    tracker_value = fields.get(STUDENT_FIELDS["name"], "")
    raw_marker = fields.get(STUDENT_FIELDS["publication_marker"], [])
    pub_marker = raw_marker[0] if isinstance(raw_marker, list) and raw_marker else raw_marker
    pub_marker_vals = raw_marker if isinstance(raw_marker, list) else [raw_marker]
    if any(str(v).strip() == "Yes" for v in pub_marker_vals if v):
        application = get_student_publication_record(tracker_value)
        app_fields = application["fields"] if application else {}
    else:
        app_fields = {}
    return {
        "id": record["id"],
        "name": tracker_value or "Unknown",
        "email": fields.get(email_field, email),
        "research_area": fields.get(STUDENT_FIELDS["research_area"], ""),
        "city": fields.get(STUDENT_FIELDS["city"], ""),
        "graduation_year": fields.get(STUDENT_FIELDS["graduation_year"], ""),
        "mentor": fields.get(STUDENT_FIELDS["mentor"], ""),
        "mentor_email": unwrap(fields.get(STUDENT_FIELDS["mentor_email"], "")),
        "mentor_confirmation": fields.get(STUDENT_FIELDS["mentor_confirmation"], ""),
        "background_shared": fields.get(STUDENT_FIELDS["background_shared"], ""),
        "expected_meetings": fields.get(STUDENT_FIELDS["expected_meetings"], 0),
        "completed_meetings": fields.get(STUDENT_FIELDS["completed_meetings"], 0),
        "notes_summary": fields.get(STUDENT_FIELDS["notes_summary"], ""),
        "hours_recorded": fields.get(STUDENT_FIELDS["hours_recorded"], ""),
        "foundation_student": fields.get(STUDENT_FIELDS["foundation_student"], ""),
        "pub_foundation_student": fields.get(STUDENT_FIELDS["pub_foundation_student"], ""),
        "tuition_paid": fields.get(STUDENT_FIELDS["tuition_paid"], ""),
        "program_manager_name": unwrap(fields.get(STUDENT_FIELDS["program_manager_name"], "")),
        "program_manager_email": unwrap(fields.get(STUDENT_FIELDS["program_manager_email"], "")),
        "pm_facts": fields.get(STUDENT_FIELDS["pm_facts"], ""),
        "writing_coach_name": fields.get(STUDENT_FIELDS["writing_coach_name"], ""),
        "writing_coach_email": [e.strip() for v in (fields.get(STUDENT_FIELDS["writing_coach_email"]) or []) for e in str(v).split(",") if e.strip()],
        "revised_final_paper_due": unwrap(fields.get(STUDENT_FIELDS["revised_final_paper_due"], "")),
        "student_no_shows": unwrap(fields.get(STUDENT_FIELDS["student_no_shows"], 0), default=0),
        "reason_for_interest": unwrap(fields.get(STUDENT_FIELDS["reason_for_interest"], "")),
        "publication_target": app_fields.get("Publication Target (text)", ""),
        "submission_portal": unwrap(fields.get(STUDENT_FIELDS["submission_portal"], "")),
        "publication_specialist": app_fields.get("Publication Specialist (Text)", ""),
        "publication_specialist_email": app_fields.get("Publication Specialist Email", ""),
        "publication_outcome": app_fields.get("PS: Latest Publication Outcome - (latest)", ""),
        "target_submission_workshop": app_fields.get("Target Submission Workshop", ""),
        "target_intro_workshop": app_fields.get("Target Intro Workshop", ""),
        "target_one_pager": app_fields.get("Target One-Pager", ""),
        "quiz_1_status": app_fields.get("Checkpoint: Quiz 1 Status (Automated)", ""),
        "quiz_2_status": app_fields.get("Checkpoint: Quiz 2 Status (Automated)", ""),
        "quiz_3_status": app_fields.get("Checkpoint: Quiz 3 Status (Automated)", ""),
        "publication_marker": fields.get(STUDENT_FIELDS["publication_marker"], []),
        "white_label_or_partner": fields.get(STUDENT_FIELDS["white_label_or_partner"], ""),
        "program_status": unwrap(fields.get(STUDENT_FIELDS["program_status"], "")),
        "program_pause_end_date": fields.get(STUDENT_FIELDS["program_pause_end_date"], ""),
        "student_confirmed_launched": fields.get(STUDENT_FIELDS["student_confirmed_launched"], "")
    }

@st.cache_data(ttl=3600, show_spinner=False)
def get_student_by_email(email):
    """Find student by email — returns the first matching record or None."""
    tables = get_tables()
    email_field = get_secret("STUDENT_EMAIL_FIELD", "Email")
    try:
        records = tables["students"].all(
            formula=f"LOWER({{{email_field}}}) = LOWER('{email}')"
        )
        if records:
            return _build_student_dict(records[0], email)
    except Exception as e:
        st.error(f"Error fetching student: {e}")
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_all_student_records_by_email(email):
    """Find all records for an email — returns a list (students with multiple programs)."""
    tables = get_tables()
    email_field = get_secret("STUDENT_EMAIL_FIELD", "Email")
    try:
        records = tables["students"].all(
            formula=f"LOWER({{{email_field}}}) = LOWER('{email}')"
        )
        return [_build_student_dict(r, email) for r in records]
    except Exception as e:
        st.error(f"Error fetching student records: {e}")
    return []

@st.cache_data(ttl=3600, show_spinner=False)
def get_deadlines_for_student(student_name):
    """Get all deadlines for a specific student"""
    tables = get_tables()
    try:
        formula = f"FIND('{student_name.split('|')[0].strip()}', {{Deadline Name}})"
        records = tables["deadlines"].all(formula=formula)

        deadlines = []
        for record in records:
            fields = record["fields"]

            # Collect submission files
            submissions = {}
            for field in SUBMISSION_FIELDS:
                value = fields.get(field)
                if value:
                    submissions[field] = value

            deadlines.append({
                "id": record["id"],
                "name": fields.get(DEADLINE_FIELDS["name"], ""),
                "type": fields.get(DEADLINE_FIELDS["type"], ""),
                "due_date": fields.get(DEADLINE_FIELDS["due_date"], ""),
                "status": fields.get(DEADLINE_FIELDS["status"], ""),
                "date_submitted": fields.get(DEADLINE_FIELDS["date_submitted"], ""),
                "submissions": submissions
            })

        deadlines.sort(key=lambda x: x["due_date"] or "9999-99-99")
        return deadlines
    except Exception as e:
        st.error(f"Error fetching deadlines: {e}")
        return []

# ──────────────────────────────────────────────
# Auth Token Check
# ──────────────────────────────────────────────

def check_session_cookie():
    if st.session_state.authenticated:
        return
    try:
        token = cookies.get("student_session")
    except TypeError:
        return
    if token:
        email = verify_session_token(token)
        if email:
            with st.spinner("Loading your portal..."):
                students = filter_accessible_records(get_all_student_records_by_email(email))
            if students:
                st.session_state.authenticated = True
                st.session_state.student_email = email
                st.session_state.is_preview = False
                st.session_state.student_records = students
                if len(students) == 1:
                    st.session_state.student_record = students[0]
                    st.session_state.student_name = students[0]["name"]
                    st.session_state.program_selected = True
                else:
                    st.session_state.program_selected = False
                st.rerun()
        else:
            cookies.remove("student_session")

def check_magic_link_token():
    query_params = st.query_params
    if "token" in query_params and not st.session_state.authenticated:
        token = query_params["token"]
        email = verify_magic_token(token)
        if email:
            with st.spinner("Loading your portal..."):
                students = filter_accessible_records(get_all_student_records_by_email(email))
            if students:
                st.session_state.authenticated = True
                st.session_state.student_email = email
                st.session_state.is_preview = False
                st.session_state.student_records = students
                if len(students) == 1:
                    st.session_state.student_record = students[0]
                    st.session_state.student_name = students[0]["name"]
                    st.session_state.program_selected = True
                else:
                    st.session_state.program_selected = False
                # Defer cookie write to next run — JS component not ready on first load.
                st.session_state.pending_session_cookie = email
                st.query_params.clear()
                st.rerun()
            else:
                st.error("No account found for this email. Please contact your program manager.")
                st.query_params.clear()
        else:
            st.error("This login link has expired or is invalid. Please request a new one.")
            st.query_params.clear()

# ──────────────────────────────────────────────
# PROGRAM SELECTOR
# ──────────────────────────────────────────────

def filter_accessible_records(students):
    """Remove records where White Label or Partner Payment Program is set,
    or where Student Confirmed & Launched does not contain Yes."""
    def is_accessible(s):
        if s.get("white_label_or_partner"):
            return False
        confirmed = s.get("student_confirmed_launched", "")
        confirmed_vals = confirmed if isinstance(confirmed, list) else [confirmed]
        if not any(str(v).strip().startswith("Yes") for v in confirmed_vals if v):
            return False
        return True
    return [s for s in students if is_accessible(s)]

def show_program_selector():
    import base64
    st.markdown("""
    <style>
        .stApp { background-color: #1A1A2E; }
        #MainMenu, header, footer { visibility: hidden; }
        .block-container { padding-top: 8vh !important; max-width: 100% !important; }
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) {
            background: white !important;
            border-radius: 16px !important;
            padding: 2.5rem !important;
            box-shadow: 0 20px 60px rgba(0,0,0,0.4) !important;
        }
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) p,
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) label,
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) span {
            color: #1A1A2E !important;
        }
        .prog-select-btn > button {
            background: white !important;
            color: #1A1A2E !important;
            border: 1.5px solid #E2E8F0 !important;
            border-radius: 12px !important;
            font-weight: 600 !important;
            font-size: 0.95rem !important;
            padding: 0.85rem 1.25rem !important;
            width: 100% !important;
            text-align: left !important;
            transition: border-color 0.15s, box-shadow 0.15s !important;
            margin-bottom: 0.5rem !important;
        }
        .prog-select-btn > button:hover {
            border-color: #DC1E35 !important;
            box-shadow: 0 0 0 3px rgba(220,30,53,0.08) !important;
            background: #FFF8F8 !important;
            color: #DC1E35 !important;
        }
        .prog-select-btn > button p {
            color: inherit !important;
            font-size: inherit !important;
        }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with open("assets/logo.png", "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
        st.markdown(
            f'<div style="text-align:center; margin-bottom:0.5rem;">'
            f'<img src="data:image/png;base64,{logo_b64}" width="200"></div>',
            unsafe_allow_html=True
        )
        st.markdown(
            '<h2 style="text-align:center; color:#1A1A2E; font-size:1.5rem; font-weight:700; margin:0.5rem 0 0.2rem;">Welcome back!</h2>',
            unsafe_allow_html=True
        )
        st.markdown(
            '<p style="text-align:center; color:#94A3B8; font-size:0.85rem; margin-bottom:1.75rem; line-height:1.5;">You\'ve completed multiple programs with us.<br>Which program would you like to view?</p>',
            unsafe_allow_html=True
        )

        for student in st.session_state.student_records:
            parts = [p.strip() for p in student["name"].split("|")]
            cohort = parts[1] if len(parts) > 1 else ""
            program = parts[2] if len(parts) > 2 else ""
            label = f"📚  {cohort}   •   {program}" if cohort else student["name"]
            st.markdown('<div class="prog-select-btn">', unsafe_allow_html=True)
            if st.button(label, key=f"prog_{student['id']}"):
                st.session_state.student_record = student
                st.session_state.student_name = student["name"]
                st.session_state.program_selected = True
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

# ──────────────────────────────────────────────
# LOGIN PAGE
# ──────────────────────────────────────────────

def show_login_page():
    import base64
    st.markdown("""
    <style>
        .stApp {
            background-color: #1A1A2E;
        }
        /* Hide Streamlit chrome */
        #MainMenu, header, footer { visibility: hidden; }
        /* Push card down for vertical centering */
        .block-container {
            padding-top: 10vh !important;
            max-width: 100% !important;
        }
        /* White card on the middle column
           Covers both old ("column") and new ("stColumn") Streamlit testid values */
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2),
        [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2) {
            background: white !important;
            border-radius: 16px !important;
            padding: 2.5rem !important;
            box-shadow: 0 20px 60px rgba(0,0,0,0.4) !important;
        }
        /* Text colours inside card */
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) p,
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) label,
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) span,
        [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2) p,
        [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2) label,
        [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2) span {
            color: #1A1A2E !important;
        }
        /* Input field */
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) input,
        [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2) input {
            border: 1px solid #CBD5E1 !important;
            border-radius: 8px !important;
            color: #1A1A2E !important;
            background: white !important;
        }
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) input::placeholder,
        [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2) input::placeholder {
            color: #94A3B8 !important;
        }
        /* Buttons */
        [data-testid="stFormSubmitButton"] > button,
        .stButton > button {
            background-color: #DC1E35 !important;
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
        }
        [data-testid="stFormSubmitButton"] > button:hover,
        .stButton > button:hover {
            background-color: #B01829 !important;
        }
        [data-testid="stFormSubmitButton"] > button p,
        .stButton > button p {
            color: white !important;
        }
        /* Divider inside card */
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) hr,
        [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2) hr {
            border-color: #E2E8F0 !important;
        }
        /* Expander (Team Access) inside card */
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) details,
        [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2) details {
            background: #F8FAFC !important;
            border: 1px solid #CBD5E1 !important;
            border-radius: 8px !important;
        }
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) details summary,
        [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:nth-child(2) details summary *,
        [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2) details summary,
        [data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(2) details summary * {
            color: #1A1A2E !important;
        }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        # Logo + header inside the card
        with open("assets/logo.png", "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()
        st.markdown(
            f'<div style="text-align:center; margin-bottom:0.5rem;">'
            f'<img src="data:image/png;base64,{logo_b64}" width="220">'
            f'</div>',
            unsafe_allow_html=True
        )
        st.markdown(
            '<h2 style="text-align:center; color:#1A1A2E; font-size:1.5rem; font-weight:700; margin:0.5rem 0 0.25rem;">Student Portal</h2>',
            unsafe_allow_html=True
        )
        st.markdown(
            '<p style="text-align:center; color:#94A3B8; font-size:0.82rem; margin-bottom:1.5rem; line-height:1.5;">Track your research program progress, deadlines, and submissions all in one place.</p>',
            unsafe_allow_html=True
        )

        if st.session_state.magic_link_sent:
            st.success("Check your email! We've sent you a magic link to access the portal.")
            st.info("The link will expire in 1 hour.")
            if st.button("Send another link"):
                st.session_state.magic_link_sent = False
                st.rerun()
        else:
            st.markdown(
                '<p style="font-size:0.75rem; font-weight:600; letter-spacing:0.08em; color:#64748B; margin-bottom:0.25rem; text-transform:uppercase;">EMAIL ADDRESS</p>',
                unsafe_allow_html=True
            )
            st.markdown(
                '<p style="font-size:0.8rem; color:#94A3B8; margin-bottom:0.5rem;">Enter the email address that you\'ve shared with our team.</p>',
                unsafe_allow_html=True
            )
            with st.form("login_form"):
                email = st.text_input("Email Address", label_visibility="collapsed", placeholder="your.email@example.com")
                submitted = st.form_submit_button("Send Magic Link", use_container_width=True)

                if submitted and email:
                    with st.spinner("Looking up your account — this may take a few seconds..."):
                        all_records = get_all_student_records_by_email(email)
                    accessible = filter_accessible_records(all_records)
                    if accessible:
                        if send_magic_link(email, accessible[0]["name"]):
                            st.session_state.magic_link_sent = True
                            st.rerun()
                    elif all_records:
                        st.error("This portal is not available for your program. Please contact your program manager.")
                    else:
                        st.error("Email not found. Please check your email address.")

        # Team preview access
        st.markdown("---")
        if st.session_state.team_unlocked:
            st.markdown("#### Admin Preview Mode")
            st.caption("Preview any student's portal view")
            with st.form("preview_form"):
                preview_email = st.text_input("Student's Email", placeholder="Enter student email to preview")
                preview_submitted = st.form_submit_button("Preview as Student", use_container_width=True)

                if preview_submitted and preview_email:
                    with st.spinner("Looking up student — this may take a few seconds..."):
                        all_records = get_all_student_records_by_email(preview_email)
                    accessible = filter_accessible_records(all_records)
                    if accessible:
                        st.session_state.authenticated = True
                        st.session_state.student_email = preview_email
                        st.session_state.is_preview = True
                        st.session_state.student_records = accessible
                        if len(accessible) == 1:
                            st.session_state.student_record = accessible[0]
                            st.session_state.student_name = accessible[0]["name"]
                            st.session_state.program_selected = True
                        else:
                            st.session_state.program_selected = False
                        st.rerun()
                    elif all_records:
                        st.error("Cannot preview: this student does not have access to the portal. They may not yet be confirmed and launched, or are enrolled in a White Label or Partner Payment Program.")
                    else:
                        st.error("Student email not found.")

        else:
            with st.expander("Team Access"):
                st.markdown(
                    '<p style="font-size:0.8rem; color:#64748B; margin-bottom:0.75rem;">For Lumiere team members only. Enter your admin key to preview the portal as any student.</p>',
                    unsafe_allow_html=True
                )
                with st.form("team_unlock_form"):
                    admin_key = st.text_input("Admin Key", type="password", placeholder="Enter admin key")
                    unlock_submitted = st.form_submit_button("Unlock", use_container_width=True)

                    if unlock_submitted:
                        if admin_key == get_secret("ADMIN_KEY"):
                            st.session_state.team_unlocked = True
                            st.rerun()
                        else:
                            st.error("Invalid admin key.")

# ──────────────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────────────

def show_dashboard():
    student = st.session_state.student_record
    display_name = student["name"].split("|")[0].strip() if student else ""

    # ── Sidebar ──
    with st.sidebar:
        st.image("assets/logo_symbol.png", width=80)
        st.markdown(f"### Welcome, {display_name}")
        st.markdown(f'<p style="color:#FFFFFF; font-size:0.85rem; margin-top:-0.75rem;">{st.session_state.student_email}</p>', unsafe_allow_html=True)

        if st.session_state.is_preview:
            st.warning("Preview Mode")

        st.markdown("---")

        nav_options = [
            "Your Profile",
            "Deadlines & Submissions",
        ]
        _pub_marker = student.get("publication_marker", [])
        _pub_foundation = student.get("pub_foundation_student", "")
        _pub_foundation_vals = _pub_foundation if isinstance(_pub_foundation, list) else [_pub_foundation]
        _has_pub_marker = "Yes" in ((_pub_marker if isinstance(_pub_marker, list) else [_pub_marker]))
        _has_pub_foundation = any(str(v).strip().startswith("Yes") for v in _pub_foundation_vals if v)
        if _has_pub_marker or _has_pub_foundation:
            nav_options.append("Publication Program")
        nav_options += ["Writing Center", "Resources"]

        view = st.radio(
            "Navigation",
            nav_options,
            label_visibility="collapsed"
        )

        st.markdown("---")

        if st.button("Refresh Data"):
            st.cache_data.clear()
            refreshed = get_student_by_email(st.session_state.student_email)
            if refreshed:
                st.session_state.student_record = refreshed
            st.rerun()

        if st.button("Logout"):
            if cookies.get("student_session"):
                cookies.remove("student_session")
            for key in ["authenticated", "student_name", "student_email", "student_record", "is_preview"]:
                st.session_state[key] = False if key == "authenticated" or key == "is_preview" else None
            st.session_state.student_records = []
            st.session_state.program_selected = False
            st.rerun()

    # ── Preview banner ──
    if st.session_state.is_preview:
        st.markdown(
            '<div class="preview-banner"><strong>Preview Mode:</strong> Viewing portal as '
            + student["name"].split("|")[0].strip() + '</div>',
            unsafe_allow_html=True
        )

    # ── Student name header ──
    name_parts = [p.strip() for p in student["name"].split("|")]
    header_name = name_parts[0]
    header_sub = " · ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    st.markdown(f"""
    <div style="margin-bottom:1.25rem; padding-bottom:0.75rem; border-bottom:1px solid #E2E8F0;">
        <div style="font-size:1.5rem; font-weight:700; color:#1E293B; line-height:1.2;">{header_name}</div>
        {"<div style='font-size:0.85rem; color:#94A3B8; margin-top:0.3rem;'>" + header_sub + "</div>" if header_sub else ""}
    </div>
    """, unsafe_allow_html=True)

    # ── Program status banner (shown on all pages) ──
    STATUS_BANNERS = [
        ("program paused", "#92400E", "#FFF7ED", "#FED7AA", "⏸️", "Your program is currently paused. If you have any questions or would like to resume, please reach out to your Program Manager."),
        ("completed", "#166534", "#F0FDF4", "#86EFAC", "🎉", "Woohoo! Congratulations on completing your program! We hope you had a fantastic experience with us."),
        ("withdrawn", "#64748B", "#F8FAFC", "#E2E8F0", "📋", "You have withdrawn from the program. If you'd like to discuss re-enrolling or have any questions, please reach out to your Program Manager."),
        ("suspended", "#DC2626", "#FEF2F2", "#FECACA", "⚠️", "Your program has been suspended. Please reach out to your Program Manager to discuss next steps."),
    ]
    program_status = (student.get("program_status") or "").strip().lower()
    matched_banner = next(((txt_color, bg, border_color, icon, msg) for key, txt_color, bg, border_color, icon, msg in STATUS_BANNERS if key in program_status), None)
    if matched_banner:
        txt_color, bg, border_color, icon, msg = matched_banner
        if "program paused" in program_status:
            raw_pause_end = student.get("program_pause_end_date") or ""
            pause_end_dates = raw_pause_end if isinstance(raw_pause_end, list) else [raw_pause_end]
            pause_end_dates = [d.strip() for d in pause_end_dates if d and str(d).strip()]
            if pause_end_dates:
                try:
                    from datetime import datetime
                    latest = max(pause_end_dates, key=lambda d: datetime.strptime(d, "%Y-%m-%d"))
                    pause_end_fmt = datetime.strptime(latest, "%Y-%m-%d").strftime("%B %-d, %Y")
                    msg += f" Your program is expected to resume on {pause_end_fmt}."
                except Exception:
                    pass
        st.markdown(
            f'<div style="background:{bg}; border:1px solid {border_color}; border-radius:10px; '
            f'padding:1rem 1.25rem; margin-bottom:1.25rem; display:flex; align-items:flex-start; gap:0.85rem;">'
            f'<span style="font-size:1.5rem; line-height:1;">{icon}</span>'
            f'<div><div style="font-size:1rem; font-weight:700; color:{txt_color}; margin-bottom:0.25rem;">Program Status Update</div>'
            f'<div style="font-size:0.92rem; color:{txt_color}; line-height:1.6;">{msg}</div></div>'
            f'</div>',
            unsafe_allow_html=True
        )

    # ── Route to view ──
    if view == "Your Profile":
        show_student_profile_summary(student)
    elif view == "Deadlines & Submissions":
        show_deadlines_and_submissions(student)
    elif view == "Publication Program":
        show_publication_program(student)
    elif view == "Writing Center":
        show_writing_center(student)
    elif view == "Resources":
        show_resources(student)

# ──────────────────────────────────────────────
# VIEW: Student Profile Summary
# ──────────────────────────────────────────────

def show_student_profile_summary(student):
    st.markdown("### Your Profile")
    st.markdown("""
    <div style="background:#F8F9FA; border-left:4px solid #BE1E2D; border-radius:6px;
                padding:0.85rem 1rem; margin-bottom:1.25rem; color:#475569; font-size:0.92rem; line-height:1.55;">
        This is your at-a-glance overview of your research program. Here you can see your assigned mentor,
        your revised final paper due date, how many mentor meetings you've completed, and the contact details
        for your <strong>Program Manager</strong>.<br><br>
        Your <strong>Program Manager</strong> is your go-to point of contact — reach out to them if you need
        help getting in touch with your mentor, want to flag a concern, or need support moving through any
        roadblocks in your program.
    </div>
    """, unsafe_allow_html=True)

    mentor_name = student.get("mentor") or "Not yet assigned"
    mentor_email = student.get("mentor_email") or ""
    mentor_email_html = f'<a href="mailto:{mentor_email}" style="font-size:0.88rem; color:#BE1E2D; text-decoration:none;">{mentor_email}</a>' if mentor_email else ""
    revised_due = student.get("revised_final_paper_due", "")
    completed = student.get("completed_meetings", 0) or 0
    expected = student.get("expected_meetings", 0) or 0
    pm_name = student.get("program_manager_name") or "Not assigned"
    pm_email = student.get("program_manager_email") or ""
    pm_facts = student.get("pm_facts") or ""

    pct = int(min(completed / expected, 1.0) * 100) if expected > 0 else 0
    progress_label = f"{completed} of {expected} meetings completed" if expected > 0 else "No meetings scheduled yet"
    pm_email_html = f'<a href="mailto:{pm_email}" style="font-size:0.88rem; color:#BE1E2D; text-decoration:none;">{pm_email}</a>' if pm_email else ""

    # Mentor card — understated
    st.markdown(f"""
    <div class="info-card" style="margin-bottom:1rem; display:flex; align-items:center; gap:1rem;">
        <div style="background:#F1F5F9; border-radius:50%; width:44px; height:44px; flex-shrink:0;
                    display:flex; align-items:center; justify-content:center;
                    font-size:1.2rem; color:#64748B;">👤</div>
        <div>
            <div style="font-size:0.85rem; font-weight:700; color:#1E293B; text-transform:uppercase;
                        letter-spacing:0.05em; margin-bottom:0.2rem;">Your Mentor</div>
            <div style="font-size:1.15rem; font-weight:700; color:#1E293B; margin-bottom:0.2rem;">{mentor_name}</div>
            {mentor_email_html}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Due date + Meetings progress side by side
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown(f"""
        <div class="info-card" style="height:100%;">
            <div style="font-size:0.85rem; font-weight:700; color:#1E293B; text-transform:uppercase;
                        letter-spacing:0.05em; margin-bottom:0.4rem;">Revised Final Paper Due</div>
            <div style="font-size:1.25rem; font-weight:700; color:#1E293B;">{format_date(revised_due)}</div>
        </div>
        """, unsafe_allow_html=True)

    with col_b:
        st.markdown(f"""
        <div class="info-card" style="height:100%;">
            <div style="font-size:0.85rem; font-weight:700; color:#1E293B; text-transform:uppercase;
                        letter-spacing:0.05em; margin-bottom:0.75rem;">Meetings Progress</div>
            <div style="background:#E2E8F0; border-radius:999px; height:8px; margin-bottom:0.55rem;">
                <div style="background:linear-gradient(90deg, #BE1E2D, #8B1520); width:{pct}%;
                            height:100%; border-radius:999px; transition:width 0.3s;"></div>
            </div>
            <div style="font-size:0.88rem; color:#475569; margin-bottom:0.75rem;">{progress_label}</div>
            <a href="https://airtable.com/appK9HemdsQBzVefU/shrMUNFRb6lEQwHfk" target="_blank"
               style="display:inline-flex; align-items:center; gap:0.35rem; font-size:0.82rem;
                      font-weight:600; color:#BE1E2D; text-decoration:none; background:#FFF5F5;
                      border:1px solid #FECACA; border-radius:6px; padding:0.35rem 0.7rem;">
                📝 Just had a meeting? Fill out this form!
            </a>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='margin-top:0.75rem;'></div>", unsafe_allow_html=True)

    # Program Manager — clean up pm_facts (may arrive as list or raw string with \n)
    raw_facts = pm_facts
    if isinstance(raw_facts, list):
        raw_facts = " ".join(raw_facts)
    raw_facts = raw_facts.replace("\\n", "\n").strip()
    facts_paragraphs = [p.strip() for p in raw_facts.split("\n") if p.strip()]
    if facts_paragraphs:
        paras_html = "".join(f'<p style="margin:0 0 0.45rem 0;">{p}</p>' for p in facts_paragraphs)
        pm_facts_html = '<div style="margin-top:0.85rem; border-top:1px solid #F1F5F9; padding-top:0.75rem;"><div style="font-size:0.85rem; font-weight:700; color:#1E293B; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.4rem;">Fun facts about your Program Manager</div><div style="font-size:0.88rem; color:#475569; line-height:1.6;">' + paras_html + '</div></div>'
    else:
        pm_facts_html = ""
    st.markdown(f"""
<div class="info-card">
<div style="font-size:0.85rem; font-weight:700; color:#1E293B; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.5rem;">Program Manager</div>
<div style="font-size:1rem; font-weight:600; color:#1E293B; margin-bottom:0.25rem;">{pm_name}</div>
{pm_email_html}
<div style="font-size:0.8rem; color:#94A3B8; margin-top:0.4rem; line-height:1.4;">Your main point of contact for program support and escalations.</div>
{pm_facts_html}
</div>
""", unsafe_allow_html=True)

    # Syllabus
    all_deadlines = get_deadlines_for_student(student["name"])
    syllabus_dl = next((d for d in all_deadlines if d.get("type") == "Syllabus"), None)
    syllabus_attachment = None
    if syllabus_dl:
        raw = syllabus_dl.get("submissions", {}).get("Syllabus Submission (From Mentor)")
        if isinstance(raw, list) and raw:
            syllabus_attachment = raw[0]
        elif isinstance(raw, str) and raw.startswith("http"):
            syllabus_attachment = {"url": raw, "filename": "Syllabus"}

    if syllabus_attachment:
        url = syllabus_attachment.get("url", "")
        filename = syllabus_attachment.get("filename", "Syllabus")
        st.markdown("<div style='margin-top:0.75rem;'></div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div class="info-card">
            <div style="font-size:0.85rem; font-weight:700; color:#1E293B; text-transform:uppercase;
                        letter-spacing:0.05em; margin-bottom:0.5rem;">Program Syllabus</div>
            <div style="font-size:0.92rem; color:#475569; line-height:1.55; margin-bottom:0.75rem;">
                Here is the syllabus shared by your mentor — it outlines what you can expect
                during your program, including key milestones, meeting expectations, and deliverables.
            </div>
            <a href="{url}" target="_blank"
               style="display:inline-flex; align-items:center; gap:0.4rem; background:#F8F9FA;
                      border:1px solid #E2E8F0; border-radius:6px; padding:0.45rem 0.85rem;
                      font-size:0.88rem; font-weight:600; color:#BE1E2D; text-decoration:none;">
                📄 {filename}
            </a>
        </div>
        """, unsafe_allow_html=True)

# ──────────────────────────────────────────────
# VIEW: Deadlines & Submissions
# ──────────────────────────────────────────────

@st.dialog("📋 Your Deadlines at a Glance")
def show_deadlines_popup(overdue, upcoming):
    if overdue:
        st.markdown("#### ⚠️ Overdue")
        for d in overdue:
            st.markdown(f"""
            <div style="background:rgba(239,68,68,0.08); border:1px solid #EF4444;
                        border-radius:8px; padding:0.6rem 0.9rem; margin-bottom:0.5rem;">
                <div style="font-weight:600; color:#DC2626;">{d['type']}</div>
                <div style="font-size:0.85rem; color:#475569;">Was due {format_date(d['due_date'])}</div>
            </div>
            """, unsafe_allow_html=True)

    if upcoming:
        st.markdown("#### ⏰ Coming Up")
        for d in upcoming[:3]:
            days_left = (datetime.strptime(d["due_date"], "%Y-%m-%d") - datetime.now()).days
            st.markdown(f"""
            <div style="background:rgba(190,30,45,0.06); border:1px solid #BE1E2D;
                        border-radius:8px; padding:0.6rem 0.9rem; margin-bottom:0.5rem;">
                <div style="font-weight:600; color:#1E293B;">{d['type']}</div>
                <div style="font-size:0.85rem; color:#475569;">
                    Due {format_date(d['due_date'])} —
                    <strong>{days_left} day{"s" if days_left != 1 else ""} away</strong>
                </div>
            </div>
            """, unsafe_allow_html=True)

    if st.button("Got it", use_container_width=True, type="primary"):
        st.rerun()

def show_deadlines_and_submissions(student):
    st.markdown("### Deadlines & Submissions")
    st.markdown("""
    <div style="background:#F8F9FA; border-left:4px solid #BE1E2D; border-radius:6px;
                padding:0.85rem 1rem; margin-bottom:1.25rem; color:#475569; font-size:0.92rem; line-height:1.55;">
        This page tracks all of your program deadlines and submission statuses in one place.
        Use it to stay on top of what's coming up, what you've already submitted, and anything
        that may be overdue. <strong>Make sure to submit each deliverable on time</strong> — your
        Program Manager can help if you're unsure what's expected for a given deadline.
    </div>
    """, unsafe_allow_html=True)

    submission_portal = student.get("submission_portal") or ""
    if submission_portal:
        st.markdown(f"""
        <div class="info-card" style="display:flex; align-items:center; justify-content:space-between;
                                      flex-wrap:wrap; gap:0.75rem; margin-bottom:0.5rem;">
            <div>
                <div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase;
                            letter-spacing:0.05em; margin-bottom:0.3rem;">Submission Portal</div>
                <div style="font-size:0.9rem; color:#475569;">
                    Use this form to submit your deliverables for each deadline.
                </div>
            </div>
            <a href="{submission_portal}" target="_blank"
               style="display:inline-flex; align-items:center; gap:0.4rem;
                      background:#BE1E2D; color:white; text-decoration:none;
                      padding:0.5rem 1.1rem; border-radius:7px; font-size:0.88rem;
                      font-weight:600; white-space:nowrap;">
                Submit Here →
            </a>
        </div>
        """, unsafe_allow_html=True)

    EXCLUDED_TYPES = {"Syllabus", "Evaluation & Feedback"}
    all_deadlines = get_deadlines_for_student(student["name"])
    deadlines = [d for d in all_deadlines if d.get("type") not in EXCLUDED_TYPES]

    if not deadlines:
        st.info("No deadlines found for your program yet.")
        return

    # ── Auto-open popup once per page visit ──
    popup_key = f"deadlines_popup_shown_{student['name']}"
    if not st.session_state.get(popup_key):
        st.session_state[popup_key] = True
        now = datetime.now()
        actionable = [d for d in deadlines if d["status"] not in ("Submitted", "Deadline Waived") and d["due_date"]]
        overdue_items = [d for d in actionable if datetime.strptime(d["due_date"], "%Y-%m-%d") < now]
        upcoming_items = sorted(
            [d for d in actionable if datetime.strptime(d["due_date"], "%Y-%m-%d") >= now],
            key=lambda x: x["due_date"]
        )
        if overdue_items or upcoming_items:
            show_deadlines_popup(overdue_items, upcoming_items)

    # ── Summary bar ──
    total = len(deadlines)
    submitted_count = sum(1 for d in deadlines if d["status"] == "Submitted")
    waived_count = sum(1 for d in deadlines if d["status"] == "Deadline Waived")
    overdue_count = sum(1 for d in deadlines if is_overdue(d["due_date"], d["status"]))
    pending_count = total - submitted_count - waived_count - overdue_count

    summary_dots = [
        ("#16A34A", f"{submitted_count} Submitted"),
        ("#F59E0B", f"{pending_count} Pending"),
        ("#EF4444", f"{overdue_count} Overdue"),
    ]
    if waived_count:
        summary_dots.append(("#6366F1", f"{waived_count} Waived"))
    dots_html = "".join(
        f'<div style="display:flex; align-items:center; gap:0.4rem;">'
        f'<span style="width:10px; height:10px; border-radius:50%; background:{color}; display:inline-block;"></span>'
        f'<span style="font-size:0.9rem; color:#475569;">{label}</span>'
        f'</div>'
        for color, label in summary_dots
    )
    st.markdown(
        f'<div style="display:flex; gap:1.5rem; margin-bottom:1.25rem; flex-wrap:wrap;">{dots_html}</div>',
        unsafe_allow_html=True,
    )

    # ── Overdue + Next Deadline banners (exclude waived) ──
    try:
        now = datetime.now()
        actionable_dl = [d for d in deadlines if d["status"] not in ("Submitted", "Deadline Waived") and d["due_date"]]
        overdue_dl = [d for d in actionable_dl if datetime.strptime(d["due_date"], "%Y-%m-%d") < now]
        future_dl = [d for d in actionable_dl if datetime.strptime(d["due_date"], "%Y-%m-%d") >= now]

        if overdue_dl:
            overdue_list = ", ".join(
                f"{d['type']} ({format_date(d['due_date'])})" for d in overdue_dl
            )
            st.markdown(
                f'<div style="background:rgba(239,68,68,0.1); border:1px solid #EF4444; '
                f'border-radius:10px; padding:1rem; margin-bottom:0.75rem;">'
                f'<strong>⚠️ Overdue:</strong> {overdue_list}'
                f'</div>',
                unsafe_allow_html=True,
            )

        if future_dl:
            next_dl = future_dl[0]
            days_left = (datetime.strptime(next_dl["due_date"], "%Y-%m-%d") - now).days
            st.markdown(
                f'<div style="background:rgba(220,30,53,0.1); border:1px solid #DC1E35; '
                f'border-radius:10px; padding:1rem; margin-bottom:1rem;">'
                f'<strong>⏰ Next Deadline:</strong> {next_dl["type"]} — '
                f'due {format_date(next_dl["due_date"])} ({days_left} day{"s" if days_left != 1 else ""} away)'
                f'</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        pass

    # ── Split into active (pending/overdue/waived) and submitted groups ──
    active_deadlines = [d for d in deadlines if d["status"] not in ("Submitted", "Deadline Waived")]
    waived_deadlines = [d for d in deadlines if d["status"] == "Deadline Waived"]
    submitted_deadlines = [d for d in deadlines if d["status"] == "Submitted"]

    def _render_deadline_row(dl):
        dtype = dl["type"] or "Deadline"
        status = dl["status"]
        overdue = is_overdue(dl["due_date"], status)
        is_waived = status == "Deadline Waived"

        if status == "Submitted":
            icon = "✅"
        elif is_waived:
            icon = "〇"
        elif overdue:
            icon = "⚠️"
        else:
            icon = "📅"

        with st.container():
            guidebook_links = get_guidebook_links(dtype) if not is_waived else []
            col1, col2, col3 = st.columns([2, 1, 1])

            with col1:
                if guidebook_links:
                    helper_text = get_guidebook_helper(dtype)
                    links_html = " &nbsp;·&nbsp; ".join(
                        f'<a href="{url}" target="_blank" style="color:#BE1E2D; font-weight:600; text-decoration:none; white-space:nowrap;">{title} →</a>'
                        for title, url in guidebook_links
                    )
                    st.markdown(
                        f"{icon} **{dtype}**"
                        f'<div style="margin-top:0.45rem; background:#FFF5F5; border:1px solid #FECACA;'
                        f'border-radius:8px; padding:0.45rem 0.7rem; display:inline-block; max-width:100%;">'
                        f'<span style="font-size:0.78rem; color:#64748B;">📖 {helper_text} &nbsp;</span>'
                        f'{links_html}'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(f"{icon} **{dtype}**")

            with col2:
                if is_waived:
                    st.markdown("**Due:** —")
                else:
                    st.markdown(f"**Due:** {format_date(dl['due_date'])}")

            with col3:
                if status == "Submitted":
                    st.success(f"Submitted {format_datetime_ist(dl['date_submitted'])}" if dl["date_submitted"] else "Submitted")
                elif is_waived:
                    st.markdown(
                        '<span style="display:inline-block; background:#EEF2FF; color:#4F46E5; '
                        'padding:0.25rem 0.75rem; border-radius:20px; font-size:0.85rem; font-weight:500;">'
                        'Deadline Waived</span>',
                        unsafe_allow_html=True,
                    )
                elif overdue:
                    st.error("Overdue")
                else:
                    st.warning("Not Submitted")

            if dl.get("submissions"):
                for field_name, value in dl["submissions"].items():
                    _render_submission_value(value, label="Your submission")

    # Render active (pending + overdue) deadlines
    for dl in active_deadlines + waived_deadlines:
        _render_deadline_row(dl)
        st.markdown("---")

    # Render submitted deadlines in a clearly separated section
    if submitted_deadlines:
        st.markdown(
            '<div style="margin-top:2.5rem; margin-bottom:1.25rem; padding-top:1.5rem; border-top:2px solid #E2E8F0;">'
            '<span style="font-size:1rem; font-weight:600; color:#64748B;">Submitted Deliverables</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        for dl in submitted_deadlines:
            _render_deadline_row(dl)
            st.markdown("---")


def _render_submission_value(value, label=None):
    """Render a submission value — attachment list, URL, or plain text."""
    label_html = f'<span style="font-size:0.78rem; font-weight:600; color:#94A3B8; text-transform:uppercase; letter-spacing:0.05em; display:block; margin-bottom:0.4rem;">{label}</span>' if label else ""

    def bubble(content_html):
        return (
            f'<div style="display:inline-flex; align-items:center; gap:0.5rem; '
            f'background:#F1F5F9; border:1px solid #E2E8F0; border-radius:999px; '
            f'padding:0.4rem 0.9rem; font-size:0.88rem; color:#1E293B; margin-top:0.25rem;">'
            f'📄 {content_html}'
            f'</div>'
        )

    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                url = item.get("url", "")
                filename = item.get("filename", "Download")
                if url:
                    content = f'<a href="{url}" target="_blank" style="color:#BE1E2D; font-weight:600; text-decoration:none;">{filename}</a>'
                    st.markdown(f'{label_html}{bubble(content)}', unsafe_allow_html=True)
                    label_html = ""
            else:
                st.markdown(f'{label_html}{bubble(str(item))}', unsafe_allow_html=True)
                label_html = ""
    elif isinstance(value, str):
        if value.startswith("http"):
            content = f'<a href="{value}" target="_blank" style="color:#BE1E2D; font-weight:600; text-decoration:none;">View Submission</a>'
        else:
            content = value
        st.markdown(f'{label_html}{bubble(content)}', unsafe_allow_html=True)
    else:
        st.markdown(f'{label_html}{bubble(str(value))}', unsafe_allow_html=True)

# ──────────────────────────────────────────────
# VIEW: My Profile
# ──────────────────────────────────────────────

def show_profile(student):
    st.markdown("### My Profile")

    # Metric cards row
    c1, c2, c3 = st.columns(3)

    with c1:
        city = student.get("city") or "Not specified"
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">City of Residence</div>
            <div class="metric-value">{city}</div>
        </div>""", unsafe_allow_html=True)

    with c2:
        grad = student.get("graduation_year") or "Not specified"
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Graduation Year</div>
            <div class="metric-value">{grad}</div>
        </div>""", unsafe_allow_html=True)

    with c3:
        area = student.get("research_area") or "Not specified"
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Research Area</div>
            <div class="metric-value" style="font-size:1.1rem;">{area}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("")
    st.markdown("---")

    left, right = st.columns(2)

    with left:
        st.markdown("**Foundation Student**")
        st.markdown(student.get("foundation_student") or "—")

        st.markdown("**Program Manager Email**")
        st.markdown(student.get("program_manager_email") or "Not specified")

        st.markdown("**Revised Final Paper Due Date**")
        st.markdown(format_date(student.get("revised_final_paper_due", "")))

    with right:
        st.markdown("**Tuition Status**")
        tuition = student.get("tuition_paid") or "—"
        if tuition == "Yes":
            st.markdown(":green[Paid]")
        else:
            st.markdown(f":orange[{tuition}]" if tuition != "—" else tuition)

        st.markdown("**Reason for Interest**")
        st.markdown(student.get("reason_for_interest") or "Not specified")

# ──────────────────────────────────────────────
# VIEW: My Mentor
# ──────────────────────────────────────────────

def show_mentor_info(student):
    st.markdown("### My Mentor")

    mentor_name = student.get("mentor", "")

    # Mentor banner card
    st.markdown(f"""
    <div style="background:linear-gradient(135deg, #BE1E2D 0%, #8B1520 100%);
                border-radius:12px; padding:2rem; color:white; margin-bottom:1.5rem;">
        <div style="font-size:0.85rem; opacity:0.9;">Your Mentor</div>
        <div style="font-size:1.8rem; font-weight:700; margin-top:0.25rem;">
            {mentor_name or 'Not yet assigned'}
        </div>
    </div>
    """, unsafe_allow_html=True)

    left, right = st.columns(2)

    with left:
        st.markdown("**Mentor Confirmation**")
        confirmation = student.get("mentor_confirmation") or "—"
        if confirmation == "Yes":
            st.markdown(":green[Confirmed]")
        else:
            st.markdown(f":orange[{confirmation}]" if confirmation != "—" else confirmation)

        st.markdown("**Background Shared**")
        shared = student.get("background_shared") or "—"
        if shared == "Yes":
            st.markdown(":green[Shared]")
        else:
            st.markdown(f":orange[{shared}]" if shared != "—" else shared)

    with right:
        st.markdown("**Meetings Progress**")
        completed = student.get("completed_meetings", 0) or 0
        expected = student.get("expected_meetings", 0) or 0
        if expected > 0:
            progress = min(completed / expected, 1.0)
            st.progress(progress)
            st.caption(f"{completed} of {expected} meetings completed")
        else:
            st.markdown("No meetings scheduled yet")

        st.markdown("**Hours Recorded**")
        st.markdown(format_duration(student.get("hours_recorded", "")))

    st.markdown("---")

    c3, c4 = st.columns(2)

    with c3:
        st.markdown("**Student No-Shows**")
        no_shows = student.get("student_no_shows", 0) or 0
        try:
            ns = int(no_shows)
        except (ValueError, TypeError):
            ns = 0
        if ns > 0:
            st.markdown(f":red[{ns}]")
        else:
            st.markdown(f":green[{ns}]")

    with c4:
        st.markdown("**Meeting Updates Submitted**")
        st.markdown(str(student.get("completed_meetings", 0) or 0))

    # Notes summary
    if student.get("notes_summary"):
        st.markdown("---")
        st.markdown("**Mentor-Student Notes Summary**")
        st.markdown(format_notes_summary(student["notes_summary"]))

# ──────────────────────────────────────────────
# VIEW: Publication Program
# ──────────────────────────────────────────────

def show_publication_program(student):
    st.markdown("### Publication Program")
    st.markdown("""
    <div style="background:#F8F9FA; border-left:4px solid #BE1E2D; border-radius:6px;
                padding:0.85rem 1rem; margin-bottom:1.25rem; color:#475569; font-size:0.92rem; line-height:1.55;">
        This page shows your publication journey. Your <strong>Publication Specialist</strong> will guide
        you through the journal submission process — from selecting a target publication to navigating
        reviewer feedback. Reach out to them directly with any questions about where or how to submit
        your paper.
    </div>
    """, unsafe_allow_html=True)

    specialist = student.get("publication_specialist") or "Not yet assigned"
    specialist_email = student.get("publication_specialist_email") or ""
    target = student.get("publication_target") or ""
    outcome = student.get("publication_outcome") or ""

    OUTCOME_MESSAGES = {
        "accepted": ("Your paper has been accepted for publication, congratulations! Please remember to share the link to your final published paper with your publication specialist.", "#16A34A", "#F0FDF4"),
        "did not submit rfp": ("Your final paper has not been submitted yet. Your publication specialist will guide you through submission to your target journal once your final paper is complete.", "#64748B", "#F8FAFC"),
        "rejected": ("Your paper was not accepted to your first choice of journal. Please make sure you are in touch with your publications specialist to plan your next submission.", "#D97706", "#FFFBEB"),
        "resubmitted": ("You have resubmitted your revised paper to your target journal - well done! Now you need to wait for the journal's final decision. Please don't forget to inform your publication specialist when the journal gets back to you!", "#2563EB", "#EFF6FF"),
        "revise and resubmit": ("Your target journal has requested that you make some edits to your paper and then resubmit it. This is a really positive sign that the journal is interested in publishing your work! Please make sure you are in touch with your publication specialist about how to tackle these revisions.", "#2563EB", "#EFF6FF"),
        "student suspended": ("We have suspended your publication support due to lack of response. Please reach out to your publication specialist if you would like to reinstate publication support.", "#DC2626", "#FEF2F2"),
        "student withdrew": ("You have decided not to pursue publication at this time. If you change your mind and would like to resume working actively towards publication please reach out to your publication specialist.", "#64748B", "#F8FAFC"),
        "submitted rfp, unsubmitted to pub": ("Congratulations on submitting your revised final paper! Your next step is to submit your work to your target journal. Please make sure you are in touch with your publication specialist as they will help you coordinate this submission.", "#16A34A", "#F0FDF4"),
        "submitted to pub": ("Your paper has been submitted to your target journal, well done! You now need to wait for the journal to get back to you with feedback. Please remember to update your publication specialist as soon as you receive an update!", "#16A34A", "#F0FDF4"),
    }
    outcome_key = outcome.strip().lower()
    outcome_message, outcome_color, outcome_bg = OUTCOME_MESSAGES.get(outcome_key, ("", "#64748B", "#F8FAFC"))
    submission_workshop = student.get("target_submission_workshop") or ""
    intro_workshop = student.get("target_intro_workshop") or ""
    one_pager = student.get("target_one_pager") or ""
    quiz_1 = student.get("quiz_1_status") or ""
    quiz_2 = student.get("quiz_2_status") or ""
    quiz_3 = student.get("quiz_3_status") or ""


    # Publication Specialist card
    specialist_email_line = f'<a href="mailto:{specialist_email}" style="font-size:0.88rem; color:#BE1E2D; text-decoration:none;">{specialist_email}</a>' if specialist_email else ""
    st.markdown(
        f'<div class="info-card" style="margin-bottom:1rem; display:flex; align-items:center; gap:1rem;">'
        f'<div style="background:#F1F5F9; border-radius:50%; width:44px; height:44px; flex-shrink:0; display:flex; align-items:center; justify-content:center; font-size:1.2rem; color:#64748B;">👤</div>'
        f'<div><div style="font-size:0.72rem; font-weight:700; color:#1E293B; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.2rem;">Your Publication Specialist</div>'
        f'<div style="font-size:1.15rem; font-weight:700; color:#1E293B; margin-bottom:0.2rem;">{specialist}</div>'
        f'{specialist_email_line}'
        f'<div style="font-size:0.8rem; color:#94A3B8; margin-top:0.4rem;">Your go-to contact for all things publication — reach out with any questions about journal selection, submission, or reviewer feedback.</div>'
        f'</div></div>',
        unsafe_allow_html=True
    )

    col_a, col_b = st.columns(2)

    with col_a:
        if target:
            st.markdown(f'<div class="info-card" style="height:100%;"><div style="font-size:0.72rem; font-weight:700; color:#1E293B; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.4rem;">Publication Target</div><div style="font-size:1.1rem; font-weight:700; color:#1E293B; margin-bottom:0.3rem;">{target}</div><div style="font-size:0.8rem; color:#94A3B8;">The journal or outlet you are aiming to publish your research in.</div></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="info-card" style="height:100%;"><div style="font-size:0.72rem; font-weight:700; color:#1E293B; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.4rem;">Publication Target</div><div style="font-size:0.88rem; color:#94A3B8; line-height:1.55;">No target selected yet — please reach out to your Publication Specialist if you need help selecting your target journal.</div></div>', unsafe_allow_html=True)

    with col_b:
        if outcome_message:
            st.markdown(
                f'<div class="info-card" style="height:100%; background:{outcome_bg}; border-left:3px solid {outcome_color};">'
                f'<div style="font-size:0.72rem; font-weight:700; color:#1E293B; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.4rem;">Latest Publication Outcome</div>'
                f'<div style="font-size:0.88rem; color:#1E293B; line-height:1.55;">{outcome_message}</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(f"""
            <div class="info-card" style="height:100%;">
                <div style="font-size:0.72rem; font-weight:700; color:#1E293B; text-transform:uppercase;
                            letter-spacing:0.05em; margin-bottom:0.4rem;">Latest Publication Outcome</div>
                <div style="font-size:0.88rem; color:#94A3B8;">No update yet — check back later.</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<div style='margin-top:0.75rem;'></div>", unsafe_allow_html=True)

    # Workshop 1 — always visible
    WORKSHOP_1_URL = "https://us06web.zoom.us/rec/share/oDDE86O8mqbRv2N9FNms5ATIlxzqF-3zl3EyZkno5M-duawenv6E-yBQ6RwVWNZz.jolPyUGFJtbRvbC0"
    st.markdown(
        f'<div class="info-card" style="margin-bottom:1rem;">'
        f'<div style="font-size:0.72rem; font-weight:700; color:#1E293B; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.3rem;">Introduction to Publication</div>'
        f'<div style="font-size:0.8rem; color:#94A3B8; margin-bottom:0.65rem;">Start here — this workshop introduces you to the publication process and what to expect as you work towards submitting your research.</div>'
        f'<a href="{WORKSHOP_1_URL}" target="_blank" style="display:inline-flex; align-items:center; gap:0.4rem; background:#F8F9FA; border:1px solid #E2E8F0; border-radius:6px; padding:0.45rem 0.85rem; font-size:0.88rem; font-weight:600; color:#BE1E2D; text-decoration:none;">🔗 Publication Workshop 1 - Introduction to Publication</a>'
        f'</div>',
        unsafe_allow_html=True
    )

    # Target resources — only show if at least one target-specific resource is set
    target_resource_links = [
        ("Publication Workshop 2 - Introduction to Journal Target", intro_workshop),
        ("Publication Workshop 3 - Journal Submission Prep", submission_workshop),
        ("Target One-Pager", one_pager),
    ]
    target_available = [(label, url) for label, url in target_resource_links if url]
    if target_available:
        links_html = "".join([
            f'<a href="{url}" target="_blank" '
            f'style="display:inline-flex; align-items:center; gap:0.4rem; background:#F8F9FA; '
            f'border:1px solid #E2E8F0; border-radius:6px; padding:0.45rem 0.85rem; '
            f'font-size:0.88rem; font-weight:600; color:#BE1E2D; text-decoration:none; margin-right:0.5rem; margin-bottom:0.5rem;">🔗 {label}</a>'
            for label, url in target_available
        ])
        st.markdown(f'<div class="info-card" style="margin-bottom:1rem;"><div style="font-size:0.72rem; font-weight:700; color:#1E293B; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.3rem;">Target Resources</div><div style="font-size:0.8rem; color:#94A3B8; margin-bottom:0.65rem;">Workshops and materials curated specifically for your target publication.</div><div style="display:flex; flex-wrap:wrap;">{links_html}</div></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="info-card" style="margin-bottom:1rem;"><div style="font-size:0.72rem; font-weight:700; color:#1E293B; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.3rem;">Target Resources</div><div style="font-size:0.88rem; color:#94A3B8; line-height:1.55;">Your target-specific resources will appear here once you finalize your target journal.</div></div>', unsafe_allow_html=True)

    quizzes_incomplete = not (quiz_1 and quiz_2 and quiz_3)
    quiz_chips = "".join([
        f'<div style="display:flex; align-items:center; gap:0.5rem; background:{"#F0FDF4" if v else "#F8FAFC"}; '
        f'border:1px solid {"#86EFAC" if v else "#E2E8F0"}; border-radius:8px; padding:0.5rem 0.85rem;">'
        f'<div style="width:1.25rem; height:1.25rem; border-radius:50%; background:{"#16A34A" if v else "#CBD5E1"}; '
        f'color:white; font-size:0.75rem; font-weight:700; display:flex; align-items:center; justify-content:center;">{"✓" if v else "–"}</div>'
        f'<div><div style="font-size:0.82rem; font-weight:600; color:#1E293B;">{label}</div>'
        f'<div style="font-size:0.75rem; color:{"#16A34A" if v else "#94A3B8"};">{"Submitted" if v else "Not submitted"}</div></div>'
        f'</div>'
        for label, v in [("Quiz 1", quiz_1), ("Quiz 2", quiz_2), ("Quiz 3", quiz_3)]
    ])
    if quizzes_incomplete:
        col_quiz, col_bubble = st.columns([3, 2])
    else:
        col_quiz = st.columns(1)[0]
        col_bubble = None
    with col_quiz:
        st.markdown(f'<div class="info-card"><div style="font-size:0.72rem; font-weight:700; color:#1E293B; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.3rem;">Quiz Checkpoints</div><div style="font-size:0.8rem; color:#94A3B8; margin-bottom:0.85rem;">Track your progress through the publication program quizzes.</div><div style="display:flex; gap:0.75rem; flex-wrap:wrap;">{quiz_chips}</div></div>', unsafe_allow_html=True)
    if col_bubble:
        with col_bubble:
            st.markdown('<div class="info-card" style="background:#FFF7ED; border:1px solid #FED7AA; height:100%;"><div style="font-size:0.85rem; color:#92400E; margin-bottom:0.5rem;">Haven\'t completed your quizzes yet? Here\'s the link!</div><a href="https://airtable.com/shrgP2sLhOCV40Ok9" target="_blank" style="display:inline-flex; align-items:center; gap:0.35rem; background:#BE1E2D; color:white; text-decoration:none; padding:0.4rem 0.85rem; border-radius:6px; font-size:0.82rem; font-weight:600; white-space:nowrap;">Take the Quizzes →</a></div>', unsafe_allow_html=True)

# ──────────────────────────────────────────────
# VIEW: Writing Center
# ──────────────────────────────────────────────

def show_writing_center(student):
    st.markdown("### Writing Center")
    st.markdown("""
    <div style="background:#F8F9FA; border-left:4px solid #BE1E2D; border-radius:6px;
                padding:0.85rem 1rem; margin-bottom:1.25rem; color:#475569; font-size:0.92rem; line-height:1.55;">
        This is your hub for writing support throughout the program. Use the portal link below to
        <strong>book a session or request written feedback</strong> from your Writing Coach — they can
        help with structure, argumentation, citations, and polishing your paper.
    </div>
    """, unsafe_allow_html=True)

    # Writing Coach card
    wc_name = student.get("writing_coach_name") or "Not assigned"
    wc_emails = student.get("writing_coach_email") or []
    wc_email_html = " &nbsp;·&nbsp; ".join(
        f'<a href="mailto:{e}" style="font-size:0.88rem; color:#BE1E2D; text-decoration:none;">{e}</a>'
        for e in wc_emails
    ) if wc_emails else ""
    st.markdown(
        f'<div class="info-card" style="margin-bottom:1rem; display:flex; align-items:center; gap:1rem;">'
        f'<div style="background:#F1F5F9; border-radius:50%; width:44px; height:44px; flex-shrink:0; display:flex; align-items:center; justify-content:center; font-size:1.2rem; color:#64748B;">✍️</div>'
        f'<div><div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.2rem;">Your Writing Coach</div>'
        f'<div style="font-size:1.15rem; font-weight:700; color:#1E293B; margin-bottom:0.2rem;">{wc_name}</div>'
        f'{wc_email_html}'
        f'<div style="font-size:0.8rem; color:#94A3B8; margin-top:0.4rem;">Reach out to book a session or request written feedback on structure, argumentation, citations, and more.</div>'
        f'</div></div>',
        unsafe_allow_html=True
    )

    # Writing Center Portal link
    writing_center_url = get_secret("WRITING_CENTER_URL", "")
    if writing_center_url:
        st.markdown(
            f'<div class="info-card" style="margin-bottom:1rem;">'
            f'<div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.3rem;">Writing Center Portal</div>'
            f'<div style="font-size:0.88rem; color:#475569; margin-bottom:0.6rem;">Book a meeting or request written feedback from your writing coach.</div>'
            f'<a href="{writing_center_url}" target="_blank" style="display:inline-flex; align-items:center; gap:0.4rem; background:#F8F9FA; border:1px solid #E2E8F0; border-radius:6px; padding:0.4rem 0.8rem; font-size:0.85rem; font-weight:600; color:#BE1E2D; text-decoration:none;">🔗 Open Portal</a>'
            f'</div>',
            unsafe_allow_html=True
        )

    # ── Writing Center Requests history ──
    student_email = student.get("email", "")
    st.markdown('<div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase; letter-spacing:0.05em; margin:1.25rem 0 0.5rem;">Your Writing Center Requests</div>', unsafe_allow_html=True)
    if student_email:
        wc_requests = fetch_wc_requests(student_email)
        if not wc_requests:
            st.markdown('<div style="font-size:0.88rem; color:#94A3B8; margin-bottom:1rem;">No writing center requests found for your account.</div>', unsafe_allow_html=True)
        else:
            rows_html = ""
            for rec in wc_requests:
                f = rec.get("fields", {})
                req_type = f.get("Writing Center Request Type") or "—"
                created_raw = f.get("Created Time", "")
                responded = f.get("Responded by Writing Coach", "")
                response_dates = f.get("Response Recorded [Created Time] (from Writing Centre Responses & Recording)")
                # Lookup field returns array-of-arrays — flatten to get attachment objects
                raw_attachments = f.get("Written Feedback Upload (from Writing Centre Responses & Recording)") or []
                attachments = []
                for item in raw_attachments:
                    if isinstance(item, list):
                        attachments.extend(item)
                    elif isinstance(item, dict):
                        attachments.append(item)

                # Format request date
                try:
                    dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                    day = dt.day
                    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
                    created_str = f"{dt.strftime('%B')} {day}{suffix}, {dt.year}"
                except Exception:
                    created_str = created_raw or "—"

                # Format response date
                response_date_str = "—"
                if isinstance(response_dates, list) and response_dates:
                    try:
                        rd = datetime.fromisoformat(str(response_dates[0]).replace("Z", "+00:00"))
                        day = rd.day
                        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
                        response_date_str = f"{rd.strftime('%B')} {day}{suffix}, {rd.year}"
                    except Exception:
                        response_date_str = str(response_dates[0])

                is_responded = str(responded).strip() == "Responded"
                if is_responded:
                    badge = '<span style="display:inline-block;background:#DCFCE7;color:#15803D;font-size:0.7rem;font-weight:700;padding:0.15rem 0.55rem;border-radius:999px;">Responded</span>'
                    note = '<div style="font-size:0.75rem;color:#64748B;margin-top:0.2rem;">Your writing coach has responded — please check your email.</div>'
                    resp_date_html = f'<span style="font-size:0.8rem;color:#64748B;">{response_date_str}</span>'
                else:
                    badge = '<span style="display:inline-block;background:#FEF3C7;color:#92400E;font-size:0.7rem;font-weight:700;padding:0.15rem 0.55rem;border-radius:999px;">Pending</span>'
                    note = ""
                    resp_date_html = '<span style="font-size:0.8rem;color:#CBD5E1;">—</span>'

                # Build inline viewer — only for Written Feedback requests with attachments
                viewer_html = ""
                is_written_feedback = "written feedback" in req_type.lower()
                if is_written_feedback and attachments and is_responded:
                    for a in attachments:
                        url = a.get("url", "")
                        filename = a.get("filename", "Attachment")
                        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                        if ext == "pdf":
                            viewer_html += (
                                f'<details style="margin-top:0.65rem;">'
                                f'<summary style="cursor:pointer;display:inline-flex;align-items:center;gap:0.35rem;'
                                f'font-size:0.75rem;font-weight:600;color:#BE1E2D;background:#FFF5F5;'
                                f'border:1px solid #FECACA;border-radius:5px;padding:0.2rem 0.6rem;list-style:none;">📄 View Feedback</summary>'
                                f'<div style="margin-top:0.5rem;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;">'
                                f'<iframe src="{url}" width="100%" height="620" style="border:none;display:block;"></iframe>'
                                f'</div>'
                                f'</details>'
                            )
                        else:
                            viewer_html += (
                                f'<a href="{url}" target="_blank" style="display:inline-flex;align-items:center;gap:0.3rem;'
                                f'font-size:0.75rem;color:#BE1E2D;font-weight:600;text-decoration:none;'
                                f'background:#FFF5F5;border:1px solid #FECACA;border-radius:5px;'
                                f'padding:0.2rem 0.55rem;margin-top:0.4rem;">📎 {filename}</a>'
                            )

                rows_html += (
                    f'<div style="padding:0.75rem 1rem;border-bottom:1px solid #F1F5F9;">'
                    f'<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;">'
                    f'<div style="flex:1;min-width:0;">'
                    f'<div style="display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap;">'
                    f'<span style="font-size:0.88rem;font-weight:600;color:#1E293B;">{req_type}</span>'
                    f'{badge}</div>'
                    f'{note}'
                    f'</div>'
                    f'<div style="text-align:right;flex-shrink:0;">'
                    f'<div style="font-size:0.78rem;color:#1E293B;font-weight:500;white-space:nowrap;">{created_str}</div>'
                    f'<div style="font-size:0.72rem;color:#94A3B8;margin-top:0.1rem;white-space:nowrap;">Response: {resp_date_html}</div>'
                    f'</div>'
                    f'</div>'
                    f'{viewer_html}'
                    f'</div>'
                )

            table_html = (
                '<div class="info-card" style="margin-bottom:1.25rem;padding:0;overflow:hidden;">'
                '<div style="padding:0.6rem 1rem;background:#F8FAFC;border-bottom:1px solid #E2E8F0;display:flex;justify-content:space-between;">'
                '<span style="font-size:0.7rem;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.06em;">Request</span>'
                '<span style="font-size:0.7rem;font-weight:700;color:#94A3B8;text-transform:uppercase;letter-spacing:0.06em;">Submitted / Response</span>'
                '</div>'
                f'{rows_html}'
                '</div>'
            )
            st.markdown(table_html, unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size:0.88rem; color:#94A3B8; margin-bottom:1rem;">No requests to display.</div>', unsafe_allow_html=True)

    st.markdown('<div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase; letter-spacing:0.05em; margin:1.25rem 0 0.3rem;">Writing Center Workshops</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.88rem; color:#475569; margin-bottom:0.75rem;">These workshops are sent to students throughout the program so that you can learn more about academic research writing.</div>', unsafe_allow_html=True)
    workshops = [
        (
            "WC_WORKSHOP1",
            "Workshop 1 — Academic Writing and Grammar",
            "To familiarize you with the nuances of academic research English writing and, in turn, help you maximize rhetorical effectiveness in your work.",
        ),
        (
            "WC_WORKSHOP2",
            "Workshop 2 — Transforming a Research Proposal and Outline into a Paper",
            "To guide students through understanding how your research outlines map onto the different sections of your outline and final research paper.",
        ),
        (
            "WC_WORKSHOP3",
            "Workshop 3 — The Ins and Outs of Writing Different Paper Types",
            "A continuation of Workshop 2, solidifying the necessary components and nuances of four major paper types: literature reviews, experimental research papers, data analysis papers, and case studies.",
        ),
        (
            "WC_WORKSHOP4",
            "Workshop 4 — Citations and Plagiarism",
            "Covers the fundamentals of major citation styles across fields. Proper citations are essential to a professional research paper — and since citations appear in every research paper, this workshop is relevant to every scholar!",
        ),
        (
            "WC_WORKSHOP5",
            "Workshop 5 — Scientific Writing in LaTeX and Overleaf",
            "A brief introduction to Overleaf, a software that uses LaTeX to produce beautiful and professional scientific manuscripts. Highly recommended for students doing scientific or quantitative research.",
        ),
    ]

    for secret_key, title, description in workshops:
        url = get_secret(secret_key, "")
        if url:
            st.markdown(
                f'<div class="info-card" style="margin-bottom:0.75rem;">'
                f'<div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.3rem;">Writing Workshop</div>'
                f'<div style="font-size:1rem; font-weight:700; color:#1E293B; margin-bottom:0.3rem;">{title}</div>'
                f'<div style="font-size:0.85rem; color:#475569; margin-bottom:0.65rem; line-height:1.5;">{description}</div>'
                f'<a href="{url}" target="_blank" style="display:inline-flex; align-items:center; gap:0.4rem; background:#F8F9FA; border:1px solid #E2E8F0; border-radius:6px; padding:0.4rem 0.8rem; font-size:0.85rem; font-weight:600; color:#BE1E2D; text-decoration:none;">▶ Watch Workshop</a>'
                f'</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div class="info-card" style="margin-bottom:0.75rem; opacity:0.5;">'
                f'<div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.3rem;">Writing Workshop</div>'
                f'<div style="font-size:1rem; font-weight:700; color:#1E293B; margin-bottom:0.3rem;">{title}</div>'
                f'<div style="font-size:0.85rem; color:#475569; margin-bottom:0.5rem; line-height:1.5;">{description}</div>'
                f'<div style="font-size:0.8rem; color:#94A3B8;">Not yet released</div>'
                f'</div>',
                unsafe_allow_html=True
            )

# ──────────────────────────────────────────────
# VIEW: Resources
# ──────────────────────────────────────────────

def show_resources(student):
    st.markdown("### Resources")
    st.markdown("""
    <div style="background:#F8F9FA; border-left:4px solid #BE1E2D; border-radius:6px;
                padding:0.85rem 1rem; margin-bottom:1.5rem; color:#475569; font-size:0.92rem; line-height:1.55;">
        Everything you need for your research program — all in one place.
    </div>
    """, unsafe_allow_html=True)

    # ── Guidebook ──
    st.markdown(f"""
    <div class="info-card" style="display:flex; align-items:center; justify-content:space-between;
                                  flex-wrap:wrap; gap:0.75rem; margin-bottom:1rem;">
        <div>
            <div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase;
                        letter-spacing:0.05em; margin-bottom:0.3rem;">Program Guidebook</div>
            <div style="font-size:1rem; font-weight:600; color:#1E293B; margin-bottom:0.2rem;">
                Lumiere Research Scholar Guidebook
            </div>
            <div style="font-size:0.88rem; color:#475569;">
                Your complete guide to the Lumiere Research Scholar Program — covering expectations,
                timelines, deliverables, and tips for getting the most out of your experience.
            </div>
        </div>
        <a href="https://misty-music-eb4.notion.site/Lumiere-Research-Scholar-Guidebook-3c3dd9d9b32745c6971c50908db9b549"
           target="_blank"
           style="display:inline-flex; align-items:center; gap:0.4rem;
                  background:#BE1E2D; color:white; text-decoration:none;
                  padding:0.5rem 1.1rem; border-radius:7px; font-size:0.88rem;
                  font-weight:600; white-space:nowrap;">
            Open Guidebook →
        </a>
    </div>
    """, unsafe_allow_html=True)

    # ── Submission Portal ──
    submission_portal = student.get("submission_portal") or ""
    if submission_portal:
        st.markdown(f"""
        <div class="info-card" style="display:flex; align-items:center; justify-content:space-between;
                                      flex-wrap:wrap; gap:0.75rem; margin-bottom:1rem;">
            <div>
                <div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase;
                            letter-spacing:0.05em; margin-bottom:0.3rem;">Submission Portal</div>
                <div style="font-size:1rem; font-weight:600; color:#1E293B; margin-bottom:0.2rem;">
                    Submit Your Deliverables
                </div>
                <div style="font-size:0.88rem; color:#475569;">
                    Use this form to submit your deliverables — research question, proposal,
                    outline, milestones, and final paper. Submit each piece by its due date
                    as shown on the Deadlines &amp; Submissions page.
                </div>
            </div>
            <a href="{submission_portal}" target="_blank"
               style="display:inline-flex; align-items:center; gap:0.4rem;
                      background:#BE1E2D; color:white; text-decoration:none;
                      padding:0.5rem 1.1rem; border-radius:7px; font-size:0.88rem;
                      font-weight:600; white-space:nowrap;">
                Submit Here →
            </a>
        </div>
        """, unsafe_allow_html=True)

    # ── Weekly Update Form ──
    st.markdown(f"""
    <div class="info-card" style="display:flex; align-items:center; justify-content:space-between;
                                  flex-wrap:wrap; gap:0.75rem; margin-bottom:1rem;">
        <div>
            <div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase;
                        letter-spacing:0.05em; margin-bottom:0.3rem;">Weekly Meeting Update</div>
            <div style="font-size:1rem; font-weight:600; color:#1E293B; margin-bottom:0.2rem;">
                Meeting Update Form
            </div>
            <div style="font-size:0.88rem; color:#475569;">
                Fill this out after every mentor meeting to log your progress, discussion notes,
                and next steps. This keeps your Program Manager in the loop and counts toward
                your completed meetings tally.
            </div>
        </div>
        <a href="https://airtable.com/appK9HemdsQBzVefU/shrMUNFRb6lEQwHfk" target="_blank"
           style="display:inline-flex; align-items:center; gap:0.4rem;
                  background:#BE1E2D; color:white; text-decoration:none;
                  padding:0.5rem 1.1rem; border-radius:7px; font-size:0.88rem;
                  font-weight:600; white-space:nowrap;">
            Open Form →
        </a>
    </div>
    """, unsafe_allow_html=True)

    # ── Citations ──
    st.markdown(f"""
    <div class="info-card" style="display:flex; align-items:center; justify-content:space-between;
                                  flex-wrap:wrap; gap:0.75rem; margin-bottom:1rem;">
        <div>
            <div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase;
                        letter-spacing:0.05em; margin-bottom:0.3rem;">Writing Guide</div>
            <div style="font-size:1rem; font-weight:600; color:#1E293B; margin-bottom:0.2rem;">
                Citations 101
            </div>
            <div style="font-size:0.88rem; color:#475569;">
                A guide to citing your sources correctly. Use this whenever you're writing your
                research proposal, outline, or paper — proper citations are required for all
                written submissions.
            </div>
        </div>
        <a href="https://misty-music-eb4.notion.site/Citations-101-3211af35f82f4eb7a7a2f6fd6125b9e7"
           target="_blank"
           style="display:inline-flex; align-items:center; gap:0.4rem;
                  background:#BE1E2D; color:white; text-decoration:none;
                  padding:0.5rem 1.1rem; border-radius:7px; font-size:0.88rem;
                  font-weight:600; white-space:nowrap;">
            Open Guide →
        </a>
    </div>
    """, unsafe_allow_html=True)

    # ── Deadline-specific resources ──
    st.markdown("---")
    st.markdown("#### Deadline Resources")
    st.markdown(
        '<p style="font-size:0.88rem; color:#64748B; margin-bottom:1rem;">Reference guides for each stage of your program.</p>',
        unsafe_allow_html=True
    )

    # Canonical order; variants like Research Outline/Paper Outline are intentionally omitted (same URL)
    canonical_deadline_keys = [
        "Research Question",
        "Research Proposal",
        "Research Paper Outline",
        "Milestone",
        "Revised Final Paper",
    ]

    for key in canonical_deadline_keys:
        links = GUIDEBOOK_LINKS.get(key, [])
        helper = GUIDEBOOK_HELPER.get(key, "")
        if not links:
            continue
        buttons_html = " ".join(
            f'<a href="{url}" target="_blank"'
            f'   style="display:inline-flex; align-items:center; gap:0.4rem;'
            f'          background:#BE1E2D; color:white; text-decoration:none;'
            f'          padding:0.45rem 1rem; border-radius:7px; font-size:0.85rem;'
            f'          font-weight:600; white-space:nowrap; margin-top:0.25rem;">'
            f'    {title} →'
            f'</a>'
            for title, url in links
        )
        st.markdown(f"""
        <div class="info-card" style="margin-bottom:0.85rem;">
            <div style="font-size:0.72rem; font-weight:600; color:#94A3B8; text-transform:uppercase;
                        letter-spacing:0.05em; margin-bottom:0.3rem;">{key}</div>
            <div style="font-size:0.88rem; color:#475569; margin-bottom:0.5rem;">{helper}</div>
            <div style="display:flex; flex-wrap:wrap; gap:0.5rem;">{buttons_html}</div>
        </div>
        """, unsafe_allow_html=True)

# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    # Write deferred session cookie now that the JS component is ready
    if "pending_session_cookie" in st.session_state:
        try:
            cookies.set("student_session", generate_session_token(st.session_state.pending_session_cookie), max_age=30 * 24 * 3600)
            del st.session_state.pending_session_cookie
        except Exception:
            pass  # Component not ready yet — retry on next run
    check_session_cookie()
    check_magic_link_token()

    if not st.session_state.authenticated:
        show_login_page()
    elif not st.session_state.program_selected:
        show_program_selector()
    else:
        show_dashboard()

if __name__ == "__main__":
    main()
