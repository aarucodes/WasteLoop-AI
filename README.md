# WasteLoop AI
### Smarter waste discovery, intelligent matching, and human-approved recovery for Bengaluru

**Problem:** Bulk waste generators in Bengaluru often struggle to identify suitable nearby waste processors and coordinate pickups. WasteLoop AI simplifies this process through structured waste listings, intelligent processor matching, and human-supervised pickup coordination.

Built for **IBM Bobathon 2026 — Build for Bengaluru**

---

## 1. What is WasteLoop AI?

WasteLoop AI is an AI-assisted waste coordination platform that connects bulk waste generators with suitable waste processors.

Generators can list available waste, receive ranked processor recommendations, understand why processors were matched, and propose pickups. Processors are evaluated using material compatibility, quality requirements, available capacity, geographical proximity, and date availability.

The platform combines IBM watsonx Orchestrate with a deterministic Python matching engine. AI makes the interaction easier to understand, while backend validation keeps matching decisions consistent and independently verifiable.

**The key principle: AI-assisted discovery, deterministic matching, and human-controlled decisions.**

## 2. Core Workflow

1. **List waste:** A generator submits material type, quantity, quality grade, location, and availability.
2. **Find matches:** The user requests processor recommendations through the WasteLoop interface.
3. **Review recommendations:** The system displays ranked processors, distances, scores, and explanations.
4. **Propose pickup:** A proposed pickup is created for a selected processor.
5. **Human approval:** The pickup requires an explicit approval action.
6. **Track progress:** The pickup moves through its lifecycle until completion.

Pickup lifecycle:

`PROPOSED → APPROVED → IN_TRANSIT → COMPLETED`

Pickups can also be cancelled from a non-terminal state. The agent does not independently approve or complete pickups.

## 3. Matching Engine

The matching engine is implemented in `matching/engine.py`.

It uses a two-stage process:

**Stage 1 — Hard eligibility checks**

Processors are rejected when they fail mandatory requirements, including:

- `material_mismatch`
- `grade_too_low`
- `quantity_below_minimum`
- `insufficient_capacity_headroom`
- `no_date_overlap`

**Stage 2 — Weighted ranking**

Eligible processors are ranked using the following scoring weights:

| Matching criterion | Weight |
|---|---:|
| Material compatibility and quality | 35% |
| Capacity fit | 25% |
| Geographic proximity | 20% |
| Date availability overlap | 20% |

Geographic distance uses the Haversine formula with an Earth radius of 6,371 km. The distance score is capped at a 50 km reference distance.

This is straight-line coordinate distance, not road or live GPS distance.

The matching engine is deterministic: the same inputs and data produce the same results.

## 4. Technology Stack

| Component | Technology |
|---|---|
| Frontend | Streamlit |
| Backend | FastAPI |
| Database | SQLite, with configurable PostgreSQL support |
| ORM | SQLAlchemy |
| AI orchestration | IBM watsonx Orchestrate |
| Agent | `wasteloop_agent` |
| Matching logic | Python |
| Testing | pytest |

## 5. System Architecture

```text
             GENERATOR / USER
                    |
                    v
             STREAMLIT FRONTEND
                    |
                    v
              FASTAPI BACKEND
                    |
                    v
          IBM watsonx Orchestrate
                    |
                    v
              WasteLoop Agent
                    |
                    v
           find_waste_matches Tool
             (READ_ONLY access)
                    |
                    v
         Ranked recommendations
          + explanations + ID
                    |
                    v
          BACKEND REVALIDATION
                    |
                    v
          Deterministic Matching
              Engine + DB
                    |
                    v
             RESULTS TO USER
                    |
                    v
          HUMAN-INITIATED ACTION
                    |
                    v
            PICKUP PROPOSAL
                    |
                    v
          EXPLICIT APPROVAL
                    |
                    v
           PICKUP STATUS TRACKING
```

The Orchestrate tool operates on a versioned synthetic snapshot. The FastAPI backend independently recomputes and validates the matching results against its database before presenting the final recommendations.

This separation is intentional: the agent provides natural-language interaction and explanations, while deterministic backend logic provides consistency and validation.

The agent's matching tool is read-only. Pickup creation and status transitions are handled through separate backend operations initiated by the user.

## 6. IBM watsonx Orchestrate Integration

WasteLoop AI uses IBM watsonx Orchestrate to provide an agent-based interface for processor discovery.

**Agent configuration:** `agents/wasteloop_agent.yaml`

The `wasteloop_agent` is configured with a ReAct-style interaction flow and the `find_waste_matches` tool.

**Matching tool:** `tools/find_waste_matches.py`

