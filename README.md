# WasteLoop AI

### Smarter waste discovery, intelligent matching, and human-approved recovery for Bengaluru

**Build with IBM Bob · Bobathon 2026 · Build for Bengaluru**

WasteLoop AI is an AI-assisted waste-to-resource coordination platform that helps bulk waste generators discover suitable waste processors, compare recommendations, and coordinate human-approved pickups.

It connects the waste-discovery process across apartments, commercial establishments, and other bulk generators with recyclers, composting facilities, and resource-recovery processors.

**The core principle: AI-assisted discovery, deterministic matching, and human-controlled decisions.**

---

## The problem

Bulk waste generators may struggle to identify processors that accept their specific waste materials, quality grades, quantities, and collection windows.

Finding a suitable processor can involve repetitive manual research and coordination. At the same time, processors have different material requirements, capacity constraints, and availability.

WasteLoop AI brings these considerations into one structured workflow.

## How WasteLoop works

1. **List waste** — Submit the material type, quantity, quality grade, location, and availability window.
2. **Find matches** — Evaluate processors using eligibility checks and weighted ranking.
3. **Review recommendations** — See ranked processors with match scores, distances, and explanations.
4. **Propose a pickup** — Create a proposed pickup for the selected processor.
5. **Human approval** — An authorised person explicitly approves the pickup.
6. **Track progress** — Update the pickup through its lifecycle.

### Pickup lifecycle

`PROPOSED → APPROVED → IN_TRANSIT → COMPLETED`

A pickup can also be cancelled where permitted.

**The AI agent does not approve or complete pickups.** The backend validates the workflow, and a human must explicitly approve a proposed pickup.

---

## Matching engine

WasteLoop uses a deterministic Python matching engine in `matching/engine.py`.

Matching happens in two stages.

### Stage 1: Hard eligibility checks

A processor is excluded if it fails any required check:

- Material compatibility
- Minimum accepted quality grade
- Minimum quantity
- Available capacity headroom
- Overlapping availability dates

A processor must pass the eligibility checks before it can be ranked.

### Stage 2: Weighted ranking

Eligible processors are ranked using the following weights:

| Matching factor | Weight |
|---|---:|
| Material compatibility and quality | 35% |
| Capacity fit | 25% |
| Geographical proximity | 20% |
| Availability | 20% |
| **Total** | **100%** |

Distance is calculated using the Haversine formula, representing straight-line geographical distance rather than actual road distance.

The engine returns ranked recommendations with score breakdowns and explanations. The same inputs produce consistent results, making the matching process testable and reproducible.

---

## IBM watsonx Orchestrate integration

WasteLoop AI integrates IBM watsonx Orchestrate to provide an agent-based interface for processor discovery.

**Agent configuration:** `agents/wasteloop_agent.yaml`

**Matching tool:** `tools/find_waste_matches.py`

The `wasteloop_agent` uses the `find_waste_matches` tool to:

- Accept waste-listing information.
- Evaluate candidate processors.
- Return ranked recommendations.
- Explain why processors are suitable.
- Provide traceability to the data snapshot used.

### Why combine an AI agent with deterministic matching?

The agent provides a natural-language interaction layer. The Python matching engine handles eligibility and scoring, while the backend independently revalidates the results against its own data.

This separation prevents an LLM from becoming the authority for operational decisions.

**AI recommends. The backend validates. A human approves.**

---

## Application features

The Streamlit application provides five main areas:

- **Overview:** Dashboard showing generator, processor, listing, and pickup information.
- **Post Waste:** Create and manage waste listings. Users can also register a new generator through the workflow.
- **Find Matches:** Request and review ranked processor recommendations.
- **Pickup Approvals:** Propose pickups, explicitly approve them, and track their status.
- **Directory:** Browse generator and processor records.

### Screenshots

#### Overview dashboard

![WasteLoop AI overview](images/Picture1.png)

#### Waste listing

![Waste listing workflow](images/Picture7.png)

#### Generator registration

![Generator registration workflow](images/Picture3.png)

#### Processor matching

![WasteLoop AI matching](images/Picture5.png)

#### Pickup approvals

![Pickup approvals](images/Picture6.png)

#### Generator and processor directory

![Generator and processor directory](images/Picture4.png)

---

## Technology stack

| Component | Technology |
|---|---|
| Frontend | Streamlit |
| Backend | FastAPI |
| Database | SQLite, configurable through `DATABASE_URL` |
| ORM | SQLAlchemy |
| Validation | Pydantic |
| Matching engine | Python |
| AI agent orchestration | IBM watsonx Orchestrate |
| Agent tool | Python |
| Testing | pytest |

---

## Architecture

```text
             Streamlit Application
                      |
                      v
                FastAPI Backend
                      |
             User requests matches
                      |
                      v
          IBM watsonx Orchestrate
                wasteloop_agent
                      |
                      v
              find_waste_matches
                 READ-ONLY TOOL
                      |
                      v
             Ranked recommendations
                      |
                      v
          Backend independently validates
             matching/engine.py
                      |
                      v
                Human review
                      |
                      v
              Propose pickup
                      |
                      v
             Explicit approval
                      |
                      v
              Pickup status tracking
```

The backend remains responsible for validating matching results and enforcing pickup state transitions. The agent is not given authority to approve pickups.

---

## Prototype verification

WasteLoop AI was tested through automated tests and a live integration workflow.

### Live IBM watsonx Orchestrate test

