import streamlit as st
import xml.etree.ElementTree as ET
import html
import re
import pandas as pd
import io
import zipfile
import graphviz  # Requires Graphviz system install
from typing import List, Dict, Tuple, Optional
import os
import tempfile
import gc


# Helper: split raw XML into individual <IVRScripts> blocks
def parse_ivrscripts_blocks(xml_text: str) -> List[str]:
    xml_text = xml_text.lstrip('\ufeff')  # strip BOM
    xml_text = re.sub(r'^\s*<\?xml[^>]+\?>', '', xml_text)
    wrapped = f"<root>{xml_text}</root>"
    root = ET.fromstring(wrapped)
    blocks = [ET.tostring(node, encoding='unicode') for node in root.findall('.//IVRScripts')]
    return blocks

# Helper: clean embedded IVR XMLDefinition for valid parsing
def clean_xml_definition(raw_def: str) -> str:
    xml = html.unescape(raw_def)
    xml = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)', '&amp;', xml)
    xml = xml.replace("\x00", "")
    xml = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', xml)
    return xml

# Extract Call vs Simple Variables
def extract_variables(ivr_root: ET.Element, script_name: str) -> Tuple[List[Dict], List[Dict]]:
    call_vars, vars_ = [], []
    modules_elem = ivr_root.find('modules')
    if modules_elem is None:
        return call_vars, vars_
    for mod in modules_elem:
        tag = mod.tag
        name = mod.findtext('moduleName', default='').strip()
        for ve in mod.findall('.//variableName'):
            text = ve.text.strip() if ve.text else ''
            if not text:
                continue
            row = {'Script Name': script_name, 'Variable Name': text,
                   'Module Name': name, 'Source Module': tag}
            if '.' in text:
                group, _ = text.split('.', 1)
                row.update({'Type': 'Call Variable', 'Group': group})
                call_vars.append(row)
            else:
                row.update({'Type': 'Variable', 'Group': ''})
                vars_.append(row)
    return call_vars, vars_

# Extract Skills
def extract_skills(ivr_root: ET.Element, script_name: str) -> List[Dict]:
    skills = []
    modules_elem = ivr_root.find('modules')
    if modules_elem is None:
        return skills
    for mod in modules_elem:
        if mod.tag == 'skillTransfer':
            name = mod.findtext('moduleName', default='').strip()
            for skl in mod.findall('.//listOfSkillsEx/extrnalObj/name'):
                text = skl.text.strip() if skl.text else ''
                if text:
                    skills.append({'Script Name': script_name,
                                   'Skill Name': text,
                                   'Module Name': name})
    return skills

# Extract Prompts
def extract_prompts(ivr_root: ET.Element, script_name: str) -> List[Dict]:
    prompts = []
    modules_elem = ivr_root.find('modules')
    if modules_elem is None:
        return prompts
    for mod in modules_elem:
        name = mod.findtext('moduleName', default='').strip()
        for prm in mod.findall('.//prompt'):
            tag = prm.find('name')
            text = tag.text.strip() if tag is not None and tag.text else ''
            if text:
                prompts.append({'Script Name': script_name,
                                'Prompt Name': text,
                                'Module Name': name})
    return prompts

# Build DataFrame
def make_df(rows: List[Dict], sort_cols: List[str] = None) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).drop_duplicates()
    if sort_cols:
        df = df.sort_values(by=sort_cols)
    return df

# Build Graph Data
def build_flow_graph(ivr_root: ET.Element) -> Tuple[Dict[str, List[Tuple[str, Optional[str]]]], Dict[str, str]]:
    edges, labels = {}, {}
    modules_elem = ivr_root.find('modules')
    if modules_elem is None:
        return edges, labels
    for mod in modules_elem:
        mid = mod.findtext('moduleId', default='').strip()
        lbl = mod.findtext('moduleName', default='').strip() or mod.tag
        if mid:
            edges[mid] = []
            labels[mid] = lbl
    for mod in modules_elem:
        src = mod.findtext('moduleId', default='').strip()
        if src not in edges:
            continue
        for sd in mod.findall('singleDescendant'):
            child = sd.text.strip()
            if child in labels:
                edges[src].append((child, None))
        for entry in mod.findall('.//branches/entry'):
            k = entry.find('key')
            d = entry.find('.//value/desc')
            if k is not None and d is not None:
                child = d.text.strip()
                key = k.text.strip()
                if child in labels:
                    edges[src].append((child, key))
    return edges, labels