The tool:
- Accepts structured waste listing inputs.
- Evaluates candidate processors using the matching logic.
- Returns ranked recommendations and score breakdowns.
- Provides explanations for the recommendations.
- Returns a snapshot identifier so the result can be traced to its data snapshot.
- Operates with read-only permissions.

The agent presents the recommendations to the user, but does not independently create, approve, or complete pickups.

### Why use both an AI agent and deterministic matching?

The agent makes the system easier to interact with through natural-language requests and explanations. The deterministic matching engine handles eligibility and scoring, and the backend independently validates the result.

This avoids relying on an LLM to make final operational decisions.

## 7. Application Features

The Streamlit application in `app/streamlit_app.py` is organised into five main areas:

- **Overview:** Dashboard with generator, processor, listing, and pickup statistics.
- **Post Waste:** Create and manage waste listings.
- **Find Matches:** Request and review processor recommendations.
- **Pickup Approvals:** Propose, approve, and track pickup status.
- **Directory:** Browse generator and processor records.

The application uses synthetic demonstration records. These are explicitly identified as synthetic rather than presented as verified real-world registrations.

## 8. Prototype Verification

WasteLoop AI has been tested as a working end-to-end prototype.

### Live Orchestrate integration

A successful live IBM watsonx Orchestrate invocation was verified through the Streamlit interface.

In the recorded test:
- Four candidate processors were evaluated.
- Three eligible recommendations were displayed.
- Each recommendation included a score and distance.
- The backend independently recomputed the matching results.
- **Live IBM watsonx Orchestrate integration was successfully tested through the Streamlit application with mock mode disabled.** Four candidate processors were evaluated, and three eligible recommendations were returned. The backend independently recomputed and validated the results.

### Pickup lifecycle

The following workflow was manually tested:

1. Requested processor matches.
2. Proposed a pickup with the top-ranked processor.
3. Approved the pickup.
4. Changed its status to `IN_TRANSIT`.
5. Marked the pickup `COMPLETED`.

The completed pickup was also verified through the backend API.

### Automated tests

<badge color="success">62 tests passed</badge>

| Test file | Tests passed |
|---|---:|
| `tests/test_matching.py` | 37 |
| `tests/test_matching_drift.py` | 20 |
| `tests/test_api.py` | 5 |
| **Total** | **62** |

The tests cover matching eligibility, scoring, consistency between matching implementations, API behaviour, and pickup workflow rules.

## 9. Prototype Impact

WasteLoop AI aims to reduce the time and effort required for bulk waste generators to identify suitable processors.

To evaluate this, compare manual processor discovery with the application-assisted matching workflow.

| Measurement | Time |
|---|---:|
| Manual processor search | **[INSERT MEASURED TIME]** |
| WasteLoop AI matching workflow | **[INSERT MEASURED TIME]** |
| Time saved | **[CALCULATE AFTER MEASUREMENT]** |

**Measurement context:** This is intended to be a controlled prototype measurement using the same waste listing and synthetic processor dataset for both approaches. It is not a claim of real-world deployment impact.

The prototype also demonstrates a complete human-supervised pickup workflow, from matching through completion.

## 10. Running the Project

### Prerequisites

- Python 3.10 or later
- Git
- IBM watsonx Orchestrate access for live agent functionality

### Clone the repository

```bash
git clone https://github.com/aarucodes/WasteLoop-AI.git
cd WasteLoop-AI
```

### Create a virtual environment

