# Autonomous AI Chief of Staff Agent 🚀

An end-to-end multi-agent system built from scratch to automate enterprise operational workflows. By leveraging modern Large Language Models (LLMs) and the **Model Context Protocol (MCP)**, this system securely connects to local environments, databases, and communication tools to transform raw, messy email threads into fully executed calendar bookings and context-aware responses.

---

## 🛠️ System Architecture & Core Modules

The agent handles operational chaos through a stateful, three-tier agentic pipeline:

### 1. 🔍 The Triage Engine
* **Purpose:** Acts as the primary operational switchboard.
* **Capabilities:** Parses open-ended, multi-topic inbox communication, classifies urgency, extracts key action items, and routes data to subsequent layers based on real-time priority evaluation.

### 2. 📝 The Draft Desk
* **Purpose:** Context-aware, human-aligned correspondence generation.
* **Capabilities:** Maintains system memory across user interactions to author hyper-personalized, professional email replies. Built to avoid standard robotic tones by grounding its generation heavily in the extracted intent of the initial thread.

### 3. 📅 The Action Layer
* **Purpose:** Real-world side-effect execution.
* **Capabilities:** Interlaces natively with external APIs (such as Google Calendar or Outlook) to map schedules, resolve availability conflicts, and book meetings directly from context derived in the thread.

---

## 🧠 Core Technical Highlights

* **Model Context Protocol (MCP):** Avoided standard LLM text-silos by implementing MCP servers to securely bridge cognitive routing with local execution environments and developer tools.
* **Cognitive Chaining & State Management:** Configured a dynamic task-orchestration layer where specialized sub-agents intelligently pass state and pass execution tokens down the tool chain.
* **Human-in-the-Loop (HITL) Architecture:** Prioritizes enterprise safety by establishing rigid approval gates. The agent executes complex multi-step reasoning autonomously but halts before performing destructive or live mutations (such as booking a calendar slot or dispatching a final email outbox request) until it receives a manual edit, reject, or approval override.

---

## 🚀 Getting Started

### Prerequisites
* Python 3.10+
* Local MCP Server Configuration
* Required LLM API Credentials (e.g., OpenAI/Anthropic keys)

### Installation
1. Clone the repository:
   ```bash
   git clone [https://github.com/Dikshas09/Chief_of_Staff.git](https://github.com/Dikshas09/Chief_of_Staff.git)
   cd Chief_of_Staff