The live agent integration was successfully tested through the Streamlit application with mock mode disabled.

In the recorded test:

- Four candidate processors were evaluated.
- Three eligible recommendations were returned.
- Recommendations included match scores and distances.
- The backend independently recomputed and validated the matching results.

### Pickup workflow

The following workflow was manually tested:

1. Request processor matches.
2. Propose a pickup with a selected processor.
3. Explicitly approve the pickup.
4. Update its status to `IN_TRANSIT`.
5. Mark the pickup `COMPLETED`.

The completed pickup was also verified through the backend API.

### Automated tests

**62 tests passed.**

| Test suite | Tests | Coverage |
|---|---:|---|
| `tests/test_matching.py` | 37 | Eligibility, scoring, ranking, and matching behaviour |
| `tests/test_matching_drift.py` | 20 | Consistency between matching implementations and data |
| `tests/test_api.py` | 5 | API behaviour and pickup workflow rules |
| **Total** | **62** | |

---

## How IBM Bob contributed

IBM Bob was used throughout the development process as an AI-assisted engineering tool.

Its contribution included:

- **Architecture:** Structuring the application and separating agent responsibilities from backend decision-making.
- **Matching engine:** Supporting implementation and refinement of eligibility checks, weighted scoring, and explanations.
- **Backend development:** Assisting with FastAPI routes, database models, schemas, and validation.
- **Orchestrate integration:** Supporting agent configuration and tool integration.
- **Frontend development:** Assisting with Streamlit workflows and application structure.
- **Testing and debugging:** Helping develop tests, investigate issues, and improve consistency across components.
- **Documentation:** Supporting project documentation and technical explanations.

All generated outputs were reviewed, adapted, and tested as part of the implementation process.

---

## Running the project locally

### Prerequisites

- Python 3.10 or later
- Git
- IBM watsonx Orchestrate access for live agent functionality

### 1. Clone the repository

```bash
git clone https://github.com/aarucodes/WasteLoop-AI.git
cd WasteLoop-AI
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
```

On Windows:

```bash
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create your local `.env` file using `.env.example` as the reference.

The application uses SQLite by default:

```text
sqlite:///./wasteloop.db
```

To use PostgreSQL, configure `DATABASE_URL` with the appropriate connection string and database driver.

For local development, `USE_MOCK_AGENT=true` enables mock-agent mode. Configure the required Orchestrate credentials and settings in `.env` to use the live agent.

**Never commit `.env` or API credentials to GitHub.**

### 5. Start the backend

```bash
uvicorn api.main:app --reload
```

The API will be available at:

`http://127.0.0.1:8000`

### 6. Start the frontend

Open a second terminal, activate the virtual environment, and run:

```bash
streamlit run app/streamlit_app.py
```

The application will be available at:

`http://localhost:8501`

Alternatively, use the supplied Windows startup scripts:

- `START_BACKEND.bat`
- `START_FRONTEND.bat`

### 7. Run automated tests

```bash
pytest
```

---

## Project structure

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
│   ├── schemas.py
│   └── routers/
│       ├── _helpers.py
│       ├── generators.py
│       ├── processors.py
│       └── waste_listings.py
│
├── app/
│   ├── common.py
│   ├── streamlit_app.py
│   └── pages/
│       ├── 1_Apartments.py
│       └── 2_Processor.py
│
├── data/
│   ├── generators.csv
│   ├── processors.csv
│   ├── processor_capacity.csv
│   └── waste_listings.csv
│
├── images/
│   ├── Picture1.png
│   ├── Picture2.png
│   ├── Picture3.png
│   ├── Picture4.png
│   ├── Picture5.png
│   ├── Picture6.png
│   └── Picture7.png
│
├── matching/
│   └── engine.py
│
├── scripts/
│   ├── delete-all.sh
│   ├── import-all.sh
│   ├── inspect_smoke_flat_result.py
│   ├── seed_db.py
│   ├── smoke_test_agent.py
│   ├── smoke_test_agent_v2.py
│   └── smoke_test_flat.py
│
├── tests/
│   ├── test_api.py
│   ├── test_matching.py
│   └── test_matching_drift.py
│
├── tools/
│   ├── find_waste_matches.py
│   └── orchestrate-requirements.txt
│
├── .env.example
├── .gitignore
├── pytest.ini
├── requirements.txt
├── START_BACKEND.bat
└── START_FRONTEND.bat
```

---

## Demo data and limitations

WasteLoop AI is a functional prototype, not yet a production waste-management network.

- The included demonstration dataset is synthetic.
- Processor records and authorisations have not been independently verified as real-world registrations.
- The application does not yet connect to a live network of waste generators and processors.
- Distances are straight-line estimates, not road travel distances.
- The recorded pickup lifecycle demonstrates application functionality; it does not establish that physical waste was collected or processed.
- No measured carbon savings, recovered tonnage, or real-world time savings are claimed.

### Future scope

Potential next steps include:

- Verification of processor identity, licences, and permitted waste categories.
- Integration with live processor capacity and availability.
- Road-distance and route optimisation.
- Role-based access, audit logs, and stronger transaction traceability.
- A ward-level pilot with verified generators and processors.
- Kannada and WhatsApp-based access.

---

## Project

**GitHub:** [aarucodes/WasteLoop-AI](https://github.com/aarucodes/WasteLoop-AI)

Built with IBM Bob for **Bobathon 2026 — Build for Bengaluru**.

*Building a smarter Bengaluru, one human-approved pickup at a time.*
