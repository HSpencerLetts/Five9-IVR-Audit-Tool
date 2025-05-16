import streamlit as st
import xml.etree.ElementTree as ET
import html
import re
import pandas as pd
from typing import List, Dict, Tuple

# ------------------ Helper Functions ------------------

def parse_ivrscripts_blocks(xml_text: str) -> List[str]:
    """
    Parse the full XML text and return serialized strings of each <IVRScripts> block.
    Handles both files where <IVRScripts> is the root and those wrapped in a parent element.
    """
    # Remove any XML declaration
    xml_text = re.sub(r'^\s*<\?xml[^>]+\?>', '', xml_text)
    # Wrap in dummy root to catch standalone or wrapped IVRScripts
    wrapped = f"<root>{xml_text}</root>"
    root = ET.fromstring(wrapped)
    return [ET.tostring(node, encoding='unicode') for node in root.findall('.//IVRScripts')]


def clean_xml_definition(raw_def: str) -> str:
    """
    Unescape HTML entities, fix stray ampersands, remove null bytes.
    """
    xml = html.unescape(raw_def)
    xml = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)', '&amp;', xml)
    return xml.replace("\x00", "")


def extract_variables(ivr_root: ET.Element) -> Tuple[List[Dict], List[Dict]]:
    """
    Extract call variables (with dot notation) and simple variables.
    """
    call_vars, vars_ = [], []
    modules = ivr_root.find('modules')
    if modules is not None:
        for mod in modules:
            tag = mod.tag
            mod_name = mod.findtext('moduleName', default='').strip()
            for ve in mod.findall('.//variableName'):
                text = ve.text.strip() if ve.text else ''
                if not text:
                    continue
                row = {
                    'Variable Name': text,
                    'Module Name': mod_name,
                    'Source Module': tag
                }
                if '.' in text:
                    group, _ = text.split('.', 1)
                    row.update({'Type': 'Call Variable', 'Group': group})
                    call_vars.append(row)
                else:
                    row.update({'Type': 'Variable', 'Group': ''})
                    vars_.append(row)
    return call_vars, vars_


def extract_skills(ivr_root: ET.Element) -> List[Dict]:
    """
    Extract skillTransfer names.
    """
    skills = []
    modules = ivr_root.find('modules')
    if modules is not None:
        for mod in modules:
            if mod.tag == 'skillTransfer':
                mod_name = mod.findtext('moduleName', default='').strip()
                for skl in mod.findall('.//listOfSkillsEx/extrnalObj/name'):
                    name = skl.text.strip() if skl.text else ''
                    if name:
                        skills.append({'Skill Name': name, 'Module Name': mod_name})
    return skills


def extract_prompts(ivr_root: ET.Element) -> List[Dict]:
    """
    Extract prompt names.
    """
    prompts = []
    modules = ivr_root.find('modules')
    if modules is not None:
        for mod in modules:
            mod_name = mod.findtext('moduleName', default='').strip()
            for prm in mod.findall('.//prompt'):
                name_tag = prm.find('name')
                text = name_tag.text.strip() if name_tag is not None and name_tag.text else ''
                if text:
                    prompts.append({'Prompt Name': text, 'Module Name': mod_name})
    return prompts


def make_df(rows: List[Dict], sort_cols: List[str] = None) -> pd.DataFrame:
    """
    Build DataFrame, drop duplicates, optionally sort.
    """
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).drop_duplicates()
    if sort_cols:
        df = df.sort_values(by=sort_cols)
    return df

# ------------------ Streamlit UI ------------------

st.set_page_config(page_title='Five9 IVR Audit Tool', layout='wide')

# Disclaimer
st.info("""
**Disclaimer & Terms of Use**

This tool is provided *as-is*, without warranty.  
All processing is local; no data is stored externally.  
Use at your own risk.
""")

st.title('📞 Five9 IVR Audit Tool')
st.markdown('Upload a Five9 IVR XML file to extract **Call Variables**, **Variables**, **Skills**, and **Prompts**.')

uploaded_file = st.file_uploader('Upload IVR XML file', type='xml')
if uploaded_file:
    raw = uploaded_file.read().decode('utf-8')
    try:
        blocks = parse_ivrscripts_blocks(raw)
    except ET.ParseError as e:
        st.error(f'Error parsing XML: {e}')
        blocks = []

    call_vars, vars_, skills, prompts, failed = [], [], [], [], []
    debug_data = {}
    processed = 0

    for idx, blk in enumerate(blocks, start=1):
        with st.spinner(f'Processing script {idx}/{len(blocks)}…'):
            try:
                root = ET.fromstring(blk)
            except ET.ParseError as e:
                failed.append({'Script Name': 'Unknown', 'Error': str(e)})
                continue

            name = root.findtext('Name', default='').strip() or f'Script {idx}'
            xml_def = root.findtext('XMLDefinition', default='')
            if not xml_def:
                failed.append({'Script Name': name, 'Error': 'Missing XMLDefinition'})
                continue

            cleaned = clean_xml_definition(xml_def)
            try:
                ivr = ET.fromstring(cleaned)
                processed += 1
            except ET.ParseError as e:
                failed.append({'Script Name': name, 'Error': str(e)})
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
            debug_data[name] = {
                'Call Variables': cvs,
                'Variables': vs,
                'Skills': ss,
                'Prompts': ps
            }

    # Display sections
    def show_section(title: str, rows: List[Dict], filename: str, sort_cols: List[str]):
        st.subheader(title)
        df = make_df(rows, sort_cols)
        if not df.empty:
            st.dataframe(df, use_container_width=True, height=300)
            st.download_button(f'Download {filename}', df.to_csv(index=False), filename)
        else:
            st.info(f'No {title.lower()} found.')

    show_section('📂 Call Variables', call_vars, 'call_variables.csv', ['Script Name', 'Variable Name'])
    show_section('📂 Variables', vars_, 'variables.csv', ['Script Name', 'Variable Name'])
    show_section('🎯 Skills', skills, 'skills.csv', ['Script Name', 'Skill Name'])
    show_section('🔊 Prompts', prompts, 'prompts.csv', ['Script Name', 'Prompt Name'])

    # Failures
    if failed:
        st.subheader(f'⚠️ {len(failed)} script(s) failed to process')
        df_fail = pd.DataFrame(failed)
        st.dataframe(df_fail, use_container_width=True, height=200)
        st.download_button('Download failures CSV', df_fail.to_csv(index=False), 'ivr_failures.csv')

    st.success(f'✅ Processed {processed} script(s); {len(failed)} failed.')

    # Debug tools in expander
    with st.expander('🐞 Debug Tools'):
        if debug_data:
            script_names = list(debug_data.keys())
            sel = st.selectbox('Select a script to inspect', script_names)
            for section, rows in debug_data[sel].items():
                st.markdown(f"**{section}**")
                df = make_df(rows)
                if not df.empty:
                    st.dataframe(df, use_container_width=True, height=200)
                else:
                    st.info(f"No {section.lower()} for this script.")
        else:
            st.info('No data to debug.')

# Footer
st.markdown('---')
st.markdown(
    "<div style='text-align:center; color:gray; font-size:0.8em;'>"
    "Version 8.0 &#9679; <a href='mailto:harry.spencerletts@five9.com'>Feedback</a>"
    "</div>",
    unsafe_allow_html=True
)
