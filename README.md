# GenAI-Driven MIL Verification Framework (PoC-1)

An automated Model-in-the-Loop (MIL) and Hardware-in-the-Loop (HIL) verification framework for automotive control systems, featuring **Option B: Shift-Left SIL / Target-Fitness Screening**.

Demonstrated on an Adaptive Cruise Control (**mpcACCsystem**) controller benchmark.

---

## Key Highlights

- **Stage A: Requirements Parsing**: Formal EARS (Easy Approach to Requirements Syntax) requirements parsed into structured, validated Test-Intent JSONs using Groq LLM with Draft-07 JSON Schema validation.
- **Stage B: MIL Test Generation**: Dynamic synthesis of executable Python MIL test scripts evaluating functional and safety requirements.
- **Stage B: HIL Stub Generation**: Automated generation of dSPACE MicroLabBox YAML stubs for real-time target execution.
- **Option B: Target-Fitness Screening**: Shift-left SIL screening to assess controller resilience under hardware constraints:
  - **Precision Degradation**: `float64` $\to$ `float32` $\to$ `fixed16` $\to$ `fixed8` word-length emulation.
  - **Sample-Time Degradation**: $T_s = 0.10\text{ s} \to 0.20\text{ s} \to 0.50\text{ s}$.
- **Automated Scorecards**: Generation of formatted multi-panel plots (`results/scorecard.png`) and tabular reports (`results/scorecard.txt`).
- **Resilience**: Full deterministic fallback support for offline / CI environments.

---

## Project Structure

```text
├── config/
│   └── architecture_contract.json      # Draft-07 JSON Schema for GenAI Test-Intent
├── requirements/
│   └── acc_requirements.py            # Formalized EARS requirements (ACC-REQ-001..005)
├── src/
│   ├── genai/
│   │   ├── requirement_parser.py       # Stage A: EARS -> Test-Intent JSON (Groq/Fallback)
│   │   ├── test_generator_mil.py       # Stage B: Intent -> Executable MIL tests
│   │   └── test_generator_hil.py       # Stage B (HIL): Intent -> dSPACE YAML stubs
│   ├── models/
│   │   ├── acc_controller.py           # Python MPC ACC baseline with mode arbitration
│   │   ├── plant_model.py              # Longitudinal vehicle dynamics (ego & lead)
│   │   └── target_fitness_degrader.py  # Multi-rate & multi-precision screening (Option B)
│   └── utils/
│       ├── precision_emulator.py       # Word-length & fraction emulation (float32, fixed16, fixed8)
│       └── signal_metrics.py           # RMS error, max absolute error, divergence index
├── tests/
│   ├── mil/                            # Generated executable MIL test scripts & master runner
│   │   ├── intents/                    # Validated JSON test intents
│   │   ├── test_acc_req_001.py .. 005.py
│   │   └── run_all_mil_tests.py        # Master test runner with --dtype flag
│   └── hil/                            # Generated HIL test stubs (YAML)
├── results/
│   ├── scorecard.py                    # Scorecard generator (text + matplotlib visualization)
│   ├── scorecard.txt                   # ASCII Target-Fitness Scorecard
│   └── scorecard.png                   # Multi-panel visualization plot
├── .env.example                        # Template for environment configuration
├── requirements.txt                    # Project dependencies
└── run_poc.py                          # Unified 8-step orchestrator
```

---

## Setup & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/KrithikVishal/genai-mil-verification-framework.git
cd genai-mil-verification-framework
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` and add your Groq API key:
```bash
cp .env.example .env
```
In `.env`:
```ini
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b
```
*(If no API key is provided, the framework will use deterministic fallbacks).*

---

## Usage

### Run the Complete 8-Step Pipeline (Python)
```bash
python run_poc.py
```

### Run on Real MATLAB Engine (R2024a)
You can execute the entire verification suite and Option B Target-Fitness screening directly on real MATLAB:

**Via Python CLI:**
```bash
python run_poc.py --matlab
```
*(Automatically locates your MATLAB installation, runs `run_poc.m` in batch mode, and streams results).*

**Directly in MATLAB Desktop / CLI:**
```matlab
run_poc
```
or from the shell:
```bash
matlab -batch "run_poc; exit"
```

### Additional Python Pipeline Modes
```bash
# Run in deterministic offline mode (no LLM calls)
python run_poc.py --no-llm

# Skip LLM code generation and use cached test intents
python run_poc.py --skip-gen

# Run specific steps (e.g., steps 5, 6, 7)
python run_poc.py --steps 5,6,7
```

### Run Generated MIL Tests Directly
```bash
# Baseline precision (float64)
python tests/mil/run_all_mil_tests.py --dtype float64

# Emulated fixed-point (fixed16)
python tests/mil/run_all_mil_tests.py --dtype fixed16

# Emulated fixed-point (fixed8)
python tests/mil/run_all_mil_tests.py --dtype fixed8
```

---

## Target-Fitness Verdict Summary

| Target Variant | Divergence | REQ-001 | REQ-002 | REQ-004 | Memory Footprint | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **float64 (ref)** | Never | PASS | PASS | PASS | 48 B | **PASS (Baseline)** |
| **float32** | Never | PASS | PASS | PASS | 24 B | **PASS** |
| **fixed16** | Never | PASS | PASS | PASS | 12 B | **PASS** (75% memory saved) |
| **fixed8** | 3.10 s | FAIL | FAIL | PASS | 6 B | **FAIL** (Quantization breakdown) |
| **Ts = 0.20s** | Never | PASS | PASS | PASS | 48 B | **PASS** (50% CPU cycles saved) |
| **Ts = 0.50s** | 5.80 s | FAIL | PASS | PASS | 48 B | **FAIL** (Discretization lag) |
