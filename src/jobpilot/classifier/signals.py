"""Signal definitions, platform detection, and signal extraction."""

import re

# --- Platform Detection ---

PLATFORM_PATTERNS = {
    "linkedin": {
        "sender_domains": ["linkedin.com", "e.linkedin.com"],
        "sender_patterns": [r"jobs-noreply@linkedin\.com", r"notifications-noreply@linkedin\.com"],
        "subject_patterns": [r"new job", r"jobs? for you", r"is hiring", r"match(es)?"],
    },
    "wellfound": {
        "sender_domains": ["wellfound.com", "angel.co"],
        "sender_patterns": [r".*@wellfound\.com"],
        "subject_patterns": [r"new match", r"interested in you", r"startup"],
    },
    "relocate_me": {
        "sender_domains": ["relocate.me"],
        "sender_patterns": [r".*@relocate\.me"],
        "subject_patterns": [r"relocation", r"new jobs?", r"visa sponsorship"],
    },
    "arc_dev": {
        "sender_domains": ["arc.dev"],
        "sender_patterns": [r".*@arc\.dev"],
        "subject_patterns": [r"new opportunity", r"remote.*job"],
    },
    "toptal": {
        "sender_domains": ["toptal.com"],
        "sender_patterns": [r".*@toptal\.com"],
        "subject_patterns": [r"new project", r"opportunity"],
    },
    "turing": {
        "sender_domains": ["turing.com"],
        "sender_patterns": [r".*@turing\.com"],
        "subject_patterns": [r"new job", r"matched", r"opportunity"],
    },
    "google_alerts": {
        "sender_domains": ["google.com"],
        "sender_patterns": [r"googlealerts-noreply@google\.com"],
        "subject_patterns": [r"google alert"],
    },
    "indeed": {
        "sender_domains": ["indeed.com", "indeedmail.com"],
        "sender_patterns": [r".*@indeed\.com", r".*@indeedmail\.com"],
        "subject_patterns": [r"new jobs? for", r"daily job", r"recommended"],
    },
    "glassdoor": {
        "sender_domains": ["glassdoor.com"],
        "sender_patterns": [r".*@glassdoor\.com"],
        "subject_patterns": [r"new jobs?", r"hiring"],
    },
    "stackoverflow_jobs": {
        "sender_domains": ["stackoverflow.com", "stackoverflowmail.com"],
        "sender_patterns": [r".*@stackoverflow\.com"],
        "subject_patterns": [r"jobs? alert", r"new listing"],
    },
    "hired": {
        "sender_domains": ["hired.com"],
        "sender_patterns": [r".*@hired\.com"],
        "subject_patterns": [r"interview request", r"new opportunity"],
    },
    "landing_jobs": {
        "sender_domains": ["landing.jobs"],
        "sender_patterns": [r".*@landing\.jobs"],
        "subject_patterns": [r"new job", r"match", r"opportunity", r"visa"],
    },
    "arbeitnow": {
        "sender_domains": ["arbeitnow.com"],
        "sender_patterns": [r".*@arbeitnow\.com"],
        "subject_patterns": [r"new jobs?", r"relocation", r"visa sponsorship"],
    },
    "the_global_move": {
        "sender_domains": ["substack.com", "globalmove.co"],
        "sender_patterns": [r".*relocateme.*@substack\.com", r".*@globalmove\.co"],
        "subject_patterns": [r"jobs? with relocation", r"visa", r"weekly"],
    },
    "toughbyte": {
        "sender_domains": ["toughbyte.com"],
        "sender_patterns": [r".*@toughbyte\.com"],
        "subject_patterns": [r"opportunity", r"position", r"role"],
    },
    "agile_search": {
        "sender_domains": ["agilesearch.io"],
        "sender_patterns": [r".*@agilesearch\.io"],
        "subject_patterns": [r"opportunity", r"position", r"scandina"],
    },
    "nederlia": {
        "sender_domains": ["nederlia.com"],
        "sender_patterns": [r".*@nederlia\.com"],
        "subject_patterns": [r"opportunity", r"role", r"position"],
    },
}

# --- Tech Stack Keywords ---

TECH_STACK_KEYWORDS = {
    "flutter": {"weight": 1.0, "category": "primary"},
    "dart": {"weight": 1.0, "category": "primary"},
    "mobile developer": {"weight": 0.9, "category": "primary"},
    "mobile engineer": {"weight": 0.9, "category": "primary"},
    "cross-platform": {"weight": 0.8, "category": "primary"},
    "android": {"weight": 0.7, "category": "secondary"},
    "ios": {"weight": 0.7, "category": "secondary"},
    "kotlin": {"weight": 0.8, "category": "secondary"},
    "swift": {"weight": 0.6, "category": "secondary"},
    "react native": {"weight": 0.5, "category": "secondary"},
    "swiftui": {"weight": 0.6, "category": "secondary"},
}

# --- Location Patterns ---