# Process a single script block
@st.cache_data
def process_script(blk: str, idx: int) -> Tuple[str, Dict, bool]:
    try:
        outer = ET.fromstring(blk)
    except Exception as e:
        return f'Script {idx}', {'error': str(e)}, False
    
    name = outer.findtext('Name', default='').strip() or f'Script {idx}'
    xml_def = outer.findtext('XMLDefinition', default='')
    
    if not xml_def:
        return name, {'error': 'Missing XMLDefinition'}, False
    
    cleaned = clean_xml_definition(xml_def)
    try:
        ivr = ET.fromstring(cleaned)
    except ET.ParseError as e:
        return name, {'error': f'Inner XML parse: {e}'}, False
    
    cvs, vs = extract_variables(ivr, name)
    ss = extract_skills(ivr, name)
    ps = extract_prompts(ivr, name)
    
    data = {
        'Call Variables': cvs,
        'Variables': vs,
        'Skills': ss,
        'Prompts': ps,
        'XMLDefinition': cleaned  # Store for diagram rendering
    }
    
    return name, data, True

# Main function to batch process all scripts
@st.cache_data
def process_all_scripts(scripts: List[str]) -> Tuple[List[str], List[Dict], List[Dict], List[Dict], List[Dict], List[Dict]]:
    call_vars, vars_, skills, prompts, failed = [], [], [], [], []
    script_names = []
    script_data = {}
    
    for idx, blk in enumerate(scripts, start=1):
        name, data, success = process_script(blk, idx)
        script_names.append(name)
        
        if not success:
            failed.append({'Script Name': name, 'Error': data.get('error', 'Unknown error')})
            continue
        
        script_data[name] = data
        call_vars.extend(data['Call Variables'])
        vars_.extend(data['Variables'])
        skills.extend(data['Skills'])
        prompts.extend(data['Prompts'])
    
    return script_names, script_data, call_vars, vars_, skills, prompts, failed

# Generate a single diagram SVG
@st.cache_data
def generate_diagram(xml_def: str) -> graphviz.Digraph:
    try:
        ivr_tree = ET.fromstring(xml_def)
        edges, labels = build_flow_graph(ivr_tree)
        
        dot = graphviz.Digraph(
            format='svg',
            graph_attr={'rankdir':'LR'},
            node_attr={'shape':'box','style':'rounded,filled','fillcolor':'#eef4fd'},
            edge_attr={'arrowsize':'0.7'}
        )
        
        for nid, lbl in labels.items():
            dot.node(nid, lbl)
            
        for src, succs in edges.items():
            for dst, key in succs:
                if key:
                    dot.edge(src, dst, xlabel=key)
                else:
                    dot.edge(src, dst)
                    
        return dot
    except Exception as e:
        st.error(f"Diagram generation error: {e}")
        return None

# Streamlit UI
st.set_page_config(page_title='Five9 IVR Audit Tool v10.3', page_icon='📞', layout='wide')

st.info(
    """
    **Disclaimer & Terms of Use**

    This web tool is provided *as-is*, without warranty or official support from Five9.  
    - All file processing is local. No data is stored externally.  
    - Intended for educational and illustrative use only.  
    - Use at your own risk.
    """
)

st.markdown(
    """
    <style>
    footer{visibility:hidden;}#MainMenu{visibility:hidden}
    .diagram-container{background:#fff;padding:1rem;border-radius:1rem;box-shadow:0 4px 12px rgba(0,0,0,0.1)}
    .stSelectbox>div{background:#f9f9f9;border-radius:.5rem;padding:.5rem}
    </style>
    """, unsafe_allow_html=True
)

st.title('📞 Five9 IVR Audit Tool v10.3')
st.markdown('Upload IVR XML to extract data and render call-flow diagrams.')

# State management
if 'processed' not in st.session_state:
    st.session_state.processed = False
    st.session_state.script_names = []
    st.session_state.script_data = {}
    st.session_state.call_vars = []
    st.session_state.vars_ = []
    st.session_state.skills = []
    st.session_state.prompts = []
    st.session_state.failed = []

# File uploader
uploaded_file = st.file_uploader('Upload IVR XML file', type='xml')

