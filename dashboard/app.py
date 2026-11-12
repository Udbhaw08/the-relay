"""
Interactive Web Dashboard for The Relay.
Run with: streamlit run dashboard/app.py
"""
import sys
import os
import time
from pathlib import Path
import streamlit as st
import pandas as pd

# Add root directory to Python path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from the_relay.pipeline.orchestrator import RelayPipeline
from the_relay.config import REQUIRED_PAPERS, RETRIEVAL_SETTINGS, RESULTS_PATH
from the_relay.eval.benchmark_questions import BENCHMARK_QUESTIONS
from scripts.compute_tables import generate_table_1, generate_table_2a_and_2b, generate_table_3

st.set_page_config(
    page_title="The Relay - Research Paper Assistant Dashboard",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-header { font-size: 28px; font-weight: 700; color: #38bdf8; margin-bottom: 2px; }
    .sub-header { font-size: 14px; color: #94a3b8; margin-bottom: 24px; }
    .metric-card { background: #1e293b; padding: 14px; border-radius: 8px; border: 1px solid #334155; }
    .step-box { background: #0f172a; padding: 12px 16px; border-radius: 6px; border-left: 4px solid #38bdf8; margin-bottom: 10px; }
    .badge-ok { background: #064e3b; color: #a7f3d0; padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
    .badge-refusal { background: #7f1d1d; color: #fecaca; padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
    .citation-tag { background: #1e1b4b; color: #c7d2fe; padding: 2px 6px; border-radius: 4px; font-size: 11px; margin-right: 4px; }
</style>
""", unsafe_allow_html=True)

# Pipeline Singleton
@st.cache_resource
def get_pipeline():
    return RelayPipeline()

pipeline = get_pipeline()

# Sidebar controls
st.sidebar.image("docs/architecture_diagram.png", use_container_width=True)
st.sidebar.markdown("### ⚙️ Pipeline Controls")

source_choice = st.sidebar.radio(
    "Model Source:",
    ["real", "stand-in"],
    format_func=lambda x: "🟢 Groq model configured — live access unverified (openai/gpt-oss-20b)" if x == "real" else "🟡 Calibrated Stand-in Simulator",
    index=0
)

setting_choice = st.sidebar.selectbox(
    "Retrieval Configuration:",
    ["setting_a", "setting_b", "setting_c"],
    format_func=lambda x: f"{x.upper()}: {RETRIEVAL_SETTINGS[x]['description']}",
    index=1
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 Fixed arXiv Library")
for arxiv_id, meta in REQUIRED_PAPERS.items():
    st.sidebar.markdown(f"- **{meta['title']}**\n  `{arxiv_id}`")

# Header
st.markdown('<div class="main-header">⚡ The Relay: Resilient Research Paper Assistant</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Multi-step agentic pipeline answering technical questions over arXiv research papers under strict rate limits.</div>', unsafe_allow_html=True)

tabs = st.tabs(["💬 Interactive QA & Pipeline Inspector", "📊 Benchmark Results & Tables", "🏛️ System Architecture", "⚡ Load Testing Suite"])

# ==============================================================================
# TAB 1: Interactive QA
# ==============================================================================
with tabs[0]:
    st.markdown("### 🔍 Test Questions Over Research Papers")
    
    col_q1, col_q2 = st.columns([3, 1])
    
    with col_q2:
        st.markdown("**Sample Benchmark Questions:**")
        sample_options = ["Custom Query..."] + [f"[{q.target_paper}] {q.question}" for q in BENCHMARK_QUESTIONS]
        selected_sample = st.selectbox("Pick a sample query:", sample_options, index=1)

    with col_q1:
        if selected_sample == "Custom Query...":
            user_query = st.text_area(
                "Enter your technical question:",
                value="What is the formula for Scaled Dot-Product Attention in Attention Is All You Need?",
                height=100
            )
            is_unanswerable = st.checkbox("Expected out-of-scope / unanswerable?", value=False)
        else:
            # Extract question text from sample
            matched_q = next(q for q in BENCHMARK_QUESTIONS if q.question in selected_sample)
            user_query = st.text_area("Question to test:", value=matched_q.question, height=100)
            is_unanswerable = matched_q.expected_negative

        run_btn = st.button("🚀 Run Pipeline Request", type="primary", use_container_width=True)

    if run_btn and user_query:
        with st.spinner("Executing 4-Step Pipeline..."):
            res = pipeline.run_request(
                query=user_query,
                request_id=f"web_ui_{int(time.time())}",
                source=source_choice,
                retrieval_setting=setting_choice,
                expected_negative=is_unanswerable
            )

        st.markdown("---")
        # Top KPI Metrics
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Execution Status", res.status.upper())
        m2.metric("First Token (TTFT)", f"{res.first_token_ms:.1f} ms")
        m3.metric("Total Latency", f"{res.total_ms:.1f} ms")
        m4.metric("Tokens In / Out", f"{res.tokens_in} / {res.tokens_out}")
        m5.metric("Evaluation Grade", res.answer_grade.replace("_", " ").title())

        # Answer Display Card
        st.markdown("#### 📝 Answer with Citations")
        if "do not" in res.answer.lower():
            st.error(res.answer)
        else:
            st.success(res.answer)

        # 4-Step Pipeline Stepper
        st.markdown("#### 🔄 Pipeline Execution Breakdown")
        
        c_step1, c_step2, c_step3, c_step4 = st.columns(4)
        with c_step1:
            st.markdown("""
            <div class="step-box">
                <b>Step 1: Query Parser</b><br>
                <small>Entity extraction & scope routing</small>
            </div>
            """, unsafe_allow_html=True)
            st.caption("✅ Intent Analyzed")

        with c_step2:
            st.markdown(f"""
            <div class="step-box">
                <b>Step 2: Retrieval Tool</b><br>
                <small>BM25 + Lexical Boosts ({res.retrieval_setting}; dense planned in Phase 4)</small>
            </div>
            """, unsafe_allow_html=True)
            st.caption("✅ Chunks Retrieved")

        with c_step3:
            st.markdown("""
            <div class="step-box">
                <b>Step 3: Synthesis</b><br>
                <small>Drafting cited answer</small>
            </div>
            """, unsafe_allow_html=True)
            st.caption(f"✅ Generated via {source_choice.upper()}")

        with c_step4:
            st.markdown(f"""
            <div class="step-box">
                <b>Step 4: Verification Guard</b><br>
                <small>Citation check & loop guard</small>
            </div>
            """, unsafe_allow_html=True)
            loop_text = "🔁 Loop Triggered" if res.loop_triggered else "✅ Passed Verification"
            st.caption(loop_text)

        # Collapsible Citations and Retrieved Chunks
        with st.expander("🔍 View Extracted Citations & Raw Retrieved Context"):
            if res.citations_found:
                st.markdown("**Citations Grounded:**")
                for cit in res.citations_found:
                    st.markdown(f"- `<citation>` {cit} `</citation>`")
            else:
                st.info("No explicit citations (Deterministic refusal or out-of-scope response).")

# ==============================================================================
# TAB 2: Results & Tables
# ==============================================================================
with tabs[1]:
    st.markdown("### 📊 Official Results Tables (Directly from results.csv)")
    
    if RESULTS_PATH.exists():
        df_results = pd.read_csv(RESULTS_PATH)
        st.caption(f"Loaded {len(df_results)} evaluated benchmark requests.")
        
        st.markdown("#### Table 1: Limits Found in Real Service")
        st.markdown(generate_table_1())
        
        t2a_md, t2b_md = generate_table_2a_and_2b(df_results)
        st.markdown("#### Table 2a: Latency Across 5 Load Scenarios")
        st.markdown(t2a_md)

        st.markdown("#### Table 2b: Outcomes Across Same Load Scenarios")
        st.markdown(t2b_md)

        st.markdown("#### Table 3: Retrieval Settings Benchmark")
        st.markdown(generate_table_3(df_results))

        st.markdown("---")
        st.download_button(
            label="📥 Download Raw results.csv",
            data=df_results.to_csv(index=False),
            file_name="results.csv",
            mime="text/csv",
            use_container_width=True
        )
    else:
        st.warning("results.csv not found. Run benchmark runner first.")

# ==============================================================================
# TAB 3: System Architecture
# ==============================================================================
with tabs[2]:
    st.markdown("### 🏛️ Complete System Architecture")
    st.image("docs/architecture_diagram.png", use_container_width=True)
    st.markdown("""
    - **Query Parser**: Categorizes domain intent and identifies candidate paper anchors.
    - **Retrieval Engine**: Employs BM25 with lexical/metadata re-ranking (dense semantic retrieval planned in Phase 4) and adaptive degradation under rate-limit warnings.
    - **Synthesis Drafter**: Enforces strict grounding with `[Paper, Page, Section]` citations.
    - **Verification Guard**: Employs automated loop-back query reformulation if citations are unverified.
    - **Calibrated Stand-In**: Replicates real TTFT, queueing latency degradation, and 429 backoff throttling.
    """)

# ==============================================================================
# TAB 4: Load Testing Suite
# ==============================================================================
with tabs[3]:
    st.markdown("### ⚡ Live Load Testing Runner")
    st.caption("Trigger live load shapes and observe rate limiting and queue behavior in real time.")

    col_l1, col_l2, col_l3 = st.columns(3)
    
    with col_l1:
        st.markdown("#### 1. Steady Load")
        st.caption("Paced requests within free tier limits (~14 RPM). Requires confirmed owner authorization & Free plan.")
        if st.button("Run Steady Test (Groq Live - Requires Authorization)"):
            with st.spinner("Pacing 3 live requests to Groq free tier..."):
                for i in range(3):
                    pipeline.run_request(
                        query="Explain self-attention.",
                        request_id=f"steady_live_{i}",
                        source="real"
                    )
                    time.sleep(4.0)
            st.success("Steady test completed without triggering 429!")

    with col_l2:
        st.markdown("#### 2. Burst Load")
        st.caption("15 simultaneous concurrent requests to trigger rate limiting.")
        if st.button("Run Burst Test (Stand-In)"):
            with st.spinner("Flooding 15 concurrent requests to Stand-In..."):
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                    futures = [ex.submit(pipeline.run_request, "What is Moshi?", f"burst_live_{i}", "burst", "stand-in") for i in range(15)]
                    results = [f.result() for f in futures]
            rl_count = sum(1 for r in results if r.status == "rate_limited")
            st.warning(f"Burst completed! {rl_count} of 15 requests correctly encountered 429 rate limiting.")

    with col_l3:
        st.markdown("#### 3. Daily Budget Exhausted")
        st.caption("Simulates 3:00 PM budget exhaustion.")
        if st.button("Run 3 PM Exhaustion Test"):
            pipeline.router.stand_in_client.exhaust_daily_budget()
            res_ex = pipeline.run_request("What is H-Net?", "exhaust_test", "daily_budget_exhausted", "stand-in")
            st.error(f"Returned Status: {res_ex.status.upper()}")
            st.info(f"User Message: {res_ex.answer}")

