import streamlit as st
import subprocess
import os
import signal
import re
import queue
import threading
import time

def enqueue_output(out, q):
    for line in iter(out.readline, ''):
        q.put(line)
    out.close()

# --- CONFIGURATION ---
st.set_page_config(page_title="AI Story Writer Pro MAX XDR", layout="wide", page_icon="📚")

# Standard Ollama Tiers
MODEL_TIERS = {
    "🚀 Fast / Low VRAM (8GB)": ["llama3", "mistral", "phi3", "gemma2:9b"],
    "⚖️ Balanced / Med VRAM (12-16GB)": ["mistral-nemo:12b", "qwen2.5:14b", "solar"],
    "🧠 Heavy / High VRAM (24GB - RTX 3090)": ["deepseek-r1:32b", "gpt-oss:20b", "llama3:70b-q4_0", "command-r", "qwen2.5:32b"]
}

st.title("📚 AI Story Writer Pro MAX XDR")
st.markdown("Running on **Localhost** | 🛑 **Emergency Stop Available**")

# --- SESSION STATE ---
if 'process' not in st.session_state: st.session_state.process = None
if 'logs' not in st.session_state: st.session_state.logs = ""
if 'progress_val' not in st.session_state: st.session_state.progress_val = 0
if 'queue' not in st.session_state: st.session_state.queue = None

is_running = st.session_state.process is not None

# --- SIDEBAR SETTINGS ---
with st.sidebar:
    st.header("⚙️ Engine Settings")
    
    # TABS for Standard vs Custom
    tab_std, tab_custom = st.tabs(["Ollama Local", "Custom / vLLM"])
    
    with tab_std:
        tier_choice = st.selectbox("Hardware Tier", list(MODEL_TIERS.keys()), index=2, disabled=is_running)
        std_model_name = st.selectbox("Select Model", MODEL_TIERS[tier_choice], disabled=is_running)
        use_custom = False

    with tab_custom:
        st.info("Point to any OpenAI-compatible API (vLLM, LM Studio, etc)")
        custom_api_url = st.text_input("API Base URL", "http://localhost:8000/v1", disabled=is_running)
        custom_model_name = st.text_input("Model Name", "my-custom-model", disabled=is_running)
        use_custom = True # Logic flag
        
        # If the user is actually in this tab, we prefer these settings
        # We'll decide which to use based on which tab is "active" logic below? 
        # Actually Streamlit tabs don't hold state like that easily. 
        # Better UX: A checkbox at the top of sidebar.
    
    st.divider()
    
    # MASTER SWITCH for Custom Mode
    # We put this outside tabs to be explicit
    enable_custom_mode = st.checkbox("🔌 Use Custom Endpoint (vLLM)", value=False, disabled=is_running)
    
    st.write("### 📏 Story Length")
    is_short_story = st.checkbox("Short Story Mode?", value=True, disabled=is_running)
    
    if is_short_story:
        chapter_limit = st.slider("Target Chapters", 3, 15, 5, disabled=is_running)
    else:
        st.caption("Full Novel Mode")
        chapter_limit = 20

# --- MAIN AREA ---
user_prompt = st.text_area("Story Concept:", height=150, disabled=is_running)

col1, col2 = st.columns(2)

# START BUTTON
if col1.button("🚀 Start Writing", type="primary", use_container_width=True, disabled=is_running):
    if not user_prompt:
        st.error("Please enter a prompt.")
    else:
        # 1. Prompt Logic
        final_prompt_text = user_prompt
        if is_short_story:
            final_prompt_text += f"\n\n[IMPORTANT]: Limit Outline to EXACTLY {chapter_limit} chapters."

        os.makedirs("Prompts", exist_ok=True)
        with open("Prompts/webui_prompt.txt", "w", encoding="utf-8") as f:
            f.write(final_prompt_text)

        # 2. Model Logic
        my_env = os.environ.copy()
        my_env["PYTHONUNBUFFERED"] = "1"
        my_env["PYTHONIOENCODING"] = "utf-8" # Fixes Unicode Crash

        if enable_custom_mode:
            # CUSTOM VLLM MODE
            # We use the 'openai' provider but swap the Base URL
            # Format: openai://model_name
            target_model = f"openai://{custom_model_name}"
            
            # Set environment variables for the script to find the server
            my_env["OPENAI_API_BASE"] = custom_api_url
            my_env["OPENAI_API_KEY"] = "sk-dummy" # vLLM usually ignores this, but it must be present
            
            st.success(f"Using Custom Endpoint: {custom_api_url}")
        else:
            # STANDARD OLLAMA MODE
            target_model = f"ollama://{std_model_name}"
            # Ensure we don't accidentally use old OpenAI env vars
            if "OPENAI_API_BASE" in my_env: del my_env["OPENAI_API_BASE"]

        # 3. Construct Command (Total Override)
        command = [
            "python", "-u", "Write.py", 
            "-Prompt", "Prompts/webui_prompt.txt",
            "-InitialOutlineModel", target_model, "-ChapterOutlineModel", target_model,
            "-ChapterS1Model", target_model, "-ChapterS2Model", target_model,
            "-ChapterS3Model", target_model, "-ChapterS4Model", target_model,
            "-ChapterRevisionModel", target_model, "-RevisionModel", target_model,
            "-EvalModel", target_model, "-InfoModel", target_model,
            "-ScrubModel", target_model, "-CheckerModel", target_model,
            "-TranslatorModel", target_model,
            "-OutlineMaxRevisions", "2", "-ChapterMaxRevisions", "2"
        ]
        
        try:
            p = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                text=True, encoding="utf-8", errors="replace", env=my_env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            st.session_state.process = p
            st.session_state.logs = ""
            st.session_state.progress_val = 0
            
            # Start queue and reader thread
            q = queue.Queue()
            t = threading.Thread(target=enqueue_output, args=(p.stdout, q), daemon=True)
            t.start()
            st.session_state.queue = q
            
            st.rerun()
        except Exception as e:
            st.error(f"Failed to start: {e}")

# STOP BUTTON
if col2.button("🛑 STOP EVERYTHING", type="secondary", use_container_width=True):
    if st.session_state.process:
        st.session_state.process.terminate()
        st.session_state.process = None
        st.error("🚫 Process Terminated")
        st.rerun()

# LIVE OUTPUT
if is_running:
    st.subheader("📝 Writing in Progress...")
    progress_bar = st.progress(st.session_state.progress_val)
    status_text = st.empty()
    log_container = st.empty()
    
    p = st.session_state.process
    q = st.session_state.queue
    
    if q is not None:
        while not q.empty():
            try:
                line = q.get_nowait()
                if line:
                    st.session_state.logs += line
                    if "Generating Chapter" in line:
                        match = re.search(r"Generating Chapter (\d+)", line)
                        if match:
                            current_chap = int(match.group(1))
                            new_progress = min(int((current_chap / chapter_limit) * 100), 95)
                            st.session_state.progress_val = new_progress
            except queue.Empty:
                break
                
    progress_bar.progress(st.session_state.progress_val)
    log_container.code(st.session_state.logs[-5000:], language="bash")
    
    if p.poll() is not None and (q is None or q.empty()):
        st.session_state.process = None
        st.session_state.queue = None
        progress_bar.progress(100)
        st.balloons()
        st.rerun()
    else:
        time.sleep(0.5)
        st.rerun()
else:
    if st.session_state.logs:
        st.subheader("📝 Output Log")
        st.code(st.session_state.logs[-5000:], language="bash")