if uploaded_file is not None and not st.session_state.processed:
    with st.spinner('Processing XML file...'):
        raw = uploaded_file.read().decode('utf-8')
        try:
            scripts = parse_ivrscripts_blocks(raw)
            st.session_state.script_names, st.session_state.script_data, st.session_state.call_vars, \
            st.session_state.vars_, st.session_state.skills, st.session_state.prompts, \
            st.session_state.failed = process_all_scripts(scripts)
            st.session_state.processed = True
            # Clear memory
            del raw, scripts
            gc.collect()
        except Exception as e:
            st.error(f"Failed to process XML: {e}")
            st.stop()

if not st.session_state.processed:
    st.stop()

# Sidebar: Global Search & Excel export
st.sidebar.header('🔎 Global Search')
search = st.sidebar.text_input('Filter all tables')
def filter_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or not search:
        return df
    mask = df.apply(lambda row: row.astype(str).str.contains(search, case=False).any(), axis=1)
    return df[mask]

# Build DataFrames on demand
@st.cache_data
def get_dataframes(call_vars, vars_, skills, prompts):
    df_call = make_df(call_vars, sort_cols=['Script Name', 'Variable Name'])
    df_vars = make_df(vars_, sort_cols=['Script Name', 'Variable Name'])
    df_skill = make_df(skills, sort_cols=['Script Name', 'Skill Name'])
    df_prompt = make_df(prompts, sort_cols=['Script Name', 'Prompt Name'])
    return df_call, df_vars, df_skill, df_prompt

df_call, df_vars, df_skill, df_prompt = get_dataframes(
    st.session_state.call_vars,
    st.session_state.vars_,
    st.session_state.skills,
    st.session_state.prompts
)

# Filter DataFrames
fc = filter_df(df_call)
fv = filter_df(df_vars)
fs = filter_df(df_skill)
fp = filter_df(df_prompt)

