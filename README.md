# ♻️ WasteLoop AI
### Turning Waste into Resources Through Intelligent Matching

**Build with IBM Bob | Bobathon 2026 | Smarter Streets, Better Living**

WasteLoop AI is an AI-assisted waste-to-resource coordination platform designed to connect waste generators with suitable recyclers, composting facilities and other resource-recovery processors.

The platform helps identify suitable destinations for different waste streams using material compatibility, quality, processor capacity, distance and availability.

Rather than relying entirely on manual discovery and coordination, WasteLoop AI generates an explainable shortlist of potential processors and supports a human-approved pickup workflow.

---

## 1. The Problem

Bengaluru has a diverse waste ecosystem involving restaurants, apartments, commercial establishments, institutions, recyclers and resource-recovery facilities.

However, identifying the right destination for a particular waste stream can involve manual coordination.

Some of the challenges include:

- Generators may not know which processors accept their waste type.
- Processors have different material acceptance requirements and capacity limits.
- Waste quality and segregation affect processing suitability.
- Distance and pickup availability influence operational feasibility.
- Finding and coordinating with suitable processors can involve repetitive manual work.

**The opportunity:** Build a digital coordination layer that helps connect suitable waste streams with appropriate downstream processors.

## 2. Our Solution

WasteLoop AI provides a structured workflow:

1. **List waste:** Submit material type, quantity, quality, location and pickup availability.
2. **Find matches:** Evaluate processors using eligibility constraints and weighted matching.
3. **Review recommendations:** Display a ranked shortlist with match scores and relevant information.
4. **Approve pickup:** Require explicit human approval before a pickup is authorised.
5. **Track progress:** Maintain pickup status through completion.

### Pickup lifecycle

`PROPOSED → APPROVED → IN_TRANSIT → COMPLETED`

Pickups can also be cancelled.

**Design principle: AI recommends. The backend validates. A human approves.**

## 3. Intelligent Matching Engine

The matching engine first applies eligibility checks to filter unsuitable processors.

It then ranks eligible candidates using four weighted factors:

| Factor | Weight |
|---|---:|
| Material type and quality compatibility | 35% |
| Processor capacity fit | 25% |
| Geographic distance | 20% |
| Availability | 20% |
| **Total** | **100%** |

This approach prioritises suitability before ranking.

A nearby processor should not be recommended if it cannot accept the material or handle the required quantity.

## 4. Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | Streamlit | Interactive application and dashboard |
| Backend | FastAPI | API endpoints and business logic |
| Database | SQLite | Local application data |
| AI orchestration | IBM watsonx Orchestrate | Agent-based matching interaction |
| Agent tool | `find_waste_matches` | Retrieves candidate processor matches |
| Programming language | Python | Application and matching implementation |
| Testing | Pytest | Automated API and matching tests |

## 5. IBM watsonx Orchestrate Integration

The project includes a configured IBM watsonx Orchestrate agent:

**WasteLoop AI Agent**

The agent invokes the `find_waste_matches` tool to retrieve candidate processor matches.

The backend independently recomputes and validates the matching results before returning recommendations to the frontend.

The agent does not independently approve or create pickups.

This separation helps maintain predictable matching behaviour and human control over operational actions.

## 6. Application Features

The Streamlit application contains five main sections:

- **Overview:** Dashboard metrics and recent waste listings.
- **Post Waste:** Submit waste listings.
- **Find Matches:** Retrieve and review ranked processor recommendations.
- **Pickup Approvals:** Propose pickups, approve them and update their status.
- **Directory:** View generator and processor records.

## 7. Prototype Verification

The prototype has been tested locally.

### Demonstrated results

| Test / workflow | Result |
|---|---|
| Live IBM watsonx Orchestrate invocation | Successful |
| Candidate processors evaluated in latest demo run | 4 |
| Ranked matches returned | 3 |
| Backend match validation | Successful |
| Pickup proposal and approval | Successful |
| Pickup status transition to IN_TRANSIT | Successful |
| Pickup completion | Successful |
| Automated test suite | 62 passed |

### Automated test breakdown

- API tests: 5 passed.
- Matching tests: 37 passed.
- Matching drift tests: 20 passed.

The pickup workflow was exercised end-to-end in the local demonstration environment.

## 8. Running the Project Locally

### Prerequisites

- Python 3.10 or later (use a version compatible with the project dependencies).
- Git.
- IBM watsonx Orchestrate credentials and a configured agent for live integration.

### Clone the repository

```bash
git clone https://github.com/aarucodes/WasteLoop-AI.git
cd WasteLoop-AI
```

### Create and activate a virtual environment

Windows:

```cmd
python -m venv venv
venv\Scripts\activate
```

### Install dependencies

```cmd
pip install -r requirements.txt
```

Install the additional Orchestrate client dependencies if required by the project setup:

```cmd
pip install -r tools/orchestrate-requirements.txt
```

### Configure environment variables

Create a local `.env` file in the project root.

Use the variable names below and supply your own credentials:

```env
API_BASE_URL=http://127.0.0.1:8000

ORCHESTRATE_INSTANCE_URL=YOUR_INSTANCE_URL
ORCHESTRATE_AGENT_ID=YOUR_AGENT_ID

USE_MOCK_AGENT=false
```

Never commit your `.env` file, API keys or access tokens.

### Start the backend

In the first terminal:

```cmd
uvicorn api.main:app --reload
```

The backend will be available at:

`http://127.0.0.1:8000`

Health check:

`http://127.0.0.1:8000/health`

### Start the frontend

In a second terminal:

```cmd
streamlit run app/streamlit_app.py
```

The frontend will be available at:

`http://localhost:8501`

The repository also includes Windows startup scripts where applicable.

### Run automated tests

```cmd
pytest
```

## 9. Demo Data and Limitations

The current prototype uses synthetic seed data for demonstration and testing.

Processor names, capacities, listings and example transactions should not be interpreted as verified real-world partnerships or operational records.

The completed pickup shown in the demonstration represents a successful prototype workflow, not independently verified physical waste collection.

The project does not currently claim verified recovered tonnage, carbon savings or environmental credits.

## 10. Future Scope

### Phase 1 — Real-world validation

- Onboard verified Bengaluru waste generators and processors.
- Validate processor licences and material acceptance requirements.
- Replace synthetic data with verified operational records.
- Introduce authentication and role-based access.
- Add real pickup scheduling and notifications.
- Conduct a small operational pilot.

### Phase 2 — Intelligent optimisation

- Improve matching using historical acceptance and completion data.
- Introduce dynamic processor capacity updates.
- Add route-aware matching and pickup consolidation.
- Forecast recurring waste availability.
- Add alerts for delayed pickups and operational issues.

### Phase 3 — Scalable circular economy platform

- Expand coverage across Bengaluru and other cities.
- Integrate with relevant authorised waste management systems.
- Add verified material recovery reporting.
- Develop auditable waste traceability.
- Introduce environmental impact measurement using documented methodologies.

## 11. Project Vision

WasteLoop AI aims to make the next useful destination for waste easier to discover.

By connecting generators with suitable processors through explainable matching and structured coordination, the project explores how technology can support a more connected circular economy.

**Turning Waste into Resources. Building a Smarter Bengaluru.**

---

**Project:** WasteLoop AI  
**Hackathon:** Build with IBM Bob — Bobathon 2026  
**Theme:** Smarter Streets, Better Living  
**Repository:** https://github.com/aarucodes/WasteLoop-AI