LOCATION_PATTERNS = {
    "netherlands": {"weight": 1.0, "target": True},
    "remote": {"weight": 0.9, "target": True},
    "norway": {"weight": 0.6, "target": False},
    "sweden": {"weight": 0.6, "target": False},
    "us only": {"weight": -0.5, "target": False},
    "usa only": {"weight": -0.5, "target": False},
    "must be located in": {"weight": -0.2, "target": False},
}

# --- Job Titles ---

TARGET_JOB_TITLES = {
    "senior mobile engineer": {"weight": 1.0},
    "mobile team lead": {"weight": 1.0},
    "mobile engineering lead": {"weight": 1.0},
    "flutter developer": {"weight": 1.0},
    "senior flutter developer": {"weight": 1.0},
    "flutter engineer": {"weight": 1.0},
    "senior flutter engineer": {"weight": 1.0},
    "flutter team lead": {"weight": 1.0},
    "mobile lead": {"weight": 0.9},
    "mobile engineering manager": {"weight": 0.8},
    "head of mobile": {"weight": 0.8},
    "mobile developer": {"weight": 0.8},
    "mobile engineer": {"weight": 0.8},
    "cross-platform developer": {"weight": 0.7},
    "software engineer": {"weight": 0.3},
}

# --- Seniority ---

SENIORITY_PATTERNS = {
    "senior": {"weight": 1.0, "level": "senior"},
    "sr.": {"weight": 1.0, "level": "senior"},
    "lead": {"weight": 0.8, "level": "lead"},
    "team lead": {"weight": 1.0, "level": "lead"},
    "tech lead": {"weight": 0.9, "level": "lead"},
    "engineering manager": {"weight": 0.7, "level": "lead"},
    "staff": {"weight": 0.7, "level": "staff"},
    "principal": {"weight": 0.6, "level": "principal"},
    "mid-level": {"weight": 0.3, "level": "mid"},
    "junior": {"weight": -0.5, "level": "junior"},
    "intern": {"weight": -1.0, "level": "intern"},
    "entry-level": {"weight": -0.8, "level": "entry"},
}

# --- Salary Patterns ---

SALARY_PATTERNS = [
    # EUR patterns
    r"€\s*(\d{2,3})[,.]?(\d{3})?\s*[-–to]+\s*€?\s*(\d{2,3})[,.]?(\d{3})?",
    r"(\d{2,3})[,.]?(\d{3})?\s*[-–to]+\s*(\d{2,3})[,.]?(\d{3})?\s*(eur|€)",
    # USD patterns
    r"\$\s*(\d{2,3})[,.]?(\d{3})?\s*[-–to]+\s*\$?\s*(\d{2,3})[,.]?(\d{3})?",
    r"(\d{2,3})[,.]?(\d{3})?\s*[-–to]+\s*(\d{2,3})[,.]?(\d{3})?\s*(usd|\$)",
    # Generic with k notation
    r"(\d{2,3})k\s*[-–to]+\s*(\d{2,3})k\s*(eur|usd|€|\$)",
    r"(eur|usd|€|\$)\s*(\d{2,3})k\s*[-–to]+\s*(\d{2,3})k",
]

# --- Negative Signals ---

NEGATIVE_SIGNALS = [
    "no visa sponsorship",
    "must have work authorization",
    "no relocation",
    "clearance required",
    "security clearance",
    "on-site only",
    "contract-to-hire",
    "unpaid",
    "equity only",
    "volunteer",
]


# --- Detection and Extraction Functions ---


def detect_platform(sender: str, sender_domain: str, subject: str) -> str | None:
    """Detect which job platform sent this email."""
    sender_lower = sender.lower()

    for platform, patterns in PLATFORM_PATTERNS.items():
        # Check sender domain
        if sender_domain in patterns["sender_domains"]:
            return platform

        # Check sender patterns
        for pattern in patterns["sender_patterns"]:
            if re.search(pattern, sender_lower):
                return platform

    return None


def extract_signals(subject: str, body: str, platform: str | None) -> list[dict]:
    """Extract all signals from email subject and body text."""
    signals = []
    text = f"{subject}\n{body}".lower()

    # Tech stack
    for keyword, info in TECH_STACK_KEYWORDS.items():
        if keyword in text:
            signals.append({"type": "tech_stack", "value": keyword})

    # Locations
    for location, info in LOCATION_PATTERNS.items():
        if location in text:
            signals.append({"type": "location", "value": location})

    # Job titles
    for title, info in TARGET_JOB_TITLES.items():
        if title in text:
            signals.append({"type": "job_title", "value": title})

    # Seniority
    for pattern, info in SENIORITY_PATTERNS.items():
        if pattern in text:
            signals.append({"type": "seniority", "value": info["level"]})
            break  # Take the first match

    # Salary
    for pattern in SALARY_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            signals.append({"type": "salary", "value": match.group(0)})
            break

    # Negative signals
    for neg in NEGATIVE_SIGNALS:
        if neg in text:
            signals.append({"type": "negative", "value": neg})

    # Platform
    if platform:
        signals.append({"type": "platform", "value": platform})

    return signals
