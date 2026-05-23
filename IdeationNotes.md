### System Architecture & Data Flow

- Core agent system using Hermes/OpenClaw for orchestration
  - Hermes runs on Daytona sandbox with full permissions (isolated environment)
  - Agent interfaces: Telegram (easiest), WhatsApp, Slack, Discord options
  - Model: Quinn/Nemotron running on Kishore’s Nvidia machine (shared key for demo)
- Data infrastructure stack:
  - Clickhouse: Price/deals data from flight trackers, e-commerce
  - Sensor: User context, preferences, agent data
  - Nimble: Web scraping API for real-time data gathering
- Agent workflow: User intent → Clickhouse/Sensor query → Nimble scraping → Decision/Alert

### MVP Scope & Prioritization

- V1: Simple product price optimization (Amazon/Walmart focus)
  - Cross-platform price comparison for $100+ purchases
  - Autonomous monitoring with proactive alerts via Telegram
  - Historical price tracking through Clickhouse storage
- V1.1: Flight price tracking integration
- V2: Voice interface for real-time purchase decisions
- V3: Credit card points optimization layer
- Stretch goals: Computer vision for in-store price checking

### Technical Implementation Plan

- Data sources strategy:
  - Start with Nimble’s pre-built Amazon/Walmart scrapers
  - Manual data source identification for demo prep
  - Fake historical data acceptable for initial demo
- Interface approach:
  - V1: Telegram bot for alerts and basic interaction
  - Landing page for user onboarding (time permitting)
  - Voice interface as stretch goal using transcription buffer
- Agent intelligence: Minimal reasoning required due to structured data approach

### Next Steps (30min sprint)

- Individual research phase on Nimble capabilities and data sources
- GitHub repo setup (using Matt’s existing scaffolding)
- Task division:
  - Kishore: Hermes agent setup in Daytona and orchestration with TG setup
  - Team: Nimble integration and Clickhouse data pipeline
  - Sensor integration for user preferences
- Reconvene to finalize interfaces and demo flow
- Target: Working demo by 3:30pm deadline