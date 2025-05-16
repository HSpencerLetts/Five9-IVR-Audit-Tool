import streamlit as st
import xml.etree.ElementTree as ET
import html
import re
import pandas as pd
import io
import zipfile
import graphviz  # Requires Graphviz system install
from typing import List, Dict, Tuple, Optional


# Helper: split raw XML into individual <IVRScripts> blocks
def parse_ivrscripts_blocks(xml_text: str) -> List[str]:
    xml_text = xml_text.lstrip('\ufeff')  # strip BOM
    xml_text = re.sub(r'^\s*<\?xml[^>]+\?>', '', xml_text)
    wrapped = f"<root>{xml_text}</root>"
    root = ET.fromstring(wrapped)
    return [ET.tostring(node, encoding='unicode') for node in root.findall('.//IVRScripts')]

# Helper: clean embedded IVR XMLDefinition for valid parsing
def clean_xml_definition(raw_def: str) -> str:
    xml = html.unescape(raw_def)
    xml = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)', '&amp;', xml)
    xml = xml.replace("\x00", "")
    xml = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', xml)
    return xml

# Extract Call vs Simple Variables
def extract_variables(ivr_root: ET.Element) -> Tuple[List[Dict], List[Dict]]:
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
            row = {'Script Name': None, 'Variable Name': text,
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
def extract_skills(ivr_root: ET.Element) -> List[Dict]:
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
                    skills.append({'Script Name': None,
                                   'Skill Name': text,
                                   'Module Name': name})
    return skills

# Extract Prompts
def extract_prompts(ivr_root: ET.Element) -> List[Dict]:
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
                prompts.append({'Script Name': None,
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

# Streamlit UI
st.set_page_config(page_title='Five9 IVR Audit Tool v10.2', page_icon='📞', layout='wide')

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

st.title('📞 Five9 IVR Audit Tool v10.2')
st.markdown('Upload IVR XML to extract data and render call-flow diagrams.')

# File uploader
uploaded_file = st.file_uploader('Upload IVR XML file', type='xml')
if not uploaded_file:
    st.stop()
raw = uploaded_file.read().decode('utf-8')
try:
    scripts = parse_ivrscripts_blocks(raw)
except Exception as e:
    st.error(f"Failed to split IVRScripts blocks: {e}")
    st.stop()

# Parse scripts
debug_data, script_names = {}, []
call_vars, vars_, skills, prompts, failed = [], [], [], [], []
processed = 0
for idx, blk in enumerate(scripts, start=1):
    try:
        outer = ET.fromstring(blk)
    except Exception as e:
        failed.append({'Script Name': f'Script {idx}', 'Error': str(e)})
        continue
    name = outer.findtext('Name', default='').strip() or f'Script {idx}'
    script_names.append(name)
    xml_def = outer.findtext('XMLDefinition', default='')
    if not xml_def:
        failed.append({'Script Name': name, 'Error': 'Missing XMLDefinition'})
        continue
    cleaned = clean_xml_definition(xml_def)
    try:
        ivr = ET.fromstring(cleaned)
        processed += 1
    except ET.ParseError as e:
        failed.append({'Script Name': name, 'Error': f'Inner XML parse: {e}'})
        continue
    cvs, vs = extract_variables(ivr)
    ss = extract_skills(ivr)
    ps = extract_prompts(ivr)
    for row in cvs + vs + ss + ps:
        row['Script Name'] = name
    call_vars.extend(cvs)
    vars_.extend(vs)
    skills.extend(ss)
    prompts.extend(ps)
    debug_data[name] = {'Call Variables': cvs, 'Variables': vs, 'Skills': ss, 'Prompts': ps}

# Sidebar: Global Search & Excel export
st.sidebar.header('🔎 Global Search')
search = st.sidebar.text_input('Filter all tables')
def filter_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or not search:
        return df
    mask = df.apply(lambda row: row.astype(str).str.contains(search, case=False).any(), axis=1)
    return df[mask]

# Build and filter DataFrames
df_call = make_df(call_vars, sort_cols=['Script Name', 'Variable Name'])
df_vars = make_df(vars_, sort_cols=['Script Name', 'Variable Name'])
df_skill = make_df(skills, sort_cols=['Script Name', 'Skill Name'])
df_prompt = make_df(prompts, sort_cols=['Script Name', 'Prompt Name'])
fc = filter_df(df_call)
fv = filter_df(df_vars)
fs = filter_df(df_skill)
fp = filter_df(df_prompt)

# Excel export
e_buf = io.BytesIO()
with pd.ExcelWriter(e_buf, engine='openpyxl') as writer:
    df_call.to_excel(excel_writer=writer, sheet_name='Call Variables', index=False)
    df_vars.to_excel(excel_writer=writer, sheet_name='Variables', index=False)
    df_skill.to_excel(excel_writer=writer, sheet_name='Skills', index=False)
    df_prompt.to_excel(excel_writer=writer, sheet_name='Prompts', index=False)
    if failed:
        pd.DataFrame(failed).to_excel(excel_writer=writer, sheet_name='Failures', index=False)
st.sidebar.download_button(
    'Download Excel Report',
    data=e_buf.getvalue(),
    file_name='ivr_report_v10.2.xlsx',
    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
)

# Summary Metrics
st.subheader('🔍 Summary Metrics')
c1, c2, c3, c4 = st.columns(4)
c1.metric('Scripts Processed', processed)
c2.metric('Failures', len(failed))
c3.metric('Unique Call Variables', fc['Variable Name'].nunique() if not fc.empty else 0)
c4.metric('Unique Variables', fv['Variable Name'].nunique() if not fv.empty else 0)

# Detail Sections
def show_section(title: str, df: pd.DataFrame, filename: str):
    st.markdown(f'**{title}**')
    if not df.empty:
        st.dataframe(df, use_container_width=True, height=200)
    else:
        st.info(f'No {title.lower()} found.')
    st.download_button(
        f'Download {filename}',
        df.to_csv(index=False),
        filename
    )

show_section('📂 Call Variables', fc, 'call_variables.csv')
show_section('📂 Variables', fv, 'variables.csv')
show_section('🎯 Skills', fs, 'skills.csv')
show_section('🔊 Prompts', fp, 'prompts.csv')
if failed:
    st.subheader(f'⚠️ Failures: {len(failed)}')
    df_fail = filter_df(pd.DataFrame(failed))
    st.dataframe(df_fail, use_container_width=True, height=200)
    st.download_button('Download failures.csv', df_fail.to_csv(index=False), 'ivr_failures.csv')

# Call Flow Diagram only (no PDF export)
st.subheader('🎨 Call Flow Diagram')
selected = st.selectbox('Select Script', script_names)
blk = scripts[script_names.index(selected)]
xml_txt = ET.fromstring(blk).findtext('XMLDefinition', default='')
try:
    ivr_tree = ET.fromstring(clean_xml_definition(xml_txt))
except ET.ParseError as e:
    st.error(f'Diagram parse error: {e}')
    st.stop()
edges, labels = build_flow_graph(ivr_tree)
with st.container():
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
    st.graphviz_chart(dot)

# Offer SVG export for the selected diagram
svg_data = dot.pipe(format='svg')
st.download_button(
    "Download Diagram (SVG)",
    data=svg_data,
    file_name=f"{selected}.svg",
    mime="image/svg+xml"
)

# Batch export all diagrams as SVG ZIP
if st.button('Generate All Diagrams (SVG) ZIP'):
    with st.spinner('Building ZIP of all SVG diagrams…'):
        progress = st.progress(0)
        total = len(script_names)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            for idx, (name, blk) in enumerate(zip(script_names, scripts), start=1):
                xml_txt = ET.fromstring(blk).findtext('XMLDefinition', default='')
                try:
                    tree = ET.fromstring(clean_xml_definition(xml_txt))
                except ET.ParseError:
                    continue
                edges2, labels2 = build_flow_graph(tree)
                dot2 = graphviz.Digraph(
                    format='svg',
                    graph_attr={'rankdir':'LR'},
                    node_attr={'shape':'box','style':'rounded,filled','fillcolor':'#eef4fd'},
                    edge_attr={'arrowsize':'0.7'}
                )
                for nid, lbl in labels2.items():
                    dot2.node(nid, lbl)
                for s, succs in edges2.items():
                    for d, k in succs:
                        if k:
                            dot2.edge(s, d, xlabel=k)
                        else:
                            dot2.edge(s, d)
                svg_all = dot2.pipe(format='svg')
                zf.writestr(f"{name}.svg", svg_all)
                progress.progress(idx/total)
        zip_buffer.seek(0)
        st.download_button(
            'Download All Diagrams (SVG ZIP)',
            data=zip_buffer.getvalue(),
            file_name='all_diagrams_svg.zip',
            mime='application/zip'
        )

# Debug Tools
with st.expander('🐞 Debug Tools'):
    sel2 = st.selectbox('Inspect Script', script_names)
    for section, rows in debug_data[sel2].items():
        st.markdown(f'**{section}**')
        df_dbg = make_df(rows)
        if not df_dbg.empty:
            st.dataframe(df_dbg, use_container_width=True, height=200)
        else:
            st.info(f'No {section.lower()} for this script.')

# Sidebar: App Info
with st.sidebar.expander("⚙️ App Info"):
    st.markdown("Version: **10.2**")
    st.markdown("Built by: Harry Spencer Letts")
    st.markdown("[📧 Contact](mailto:harry.spencerletts@five9.com)")


# Footer
st.markdown('---')
st.markdown(
    "<div style='text-align:center; color:gray; font-size:0.8em;'>"
    "Version 10.2 &#9679; <a href='mailto:harry.spencerletts@five9.com'>Feedback</a>"
    "</div>",
    unsafe_allow_html=True
)
