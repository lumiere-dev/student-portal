import os
import streamlit as st
from pyairtable import Api
import pandas as pd
from datetime import datetime, timedelta, timezone
import resend
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import re


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

@st.cache_resource
def get_airtable_api():
    return Api(get_secret("AIRTABLE_API_KEY"))

@st.cache_resource
def get_tables():
    api = get_airtable_api()
    base = api.base(get_secret("AIRTABLE_BASE_ID"))
    return {
        "students": base.table(get_secret("STUDENT_TABLE")),
        "deadlines": base.table(get_secret("DEADLINES_TABLE")),
        "mentors": base.table(get_secret("MENTOR_TABLE"))
    }

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
                <h2 style="color: #8B1A2B;">Welcome to the Student Portal</h2>
                <p>Hi {first_name},</p>
                <p>Click the button below to access your student dashboard:</p>
                <p style="margin: 30px 0;">
                    <a href="{magic_link}"
                       style="background: linear-gradient(135deg, #8B1A2B 0%, #6B1520 100%);
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
    "tuition_paid": "OB: Full Tuition Paid",
    "program_manager_email": "Program Manager Email",
    "revised_final_paper_due": "PM: Student's Revised Final Paper - Due date",
    "student_no_shows": "[Current + Archived] No. of Student No Shows in Mentor Meetings",
    "reason_for_interest": "Reason for Interest in Areas",
    "publication_specialist": "Publication Specialist",
    "publication_target": "Publication Target",
    "publication_specialist_email": "Publication Specialist Email",
    "publication_outcome": "PS: Latest Publication Outcome - Latest"
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

# ──────────────────────────────────────────────
# Custom CSS — Teal / Emerald Student Theme
# ──────────────────────────────────────────────