```bash
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure environment

The application uses SQLite by default. `DATABASE_URL` can be configured to use PostgreSQL with the appropriate database driver installed.

`USE_MOCK_AGENT` defaults to `true` for local development and mock-mode testing.

For the actual hackathon demonstration, use the deployed IBM watsonx Orchestrate agent and the live integration rather than mock mode.


### Start the backend

```bash
uvicorn api.main:app --reload
```

### Start the frontend

In a separate terminal:

```bash
streamlit run app/streamlit_app.py
```

### Run tests

```bash
pytest
```

## 11. Demo Data and Current Limitations

WasteLoop AI is currently a functional prototype, not a production waste-management network.

The following limitations are important:

- Generator, processor, capacity, and listing records are synthetic demonstration data.
- Processor names do not represent verified partnerships.
- The prototype does not verify actual KSPCB or CPCB authorisations.
- No real-world waste collection or processing has been independently verified.
- Completed demo pickups do not establish verified material recovery.
- No carbon savings or environmental credits are claimed.
- Haversine distance represents straight-line distance, not actual road travel.
- The current prototype has not been validated through a live municipal deployment.

The platform is designed to demonstrate the workflow and technical architecture. Real-world deployment would require processor onboarding, regulatory checks, operational validation, and appropriate agreements.

## 12. Future Scope

All phases below are planned enhancements. They are not represented as implemented features.

### Phase 1 — Trust and real-world validation
- Onboard real generators and processors.
- Introduce KYC and licence-document collection.
- Verify relevant authorisations against issuing authority records.
- Add role-based access control and audit logging.
- Introduce SMS and WhatsApp notifications.
- Conduct a ward-level pilot with appropriate local stakeholders.

### Phase 2 — Better matching and coordination
- Use historical pickup and processing records to improve recommendations.
- Support processor-managed, dynamically updated capacity.
- Add road-distance and route-aware matching.
- Introduce demand forecasting and operational alerts.
- Explore multi-stop pickup coordination.

### Phase 3 — Accessibility and traceability
- Add Kannada and English language support.
- Explore WhatsApp-based access for smaller waste generators.
- Provide segregation guidance while users create waste listings.
- Add pickup evidence, actual weight records, processor receipts, and material traceability.
- Explore integrations with relevant municipal systems, subject to permissions and agreements.

### Phase 4 — Waste reduction and marketplace capabilities
- Develop a two-sided generator and processor directory.
- Provide personalised waste-reduction and segregation suggestions.
- Explore price discovery between generators and processors.

## 13. IBM Bob — Development Contributions

IBM Bob was a major development collaborator throughout the creation of WasteLoop AI. It was used for architecture design, implementation, code generation, debugging, test development, integration support, and documentation.

Rather than using Bob only for isolated code suggestions, the project involved using it across multiple stages of the software development lifecycle.

### Architecture and system design

Bob assisted in designing the overall application architecture, including:

- The Streamlit and FastAPI application structure.
- The separation between AI orchestration and deterministic matching.
- The human-approval boundary for pickup operations.
- The data flow between the Orchestrate agent, matching tool, backend, and database.

### Backend and database development

Bob assisted with the implementation of the backend and data layer, including:

- `api/models.py` — SQLAlchemy data models and application enumerations.
- `api/schemas.py` — Pydantic request and response schemas.
- `api/database.py` — database engine, session management, and initialisation.
- `api/main.py` — FastAPI application and API functionality.

### Matching engine development

Bob played a major role in developing `matching/engine.py`, including the deterministic eligibility and ranking architecture.

This involved:
- Material and quality compatibility.
- Quantity and capacity checks.
- Geographic distance calculations.
- Availability overlap.
- Weighted scoring and match explanations.
- Structured matching inputs and outputs.

### IBM watsonx Orchestrate integration

Bob assisted with the development and configuration of:

- `agents/wasteloop_agent.yaml` — agent definition, instructions, and tool configuration.
- `tools/find_waste_matches.py` — the matching tool exposed to the Orchestrate agent.
- Structured tool inputs and outputs.
- Read-only tool permissions.
- Integration and debugging of the live agent workflow.

### Frontend development

Bob assisted with the implementation and refinement of `app/streamlit_app.py`, including the dashboard, waste listing workflow, matching interface, pickup approval interface, and directory views.

### Testing and debugging

Bob also contributed to test development and debugging, including:

- `tests/test_matching.py`
- `tests/test_matching_drift.py`
- `tests/test_api.py`

The matching drift tests help ensure that the agent-side matching implementation and backend matching engine remain consistent.

Bob was also used to investigate integration issues, diagnose errors, refine implementation details, and improve the overall reliability of the prototype.

### Documentation and project structure

Bob assisted in generating and refining the project documentation, repository structure, synthetic seed data, and setup instructions.

### Human review and validation

Bob's generated code and recommendations were reviewed, adapted, integrated, and tested as part of the development process. The final implementation was validated through automated tests, live Orchestrate invocation, backend checks, and manual testing of the pickup lifecycle.

**WasteLoop AI demonstrates how IBM Bob can contribute beyond code completion: from system architecture and implementation to integration, debugging, testing, and documentation of a working AI-assisted application.**

---

## 14. Repository Structure

```text
WasteLoop-AI/
│
├── agents/
│   └── wasteloop_agent.yaml
│
├── api/
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   └── schemas.py
│
├── app/
│   └── streamlit_app.py
│
├── data/
│   ├── generators.csv
│   ├── processors.csv
│   ├── processor_capacity.csv
│   └── waste_listings.csv
│
├── matching/
│   └── engine.py
│
├── tests/
│   ├── test_api.py
│   ├── test_matching.py
│   └── test_matching_drift.py
│
├── tools/
│   └── find_waste_matches.py
│
├── requirements.txt
└── README.md
```

---

**WasteLoop AI — Smarter Streets, Better Living.**

*Built with Python, Streamlit, FastAPI, IBM watsonx Orchestrate, and IBM Bob.*
