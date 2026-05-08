# Improvement: Parse Digest Emails into Individual Job Listings

## Problem

Job platforms like LinkedIn send **digest emails** containing multiple job listings in a single message. Currently JobPilot scores the entire email as one item, which is wrong — a digest with 3 iOS roles and 1 Flutter role gets a mediocre score, hiding the relevant listing.

## Requirements

### 1. Parse digest emails into individual jobs

Detect when an email is a digest (contains multiple job listings) and extract each listing separately.

**Per listing, extract:**
- Job title (e.g., "Senior App-utvecklare")
- Company name (e.g., "Deploja")
- Location (e.g., "Gothenburg")
- Job URL (the `linkedin.com/comm/jobs/view/...` link or equivalent)
- Platform source (inherited from parent email)

**Platforms to support:**
- **LinkedIn job alerts** — pattern: blocks separated by `---` or whitespace, each containing title, company, location, and a "View job:" URL
- **Indeed daily digest** — similar multi-job format
- **Glassdoor job alerts** — multi-job emails
- **Relocate.me weekly digest** — curated list of jobs with relocation
- **Google Alerts** — links to job postings
- Any other platform that sends multi-job emails — build a generic fallback parser that looks for repeated patterns of (title + company + location + URL)

### 2. Store extracted jobs

Use the existing `scraped_jobs` table (or a new `extracted_jobs` table — decide which is cleaner) to store each individual job listing. Each entry must reference the parent `email_id` it was extracted from.

Fields: source (platform), title, company, location, url, email_id (parent reference).

Deduplicate by URL — if the same job URL appears in multiple digest emails, don't create a duplicate.

### 3. Score each job individually

Run the existing `RuleBasedScorer` on each extracted job using its title, company, and location text. Each job gets its own score and classification ("worth_checking" / "skip").

### 4. Display in review queue

Each extracted job appears as its **own card** in the inbox review queue (flat list, same level as other items). The card shows:
- Job title
- Company + location
- Platform badge (e.g., "linkedin")
- Individual score
- **"Open Origin"** button that opens the job URL directly (not Gmail)
- Worth Checking / Skip buttons

### 5. Replace "Open in Gmail" with "Open Origin"

For ALL items in the review queue:
- If the item has a direct job URL → show **"Open Origin"** button linking to that URL
- If the item is a plain email with no extracted URL → show **"Open in Gmail"** button as fallback
- Remove the expandable email detail view entirely (the `email_detail.html` template, the `/api/email/<id>/detail` endpoint, the htmx expand/collapse behavior, and related CSS)

### 6. Handle non-digest emails

For emails that contain only a single job (e.g., "Someone viewed your profile" or a single job recommendation), extract the job URL if present and attach it to the email card directly. No need to create a separate entry — just add the URL so "Open Origin" works.

## Technical Notes

### LinkedIn digest email structure (example)

```
Your job alert for senior mobile engineer in Sweden
New jobs match your preferences.

Senior App-utvecklare
Deploja
Gothenburg
View job: https://www.linkedin.com/comm/jobs/view/4408668238/...

---------------------------------------------------------

Android Developer
E-Solutions
Stockholm
View job: https://www.linkedin.com/comm/jobs/view/4407811915/...

---------------------------------------------------------

Senior iOS Developer
Incluso
Stockholm
View job: https://www.linkedin.com/comm/jobs/view/4410029616/...
```

Each block has: title (first line), company (second line), location (third line), optional "This company is actively hiring" / "Apply with resume & profile" lines, and a "View job: URL" line.

### Parsing approach

1. Split the email body by the separator pattern (`---+` or similar)
2. For each block, extract title/company/location/URL using regex or line-by-line parsing
3. Skip blocks that don't have a URL (they're headers or footers)
4. Strip tracking parameters from URLs if possible (keep the base `linkedin.com/jobs/view/ID` part)
5. **Validate each extracted block is actually a job listing** — skip boilerplate/intro text

### IMPORTANT: Boilerplate filtering (known bug)

LinkedIn "job alert created" emails have this structure:

```
Your job alert has been created: Senior Software Engineer in United States

You'll receive notifications when new jobs are posted that match your search preferences.

[Company logo] Senior Software Engineer (Remote)
               Quik Hire Staffing · United States
...
```

The intro line ("You'll receive notifications...") gets incorrectly extracted as a job title because it sits above a job URL. The parser MUST filter out boilerplate blocks.

**Validation rules — a block is a valid job listing ONLY if:**
- It has a recognizable job title (contains words like engineer, developer, lead, manager, designer, analyst, architect, etc.)
- It has a company name (short line, not a full sentence)
- The "title" line is short (under ~80 characters) — real job titles are concise, boilerplate sentences are long

**Known boilerplate patterns to skip (case-insensitive):**
- Lines containing "you'll receive notifications"
- Lines containing "match your search preferences"
- Lines containing "job alert has been created"
- Lines containing "new jobs are posted"
- Lines containing "based on your profile"
- Lines containing "jobs for you"
- Any line longer than 100 characters as a title (real job titles are rarely this long)

**General heuristic:** if the first line of a block reads like a sentence (contains "you", "your", "when", "that", "will"), it's probably boilerplate, not a job title.

### KNOWN BUG: Single-job LinkedIn alerts use email subject as title

LinkedIn single-job alert emails have the subject "A new job matches your preferences." and the actual job title ("Senior Android Developer") appears only in the body. The digest parser currently extracts the email subject as the job title, resulting in a scraped_job with:
- title: "A new job matches your preferences." (wrong — this is the subject)
- company field showing the real job title instead

**Fix:** When parsing single-job LinkedIn alerts (one job URL, subject matches "A new job matches your preferences" or similar generic patterns), extract the job title from the body text instead of the email subject. Look for the pattern: company logo line → job title line → company · location line.

### Files to modify

- `src/jobpilot/gmail/parser.py` — add digest detection and per-job extraction
- `src/jobpilot/classifier/signals.py` — may need platform-specific digest patterns
- `src/jobpilot/storage/repository.py` — add methods for extracted jobs
- `src/jobpilot/storage/database.py` — add table if needed
- `src/jobpilot/web/routes.py` — remove email detail endpoint, update inbox to show extracted jobs, update "Open" button logic
- `src/jobpilot/web/templates/inbox.html` — remove expand/collapse, add "Open Origin" button, show extracted job cards
- `src/jobpilot/web/templates/email_detail.html` — DELETE this file
- `src/jobpilot/web/static/style.css` — remove expand-related styles, add "Open Origin" button style
- `src/jobpilot/gmail/fetcher.py` — after storing email, run digest parser and store extracted jobs

### Existing files for reference

- Current scorer: `src/jobpilot/classifier/rules.py` — `RuleBasedScorer.score(subject, body)`
- Current signals: `src/jobpilot/classifier/signals.py` — `PLATFORM_PATTERNS`, `extract_signals()`
- Current models: `src/jobpilot/storage/models.py` — `ScrapedJob` dataclass can potentially be reused
- Current repo: `src/jobpilot/storage/repository.py` — `insert_scraped_job()`, `get_scraped_jobs_for_review()`

## Out of Scope

- Do not change the scoring algorithm itself
- Do not implement ML model changes
- Do not add new platforms to email fetching
- Keep the current UI layout (cards with buttons), just change what each card represents