st.markdown("""
<style>
    /* Header styles */
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #8B1A2B;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #64748B;
        margin-bottom: 2rem;
    }
    .student-name-header {
        font-size: 1.6rem;
        font-weight: 600;
        color: #1E293B;
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #8B1A2B;
    }

    /* Cards */
    .metric-card {
        background: linear-gradient(135deg, #8B1A2B 0%, #6B1520 100%);
        border-radius: 12px;
        padding: 1.25rem;
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
        background-color: #DEF7EC;
        color: #03543F;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 500;
        display: inline-block;
    }
    .status-pending {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 500;
        display: inline-block;
    }
    .status-overdue {
        background-color: #FEE2E2;
        color: #991B1B;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 500;
        display: inline-block;
    }

    /* Preview mode */
    .preview-banner {
        background-color: #FEF3C7;
        border: 1px solid #F59E0B;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        margin-bottom: 1rem;
    }

    /* Sidebar tweaks */
    [data-testid="stSidebar"] {
        background-color: #1A1A1A;
    }
    [data-testid="stSidebar"] .stMarkdown h3,
    [data-testid="stSidebar"] .stMarkdown p,
    [data-testid="stSidebar"] .stMarkdown strong,
    [data-testid="stSidebar"] .stMarkdown span,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label span,
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label div {
        color: #F1F5F9 !important;
    }
    [data-testid="stSidebar"] .stCaption p {
        color: #94A3B8 !important;
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
    """Format date string as 'DD Month YYYY' (e.g. 04 July 2025)"""
    if not date_str:
        return "Not set"
    if isinstance(date_str, list):
        date_str = date_str[0] if date_str else ""
    if not date_str:
        return "Not set"
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{date_obj.day:02d} {date_obj.strftime('%B')} {date_obj.year}"
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
    if status == "Submitted":
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

@st.cache_data(ttl=300)
def get_student_by_email(email):
    """Find student by email in Student Table"""
    tables = get_tables()
    email_field = get_secret("STUDENT_EMAIL_FIELD", "Email")
    try:
        records = tables["students"].all(
            formula=f"LOWER({{{email_field}}}) = LOWER('{email}')"
        )
        if records:
            record = records[0]
            fields = record["fields"]
            return {
                "id": record["id"],
                "name": fields.get(STUDENT_FIELDS["name"], "Unknown"),
                "email": fields.get(email_field, email),
                "research_area": fields.get(STUDENT_FIELDS["research_area"], ""),
                "city": fields.get(STUDENT_FIELDS["city"], ""),
                "graduation_year": fields.get(STUDENT_FIELDS["graduation_year"], ""),
                "mentor": fields.get(STUDENT_FIELDS["mentor"], ""),
                "mentor_confirmation": fields.get(STUDENT_FIELDS["mentor_confirmation"], ""),
                "background_shared": fields.get(STUDENT_FIELDS["background_shared"], ""),
                "expected_meetings": fields.get(STUDENT_FIELDS["expected_meetings"], 0),
                "completed_meetings": fields.get(STUDENT_FIELDS["completed_meetings"], 0),
                "notes_summary": fields.get(STUDENT_FIELDS["notes_summary"], ""),
                "hours_recorded": fields.get(STUDENT_FIELDS["hours_recorded"], ""),
                "foundation_student": fields.get(STUDENT_FIELDS["foundation_student"], ""),
                "tuition_paid": fields.get(STUDENT_FIELDS["tuition_paid"], ""),
                "program_manager_email": unwrap(fields.get(STUDENT_FIELDS["program_manager_email"], "")),
                "revised_final_paper_due": unwrap(fields.get(STUDENT_FIELDS["revised_final_paper_due"], "")),
                "student_no_shows": unwrap(fields.get(STUDENT_FIELDS["student_no_shows"], 0), default=0),
                "reason_for_interest": unwrap(fields.get(STUDENT_FIELDS["reason_for_interest"], "")),
                "publication_specialist": unwrap(fields.get(STUDENT_FIELDS["publication_specialist"], "")),
                "publication_target": unwrap(fields.get(STUDENT_FIELDS["publication_target"], "")),
                "publication_specialist_email": unwrap(fields.get(STUDENT_FIELDS["publication_specialist_email"], "")),
                "publication_outcome": unwrap(fields.get(STUDENT_FIELDS["publication_outcome"], ""))
            }
    except Exception as e:
        st.error(f"Error fetching student: {e}")
    return None

@st.cache_data(ttl=300)
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

def check_magic_link_token():
    query_params = st.query_params
    if "token" in query_params and not st.session_state.authenticated:
        token = query_params["token"]
        email = verify_magic_token(token)
        if email:
            student = get_student_by_email(email)
            if student:
                st.session_state.authenticated = True
                st.session_state.student_name = student["name"]
                st.session_state.student_email = email
                st.session_state.student_record = student
                st.session_state.is_preview = False
                st.query_params.clear()
                st.rerun()
        else:
            st.error("This login link has expired or is invalid. Please request a new one.")
            st.query_params.clear()

# ──────────────────────────────────────────────
# LOGIN PAGE
# ──────────────────────────────────────────────

def show_login_page():
    st.image("assets/logo.png", width=300)
    st.markdown('<p class="main-header">Student Portal</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Lumiere Education — Access your research program dashboard</p>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("### Sign In")

        if st.session_state.magic_link_sent:
            st.success("Check your email! We've sent you a magic link to access the portal.")
            st.info("The link will expire in 1 hour.")
            if st.button("Send another link"):
                st.session_state.magic_link_sent = False
                st.rerun()
        else:
            with st.form("login_form"):
                email = st.text_input("Email Address", placeholder="Enter your student email")
                submitted = st.form_submit_button("Send Magic Link", use_container_width=True)

                if submitted and email:
                    student = get_student_by_email(email)
                    if student:
                        if send_magic_link(email, student["name"]):
                            st.session_state.magic_link_sent = True
                            st.rerun()
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
                    student = get_student_by_email(preview_email)
                    if student:
                        st.session_state.authenticated = True
                        st.session_state.student_name = student["name"]
                        st.session_state.student_email = preview_email
                        st.session_state.student_record = student
                        st.session_state.is_preview = True
                        st.rerun()
                    else:
                        st.error("Student email not found.")
        else:
            with st.expander("Team Access"):
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

    # ── Sidebar ──
    with st.sidebar:
        st.image("assets/logo.png", width=200)
        st.caption("Research Program Student Portal")
        st.markdown("---")

        display_name = student["name"].split("|")[0].strip() if student else ""
        st.markdown(f"**{display_name}**")
        st.caption(st.session_state.student_email)

        if st.session_state.is_preview:
            st.warning("Preview Mode")

        st.markdown("---")

        view = st.radio(
            "Navigation",
            [
                "Student Profile Summary",
                "Deadlines & Submissions",
                "Publication Program",
                "Writing Center",
            ],
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
            for key in ["authenticated", "student_name", "student_email", "student_record", "is_preview"]:
                st.session_state[key] = False if key == "authenticated" or key == "is_preview" else None
            st.rerun()

    # ── Preview banner ──
    if st.session_state.is_preview:
        st.markdown(
            '<div class="preview-banner"><strong>Preview Mode:</strong> Viewing portal as '
            + student["name"].split("|")[0].strip() + '</div>',
            unsafe_allow_html=True
        )

    # ── Student name header ──
    st.markdown(
        f'<p class="student-name-header">{student["name"]}</p>',
        unsafe_allow_html=True
    )

    # ── Route to view ──
    if view == "Student Profile Summary":
        show_student_profile_summary(student)
    elif view == "Deadlines & Submissions":
        show_deadlines_and_submissions(student)
    elif view == "Publication Program":
        show_publication_program(student)
    elif view == "Writing Center":
        show_writing_center(student)

# ──────────────────────────────────────────────
# VIEW: Student Profile Summary
# ──────────────────────────────────────────────

def show_student_profile_summary(student):
    st.markdown("### Student Profile Summary")

    mentor_name = student.get("mentor") or "Not yet assigned"
    revised_due = student.get("revised_final_paper_due", "")

    # Mentor banner card
    st.markdown(f"""
    <div style="background:linear-gradient(135deg, #8B1A2B 0%, #6B1520 100%);
                border-radius:12px; padding:2rem; color:white; margin-bottom:1.5rem;">
        <div style="font-size:0.85rem; opacity:0.9;">Your Mentor</div>
        <div style="font-size:1.8rem; font-weight:700; margin-top:0.25rem;">{mentor_name}</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="info-card">
        <div style="font-size:0.85rem; color:#64748B;">Revised Final Paper Due Date</div>
        <div style="font-size:1.15rem; font-weight:600; color:#1E293B; margin-top:0.25rem;">{format_date(revised_due)}</div>
    </div>
    """, unsafe_allow_html=True)

# ──────────────────────────────────────────────
# VIEW: Deadlines & Submissions
# ──────────────────────────────────────────────

def show_deadlines_and_submissions(student):
    deadlines = get_deadlines_for_student(student["name"])

    if not deadlines:
        st.info("No deadlines found for your program yet.")
        return

    # ── Summary bar ──
    total = len(deadlines)
    submitted = sum(1 for d in deadlines if d["status"] == "Submitted")
    overdue_count = sum(1 for d in deadlines if is_overdue(d["due_date"], d["status"]))
    pending = total - submitted - overdue_count

    st.markdown(f"""
    <div style="display:flex; gap:1.5rem; margin-bottom:1.5rem; flex-wrap:wrap;">
        <div style="display:flex; align-items:center; gap:0.4rem;">
            <span style="width:10px; height:10px; border-radius:50%; background:#16A34A; display:inline-block;"></span>
            <span style="font-size:0.9rem; color:#475569;">{submitted} Submitted</span>
        </div>
        <div style="display:flex; align-items:center; gap:0.4rem;">
            <span style="width:10px; height:10px; border-radius:50%; background:#F59E0B; display:inline-block;"></span>
            <span style="font-size:0.9rem; color:#475569;">{pending} Pending</span>
        </div>
        <div style="display:flex; align-items:center; gap:0.4rem;">
            <span style="width:10px; height:10px; border-radius:50%; background:#EF4444; display:inline-block;"></span>
            <span style="font-size:0.9rem; color:#475569;">{overdue_count} Overdue</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Timeline-style deadline cards ──
    for dl in deadlines:
        dtype = dl["type"] or "Deadline"
        due_date = format_date(dl["due_date"])
        status = dl["status"]
        date_submitted = dl["date_submitted"]
        submissions = dl.get("submissions", {})
        overdue = is_overdue(dl["due_date"], status)

        if status == "Submitted":
            dot_color = "#16A34A"
            badge = '<span style="background:#DEF7EC; color:#03543F; padding:0.2rem 0.65rem; border-radius:20px; font-size:0.8rem; font-weight:500;">Submitted</span>'
        elif overdue:
            dot_color = "#EF4444"
            badge = '<span style="background:#FEE2E2; color:#991B1B; padding:0.2rem 0.65rem; border-radius:20px; font-size:0.8rem; font-weight:500;">Overdue</span>'
        else:
            dot_color = "#F59E0B"
            badge = '<span style="background:#FEF3C7; color:#92400E; padding:0.2rem 0.65rem; border-radius:20px; font-size:0.8rem; font-weight:500;">Pending</span>'

        # Submission date text
        if date_submitted:
            sub_text = f"Submitted {format_datetime_ist(date_submitted)}"
        elif status == "Submitted":
            sub_text = "Submitted"
        else:
            sub_text = ""

        st.markdown(f"""
        <div style="display:flex; gap:1rem; margin-bottom:0.25rem;">
            <div style="display:flex; flex-direction:column; align-items:center; padding-top:0.35rem;">
                <div style="width:12px; height:12px; border-radius:50%; background:{dot_color}; flex-shrink:0;"></div>
                <div style="width:2px; flex:1; background:#E2E8F0; margin-top:4px;"></div>
            </div>
            <div style="flex:1; background:white; border-radius:10px; padding:1rem 1.25rem;
                        box-shadow:0 1px 4px rgba(0,0,0,0.06); margin-bottom:0.5rem;">
                <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
                    <div>
                        <div style="font-size:1rem; font-weight:600; color:#1E293B;">{dtype}</div>
                        <div style="font-size:0.85rem; color:#64748B; margin-top:0.2rem;">Due {due_date}</div>
                    </div>
                    <div>{badge}</div>
                </div>
                {"<div style='font-size:0.8rem; color:#64748B; margin-top:0.5rem;'>" + sub_text + "</div>" if sub_text else ""}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Show submission content / attachments below the card
        if submissions:
            for field_name, value in submissions.items():
                st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;**{field_name}**")
                _render_submission_value(value)

    # Close the timeline
    st.markdown("")


def _render_submission_value(value):
    """Render a submission value — attachment list, URL, or plain text."""
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                url = item.get("url", "")
                filename = item.get("filename", "Download")
                if url:
                    st.markdown(f"[{filename}]({url})")
            else:
                st.markdown(f"{item}")
    elif isinstance(value, str):
        if value.startswith("http"):
            st.markdown(f"[View Submission]({value})")
        else:
            st.markdown(value)
    else:
        st.markdown(str(value))

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
    <div style="background:linear-gradient(135deg, #8B1A2B 0%, #6B1520 100%);
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

    specialist = student.get("publication_specialist") or "Not yet assigned"
    specialist_email = student.get("publication_specialist_email") or ""
    target = student.get("publication_target") or "Not yet set"
    outcome = student.get("publication_outcome") or "—"

    # Specialist banner card
    st.markdown(f"""
    <div style="background:linear-gradient(135deg, #8B1A2B 0%, #6B1520 100%);
                border-radius:12px; padding:2rem; color:white; margin-bottom:1.5rem;">
        <div style="font-size:0.85rem; opacity:0.9;">Your Publication Specialist</div>
        <div style="font-size:1.8rem; font-weight:700; margin-top:0.25rem;">{specialist}</div>
        {"<div style='font-size:0.95rem; opacity:0.85; margin-top:0.35rem;'>" + specialist_email + "</div>" if specialist_email else ""}
    </div>
    """, unsafe_allow_html=True)

    left, right = st.columns(2)

    with left:
        st.markdown(f"""
        <div class="info-card">
            <div style="font-size:0.85rem; color:#64748B;">Publication Target</div>
            <div style="font-size:1.15rem; font-weight:600; color:#1E293B; margin-top:0.25rem;">{target}</div>
        </div>
        """, unsafe_allow_html=True)

    with right:
        st.markdown(f"""
        <div class="info-card">
            <div style="font-size:0.85rem; color:#64748B;">Latest Publication Outcome</div>
            <div style="font-size:1.15rem; font-weight:600; color:#1E293B; margin-top:0.25rem;">{outcome}</div>
        </div>
        """, unsafe_allow_html=True)

# ──────────────────────────────────────────────
# VIEW: Writing Center
# ──────────────────────────────────────────────

def show_writing_center(student):
    st.markdown("### Writing Center")

    st.markdown("""
    <div class="info-card">
        <p>This is the interface for the Research Scholar Program Writing Center!</p>
        <p>Here you'll find relevant resources from the writing center, including a link
        to the writing center portal and any writing center workshops that have been
        distributed as part of the program!</p>
    </div>
    """, unsafe_allow_html=True)

    # Writing Center Portal link
    writing_center_url = get_secret("WRITING_CENTER_URL", "")
    if writing_center_url:
        st.markdown("#### Program Writing Center Portal")
        st.markdown(f"""
        <div class="info-card">
            <p>Use the following link to book a meeting or request written feedback
            from your writing coach!</p>
            <p><a href="{writing_center_url}" target="_blank"
                  style="color:#8B1A2B;">{writing_center_url}</a></p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("#### Writing Center Workshops")
    st.markdown("""
    <div class="info-card">
        <p>The section below will populate as writing center workshops are released
        for the program!</p>
        <p>Workshops begin at the start of week 4, so be sure to check this page
        weekly starting then!</p>
    </div>
    """, unsafe_allow_html=True)

# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    check_magic_link_token()

    if not st.session_state.authenticated:
        show_login_page()
    else:
        show_dashboard()

if __name__ == "__main__":
    main()