# Excel export - generate only when requested
if st.sidebar.button('Generate Excel Report'):
    with st.spinner('Generating Excel report...'):
        e_buf = io.BytesIO()
        with pd.ExcelWriter(e_buf, engine='openpyxl') as writer:
            df_call.to_excel(excel_writer=writer, sheet_name='Call Variables', index=False)
            df_vars.to_excel(excel_writer=writer, sheet_name='Variables', index=False)
            df_skill.to_excel(excel_writer=writer, sheet_name='Skills', index=False)
            df_prompt.to_excel(excel_writer=writer, sheet_name='Prompts', index=False)
            if st.session_state.failed:
                pd.DataFrame(st.session_state.failed).to_excel(excel_writer=writer, sheet_name='Failures', index=False)
        
        st.sidebar.download_button(
            'Download Excel Report',
            data=e_buf.getvalue(),
            file_name='ivr_report_v10.3.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        del e_buf
        gc.collect()

# Summary Metrics
st.subheader('🔍 Summary Metrics')
c1, c2, c3, c4 = st.columns(4)
processed_count = len(st.session_state.script_names) - len(st.session_state.failed)
c1.metric('Scripts Processed', processed_count)
c2.metric('Failures', len(st.session_state.failed))
c3.metric('Unique Call Variables', fc['Variable Name'].nunique() if not fc.empty else 0)
c4.metric('Unique Variables', fv['Variable Name'].nunique() if not fv.empty else 0)

# Detail Sections with pagination
def show_section(title: str, df: pd.DataFrame, filename: str):
    st.markdown(f'**{title}**')
    if not df.empty:
        # Pagination
        page_size = 10
        total_pages = (len(df) + page_size - 1) // page_size
        page_key = f"page_{title}"
        
        if page_key not in st.session_state:
            st.session_state[page_key] = 0
            
        col1, col2 = st.columns([4, 1])
        with col2:
            page = st.number_input(f"Page (of {total_pages})", 
                                  min_value=1, 
                                  max_value=max(1, total_pages),
                                  value=st.session_state[page_key] + 1,
                                  key=f"page_input_{title}")
            st.session_state[page_key] = page - 1
            
        start_idx = st.session_state[page_key] * page_size
        end_idx = min(start_idx + page_size, len(df))
        st.dataframe(df.iloc[start_idx:end_idx], use_container_width=True)
        
        if st.button(f'Download {filename}', key=f"download_{title}"):
            csv = df.to_csv(index=False)
            st.download_button(
                f'Download {filename}',
                csv,
                filename
            )
    else:
        st.info(f'No {title.lower()} found.')

# Display sections with tabs for better organization
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Call Variables", "Variables", "Skills", "Prompts", "Failures"])

with tab1:
    show_section('📂 Call Variables', fc, 'call_variables.csv')
with tab2:
    show_section('📂 Variables', fv, 'variables.csv')
with tab3:
    show_section('🎯 Skills', fs, 'skills.csv')
with tab4:
    show_section('🔊 Prompts', fp, 'prompts.csv')
with tab5:
    if st.session_state.failed:
        df_fail = pd.DataFrame(st.session_state.failed)
        st.dataframe(df_fail, use_container_width=True)
        if st.button('Download failures.csv'):
            csv = df_fail.to_csv(index=False)
            st.download_button('Download failures.csv', csv, 'ivr_failures.csv')
    else:
        st.info('No failures reported.')

# Call Flow Diagram
st.subheader('🎨 Call Flow Diagram')
selected = st.selectbox('Select Script', st.session_state.script_names)

if selected:
    script_data = st.session_state.script_data.get(selected, {})
    xml_def = script_data.get('XMLDefinition', '')
    
    if xml_def:
        with st.spinner('Rendering diagram...'):
            dot = generate_diagram(xml_def)
            if dot:
                st.graphviz_chart(dot)
                
                # Get SVG string for download
                svg_str = dot.pipe(format='svg').decode('utf-8')
                st.download_button(
                    "Download Diagram (SVG)",
                    data=svg_str,
                    file_name=f"{selected}.svg",
                    mime="image/svg+xml"
                )
    else:
        st.error(f"Failed to load diagram data for {selected}")

# Batch export diagrams with chunking
if st.button('Generate All Diagrams (SVG) ZIP'):
    with st.spinner('Building ZIP of all SVG diagrams…'):
        progress = st.progress(0)
        total = len(st.session_state.script_names)
        
        # Create ZIP buffer
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            # Process diagrams in chunks to reduce memory usage
            chunk_size = 5
            for i in range(0, total, chunk_size):
                chunk = st.session_state.script_names[i:i+chunk_size]
                
                for idx, name in enumerate(chunk):
                    script_data = st.session_state.script_data.get(name, {})
                    xml_def = script_data.get('XMLDefinition', '')
                    
                    if xml_def:
                        try:
                            dot = generate_diagram(xml_def)
                            if dot:
                                # Get SVG as string and write directly to ZIP
                                svg_str = dot.pipe(format='svg').decode('utf-8')
                                zf.writestr(f"{name}.svg", svg_str)
                        except Exception as e:
                            st.error(f"Error generating diagram for {name}: {e}")
                
                progress.progress(min(1.0, (i + len(chunk)) / total))
                gc.collect()  # Clear memory after each chunk
            
        zip_buffer.seek(0)
        st.download_button(
            'Download All Diagrams (SVG ZIP)',
            data=zip_buffer.getvalue(),
            file_name='all_diagrams_svg.zip',
            mime='application/zip'
        )
        # Clean up
        del zip_buffer
        gc.collect()

# Debug Tools - load on demand
with st.expander('🐞 Debug Tools'):
    sel2 = st.selectbox('Inspect Script', st.session_state.script_names)
    script_debug_data = st.session_state.script_data.get(sel2, {})
    
    if script_debug_data:
        for section in ['Call Variables', 'Variables', 'Skills', 'Prompts']:
            rows = script_debug_data.get(section, [])
            st.markdown(f'**{section}**')
            df_dbg = make_df(rows)
            if not df_dbg.empty:
                st.dataframe(df_dbg, use_container_width=True, height=200)
            else:
                st.info(f'No {section.lower()} for this script.')

# Sidebar: App Info
with st.sidebar.expander("⚙️ App Info"):
    st.markdown("Version: **10.3**")
    st.markdown("Built by: Harry Spencer Letts")
    st.markdown("[📧 Contact](mailto:harry.spencerletts@five9.com)")

# Force garbage collection before finishing
gc.collect()

# Footer
st.markdown('---')
st.markdown(
    "<div style='text-align:center; color:gray; font-size:0.8em;'>"
    "Version 10.3 &#9679; <a href='mailto:harry.spencerletts@five9.com'>Feedback</a>"
    "</div>",
    unsafe_allow_html=True
)
